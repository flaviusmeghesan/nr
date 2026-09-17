"""Surse de postari, in ordinea in care le folosesti:

  scraper/      - automat, prin browserul tau, pentru paginile pe care le administrezi
  csvfile.py    - import din exportul platformei (Business Suite / TikTok Studio)
  internal_csv.py - import/export in formatul propriu al aplicatiei
  graph.py      - Meta Graph API, optional, doar daca faci App Review

Toate produc acelasi dict normalizat si trec prin `store.import_post()`, care
face reconcilierea cu ce era deja planificat.
"""

from . import csvfile, graph, internal_csv, scraper  # noqa: F401


def run(account: dict, limit: int = 50) -> dict:
    """Sincronizeaza un cont, alegand cea mai buna sursa disponibila.

    Preferam scraperul prin browser (merge pe orice cont, fara aprobari). Daca
    Playwright nu e instalat si contul are token Meta, cadem pe Graph API.
    """
    platform = account.get("platform")
    available, _hint = scraper.is_available()

    if available:
        return scraper.sync_account(account, limit=limit)

    if platform in ("instagram", "facebook") and account.get("access_token"):
        return graph.sync_account(account, limit=limit)

    return {"ok": False, "created": 0, "updated": 0, "linked_planned": 0,
            "error": _hint or "Nicio sursa de sincronizare disponibila."}
