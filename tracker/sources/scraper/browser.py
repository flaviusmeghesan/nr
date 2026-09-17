"""Conduce un browser real (Playwright) peste paginile pe care le administrezi.

De ce browser real si nu cereri HTTP simple: Instagram si Facebook nu mai arata
nimic fara sesiune, iar TikTok cere JavaScript ca sa-si construiasca feed-ul. Un
browser adevarat vede exact ce vezi tu cand deschizi pagina.

Sesiunea se tine intr-un profil de browser propriu (`data/browser-profile/`),
la fel ca un Chrome obisnuit. Te loghezi *o singura data*, manual
(`python3 run.py --login`), iar dupa aia rularile se fac in fundal, fara fereastra.
Parolele nu trec prin codul asta si nu sunt salvate nicaieri de aplicatie - stau
in profilul de browser, ca in orice Chrome.

Playwright e optional: daca nu e instalat, restul aplicatiei merge normal, iar
sincronizarea prin scraper spune clar ce ai de instalat.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from ...db import ROOT

PROFILE_DIR = ROOT / "data" / "browser-profile"
DEBUG_DIR = ROOT / "data" / "debug"

# Daca ai deja un Chrome/Chromium instalat si nu vrei sa mai descarci unul prin
# `playwright install`, pune calea in TRACKER_BROWSER_PATH. Ex. pe Windows:
#   set TRACKER_BROWSER_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
BROWSER_PATH = os.environ.get("TRACKER_BROWSER_PATH", "").strip()

PAGE_TIMEOUT = 45_000     # ms pana se incarca pagina
SETTLE_MS = 3_500         # cat asteptam dupa incarcare, sa apuce sa ceara datele
SCROLL_STEPS = 4          # de cate ori derulam, ca sa incarce mai multe postari
SCROLL_PAUSE_MS = 2_000

# JSON-uri pe care platformele le pun direct in HTML
INLINE_JSON_PATTERNS = (
    re.compile(r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
               re.DOTALL),
    re.compile(r'<script[^>]*id="SIGI_STATE"[^>]*>(.*?)</script>', re.DOTALL),
    re.compile(r'<script[^>]*type="application/json"[^>]*>(\{.*?\})</script>', re.DOTALL),
)

PROFILE_URLS = {
    "instagram": "https://www.instagram.com/{handle}/",
    "tiktok": "https://www.tiktok.com/@{handle}",
    "facebook": "https://www.facebook.com/{handle}/",
}


class ScraperUnavailable(RuntimeError):
    """Playwright sau browserul lipsesc - mesajul spune exact ce ai de facut."""


class ScrapeFailed(RuntimeError):
    """Pagina s-a incarcat dar nu am gasit postari (login expirat, alt format...)."""


def is_available() -> tuple[bool, str]:
    """(merge?, mesaj de ajutor). Verificam si pachetul, si browserul descarcat."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, ("Playwright nu e instalat. Ruleaza:\n"
                       "    pip install playwright\n"
                       "    playwright install chromium")
    return True, ""


def _launch_options(headless: bool) -> dict:
    options = {
        "user_data_dir": str(PROFILE_DIR),
        "headless": headless,
        "viewport": {"width": 1366, "height": 900},
        "locale": "ro-RO",
    }
    if BROWSER_PATH:
        options["executable_path"] = BROWSER_PATH
    return options


def _collect_inline_json(html: str) -> list:
    out = []
    for pattern in INLINE_JSON_PATTERNS:
        for match in pattern.findall(html or ""):
            try:
                out.append(json.loads(match))
            except (ValueError, TypeError):
                continue
    return out


def _dump_debug(platform: str, handle: str, html: str, payloads: list, page=None) -> Path:
    """Cand nu gasim postari, salvam tot ce am vazut, ca sa se poata repara rapid."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = DEBUG_DIR / f"{platform}-{handle.strip('@') or 'cont'}-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pagina.html").write_text(html or "", encoding="utf-8")
    (folder / "raspunsuri.json").write_text(
        json.dumps(payloads[:60], ensure_ascii=False, indent=2)[:8_000_000],
        encoding="utf-8")
    if page is not None:
        try:
            page.screenshot(path=str(folder / "ecran.png"), full_page=False)
        except Exception:  # un screenshot ratat nu trebuie sa ascunda eroarea reala
            pass
    return folder


def fetch_payloads(platform: str, handle: str, headless: bool = True,
                   scrolls: int = SCROLL_STEPS) -> tuple[list, str, Path | None]:
    """Deschide profilul si intoarce (raspunsuri JSON, html, folder debug daca a esuat).

    Ascultam raspunsurile de retea ale paginii - adica exact datele din care
    isi deseneaza ea feed-ul - in loc sa citim HTML-ul randat.
    """
    ok, message = is_available()
    if not ok:
        raise ScraperUnavailable(message)
    if platform not in PROFILE_URLS:
        raise ScrapeFailed(f"Platforma {platform!r} nu are scraper.")

    from playwright.sync_api import sync_playwright

    url = PROFILE_URLS[platform].format(handle=handle.strip().lstrip("@"))
    payloads: list = []
    html = ""

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(**_launch_options(headless))
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(response):
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            try:
                payloads.append(response.json())
            except Exception:
                pass  # raspuns gol / deja consumat / nu e JSON valid - il sarim

        page.on("response", on_response)

        try:
            page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            page.wait_for_timeout(SETTLE_MS)
            for _ in range(max(0, scrolls)):
                page.mouse.wheel(0, 2400)
                page.wait_for_timeout(SCROLL_PAUSE_MS)
            html = page.content()
        except Exception as exc:
            folder = _dump_debug(platform, handle, html, payloads, page)
            context.close()
            raise ScrapeFailed(
                f"Nu am putut incarca {url} ({exc}). Detalii salvate in {folder}.") from None

        payloads.extend(_collect_inline_json(html))
        debug_folder = None
        if not payloads:
            debug_folder = _dump_debug(platform, handle, html, payloads, page)
        context.close()

    return payloads, html, debug_folder


def open_login_window() -> None:
    """Deschide un browser vizibil, o singura data, ca sa te loghezi manual.

    Sesiunea ramane salvata in profil, deci rularile urmatoare merg in fundal.
    """
    ok, message = is_available()
    if not ok:
        raise ScraperUnavailable(message)

    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("\n  Se deschide un browser. Logheaza-te in conturile de care ai nevoie")
    print("  (Instagram / Facebook / TikTok), apoi INCHIDE fereastra.")
    print(f"  Sesiunea se salveaza in {PROFILE_DIR}\n")

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(**_launch_options(headless=False))
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://www.instagram.com/accounts/login/", timeout=PAGE_TIMEOUT)
        except Exception:
            pass
        # Asteptam pana inchide utilizatorul fereastra.
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass
    print("  Sesiune salvata.\n")
