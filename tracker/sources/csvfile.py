"""Import generic din CSV, condus de o mapare de coloane.

Fluxul din interfata:
  1. `preview(text, platform)` - citeste antetele si primele randuri, ghiceste
     o mapare (din profilul salvat pentru platforma, altfel din alias-uri).
  2. Utilizatorul confirma/corecteaza maparea.
  3. `import_rows(text, account, mapping)` - aplica maparea pe tot fisierul,
     scrie postarile prin `store.import_post()` (care face reconcilierea cu
     ce era deja planificat) si intoarce un raport.

Asta functioneaza cu orice export care are un antet si randuri - Meta
Business Suite, TikTok Studio, sau un Excel salvat ca CSV de la client.
"""

from __future__ import annotations

import csv
import io

from .. import store, weeks
from . import presets
from .base import build_post, fallback_external_id, normalize_metrics

PREVIEW_ROWS = 5
MAX_ERRORS = 20


def _read(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    rows = [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
    return headers, rows


def preview(text: str, platform: str = "") -> dict:
    headers, rows = _read(text)
    if not headers:
        return {"headers": [], "sample": [], "mapping": {}, "fields": [],
                "profile_name": "", "error": "Fisierul CSV e gol sau nu are antet."}

    profile = store.get_import_profile(platform) if platform else None
    saved_mapping = profile["mapping"] if profile else {}
    guessed = presets.guess_mapping(headers)
    # Preferam maparea salvata; daca ea refera o coloana care nu mai exista in
    # fisierul curent (platforma a redenumit-o), cadem pe ghicitul automat.
    mapping = {field: saved_mapping.get(field) if saved_mapping.get(field) in headers
              else guessed.get(field) for field in presets.TARGET_FIELDS}

    return {
        "headers": headers,
        "sample": rows[:PREVIEW_ROWS],
        "row_count": len(rows),
        "mapping": mapping,
        "fields": [{"key": f, "label": presets.FIELD_LABELS[f],
                   "required": f in presets.REQUIRED_FIELDS} for f in presets.TARGET_FIELDS],
        "profile_name": profile["name"] if profile else "",
    }


def _row_value(row: dict[str, str], mapping: dict, field: str) -> str:
    header = mapping.get(field)
    return row.get(header, "").strip() if header else ""


def import_rows(text: str, account: dict, mapping: dict[str, str | None],
                save_profile: bool = True) -> dict:
    headers, rows = _read(text)
    if not headers:
        return {"created": 0, "updated": 0, "linked_planned": 0, "skipped": 0,
                "errors": ["Fisierul CSV e gol sau nu are antet."]}

    missing = [f for f in presets.REQUIRED_FIELDS if not mapping.get(f)]
    if missing:
        labels = ", ".join(presets.FIELD_LABELS[f] for f in missing)
        return {"created": 0, "updated": 0, "linked_planned": 0, "skipped": len(rows),
                "errors": [f"Lipseste maparea pentru: {labels}."]}

    if save_profile:
        store.save_import_profile(account["platform"], mapping)

    created = updated = linked = skipped = 0
    errors: list[str] = []

    for index, row in enumerate(rows, start=2):
        try:
            posted_raw = _row_value(row, mapping, "posted_at")
            posted_dt = weeks.parse_datetime(posted_raw)
            if not posted_dt:
                skipped += 1
                if len(errors) < MAX_ERRORS:
                    errors.append(f"Randul {index}: data nerecunoscuta ({posted_raw!r}).")
                continue

            url = _row_value(row, mapping, "url")
            title = _row_value(row, mapping, "title")
            external_id = (_row_value(row, mapping, "external_id") or
                           (url if url else fallback_external_id(
                               account["handle"], title, posted_raw)))

            metrics = normalize_metrics({
                m.removeprefix("metric_"): _row_value(row, mapping, m)
                for m in presets.METRIC_FIELDS
            })

            payload = build_post(
                external_id=external_id,
                content_type=presets.guess_content_type(
                    _row_value(row, mapping, "content_type"),
                    default="video" if account["platform"] == "tiktok" else "photo"),
                status="posted",
                posted_at=posted_dt.isoformat(sep=" "),
                title=title,
                caption=_row_value(row, mapping, "caption"),
                url=url,
                author=_row_value(row, mapping, "author"),
                thumb_url=_row_value(row, mapping, "thumb_url"),
                source="csv",
                metrics=metrics,
            )
            result = store.import_post(account["id"], external_id, payload)
            if result["created"]:
                created += 1
            elif result["linked_planned"]:
                linked += 1
            else:
                updated += 1
        except (store.ValidationError, ValueError) as exc:
            skipped += 1
            if len(errors) < MAX_ERRORS:
                errors.append(f"Randul {index}: {exc}")

    return {"created": created, "updated": updated, "linked_planned": linked,
            "skipped": skipped, "errors": errors}
