"""Logica de business: clienti, conturi, tinte saptamanale, postari, dashboard."""

from __future__ import annotations

import json

from . import db, weeks
from .db import ANY_WEEK, CONTENT_LABELS, CONTENT_TYPES, PLATFORM_LABELS, PLATFORMS, STATUSES


class ValidationError(ValueError):
    """Date invalide trimise de interfata."""


def _clean(value, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _one_of(value, allowed, field: str, default=None):
    value = _clean(value) or (default or "")
    if value not in allowed:
        raise ValidationError(f"{field} invalid: {value!r} (acceptat: {', '.join(allowed)})")
    return value


# --------------------------------------------------------------------------- clienti

def list_clients(include_inactive: bool = True) -> list[dict]:
    sql = "SELECT * FROM clients"
    if not include_inactive:
        sql += " WHERE active = 1"
    return db.query(sql + " ORDER BY active DESC, name COLLATE NOCASE")


def get_client(client_id: int) -> dict | None:
    return db.query_one("SELECT * FROM clients WHERE id = ?", (client_id,))


def create_client(payload: dict) -> dict:
    name = _clean(payload.get("name"))
    if not name:
        raise ValidationError("Clientul are nevoie de un nume.")
    if db.query_one("SELECT id FROM clients WHERE name = ? COLLATE NOCASE", (name,)):
        raise ValidationError(f"Exista deja un client cu numele {name!r}.")
    cur = db.execute(
        "INSERT INTO clients (name, notes, active, created_at) VALUES (?, ?, ?, ?)",
        (name, _clean(payload.get("notes")), int(bool(payload.get("active", True))), db.now()),
    )
    return get_client(cur.lastrowid)


def update_client(client_id: int, payload: dict) -> dict:
    current = get_client(client_id)
    if not current:
        raise ValidationError("Clientul nu exista.")
    name = _clean(payload.get("name", current["name"])) or current["name"]
    clash = db.query_one(
        "SELECT id FROM clients WHERE name = ? COLLATE NOCASE AND id <> ?", (name, client_id))
    if clash:
        raise ValidationError(f"Exista deja un client cu numele {name!r}.")
    db.execute(
        "UPDATE clients SET name = ?, notes = ?, active = ? WHERE id = ?",
        (name, _clean(payload.get("notes", current["notes"])),
         int(bool(payload.get("active", current["active"]))), client_id),
    )
    return get_client(client_id)


def delete_client(client_id: int) -> None:
    db.execute("DELETE FROM clients WHERE id = ?", (client_id,))


# --------------------------------------------------------------------------- conturi

def list_accounts(client_id: int | None = None) -> list[dict]:
    sql = ("SELECT a.*, c.name AS client_name FROM accounts a "
           "JOIN clients c ON c.id = a.client_id")
    params: tuple = ()
    if client_id:
        sql += " WHERE a.client_id = ?"
        params = (client_id,)
    rows = db.query(sql + " ORDER BY c.name COLLATE NOCASE, a.platform, a.handle")
    for row in rows:
        row["platform_label"] = PLATFORM_LABELS[row["platform"]]
        row["has_token"] = bool(row.pop("access_token", ""))
    return rows


def get_account(account_id: int, with_token: bool = False) -> dict | None:
    row = db.query_one(
        "SELECT a.*, c.name AS client_name FROM accounts a "
        "JOIN clients c ON c.id = a.client_id WHERE a.id = ?", (account_id,))
    if row:
        row["platform_label"] = PLATFORM_LABELS[row["platform"]]
        row["has_token"] = bool(row["access_token"])
        if not with_token:
            row.pop("access_token", None)
    return row


def create_account(payload: dict) -> dict:
    client_id = int(payload.get("client_id") or 0)
    if not get_client(client_id):
        raise ValidationError("Alege un client valid pentru cont.")
    platform = _one_of(payload.get("platform"), PLATFORMS, "Platforma")
    handle = _clean(payload.get("handle"))
    if not handle:
        raise ValidationError("Contul are nevoie de un handle (ex. @numeclient).")
    if db.query_one(
        "SELECT id FROM accounts WHERE client_id = ? AND platform = ? AND handle = ?",
        (client_id, platform, handle),
    ):
        raise ValidationError(f"Contul {handle} pe {PLATFORM_LABELS[platform]} exista deja.")
    cur = db.execute(
        "INSERT INTO accounts (client_id, platform, handle, external_id, access_token, "
        "active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (client_id, platform, handle, _clean(payload.get("external_id")),
         _clean(payload.get("access_token")), int(bool(payload.get("active", True))), db.now()),
    )
    return get_account(cur.lastrowid)


