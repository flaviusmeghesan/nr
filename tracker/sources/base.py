"""Contractul comun al surselor de postari: toate produc acelasi dict normalizat,
pe care `tracker.store.import_post()` il scrie in baza de date si il
reconciliaza cu ce era deja planificat. O sursa noua (alt agregator, alt API)
inseamna un fisier nou aici - restul aplicatiei nu se schimba.
"""

from __future__ import annotations

import hashlib

# Campurile pe care le poate produce o sursa (subset acceptat de store.import_post).
POST_FIELDS = ("external_id", "content_type", "status", "posted_at", "planned_for",
               "title", "caption", "url", "author", "thumb_url", "media_path",
               "source", "metrics")


def build_post(*, external_id: str = "", content_type: str = "video",
              status: str = "posted", posted_at: str = "", title: str = "",
              caption: str = "", url: str = "", author: str = "", thumb_url: str = "",
              source: str = "manual", metrics: dict | None = None) -> dict:
    """Construieste un dict normalizat, cu valorile implicite completate."""
    return {
        "external_id": external_id, "content_type": content_type, "status": status,
        "posted_at": posted_at, "title": title[:200], "caption": caption,
        "url": url, "author": author, "thumb_url": thumb_url,
        "source": source, "metrics": {k: v for k, v in (metrics or {}).items() if v is not None},
    }


def fallback_external_id(*parts: str) -> str:
    """ID stabil generat cand sursa nu ofera unul (ex. rand CSV fara ID de postare).

    Foloseste hash-ul continutului, nu al pozitiei randului, ca reimportul
    aceluiasi fisier sa produca acelasi ID si sa nu creeze duplicate.
    """
    raw = "|".join(p.strip().lower() for p in parts if p)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"gen-{digest}"


def normalize_metrics(raw: dict) -> dict:
    out = {}
    for key, value in raw.items():
        if value in (None, ""):
            continue
        text = str(value).replace(",", "").replace(" ", "")
        try:
            out[key] = int(float(text))
        except ValueError:
            out[key] = value
    return out


class SourceError(RuntimeError):
    """Eroare de la o sursa externa (retea, autentificare, format neasteptat)."""
