"""Calendar dates used in new application identifiers and exports."""

from datetime import date, datetime, timezone, tzinfo
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


def configured_timezone_name() -> str | None:
    """``CVTAILOR_TIMEZONE`` as set in the environment, else ``None`` (not configured)."""
    import os

    return os.getenv("CVTAILOR_TIMEZONE", "").strip() or None


def calendar_today(name: str | None = None, *, now: datetime | None = None) -> date:
    """Today's date in the named IANA zone; the machine's local date when no zone is set."""
    if not name:
        return (now or datetime.now()).date()
    zone = calendar_zone(name)
    return (now.astimezone(zone) if now is not None else datetime.now(zone)).date()
