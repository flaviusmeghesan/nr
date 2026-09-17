"""Extragerea postarilor din JSON-ul pe care il incarca singura pagina.

De ce asa: HTML-ul retelelor se schimba la fiecare redesign, iar un parser
legat de clase CSS se rupe in cateva saptamani. In schimb, fiecare platforma
isi deseneaza feed-ul dintr-un JSON pe care si-l cere singura (GraphQL / XHR).
Noi ascultam raspunsurile alea si cautam obiectele care *arata* a postare -
dupa semnatura campurilor, nu dupa calea in arbore. Asa supravietuim si cand
platforma muta datele in alta parte a raspunsului.

Functiile de aici sunt pure (JSON in -> postari normalizate out), ca sa poata
fi testate fara browser si fara retea.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator


def walk(node: Any) -> Iterator[dict]:
    """Trece prin toate dictionarele din arborele JSON, oricat de adanc."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def pick(source: dict, *keys: str, default=None):
    """Prima cheie prezenta si nevida dintr-o lista de variante."""
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return default


def deep(source: Any, path: str, default=None):
    """deep(obj, 'stats.playCount') - fara sa crape daca lipseste ceva pe drum."""
    current = source
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return default
    return current if current not in (None, "") else default


def as_int(value) -> int | None:
    """Numerele vin uneori ca text, alteori prescurtate ('1.2K', '3,4 mii')."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    multiplier = 1
    if text[-1:].upper() in ("K", "M", "B"):
        multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[text[-1].upper()]
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def timestamp_to_iso(value) -> str:
    """Secunde Unix (sau milisecunde) -> '2026-09-15 10:00:00' ora locala."""
    number = as_int(value)
    if not number:
        return ""
    if number > 10_000_000_000:  # milisecunde
        number //= 1000
    try:
        moment = datetime.fromtimestamp(number, tz=timezone.utc).astimezone()
        return moment.replace(tzinfo=None, microsecond=0).isoformat(sep=" ")
    except (OverflowError, OSError, ValueError):
        return ""


def first_line(text: str, limit: int = 80) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0][:limit] if lines else ""


def dedupe(posts: list[dict]) -> list[dict]:
    """Acelasi obiect apare de multe ori in raspunsuri diferite - pastram
    varianta cu cele mai multe campuri completate."""
    best: dict[str, dict] = {}
    for post in posts:
        key = post.get("external_id") or ""
        if not key:
            continue
        current = best.get(key)
        if current is None or _filled(post) > _filled(current):
            best[key] = post
    return sorted(best.values(), key=lambda p: p.get("posted_at", ""), reverse=True)


def _filled(post: dict) -> int:
    score = sum(1 for value in post.values() if value not in (None, "", {}, []))
    return score + len(post.get("metrics") or {})
