"""Alias-uri de coloane pentru recunoasterea automata a exporturilor.

Nu tintim un schema exact de la Meta Business Suite sau TikTok Studio - ambele
isi schimba denumirile de coloane de la o versiune la alta, fara preaviz. In
schimb, pentru fiecare camp intern tinem o lista de variante de nume intalnite
in exporturi (engleza, romana, cu spatii/underscore/majuscule diferite) si
potrivim dupa un antet normalizat. Cand o platforma redenumeste o coloana si
ghicitul nu mai nimereste, utilizatorul o mapeaza manual din interfata o
singura data - maparea se salveaza in `import_profiles` si e refolosita.
"""

from __future__ import annotations

import re

from ..db import CONTENT_TYPES, PLATFORMS, STATUSES

# Campurile pe care le poate umple o mapare de import, in ordinea din UI.
TARGET_FIELDS = (
    "external_id", "posted_at", "content_type", "title", "caption", "url",
    "author", "thumb_url",
    "metric_views", "metric_likes", "metric_comments", "metric_shares", "metric_reach",
)

FIELD_LABELS = {
    "external_id": "ID postare (recomandat, evita duplicate)",
    "posted_at": "Data publicarii",
    "content_type": "Tip continut",
    "title": "Titlu",
    "caption": "Text / descriere",
    "url": "Link catre postare",
    "author": "Autor",
    "thumb_url": "Link poza/copertă",
    "metric_views": "Vizualizari",
    "metric_likes": "Aprecieri",
    "metric_comments": "Comentarii",
    "metric_shares": "Distribuiri",
    "metric_reach": "Acoperire (reach)",
}

REQUIRED_FIELDS = ("posted_at",)
METRIC_FIELDS = tuple(f for f in TARGET_FIELDS if f.startswith("metric_"))


def normalize_header(header: str) -> str:
    """'Publish Time' / 'publish_time' / 'Publish  time:' -> 'publish time'."""
    text = re.sub(r"[_\-/.:]+", " ", str(header or "").strip().lower())
    return re.sub(r"\s+", " ", text).strip()


# Fiecare intrare: campul intern -> set de antete normalizate cunoscute.
ALIASES: dict[str, set[str]] = {
    "external_id": {"post id", "id", "media id", "video id", "content id", "item id"},
    "posted_at": {"publish time", "post time", "date", "created", "created time",
                  "create time", "creation time", "video create time",
                  "post date", "date posted", "publish date", "time", "data",
                  "data postarii", "data publicarii"},
    "content_type": {"post type", "type", "media type", "content type", "format", "tip"},
    "title": {"title", "post title", "name", "video title", "titlu"},
    "caption": {"caption", "description", "message", "text", "post text",
                "video description", "descriere", "text postare"},
    "url": {"permalink", "post link", "link", "url", "share url", "post url",
            "video link", "web link"},
    "author": {"author", "posted by", "created by", "creator", "autor", "postat de"},
    "thumb_url": {"thumbnail", "thumbnail url", "cover", "cover image",
                  "cover image url", "picture", "image url"},
    "metric_views": {"views", "video views", "plays", "play count",
                     "total views", "vizualizari"},
    "metric_likes": {"likes", "like count", "reactions", "total likes", "aprecieri"},
    "metric_comments": {"comments", "comment count", "total comments", "comentarii"},
    "metric_shares": {"shares", "share count", "total shares", "distribuiri"},
    "metric_reach": {"reach", "impressions", "total reach", "acoperire"},
}


def guess_mapping(headers: list[str]) -> dict[str, str | None]:
    """Pentru fiecare camp tinta, ghiceste antetul CSV cel mai probabil."""
    normalized = {normalize_header(h): h for h in headers}
    mapping: dict[str, str | None] = {}
    for field in TARGET_FIELDS:
        found = None
        for candidate in ALIASES.get(field, ()):
            if candidate in normalized:
                found = normalized[candidate]
                break
        mapping[field] = found
    return mapping


# Alias-uri de *valori* - reutilizate si de importul in format intern.
PLATFORM_ALIASES = {"ig": "instagram", "insta": "instagram", "instagram": "instagram",
                    "fb": "facebook", "facebook": "facebook",
                    "tt": "tiktok", "tik tok": "tiktok", "tiktok": "tiktok"}

TYPE_ALIASES = {"video": "video", "reel": "video", "reels": "video", "clip": "video",
                "poza": "photo", "photo": "photo", "image": "photo", "imagine": "photo",
                "foto": "photo", "picture": "photo", "link": "photo", "share": "photo",
                "carusel": "carousel", "carousel": "carousel", "carousel album": "carousel",
                "album": "carousel", "story": "story", "stories": "story",
                "insta story": "story"}

STATUS_ALIASES = {"postat": "posted", "posted": "posted", "gata": "posted",
                  "published": "posted", "live": "posted",
                  "planificat": "planned", "planned": "planned", "plan": "planned",
                  "programat": "scheduled", "scheduled": "scheduled",
                  "idee": "idea", "idea": "idea", "draft": "idea"}


def map_value(raw: str, aliases: dict, allowed: tuple, default: str) -> str:
    key = (raw or "").strip().lower()
    mapped = aliases.get(key, key)
    return mapped if mapped in allowed else default


def guess_content_type(raw: str, default: str = "video") -> str:
    return map_value(raw, TYPE_ALIASES, CONTENT_TYPES, default)


def guess_status(raw: str, default: str = "posted") -> str:
    return map_value(raw, STATUS_ALIASES, STATUSES, default)


def guess_platform(raw: str, default: str = "") -> str:
    return map_value(raw, PLATFORM_ALIASES, PLATFORMS, default)
