"""Logica de business: clienti, conturi, tinte saptamanale, postari, dashboard."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from difflib import SequenceMatcher

from . import db, weeks
from .db import (ANY_WEEK, CONTENT_LABELS, CONTENT_TYPES, PERIODS, PLATFORM_LABELS,
                 PLATFORMS, POST_CONTENT_TYPES, STATUSES)


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

def list_targets(client_id: int | None = None, account_id: int | None = None) -> list[dict]:
    sql = ("SELECT t.*, c.name AS client_name, a.platform, a.handle "
           "FROM targets t "
           "LEFT JOIN clients c ON c.id = t.client_id "
           "LEFT JOIN accounts a ON a.id = t.account_id WHERE 1 = 1")
    params: list = []
    if client_id:
        sql += " AND (t.client_id = ? OR a.client_id = ?)"
        params += [int(client_id), int(client_id)]
    if account_id:
        sql += " AND t.account_id = ?"
        params.append(int(account_id))
    return db.query(sql + " ORDER BY t.period, t.period_key, t.content_type", tuple(params))


def _valid_period_key(period: str, key: str) -> bool:
    if key == ANY_WEEK:
        return True
    return weeks.is_week(key) if period == "week" else weeks.is_month(key)


def set_target(payload: dict) -> dict:
    """Creeaza/actualizeaza o tinta. `target_max` gol inseamna acelasi numar ca min.

    Tinta e fie pe client (toate platformele la un loc), fie pe un cont anume.
    """
    client_id = int(payload.get("client_id") or 0) or None
    account_id = int(payload.get("account_id") or 0) or None
    if account_id:
        if not get_account(account_id):
            raise ValidationError("Contul nu exista.")
        client_id = None
    elif client_id:
        if not get_client(client_id):
            raise ValidationError("Clientul nu exista.")
    else:
        raise ValidationError("Tinta are nevoie de un client sau de un cont.")

    period = _one_of(payload.get("period", "week"), PERIODS, "Perioada", "week")
    period_key = _clean(payload.get("period_key")) or ANY_WEEK
    if not _valid_period_key(period, period_key):
        raise ValidationError(
            f"Perioada invalida: {period_key!r} "
            f"(asteptat {'2026-W38' if period == 'week' else '2026-09'} sau *).")
    content_type = _one_of(payload.get("content_type"), CONTENT_TYPES, "Tipul de continut")

    try:
        minimum = int(payload.get("target_min", payload.get("target_count", 0)) or 0)
        raw_max = payload.get("target_max")
        maximum = int(raw_max) if raw_max not in (None, "") else minimum
    except (TypeError, ValueError):
        raise ValidationError("Tintele trebuie sa fie numere intregi.") from None
    if minimum < 0 or maximum < 0:
        raise ValidationError("Tintele nu pot fi negative.")
    if maximum < minimum:
        minimum, maximum = maximum, minimum

    owner_sql = "client_id = ?" if client_id else "account_id = ?"
    owner_id = client_id or account_id

    if minimum == 0 and maximum == 0:
        db.execute(
            f"DELETE FROM targets WHERE {owner_sql} AND period = ? AND period_key = ? "
            "AND content_type = ?", (owner_id, period, period_key, content_type))
        return {"deleted": True, "content_type": content_type, "period": period}

    existing = db.query_one(
        f"SELECT id FROM targets WHERE {owner_sql} AND period = ? AND period_key = ? "
        "AND content_type = ?", (owner_id, period, period_key, content_type))
    if existing:
        db.execute("UPDATE targets SET target_min = ?, target_max = ? WHERE id = ?",
                   (minimum, maximum, existing["id"]))
        target_id = existing["id"]
    else:
        cursor = db.execute(
            "INSERT INTO targets (client_id, account_id, period, period_key, content_type, "
            "target_min, target_max) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (client_id, account_id, period, period_key, content_type, minimum, maximum))
        target_id = cursor.lastrowid
    return db.query_one("SELECT * FROM targets WHERE id = ?", (target_id,))


def delete_target(target_id: int) -> None:
    db.execute("DELETE FROM targets WHERE id = ?", (target_id,))


def effective_targets(period: str, period_key: str, client_id: int | None = None,
                      account_id: int | None = None) -> dict[str, dict]:
    """Tintele valabile intr-o perioada: recurentele ('*') suprascrise de cele punctuale."""
    owner_sql = "client_id = ?" if client_id else "account_id = ?"
    owner_id = client_id or account_id
    result: dict[str, dict] = {}
    for key in (ANY_WEEK, period_key):
        for row in db.query(
            f"SELECT content_type, target_min, target_max FROM targets "
            f"WHERE {owner_sql} AND period = ? AND period_key = ?",
            (owner_id, period, key),
        ):
            result[row["content_type"]] = {"min": row["target_min"],
                                           "max": row["target_max"]}
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


# Cat de departe pot fi doua publicari ca sa fie acelasi material distribuit pe
# mai multe retele (postezi reel-ul azi pe IG, maine pe TikTok).
SAME_CONTENT_HOURS = 36
# Cand nu avem text de comparat, ne bazam doar pe timp - si atunci strangem mult
# fereastra, ca sa nu lipim doua materiale diferite din aceeasi zi.
SAME_CONTENT_HOURS_BLIND = 3
SIMILAR_TEXT_RATIO = 0.65

_NOISE_RE = re.compile(r"(https?://\S+|[#@]\w+)")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _fingerprint(title: str, caption: str) -> str:
    """Textul postarii, curatat, ca sa putem compara aceeasi piesa intre retele.

    Scoatem linkuri, hashtaguri, mentiuni, emoji si punctuatie - alea difera de
    la o platforma la alta chiar cand materialul e identic.
    """
    text = f"{title or ''} {caption or ''}".lower()
    text = _NOISE_RE.sub(" ", text)
    text = _NON_WORD_RE.sub(" ", text)
    return " ".join(text.split())[:300]


def _similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= SIMILAR_TEXT_RATIO


def _assign_content_group(post_id: int, account_id: int, content_type: str,
                          when: str, title: str = "", caption: str = "") -> str:
    """Leaga postarea de acelasi material publicat pe alta platforma, daca exista.

    Asa se numara "4 postari pe saptamana" o singura data, chiar daca acelasi
    video apare pe Instagram, Facebook si TikTok. Potrivirea se face pe textul
    postarii plus o fereastra de timp; fara text, doar pe o fereastra stransa.
    """
    moment = weeks.parse_datetime(when)
    own_group = f"g{post_id}"
    if not moment:
        return own_group

    account = get_account(account_id)
    if not account:
        return own_group

    mine = _fingerprint(title, caption)
    candidates = db.query(
        "SELECT p.id, p.content_group, p.posted_at, p.planned_for, p.title, p.caption "
        "FROM posts p JOIN accounts a ON a.id = p.account_id "
        "WHERE a.client_id = ? AND p.content_type = ? AND p.account_id <> ? "
        "AND p.id <> ? AND p.content_group <> ''",
        (account["client_id"], content_type, account_id, post_id))

    best: tuple[float, str] | None = None
    for row in candidates:
        other_moment = weeks.parse_datetime(row["posted_at"] or row["planned_for"])
        if not other_moment:
            continue
        distance = abs(other_moment - moment)
        theirs = _fingerprint(row["title"], row["caption"])

        if _similar(mine, theirs):
            if distance > timedelta(hours=SAME_CONTENT_HOURS):
                continue
        elif mine or theirs:
            continue  # amandoua au text, dar diferit -> materiale diferite
        elif distance > timedelta(hours=SAME_CONTENT_HOURS_BLIND):
            continue  # fara text, ne bazam doar pe timp, si atunci strict

        seconds = distance.total_seconds()
        if best is None or seconds < best[0]:
            best = (seconds, row["content_group"])

    return best[1] if best else own_group


def _write_derived(post_id: int, data: dict, keep_group: str = "") -> None:
    """Completeaza campurile calculate: saptamana, luna si grupul de continut."""
    when = data["posted_at"] or data["planned_for"]
    month = weeks.month_of(when) if when else weeks.current_month()
    group = keep_group or _assign_content_group(
        post_id, data["account_id"], data["content_type"], when,
        data.get("title", ""), data.get("caption", ""))
    db.execute("UPDATE posts SET month = ?, content_group = ? WHERE id = ?",
               (month, group, post_id))


def create_post(payload: dict) -> dict:
    data = _normalize_post(payload)
    columns = ", ".join(POST_FIELDS) + ", week, created_at, updated_at"
    holders = ", ".join(["?"] * (len(POST_FIELDS) + 3))
    values = tuple(data[f] for f in POST_FIELDS) + (data["week"], db.now(), db.now())
    cur = db.execute(f"INSERT INTO posts ({columns}) VALUES ({holders})", values)
    _write_derived(cur.lastrowid, data)
    return get_post(cur.lastrowid)


def update_post(post_id: int, payload: dict) -> dict:
    current = get_post(post_id)
    if not current:
        raise ValidationError("Postarea nu exista.")
    data = _normalize_post(payload, current)
    assignments = ", ".join(f"{f} = ?" for f in POST_FIELDS)
    values = tuple(data[f] for f in POST_FIELDS) + (data["week"], db.now(), post_id)
    db.execute(f"UPDATE posts SET {assignments}, week = ?, updated_at = ? WHERE id = ?", values)
    # daca data sau tipul s-au schimbat, regrupam; altfel pastram grupul existent
    same_slot = (current["content_type"] == data["content_type"]
                 and current["posted_at"] == data["posted_at"]
                 and current["planned_for"] == data["planned_for"])
    _write_derived(post_id, data, keep_group=current["content_group"] if same_slot else "")
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
        dest[key] += src.get(key, 0)


def _count(period: str, period_key: str, *, client_id: int | None = None,
           account_id: int | None = None, content_type: str = "any",
           statuses: tuple = ("posted",)) -> int:
    """Cate bucati de continut intra intr-o tinta.

    Pentru tintele pe client numaram *grupuri* de continut, nu postari: acelasi
    material publicat pe Instagram, Facebook si TikTok se pune la socoteala o
    singura data. Pentru tintele pe un cont anume numaram postarile lui.
    """
    column = "p.week" if period == "week" else "p.month"
    sql = ("SELECT COUNT(DISTINCT COALESCE(NULLIF(p.content_group, ''), 'p' || p.id)) AS n "
           if client_id else "SELECT COUNT(*) AS n ")
    sql += ("FROM posts p JOIN accounts a ON a.id = p.account_id "
            f"WHERE {column} = ? AND p.status IN ({','.join('?' * len(statuses))})")
    params: list = [period_key, *statuses]
    if client_id:
        sql += " AND a.client_id = ?"
        params.append(int(client_id))
    if account_id:
        sql += " AND p.account_id = ?"
        params.append(int(account_id))
    if content_type != "any":
        sql += " AND p.content_type = ?"
        params.append(content_type)
    return db.query(sql, tuple(params))[0]["n"]


def _build_rows(period_keys: dict, *, client_id: int | None = None,
                account_id: int | None = None) -> list[dict]:
    """Randurile de progres pentru un client sau un cont, pe ambele perioade."""
    rows = []
    for period, period_key in period_keys.items():
        targets = effective_targets(period, period_key, client_id=client_id,
                                    account_id=account_id)
        for content_type in CONTENT_TYPES:
            target = targets.get(content_type)
            if not target:
                continue
            posted = _count(period, period_key, client_id=client_id,
                            account_id=account_id, content_type=content_type)
            planned = _count(period, period_key, client_id=client_id,
                             account_id=account_id, content_type=content_type,
                             statuses=("idea", "planned", "scheduled"))
            rows.append({
                "content_type": content_type,
                "label": CONTENT_LABELS[content_type],
                "period": period,
                "period_label": "saptamana" if period == "week" else "luna",
                "target": target["min"],
                "target_min": target["min"],
                "target_max": target["max"],
                "is_range": target["max"] > target["min"],
                "posted": posted,
                "planned": planned,
                "remaining": max(0, target["min"] - posted),
                "done": posted >= target["min"],
            })
    return rows


def dashboard(week: str | None = None, client_id: int | None = None,
              include_inactive: bool = False) -> dict:
    week = week if week and weeks.is_week(week) else weeks.current_week()
    month = weeks.month_of_week(week)
    period_keys = {"week": week, "month": month}

    sql = ("SELECT a.*, c.name AS client_name FROM accounts a "
           "JOIN clients c ON c.id = a.client_id WHERE 1 = 1")
    params: list = []
    if client_id:
        sql += " AND a.client_id = ?"
        params.append(int(client_id))
    if not include_inactive:
        sql += " AND a.active = 1 AND c.active = 1"
    accounts = db.query(sql + " ORDER BY c.name COLLATE NOCASE, a.platform, a.handle",
                        tuple(params))

    clients_out: dict[int, dict] = {}
    grand = _empty_totals()

    for account in accounts:
        bucket = clients_out.setdefault(account["client_id"], {
            "id": account["client_id"], "name": account["client_name"],
            "rows": [], "totals": _empty_totals(), "accounts": []})
        account_rows = _build_rows(period_keys, account_id=account["id"])
        account_totals = _empty_totals()
        for row in account_rows:
            _add_totals(account_totals, row)
        bucket["accounts"].append({
            "id": account["id"], "platform": account["platform"],
            "platform_label": PLATFORM_LABELS[account["platform"]],
            "handle": account["handle"], "rows": account_rows,
            "totals": account_totals})
        _add_totals(bucket["totals"], account_totals)

    # Tintele pe client (cele care se numara o data pe toate platformele).
    for client_row in clients_out.values():
        client_rows = _build_rows(period_keys, client_id=client_row["id"])
        client_row["rows"] = client_rows
        for row in client_rows:
            _add_totals(client_row["totals"], row)
        _add_totals(grand, client_row["totals"])

    overdue = db.query(
        "SELECT COUNT(*) AS n FROM posts p JOIN accounts a ON a.id = p.account_id "
        "WHERE p.status <> 'posted' AND p.week < ?" +
        (" AND a.client_id = ?" if client_id else ""),
        (week, int(client_id)) if client_id else (week,))[0]["n"]

    return {
        "week": week,
        "label": weeks.week_label(week),
        "month": month,
        "month_label": weeks.month_label(month),
        "days_left": weeks.days_left(week),
        "is_current": week == weeks.current_week(),
        "totals": grand,
        "overdue": overdue,
        "clients": sorted(clients_out.values(), key=lambda c: c["name"].lower()),
    }
