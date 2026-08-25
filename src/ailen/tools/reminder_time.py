"""Conservative Spanish temporal parsing for persistent reminders.

Only explicit, bounded time forms are accepted. Ambiguous expressions such as
"mañana" without a clock time are intentionally rejected rather than guessed.
All returned timestamps are UTC ISO-8601 strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class ReminderRequest:
    """Reminder text plus the explicit temporal phrase supplied by the user."""

    content: str
    when_text: str


_RELATIVE_RE = re.compile(
    r"\ben\s+(\d+)\s*(segundos?|segs?|minutos?|mins?|horas?|hs?|d[ií]as?)\s*$",
    re.IGNORECASE,
)
_DAY_CLOCK_RE = re.compile(
    r"\b(hoy|ma[nñ]ana)\s+(?:a\s+las?\s+|a\s+la\s+)(\d{1,2})(?::(\d{2}))?\s*(?:hs?|h)?\s*$",
    re.IGNORECASE,
)
_DATE_CLOCK_RE = re.compile(
    r"\b(?:el\s+)?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\s+"
    r"(?:a\s+las?\s+|a\s+la\s+)(\d{1,2})(?::(\d{2}))?\s*(?:hs?|h)?\s*$",
    re.IGNORECASE,
)
_REMINDER_PREFIX_RE = re.compile(
    r"^\s*[¿?¡!.,;:]*\s*(?:record[aá]me|recu[eé]rdame|recordame|recordáme)\s+(?:que\s+)?",
    re.IGNORECASE,
)


def extract_reminder_request(text: str) -> ReminderRequest | None:
    """Extract a reminder only when the command contains an explicit due time."""
    collapsed = " ".join((text or "").strip().split())
    prefix = _REMINDER_PREFIX_RE.match(collapsed)
    if not prefix:
        return None

    body = collapsed[prefix.end():].strip()
    if not body:
        return None

    temporal_match: re.Match[str] | None = None
    for pattern in (_RELATIVE_RE, _DAY_CLOCK_RE, _DATE_CLOCK_RE):
        match = pattern.search(body)
        if match:
            temporal_match = match
            break
    if temporal_match is None:
        return None

    content = body[: temporal_match.start()].strip(" ,.-")
    when_text = body[temporal_match.start():].strip()
    if not content or not when_text:
        return None
    return ReminderRequest(content=content, when_text=when_text)


def parse_reminder_when(when_text: str, now: datetime | None = None) -> str:
    """Parse an explicit Spanish time expression and return a UTC ISO timestamp."""
    local_now = now or datetime.now().astimezone()
    if local_now.tzinfo is None:
        local_now = local_now.astimezone()
    clean = " ".join(when_text.strip().split()).lower()

    relative = _RELATIVE_RE.fullmatch(clean)
    if relative:
        amount = int(relative.group(1))
        if amount <= 0:
            raise ValueError("El tiempo relativo debe ser mayor que cero.")
        unit = relative.group(2).lower()
        if unit.startswith(("seg",)):
            delta = timedelta(seconds=amount)
        elif unit.startswith(("min",)):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("hora", "hs", "h")):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return (local_now + delta).astimezone(UTC).isoformat()

    day_clock = _DAY_CLOCK_RE.fullmatch(clean)
    if day_clock:
        day_word = day_clock.group(1).lower()
        hour = int(day_clock.group(2))
        minute = int(day_clock.group(3) or 0)
        _validate_clock(hour, minute)
        day_offset = 1 if "mañ" in day_word or "man" in day_word else 0
        target_date = (local_now + timedelta(days=day_offset)).date()
        target = datetime.combine(target_date, datetime.min.time(), tzinfo=local_now.tzinfo).replace(
            hour=hour, minute=minute
        )
        if day_offset == 0 and target <= local_now:
            raise ValueError("La hora indicada para hoy ya pasó.")
        return target.astimezone(UTC).isoformat()

    date_clock = _DATE_CLOCK_RE.fullmatch(clean)
    if date_clock:
        day = int(date_clock.group(1))
        month = int(date_clock.group(2))
        year_text = date_clock.group(3)
        year = local_now.year if year_text is None else int(year_text)
        if year < 100:
            year += 2000
        hour = int(date_clock.group(4))
        minute = int(date_clock.group(5) or 0)
        _validate_clock(hour, minute)
        try:
            target = datetime(year, month, day, hour, minute, tzinfo=local_now.tzinfo)
        except ValueError as exc:
            raise ValueError("La fecha indicada no es válida.") from exc
        if target <= local_now:
            raise ValueError("La fecha y hora del recordatorio ya pasaron.")
        return target.astimezone(UTC).isoformat()

    raise ValueError(
        "No pude interpretar la hora. Usá por ejemplo 'en 20 minutos', "
        "'mañana a las 10' o '25/08 a las 18:30'."
    )


def _validate_clock(hour: int, minute: int) -> None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("La hora indicada no es válida.")
