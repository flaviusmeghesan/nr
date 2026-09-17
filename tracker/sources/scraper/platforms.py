"""Recunoasterea postarilor in JSON-ul fiecarei platforme.

Fiecare platforma are un `looks_like_post()` (semnatura de campuri dupa care
identificam un obiect-postare oriunde ar sta in raspuns) si un `extract()`
care il transforma in formatul intern.

Toleram mai multe denumiri pentru acelasi camp, pentru ca platformele au
variante paralele in acelasi raspuns (ex. Instagram trimite si `like_count`,
si `edge_liked_by.count`, in functie de endpoint).
"""

from __future__ import annotations

from ..base import build_post
from .parse import as_int, deep, dedupe, first_line, pick, timestamp_to_iso, walk

# --------------------------------------------------------------------------- Instagram

# media_type din API-ul Instagram: 1 = imagine, 2 = video, 8 = album/carusel
IG_MEDIA_TYPES = {1: "photo", 2: "video", 8: "carousel"}


def ig_looks_like_post(node: dict) -> bool:
    has_code = bool(pick(node, "code", "shortcode"))
    has_time = bool(pick(node, "taken_at", "taken_at_timestamp", "device_timestamp"))
    return has_code and has_time


def ig_extract_one(node: dict) -> dict:
    code = str(pick(node, "code", "shortcode", default=""))
    caption = (deep(node, "caption.text")
               or deep(node, "edge_media_to_caption.edges.0.node.text")
               or "")

    if deep(node, "product_type") in ("clips", "reels"):
        content_type = "video"
    elif pick(node, "media_type") in IG_MEDIA_TYPES:
        content_type = IG_MEDIA_TYPES[pick(node, "media_type")]
    elif deep(node, "__typename") == "GraphSidecar" or node.get("carousel_media"):
        content_type = "carousel"
    elif node.get("is_video") or deep(node, "__typename") == "GraphVideo":
        content_type = "video"
    else:
        content_type = "photo"

    metrics = {
        "likes": as_int(pick(node, "like_count") or deep(node, "edge_liked_by.count")
                        or deep(node, "edge_media_preview_like.count")),
        "comments": as_int(pick(node, "comment_count")
                           or deep(node, "edge_media_to_comment.count")
                           or deep(node, "edge_media_to_parent_comment.count")),
        "views": as_int(pick(node, "play_count", "video_play_count", "view_count")
                        or deep(node, "video_view_count")),
    }

    return build_post(
        external_id=str(pick(node, "pk", "id", default=code)).split("_")[0],
        content_type=content_type,
        posted_at=timestamp_to_iso(pick(node, "taken_at", "taken_at_timestamp",
                                        "device_timestamp")),
        title=first_line(caption),
        caption=caption,
        url=f"https://www.instagram.com/p/{code}/" if code else "",
        thumb_url=(deep(node, "image_versions2.candidates.0.url")
                   or pick(node, "display_url", "thumbnail_src", default="")),
        source="scraper",
        metrics={k: v for k, v in metrics.items() if v is not None},
    )


# --------------------------------------------------------------------------- TikTok

def tt_looks_like_post(node: dict) -> bool:
    has_id = bool(pick(node, "id", "awemeId", "aweme_id"))
    has_time = bool(pick(node, "createTime", "create_time", "createTimeISO"))
    has_shape = "stats" in node or "statsV2" in node or "video" in node or "desc" in node
    return has_id and has_time and has_shape


def tt_extract_one(node: dict, handle: str = "") -> dict:
    video_id = str(pick(node, "id", "awemeId", "aweme_id", default=""))
    caption = str(pick(node, "desc", "description", default=""))
    stats = node.get("stats") or node.get("statsV2") or {}

    metrics = {
        "views": as_int(pick(stats, "playCount", "play_count")),
        "likes": as_int(pick(stats, "diggCount", "digg_count")),
        "comments": as_int(pick(stats, "commentCount", "comment_count")),
        "shares": as_int(pick(stats, "shareCount", "share_count")),
    }

    author = (deep(node, "author.uniqueId") or deep(node, "author.unique_id")
              or handle.lstrip("@"))
    url = f"https://www.tiktok.com/@{author}/video/{video_id}" if author and video_id else ""

    return build_post(
        external_id=video_id,
        content_type="video",  # pe TikTok tot ce se posteaza e video
        posted_at=timestamp_to_iso(pick(node, "createTime", "create_time")),
        title=first_line(caption),
        caption=caption,
        url=url,
        thumb_url=(deep(node, "video.cover") or deep(node, "video.originCover")
                   or deep(node, "video.dynamicCover") or ""),
        source="scraper",
        metrics={k: v for k, v in metrics.items() if v is not None},
    )


# --------------------------------------------------------------------------- Facebook

def fb_looks_like_post(node: dict) -> bool:
    has_time = bool(pick(node, "creation_time", "created_time", "publish_time",
                         "timestamp"))
    has_id = bool(pick(node, "post_id", "id", "story_id", "legacy_story_hideable_id"))
    has_shape = ("feedback" in node or "message" in node or "wwwURL" in node
                 or "permalink_url" in node)
    return has_time and has_id and has_shape


def fb_extract_one(node: dict) -> dict:
    post_id = str(pick(node, "post_id", "story_id", "id", default=""))
    message = (deep(node, "message.text") or pick(node, "message", default="") or "")
    if not isinstance(message, str):
        message = ""

    attachment_type = (deep(node, "attachments.0.media.__typename")
                       or deep(node, "attachments.0.__typename") or "")
    if "Video" in str(attachment_type):
        content_type = "video"
    elif "Album" in str(attachment_type) or deep(node, "attachments.0.subattachments"):
        content_type = "carousel"
    else:
        content_type = "photo"

    metrics = {
        "likes": as_int(deep(node, "feedback.reaction_count.count")
                        or deep(node, "feedback.reactors.count")),
        "comments": as_int(deep(node, "feedback.comment_count.total_count")
                           or deep(node, "feedback.comments.total_count")
                           or deep(node, "feedback.total_comment_count")),
        "shares": as_int(deep(node, "feedback.share_count.count")
                         or deep(node, "feedback.reshares.count")),
    }

    return build_post(
        external_id=post_id,
        content_type=content_type,
        posted_at=timestamp_to_iso(pick(node, "creation_time", "created_time",
                                        "publish_time", "timestamp")),
        title=first_line(message),
        caption=message,
        url=str(pick(node, "wwwURL", "permalink_url", "url", default="")),
        thumb_url=(deep(node, "attachments.0.media.image.uri")
                   or deep(node, "full_picture") or ""),
        source="scraper",
        metrics={k: v for k, v in metrics.items() if v is not None},
    )


# --------------------------------------------------------------------------- dispecer

EXTRACTORS = {
    "instagram": (ig_looks_like_post, lambda node, handle: ig_extract_one(node)),
    "tiktok": (tt_looks_like_post, tt_extract_one),
    "facebook": (fb_looks_like_post, lambda node, handle: fb_extract_one(node)),
}


def extract_posts(platform: str, payloads: list, handle: str = "") -> list[dict]:
    """Scoate toate postarile dintr-o lista de raspunsuri JSON captate."""
    if platform not in EXTRACTORS:
        return []
    looks_like, extract_one = EXTRACTORS[platform]
    found = []
    for payload in payloads:
        for node in walk(payload):
            if not looks_like(node):
                continue
            try:
                post = extract_one(node, handle)
            except (TypeError, ValueError, AttributeError):
                continue
            if post["external_id"] and post["posted_at"]:
                found.append(post)
    return dedupe(found)