def update_account(account_id: int, payload: dict) -> dict:
    current = get_account(account_id, with_token=True)
    if not current:
        raise ValidationError("Contul nu exista.")
    # Tokenul se pastreaza daca nu e trimis explicit (interfata nu il afiseaza).
    token = current["access_token"]
    if "access_token" in payload:
        token = _clean(payload.get("access_token"))
    db.execute(
        "UPDATE accounts SET handle = ?, external_id = ?, access_token = ?, active = ? "
        "WHERE id = ?",
        (_clean(payload.get("handle", current["handle"])) or current["handle"],
         _clean(payload.get("external_id", current["external_id"])),
         token,
         int(bool(payload.get("active", current["active"]))),
         account_id),
    )
    return get_account(account_id)


def delete_account(account_id: int) -> None:
    db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


# --------------------------------------------------------------------------- echipa

def list_members() -> list[dict]:
    return db.query("SELECT * FROM members ORDER BY active DESC, name COLLATE NOCASE")


def create_member(payload: dict) -> dict:
    name = _clean(payload.get("name"))
    if not name:
        raise ValidationError("Membrul are nevoie de un nume.")
    if db.query_one("SELECT id FROM members WHERE name = ? COLLATE NOCASE", (name,)):
        raise ValidationError(f"{name} exista deja in echipa.")
    cur = db.execute("INSERT INTO members (name, active) VALUES (?, 1)", (name,))
    return db.query_one("SELECT * FROM members WHERE id = ?", (cur.lastrowid,))


def delete_member(member_id: int) -> None:
    db.execute("DELETE FROM members WHERE id = ?", (member_id,))


# --------------------------------------------------------------------------- tinte

def list_targets(account_id: int | None = None) -> list[dict]:
    sql = "SELECT * FROM targets"
    params: tuple = ()
    if account_id:
        sql += " WHERE account_id = ?"
        params = (account_id,)
    return db.query(sql + " ORDER BY account_id, week, content_type", params)


def set_target(payload: dict) -> dict:
    account_id = int(payload.get("account_id") or 0)
    if not get_account(account_id):
        raise ValidationError("Contul nu exista.")
    week = _clean(payload.get("week")) or ANY_WEEK
    if week != ANY_WEEK and not weeks.is_week(week):
        raise ValidationError(f"Saptamana invalida: {week!r} (format 2026-W38).")
    content_type = _one_of(payload.get("content_type"), CONTENT_TYPES, "Tipul de continut")
    try:
        count = int(payload.get("target_count", 0))
    except (TypeError, ValueError):
        raise ValidationError("Numarul tinta trebuie sa fie un intreg.") from None
    if count < 0:
        raise ValidationError("Numarul tinta nu poate fi negativ.")
    if count == 0:
        db.execute(
            "DELETE FROM targets WHERE account_id = ? AND week = ? AND content_type = ?",
            (account_id, week, content_type))
        return {"account_id": account_id, "week": week,
                "content_type": content_type, "target_count": 0}
    db.execute(
        "INSERT INTO targets (account_id, week, content_type, target_count) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(account_id, week, content_type) DO UPDATE SET target_count = excluded.target_count",
        (account_id, week, content_type, count),
    )
    return db.query_one(
        "SELECT * FROM targets WHERE account_id = ? AND week = ? AND content_type = ?",
        (account_id, week, content_type))


def effective_targets(account_id: int, week: str) -> dict[str, int]:
    """Tintele pentru o saptamana: default recurent ('*') suprascris de tinta pe saptamana."""
    result: dict[str, int] = {}
    for row in db.query(
        "SELECT content_type, target_count FROM targets WHERE account_id = ? AND week = ?",
        (account_id, ANY_WEEK),
    ):
        result[row["content_type"]] = row["target_count"]
    for row in db.query(
        "SELECT content_type, target_count FROM targets WHERE account_id = ? AND week = ?",
        (account_id, week),
    ):
        result[row["content_type"]] = row["target_count"]
    return result


