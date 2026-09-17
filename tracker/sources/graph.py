"""Sincronizare optionala Instagram Business + Pagina Facebook prin Meta Graph API.

ATENTIE - nu e sursa de baza (foloseste importul CSV, tracker/sources/csvfile.py,
care merge cu orice cont fara aprobari). Asta ramane utila doar daca faci vreodata
App Review la Meta:

  - o aplicatie Meta a agentiei (una singura, nu una per client);
  - "Standard Access" merge doar pe conturi unde esti admin/tester in Meta Business
    Suite (bun pentru conturile proprii ale agentiei);
  - pentru conturile clientilor (pe care nu le detii), Meta cere Advanced Access,
    ceea ce inseamna App Review + Business Verification (saptamani, nu zile);
  - contul Instagram trebuie sa fie Business/Creator, legat de o Pagina Facebook;
  - permisiuni: instagram_basic, pages_show_list, pages_read_engagement,
    instagram_manage_insights.

Tokenul si ID-ul contului (IG user id / Page id) se seteaza per cont, in
Setari > Conturi. Fara ele, sincronizarea intoarce o eroare clara, nu crapa.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .. import store

GRAPH_VERSION = os.environ.get("TRACKER_GRAPH_VERSION", "v26.0")
GRAPH_HOST = "https://graph.facebook.com"
TIMEOUT = 30

IG_FIELDS = ("id,caption,media_type,media_product_type,media_url,permalink,"
             "thumbnail_url,timestamp,like_count,comments_count")
FB_FIELDS = ("id,message,created_time,permalink_url,full_picture,"
             "attachments{media_type},shares,"
             "likes.summary(true),comments.summary(true)")

IG_TYPE_MAP = {"IMAGE": "photo", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel"}
FB_TYPE_MAP = {"photo": "photo", "video": "video", "album": "carousel",
               "link": "photo", "share": "photo"}


class GraphError(RuntimeError):
    pass


def _get(path: str, params: dict) -> dict:
    url = f"{GRAPH_HOST}/{GRAPH_VERSION}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            message = json.loads(body)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = body[:300] or str(exc)
        raise GraphError(f"Graph API {exc.code}: {message}") from None
    except urllib.error.URLError as exc:
        raise GraphError(f"Nu am putut contacta Graph API: {exc.reason}") from None


def _pick_content_type(media: dict, platform: str) -> str:
    if platform == "instagram":
        if media.get("media_product_type") == "STORY":
            return "story"
        return IG_TYPE_MAP.get(media.get("media_type", ""), "video")
    attachments = (media.get("attachments") or {}).get("data") or []
    kind = attachments[0].get("media_type", "") if attachments else ""
    return FB_TYPE_MAP.get(kind, "photo")


def _fetch(path: str, params: dict, limit: int) -> list[dict]:
    """Ia pagina cu pagina pana la `limit` elemente."""
    items: list[dict] = []
    payload = _get(path, {**params, "limit": min(limit, 50)})
    while True:
        items.extend(payload.get("data") or [])
        next_url = ((payload.get("paging") or {}).get("next") or "")
        if len(items) >= limit or not next_url:
            break
        request = urllib.request.Request(next_url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError):
            break
    return items[:limit]


def fetch_media(account: dict, limit: int = 50) -> list[dict]:
    """Postarile reale de pe platforma, normalizate pentru store.import_post()."""
    token = (account.get("access_token") or "").strip()
    node = (account.get("external_id") or "").strip()
    if not token:
        raise GraphError("Contul nu are token. Adauga-l in Setari > Conturi.")
    if not node:
        raise GraphError("Contul nu are ID (IG user id sau Page id). Adauga-l in Setari.")

    platform = account["platform"]
    edge = "media" if platform == "instagram" else "published_posts"
    fields = IG_FIELDS if platform == "instagram" else FB_FIELDS
    raw = _fetch(f"{node}/{edge}", {"fields": fields, "access_token": token}, limit)

    out = []
    for media in raw:
        if platform == "instagram":
            metrics = {"likes": media.get("like_count"),
                       "comments": media.get("comments_count")}
            caption = media.get("caption") or ""
            url = media.get("permalink") or ""
            thumb = media.get("thumbnail_url") or media.get("media_url") or ""
            posted_at = media.get("timestamp") or ""
        else:
            metrics = {
                "likes": ((media.get("likes") or {}).get("summary") or {}).get("total_count"),
                "comments": ((media.get("comments") or {}).get("summary") or {}).get("total_count"),
                "shares": (media.get("shares") or {}).get("count"),
            }
            caption = media.get("message") or ""
            url = media.get("permalink_url") or ""
            thumb = media.get("full_picture") or ""
            posted_at = media.get("created_time") or ""
        out.append({
            "external_id": str(media.get("id") or ""),
            "content_type": _pick_content_type(media, platform),
            "status": "posted",
            "posted_at": posted_at,
            "caption": caption,
            "title": (caption.strip().splitlines() or [""])[0][:80],
            "url": url,
            "thumb_url": thumb,
            "source": platform,
            "metrics": {k: v for k, v in metrics.items() if v is not None},
        })
    return [item for item in out if item["external_id"]]


def sync_account(account: dict, limit: int = 50) -> dict:
    """Trage postarile si le scrie in baza de date, reconciliind cu ce era planificat."""
    try:
        items = fetch_media(account, limit=limit)
    except GraphError as exc:
        return {"ok": False, "created": 0, "updated": 0, "linked_planned": 0, "error": str(exc)}
    created = updated = linked = 0
    for item in items:
        external_id = item.pop("external_id")
        result = store.import_post(account["id"], external_id, item)
        if result["created"]:
            created += 1
        elif result["linked_planned"]:
            linked += 1
        else:
            updated += 1
    return {"ok": True, "created": created, "updated": updated, "linked_planned": linked,
            "fetched": len(items), "error": ""}
