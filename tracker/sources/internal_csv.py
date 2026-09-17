"""Import / export in formatul CSV *intern* al aplicatiei (nu exportul unei
platforme - pentru asta vezi `csvfile.py`). Util pentru raport catre client
si pentru a introduce rapid postari planificate dintr-un tabel simplu.
"""

from __future__ import annotations

import csv
import io

from .. import store
from . import presets

COLUMNS = ["client", "platforma", "cont", "tip", "status", "planificat_pe",
           "postat_la", "titlu", "link", "autor", "descriere"]


def export_csv(week: str | None = None, client_id: int | None = None) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for post in store.list_posts(week=week, client_id=client_id, limit=5000):
        writer.writerow([
            post["client_name"], post["platform"], post["handle"], post["content_type"],
            post["status"], post["planned_for"], post["posted_at"], post["title"],
            post["url"], post["author"], post["caption"].replace("\n", " ").strip(),
        ])
    return buffer.getvalue()


def import_csv(text: str, default_client_id: int | None = None) -> dict:
    """Importa randuri CSV. Conturile lipsa sunt create automat sub clientul potrivit."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return {"imported": 0, "skipped": 0, "errors": ["Fisierul CSV e gol."]}
    headers = {(h or "").strip().lower(): h for h in reader.fieldnames}

    def cell(row: dict, *names: str) -> str:
        for name in names:
            if name in headers:
                return (row.get(headers[name]) or "").strip()
        return ""

    clients = {c["name"].lower(): c for c in store.list_clients()}
    accounts = {(a["client_id"], a["platform"], a["handle"].lower()): a
                for a in store.list_accounts()}
    imported = skipped = 0
    errors: list[str] = []

    for index, row in enumerate(reader, start=2):
        try:
            platform = presets.guess_platform(cell(row, "platforma", "platform", "retea"))
            if not platform:
                skipped += 1
                continue
            client_name = cell(row, "client", "nume client")
            if client_name:
                client = clients.get(client_name.lower())
                if not client:
                    client = store.create_client({"name": client_name})
                    clients[client_name.lower()] = client
                client_id = client["id"]
            elif default_client_id:
                client_id = int(default_client_id)
            else:
                skipped += 1
                errors.append(f"Randul {index}: lipseste clientul.")
                continue

            handle = cell(row, "cont", "handle", "account") or f"@{platform}"
            account = accounts.get((client_id, platform, handle.lower()))
            if not account:
                account = store.create_account(
                    {"client_id": client_id, "platform": platform, "handle": handle})
                accounts[(client_id, platform, handle.lower())] = account

            posted_at = cell(row, "postat_la", "posted_at", "data postarii", "data")
            planned_for = cell(row, "planificat_pe", "planned_for", "data planificata")
            status = presets.guess_status(cell(row, "status", "stare"),
                                          "posted" if posted_at else "planned")
            store.create_post({
                "account_id": account["id"],
                "content_type": presets.guess_content_type(
                    cell(row, "tip", "type", "content_type", "format")),
                "status": status,
                "posted_at": posted_at,
                "planned_for": planned_for,
                "title": cell(row, "titlu", "title", "nume"),
                "url": cell(row, "link", "url", "permalink"),
                "author": cell(row, "autor", "author", "postat_de"),
                "caption": cell(row, "descriere", "caption", "text"),
                "source": "csv",
            })
            imported += 1
        except (store.ValidationError, ValueError) as exc:
            skipped += 1
            errors.append(f"Randul {index}: {exc}")
    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}