# --------------------------------------------------------------------------- postari

POST_FIELDS = ("account_id", "content_type", "status", "planned_for", "posted_at", "title",
               "caption", "url", "author", "media_path", "thumb_url", "source",
               "external_id", "metrics")


def derive_week(status: str, posted_at: str, planned_for: str, fallback: str = "") -> str:
    """Saptamana in care 'conteaza' postarea: data postarii, altfel data planificata."""
    if status == "posted" and posted_at:
        return weeks.week_of(posted_at)
    if planned_for:
        return weeks.week_of(planned_for)
    if posted_at:
        return weeks.week_of(posted_at)
    return fallback or weeks.current_week()


def _post_row(row: dict) -> dict:
    row["metrics"] = db.load_metrics(row.get("metrics", "{}"))
    row["content_label"] = CONTENT_LABELS.get(row["content_type"], row["content_type"])
    row["platform_label"] = PLATFORM_LABELS.get(row.get("platform", ""), "")
    return row


def list_posts(week: str | None = None, client_id: int | None = None,
               account_id: int | None = None, status: str | None = None,
               limit: int = 500) -> list[dict]:
    sql = ("SELECT p.*, a.platform, a.handle, a.client_id, c.name AS client_name "
           "FROM posts p JOIN accounts a ON a.id = p.account_id "
           "JOIN clients c ON c.id = a.client_id WHERE 1 = 1")
    params: list = []
    if week:
        sql += " AND p.week = ?"
        params.append(week)
    if client_id:
        sql += " AND a.client_id = ?"
        params.append(int(client_id))
    if account_id:
        sql += " AND p.account_id = ?"
        params.append(int(account_id))
    if status:
        sql += " AND p.status = ?"
        params.append(status)
    sql += (" ORDER BY CASE p.status WHEN 'posted' THEN 0 ELSE 1 END, "
            "COALESCE(NULLIF(p.posted_at, ''), p.planned_for) DESC, p.id DESC LIMIT ?")
    params.append(int(limit))
    return [_post_row(r) for r in db.query(sql, tuple(params))]


def get_post(post_id: int) -> dict | None:
    row = db.query_one(
        "SELECT p.*, a.platform, a.handle, a.client_id, c.name AS client_name "
        "FROM posts p JOIN accounts a ON a.id = p.account_id "
        "JOIN clients c ON c.id = a.client_id WHERE p.id = ?", (post_id,))
    return _post_row(row) if row else None


def _normalize_post(payload: dict, current: dict | None = None) -> dict:
    base = dict(current or {})
    data = {}
    account_id = int(payload.get("account_id") or base.get("account_id") or 0)
    if not get_account(account_id):
        raise ValidationError("Alege un cont valid pentru postare.")
    data["account_id"] = account_id
    data["content_type"] = _one_of(
        payload.get("content_type", base.get("content_type", "video")),
        CONTENT_TYPES, "Tipul de continut", "video")
    data["status"] = _one_of(
        payload.get("status", base.get("status", "planned")), STATUSES, "Statusul", "planned")
    data["planned_for"] = _clean(payload.get("planned_for", base.get("planned_for", "")))
    data["posted_at"] = _clean(payload.get("posted_at", base.get("posted_at", "")))
    if data["planned_for"] and not weeks.parse_date(data["planned_for"]):
        raise ValidationError(f"Data planificata invalida: {data['planned_for']!r}")
    if data["posted_at"] and not weeks.parse_date(data["posted_at"]):
        raise ValidationError(f"Data postarii invalida: {data['posted_at']!r}")
    if data["status"] == "posted" and not data["posted_at"]:
        data["posted_at"] = db.now()
    for field in ("title", "caption", "url", "author", "media_path", "thumb_url"):
        data[field] = _clean(payload.get(field, base.get(field, "")))
    data["source"] = _clean(payload.get("source", base.get("source", "manual"))) or "manual"
    data["external_id"] = _clean(payload.get("external_id", base.get("external_id", "")))
    metrics = payload.get("metrics", base.get("metrics", {}))
    if isinstance(metrics, str):
        metrics = db.load_metrics(metrics)
    data["metrics"] = json.dumps(metrics if isinstance(metrics, dict) else {})
    data["week"] = derive_week(data["status"], data["posted_at"], data["planned_for"],
                               base.get("week", ""))
    return data


