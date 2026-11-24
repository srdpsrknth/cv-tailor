"""Calendar dates used in new application identifiers and exports."""

from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def calendar_zone(name: str) -> tzinfo:
    """Resolve an IANA name, using the built-in clock for UTC."""
    if name == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError(f"Cannot load CVTAILOR_TIMEZONE={name!r}; use an available IANA timezone.") from error


def calendar_year(name: str, *, now: datetime | None = None) -> int:
    zone = calendar_zone(name)
    return (now.astimezone(zone) if now is not None else datetime.now(zone)).year
