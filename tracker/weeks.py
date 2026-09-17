"""Helpers pentru saptamani ISO (ex. '2026-W38')."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

RO_DAYS = ["Luni", "Marti", "Miercuri", "Joi", "Vineri", "Sambata", "Duminica"]


def week_of(value: date | datetime | str | None) -> str:
    """Returneaza saptamana ISO ('2026-W38') pentru o data / datetime / string ISO."""
    if value is None:
        return current_week()
    if isinstance(value, str):
        value = parse_date(value)
        if value is None:
            return current_week()
    if isinstance(value, datetime):
        value = value.date()
    iso = value.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def current_week(today: date | None = None) -> str:
    return week_of(today or date.today())


def is_week(value: str) -> bool:
    return bool(WEEK_RE.match(value or ""))


def week_bounds(week: str) -> tuple[date, date]:
    """Luni si duminica pentru o saptamana ISO."""
    m = WEEK_RE.match(week or "")
    if not m:
        raise ValueError(f"saptamana invalida: {week!r}")
    year, num = int(m.group(1)), int(m.group(2))
    try:
        monday = date.fromisocalendar(year, num, 1)
    except ValueError as exc:  # saptamana 53 inexistenta
        raise ValueError(f"saptamana invalida: {week!r}") from exc
    return monday, monday + timedelta(days=6)


def shift_week(week: str, delta: int) -> str:
    """Saptamana de peste `delta` saptamani (poate fi negativ)."""
    monday, _ = week_bounds(week)
    return week_of(monday + timedelta(weeks=delta))


def week_label(week: str) -> str:
    """Eticheta prietenoasa: '15 - 21 sep 2026'."""
    monday, sunday = week_bounds(week)
    months = ["ian", "feb", "mar", "apr", "mai", "iun",
              "iul", "aug", "sep", "oct", "nov", "dec"]
    if monday.month == sunday.month:
        return f"{monday.day} - {sunday.day} {months[sunday.month - 1]} {sunday.year}"
    return (f"{monday.day} {months[monday.month - 1]} - "
            f"{sunday.day} {months[sunday.month - 1]} {sunday.year}")


def days_left(week: str, today: date | None = None) -> int:
    """Cate zile mai sunt pana la finalul saptamanii (0 daca s-a terminat)."""
    today = today or date.today()
    _, sunday = week_bounds(week)
    return max(0, (sunday - today).days + (1 if sunday >= today else 0))


# Exporturile Meta Business Suite / TikTok Studio nu vin mereu in ISO -
# incercam si formate uzuale (US, RO, cu luna in litere) inainte sa renuntam.
FALLBACK_FORMATS = (
    "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y",
    "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d",
    "%B %d, %Y %I:%M %p", "%B %d, %Y", "%b %d, %Y %I:%M %p", "%b %d, %Y",
    "%d %B %Y", "%d %b %Y",
)


def parse_datetime(value: str | None) -> datetime | None:
    """Accepta ISO ('2026-09-17T10:30', cu 'Z' sau offset) si cateva formate
    uzuale din exporturi CSV (US, RO, cu luna in litere)."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso_text)
    except ValueError:
        pass
    for fmt in FALLBACK_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_date(value: str | None) -> date | None:
    dt = parse_datetime(value)
    return dt.date() if dt else None