def create_post(payload: dict) -> dict:
    data = _normalize_post(payload)
    columns = ", ".join(POST_FIELDS) + ", week, created_at, updated_at"
    holders = ", ".join(["?"] * (len(POST_FIELDS) + 3))
    values = tuple(data[f] for f in POST_FIELDS) + (data["week"], db.now(), db.now())
    cur = db.execute(f"INSERT INTO posts ({columns}) VALUES ({holders})", values)
    return get_post(cur.lastrowid)


def update_post(post_id: int, payload: dict) -> dict:
    current = get_post(post_id)
    if not current:
        raise ValidationError("Postarea nu exista.")
    data = _normalize_post(payload, current)
    assignments = ", ".join(f"{f} = ?" for f in POST_FIELDS)
    values = tuple(data[f] for f in POST_FIELDS) + (data["week"], db.now(), post_id)
    db.execute(f"UPDATE posts SET {assignments}, week = ?, updated_at = ? WHERE id = ?", values)
    return get_post(post_id)


def delete_post(post_id: int) -> None:
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))


def _find_reconcile_target(account_id: int, external_id: str, week: str,
                           content_type: str) -> dict | None:
    """Postarea existenta pe care o suprascrie un import: mai intai un match exact pe
    external_id (reimport), altfel o intrare planificata/programata/idee, nesincronizata
    inca, pe acelasi cont/tip/saptamana (colegul a bifat-o din timp, acum vine dovada).
    """
    exact = db.query_one(
        "SELECT * FROM posts WHERE account_id = ? AND external_id = ? AND external_id <> ''",
        (account_id, external_id))
    if exact:
        return exact
    return db.query_one(
        "SELECT * FROM posts WHERE account_id = ? AND content_type = ? AND week = ? "
        "AND status IN ('idea', 'planned', 'scheduled') "
        "AND (external_id = '' OR external_id IS NULL) ORDER BY id LIMIT 1",
        (account_id, content_type, week))


def import_post(account_id: int, external_id: str, payload: dict) -> dict:
    """Scrie o postare venita dintr-o sursa externa (CSV sau Graph API).

    Reconciliaza automat cu ce era deja in aplicatie: daca exista o postare cu
    acelasi external_id, o actualizeaza (metrici/link proaspete); daca exista o
    postare planificata nesincronizata pe acelasi cont/tip/saptamana, o leaga de
    ea in loc sa creeze un duplicat. Camp completate manual (titlu, text, autor,
    fisier) nu sunt suprascrise.

    Intoarce {"post": ..., "created": bool, "linked_planned": bool}.
    """
    external_id = _clean(external_id)
    if not external_id:
        raise ValidationError("Importul are nevoie de un identificator de postare.")
    week = derive_week("posted", payload.get("posted_at", ""), "", "")
    content_type = payload.get("content_type", "video")
    target = _find_reconcile_target(account_id, external_id, week, content_type)
    data = dict(payload, account_id=account_id, external_id=external_id, status="posted")

    if target:
        current = get_post(target["id"])
        keep = {k: current[k] for k in ("title", "caption", "author", "media_path")
                if current.get(k)}
        was_planned = current["status"] != "posted" and not current["external_id"]
        post = update_post(target["id"], {**data, **keep})
        return {"post": post, "created": False, "linked_planned": was_planned}

    return {"post": create_post(data), "created": True, "linked_planned": False}


# Alias pastrat pentru compatibilitate cu apelurile mai vechi.
upsert_external = import_post


# --------------------------------------------------------------------------- profiluri de import

def get_import_profile(platform: str, name: str = "implicit") -> dict | None:
    row = db.query_one(
        "SELECT * FROM import_profiles WHERE platform = ? AND name = ?", (platform, name))
    if row:
        row["mapping"] = db.load_metrics(row["mapping"])
    return row


