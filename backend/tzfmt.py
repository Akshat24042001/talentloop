"""Dates and times for people, in the company's time zone (Settings: time zone, default Asia/Kolkata).

The server runs in UTC, so time.localtime() would put UTC times in candidates' emails. Every time a person reads
(emails, WhatsApp, reminders) goes through here and carries its zone label, for example "Tue 7 Oct 2026, 3:00 PM IST".
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Kolkata"


def zone(name: str | None) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:                     # unknown name or no tz database: India Standard Time
        return timezone(timedelta(hours=5, minutes=30), "IST")


def org_tz(org) -> str:
    return ((getattr(org, "settings", None) or {}).get("timezone") or DEFAULT_TZ) if org else DEFAULT_TZ


def local(ts: float, tz: str | None = None) -> datetime:
    return datetime.fromtimestamp(ts, zone(tz))


def when(ts: float, tz: str | None = None) -> str:
    """Tue 07 Oct 2026, 03:00 PM IST"""
    return local(ts, tz).strftime("%a %d %b %Y, %I:%M %p %Z")


def day(ts: float, tz: str | None = None) -> str:
    return local(ts, tz).strftime("%d %b %Y")


def clock(ts: float, tz: str | None = None) -> str:
    return local(ts, tz).strftime("%I:%M %p %Z").lstrip("0")
