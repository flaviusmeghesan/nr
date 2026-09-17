"""Sincronizare prin browser propriu, pentru paginile pe care le administrezi.

Foloseste-l doar pe conturi la care ai drept de acces (ale tale sau ale
clientilor tai). Ruleaza local, cu sesiunea ta de browser, la volum mic.
"""

from __future__ import annotations

import re

from ... import store
from .browser import (DEBUG_DIR, PROFILE_DIR, ScrapeFailed, ScraperUnavailable,
                      fetch_payloads, is_available, open_login_window)
from .platforms import extract_posts

__all__ = ["sync_account", "parse_profile_url", "is_available", "open_login_window",
           "PROFILE_DIR", "DEBUG_DIR"]

# Recunoasterea platformei + handle-ului dintr-un link lipit de utilizator.
URL_PATTERNS = [
    ("instagram", re.compile(
        r"(?:https?://)?(?:www\.)?instagram\.com/(?!p/|reel/|reels/|stories/|explore/)"
        r"([A-Za-z0-9._]+)", re.I)),
    ("tiktok", re.compile(
        r"(?:https?://)?(?:www\.)?tiktok\.com/@([A-Za-z0-9._]+)", re.I)),
    ("facebook", re.compile(
        r"(?:https?://)?(?:www\.|web\.|m\.)?facebook\.com/"
        r"(?!profile\.php|pages/|groups/|watch|share)([A-Za-z0-9.\-]+)", re.I)),
    ("facebook", re.compile(
        r"(?:https?://)?(?:www\.)?facebook\.com/profile\.php\?id=(\d+)", re.I)),
]


def parse_profile_url(url: str) -> dict | None:
    """'https://www.tiktok.com/@central' -> {'platform': 'tiktok', 'handle': '@central'}.

    Accepta si un handle simplu daca platforma e evidenta din link.
    """
    text = (url or "").strip()
    if not text:
        return None
    for platform, pattern in URL_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        handle = match.group(1).strip("/.")
        if not handle or handle.lower() in ("home", "login", "accounts"):
            continue
        return {"platform": platform, "handle": f"@{handle}",
                "url": text if text.startswith("http") else ""}
    return None


def sync_account(account: dict, limit: int = 50, headless: bool = True) -> dict:
    """Trage postarile publicate de pe profilul contului si le scrie in aplicatie."""
    platform = account.get("platform", "")
    handle = account.get("handle", "")

    try:
        payloads, _html, debug_folder = fetch_payloads(platform, handle, headless=headless)
    except ScraperUnavailable as exc:
        return _result(False, str(exc))
    except ScrapeFailed as exc:
        return _result(False, str(exc))

    posts = extract_posts(platform, payloads, handle)
    if not posts:
        hint = ("Nu am gasit nicio postare. Cel mai probabil sesiunea a expirat - "
                "ruleaza `python3 run.py --login` si logheaza-te din nou.")
        if debug_folder:
            hint += f" Ce a vazut browserul e salvat in {debug_folder}."
        return _result(False, hint)

    created = updated = linked = 0
    for post in posts[:limit]:
        external_id = post.pop("external_id")
        try:
            outcome = store.import_post(account["id"], external_id, post)
        except store.ValidationError:
            continue
        if outcome["created"]:
            created += 1
        elif outcome["linked_planned"]:
            linked += 1
        else:
            updated += 1

    return _result(True, "", created=created, updated=updated, linked_planned=linked,
                   fetched=len(posts))


def _result(ok: bool, error: str, **counts) -> dict:
    return {"ok": ok, "error": error, "created": counts.get("created", 0),
            "updated": counts.get("updated", 0),
            "linked_planned": counts.get("linked_planned", 0),
            "fetched": counts.get("fetched", 0)}