def list_import_profiles() -> list[dict]:
    rows = db.query("SELECT * FROM import_profiles ORDER BY platform, name")
    for row in rows:
        row["mapping"] = db.load_metrics(row["mapping"])
    return rows


def save_import_profile(platform: str, mapping: dict, name: str = "implicit") -> dict:
    platform = _one_of(platform, PLATFORMS, "Platforma")
    payload = json.dumps({k: v for k, v in mapping.items() if v})
    db.execute(
        "INSERT INTO import_profiles (platform, name, mapping, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(platform, name) DO UPDATE SET mapping = excluded.mapping, "
        "updated_at = excluded.updated_at",
        (platform, name, payload, db.now(), db.now()))
    return get_import_profile(platform, name)


def delete_import_profile(profile_id: int) -> None:
    db.execute("DELETE FROM import_profiles WHERE id = ?", (profile_id,))


# --------------------------------------------------------------------------- dashboard

def _empty_totals() -> dict:
    return {"target": 0, "posted": 0, "planned": 0, "remaining": 0}


def _add_totals(dest: dict, src: dict) -> None:
    for key in dest:
        dest[key] += src[key]


def dashboard(week: str | None = None, client_id: int | None = None,
              include_inactive: bool = False) -> dict:
    week = week if week and weeks.is_week(week) else weeks.current_week()
    sql = ("SELECT a.*, c.name AS client_name, c.active AS client_active FROM accounts a "
           "JOIN clients c ON c.id = a.client_id WHERE 1 = 1")
    params: list = []
    if client_id:
        sql += " AND a.client_id = ?"
        params.append(int(client_id))
    if not include_inactive:
        sql += " AND a.active = 1 AND c.active = 1"
    accounts = db.query(sql + " ORDER BY c.name COLLATE NOCASE, a.platform, a.handle",
                        tuple(params))

    counts: dict[tuple[int, str, str], int] = {}
    for row in db.query(
        "SELECT account_id, content_type, status, COUNT(*) AS n FROM posts "
        "WHERE week = ? GROUP BY account_id, content_type, status", (week,)
    ):
        counts[(row["account_id"], row["content_type"], row["status"])] = row["n"]

    clients_out: dict[int, dict] = {}
    grand = _empty_totals()

    for account in accounts:
        targets = effective_targets(account["id"], week)
        seen_types = set(targets) | {
            ct for (aid, ct, _st) in counts if aid == account["id"]}
        rows = []
        acc_totals = _empty_totals()
        for content_type in CONTENT_TYPES:
            if content_type not in seen_types:
                continue
            target = int(targets.get(content_type, 0))
            posted = counts.get((account["id"], content_type, "posted"), 0)
            planned = sum(counts.get((account["id"], content_type, st), 0)
                          for st in ("planned", "scheduled", "idea"))
            row = {"content_type": content_type,
                   "label": CONTENT_LABELS[content_type],
                   "target": target, "posted": posted, "planned": planned,
                   "remaining": max(0, target - posted)}
            rows.append(row)
            _add_totals(acc_totals, row)
        if not rows:
            continue
        bucket = clients_out.setdefault(account["client_id"], {
            "id": account["client_id"], "name": account["client_name"],
            "totals": _empty_totals(), "accounts": []})
        bucket["accounts"].append({
            "id": account["id"], "platform": account["platform"],
            "platform_label": PLATFORM_LABELS[account["platform"]],
            "handle": account["handle"], "totals": acc_totals, "rows": rows})
        _add_totals(bucket["totals"], acc_totals)
        _add_totals(grand, acc_totals)

    overdue = db.query(
        "SELECT COUNT(*) AS n FROM posts p JOIN accounts a ON a.id = p.account_id "
        "WHERE p.status <> 'posted' AND p.week < ?" +
        (" AND a.client_id = ?" if client_id else ""),
        (week, int(client_id)) if client_id else (week,))[0]["n"]

    return {
        "week": week,
        "label": weeks.week_label(week),
        "days_left": weeks.days_left(week),
        "is_current": week == weeks.current_week(),
        "totals": grand,
        "overdue": overdue,
        "clients": sorted(clients_out.values(), key=lambda c: c["name"].lower()),
    }
