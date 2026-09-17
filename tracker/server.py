"""Server HTTP local (doar stdlib) care serveste interfata si API-ul JSON."""

from __future__ import annotations

import json
import mimetypes
import re
import unicodedata
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import db, sources, store, weeks
from .db import (CONTENT_LABELS, CONTENT_TYPES, PLATFORM_LABELS, PLATFORMS,
                 STATUS_LABELS, STATUSES)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MAX_UPLOAD = 512 * 1024 * 1024  # 512 MB, cat un video lung
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------------- handlere

def api_bootstrap(_params, _body) -> dict:
    return {
        "clients": store.list_clients(),
        "accounts": store.list_accounts(),
        "members": store.list_members(),
        "week": weeks.current_week(),
        "today": date.today().isoformat(),
        "platforms": [{"value": p, "label": PLATFORM_LABELS[p]} for p in PLATFORMS],
        "content_types": [{"value": c, "label": CONTENT_LABELS[c]} for c in CONTENT_TYPES],
        "statuses": [{"value": s, "label": STATUS_LABELS[s]} for s in STATUSES],
    }


def api_dashboard(params, _body) -> dict:
    return store.dashboard(
        week=_str(params, "week"),
        client_id=_int(params, "client_id"),
        include_inactive=_str(params, "all") == "1",
    )


def api_posts(params, _body) -> dict:
    return {"posts": store.list_posts(
        week=_str(params, "week") or None,
        client_id=_int(params, "client_id"),
        account_id=_int(params, "account_id"),
        status=_str(params, "status") or None,
        limit=_int(params, "limit") or 500,
    )}


def api_sync(account_id: int) -> dict:
    account = store.get_account(account_id, with_token=True)
    if not account:
        raise ApiError("Contul nu exista.", 404)
    result = sources.run(account)
    result["account"] = f"{account['handle']} ({account['platform_label']})"
    return result


def api_import(body: bytes, params) -> dict:
    """Import in formatul CSV *intern* al aplicatiei (vezi sources/internal_csv.py)."""
    text = body.decode("utf-8-sig", "replace")
    if not text.strip():
        raise ApiError("Fisierul CSV e gol.")
    return sources.internal_csv.import_csv(text, default_client_id=_int(params, "client_id"))


def api_import_preview(body: bytes, params) -> dict:
    """Pasul 1 al importului dintr-un export de platforma: arata coloanele
    gasite si o mapare ghicita, ca utilizatorul sa o confirme sau corecteze."""
    text = body.decode("utf-8-sig", "replace")
    if not text.strip():
        raise ApiError("Fisierul CSV e gol.")
    return sources.csvfile.preview(text, platform=_str(params, "platform"))


def api_import_commit(payload: dict) -> dict:
    """Pasul 2: aplica maparea confirmata si scrie postarile."""
    account_id = int(payload.get("account_id") or 0)
    account = store.get_account(account_id)
    if not account:
        raise ApiError("Alege un cont valid pentru import.", 400)
    text = payload.get("csv") or ""
    if not str(text).strip():
        raise ApiError("Lipseste continutul CSV.")
    mapping = payload.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise ApiError("Maparea de coloane trebuie sa fie un obiect.")
    result = sources.csvfile.import_rows(
        str(text), account, mapping, save_profile=bool(payload.get("save_profile", True)))
    result["account"] = f"{account['handle']} ({account['platform_label']})"
    return result


