"""Surse de postari: manual (din interfata), CSV (principal - vezi csvfile.py)
si Graph API (optional, per cont - vezi graph.py). Vezi README pentru cand
sa folosesti fiecare.
"""

from . import csvfile, graph, internal_csv  # noqa: F401


def run(account: dict, limit: int = 50) -> dict:
    """Sincronizare live pentru un cont (doar Meta Graph API, optional si per cont).

    TikTok nu are un echivalent fara aprobare - foloseste importul CSV
    (export din TikTok Studio) in loc de sincronizare live.
    """
    platform = account.get("platform")
    if platform in ("instagram", "facebook"):
        return graph.sync_account(account, limit=limit)
    return {"ok": False, "created": 0, "updated": 0, "linked_planned": 0,
            "error": f"{platform!r} nu are sincronizare live - foloseste importul CSV "
                     f"(Setari > Import) cu exportul din TikTok Studio."}