def api_upload(body: bytes, params) -> dict:
    raw_name = _str(params, "filename") or "fisier"
    name = safe_filename(raw_name)
    target = unique_path(db.MEDIA_DIR / name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {"media_path": f"media/{target.name}", "size": len(body), "name": target.name}


def safe_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", unquote(name)).encode("ascii", "ignore").decode()
    name = SAFE_NAME.sub("_", Path(name).name).strip("._") or "fisier"
    return name[:120]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, index = path.stem, path.suffix, 2
    while True:
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


# --------------------------------------------------------------------------- rutare

ROUTES = [
    ("GET",    r"^/api/bootstrap$",        lambda m, p, b: api_bootstrap(p, b)),
    ("GET",    r"^/api/dashboard$",        lambda m, p, b: api_dashboard(p, b)),

    ("GET",    r"^/api/clients$",          lambda m, p, b: {"clients": store.list_clients()}),
    ("POST",   r"^/api/clients$",          lambda m, p, b: store.create_client(b)),
    ("PUT",    r"^/api/clients/(\d+)$",    lambda m, p, b: store.update_client(int(m[0]), b)),
    ("DELETE", r"^/api/clients/(\d+)$",    lambda m, p, b: _deleted(store.delete_client, m[0])),

    ("GET",    r"^/api/accounts$",         lambda m, p, b: {"accounts": store.list_accounts(_int(p, "client_id"))}),
    ("POST",   r"^/api/accounts$",         lambda m, p, b: store.create_account(b)),
    ("PUT",    r"^/api/accounts/(\d+)$",   lambda m, p, b: store.update_account(int(m[0]), b)),
    ("DELETE", r"^/api/accounts/(\d+)$",   lambda m, p, b: _deleted(store.delete_account, m[0])),

    ("GET",    r"^/api/members$",          lambda m, p, b: {"members": store.list_members()}),
    ("POST",   r"^/api/members$",          lambda m, p, b: store.create_member(b)),
    ("DELETE", r"^/api/members/(\d+)$",    lambda m, p, b: _deleted(store.delete_member, m[0])),

    ("GET",    r"^/api/targets$",          lambda m, p, b: {"targets": store.list_targets(_int(p, "account_id"))}),
    ("POST",   r"^/api/targets$",          lambda m, p, b: store.set_target(b)),

    ("GET",    r"^/api/posts$",            lambda m, p, b: api_posts(p, b)),
    ("POST",   r"^/api/posts$",            lambda m, p, b: store.create_post(b)),
    ("PUT",    r"^/api/posts/(\d+)$",      lambda m, p, b: store.update_post(int(m[0]), b)),
    ("DELETE", r"^/api/posts/(\d+)$",      lambda m, p, b: _deleted(store.delete_post, m[0])),

    ("POST",   r"^/api/sync/(\d+)$",       lambda m, p, b: api_sync(int(m[0]))),

    ("POST",   r"^/api/import/commit$",    lambda m, p, b: api_import_commit(b)),
    ("GET",    r"^/api/import-profiles$",  lambda m, p, b: {"profiles": store.list_import_profiles()}),
    ("DELETE", r"^/api/import-profiles/(\d+)$",
                                           lambda m, p, b: _deleted(store.delete_import_profile, m[0])),
]


def _deleted(fn, raw_id) -> dict:
    fn(int(raw_id))
    return {"deleted": True}


def _str(params: dict, key: str) -> str:
    return (params.get(key, [""])[0] or "").strip()


def _int(params: dict, key: str) -> int | None:
    value = _str(params, key)
    try:
        return int(value) if value else None
    except ValueError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "TrackerSocial/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # mai putin zgomot in terminal
        if "/api/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)

    # ---- verbe HTTP
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    # ---- nucleu
    def route(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                return self.handle_api(method, path, params)
            if method == "GET":
                return self.handle_static(path)
            raise ApiError("Metoda nu e permisa aici.", 405)
        except ApiError as exc:
            self.send_json({"error": exc.message}, exc.status)
        except store.ValidationError as exc:
            self.send_json({"error": str(exc)}, 400)
        except BrokenPipeError:
            pass
        except Exception as exc:  # nu vrem sa cada serverul din cauza unui request
            self.send_json({"error": f"Eroare interna: {exc}"}, 500)

    def handle_api(self, method: str, path: str, params: dict):
        body_bytes = self.read_body()

        if method == "POST" and path == "/api/upload":
            return self.send_json(api_upload(body_bytes, params))
        if method == "POST" and path == "/api/import":
            return self.send_json(api_import(body_bytes, params))
        if method == "POST" and path == "/api/import/preview":
            return self.send_json(api_import_preview(body_bytes, params))
        if method == "GET" and path == "/api/export.csv":
            csv_text = sources.internal_csv.export_csv(
                week=_str(params, "week") or None, client_id=_int(params, "client_id"))
            return self.send_bytes(csv_text.encode("utf-8-sig"), "text/csv; charset=utf-8",
                                   extra={"Content-Disposition":
                                          'attachment; filename="postari.csv"'})

        for route_method, pattern, handler in ROUTES:
            match = re.match(pattern, path)
            if not match:
                continue
            if route_method != method:
                continue
            payload = self.parse_json(body_bytes) if method in ("POST", "PUT") else {}
            return self.send_json(handler(match.groups(), params, payload))

        raise ApiError(f"Ruta {method} {path} nu exista.", 404)

    def handle_static(self, path: str):
        if path in ("/", "/index.html"):
            return self.send_file(WEB_DIR / "index.html")
        if path.startswith("/media/"):
            name = safe_filename(path[len("/media/"):])
            return self.send_file(db.MEDIA_DIR / name)
        name = safe_filename(path.lstrip("/"))
        candidate = WEB_DIR / name
        if candidate.is_file():
            return self.send_file(candidate)
        raise ApiError("Fisierul nu exista.", 404)

    # ---- utilitare
    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise ApiError("Fisierul e prea mare (limita 512 MB).", 413)
        return self.rfile.read(length) if length else b""

    def parse_json(self, body: bytes) -> dict:
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError("JSON invalid.") from None
        if not isinstance(payload, dict):
            raise ApiError("Asteptam un obiect JSON.")
        return payload

    def send_json(self, payload, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def send_file(self, path: Path):
        if not path.is_file():
            raise ApiError(f"Nu gasesc {path.name}.", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_bytes(path.read_bytes(), ctype)

    def send_bytes(self, body: bytes, ctype: str, status: int = 200, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    db.init_db()
    db.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return ThreadingHTTPServer((host, port), Handler)
