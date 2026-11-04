"""Appointment slot generation (opening hours, closed dates, notice, conflicts)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

from .business import DAY_KEYS, DAY_NAMES_AR, DAY_NAMES_EN, Business


def get_tz(name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # tzdata missing (e.g. bare Windows): Gulf zones have no DST
        fixed = {"Asia/Dubai": 4, "Asia/Muscat": 4, "Asia/Riyadh": 3, "Asia/Qatar": 3, "Asia/Kuwait": 3, "Asia/Bahrain": 3}
        if name in fixed:
            return timezone(timedelta(hours=fixed[name]), name)
        return timezone.utc


@dataclass(frozen=True)
class Busy:
    start: datetime
    end: datetime


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def slots_for_day(
    biz: Business,
    day: date,
    minutes: int,
    now: datetime,
    busy: list[Busy] | None = None,
    capacity: int = 1,
) -> list[datetime]:
    """All bookable start times on `day` for a service lasting `minutes`."""
    tz = get_tz(biz.timezone)
    now = now.astimezone(tz)
    if day in biz.closed_dates:
        return []
    earliest = now + timedelta(minutes=biz.min_notice_minutes)
    out = []
    for start_m, end_m in biz.hours.get(DAY_KEYS[day.weekday()], []):
        t = start_m
        while t + minutes <= end_m:
            start = datetime(day.year, day.month, day.day, t // 60, t % 60, tzinfo=tz)
            end = start + timedelta(minutes=minutes)
            if start >= earliest:
                clashes = sum(1 for b in (busy or []) if _overlaps(start, end, b.start, b.end))
                if clashes < capacity:
                    out.append(start)
            t += biz.slot_step_minutes
    return out


def available_days(
    biz: Business, minutes: int, now: datetime, busy: list[Busy] | None = None, limit: int = 7, capacity: int = 1
) -> list[date]:
    tz = get_tz(biz.timezone)
    today = now.astimezone(tz).date()
    days = []
    for i in range(biz.booking_horizon_days + 1):
        d = today + timedelta(days=i)
        if slots_for_day(biz, d, minutes, now, busy, capacity):
            days.append(d)
            if len(days) >= limit:
                break
    return days


def day_label(d: date, today: date, arabic: bool = True) -> str:
    """'اليوم' / 'بكرة' / 'الأحد 8/11' style labels (<= 24 chars, fits list rows)."""
    if d == today:
        return "اليوم" if arabic else "Today"
    if d == today + timedelta(days=1):
        return "بكرة" if arabic else "Tomorrow"
    key = DAY_KEYS[d.weekday()]
    name = DAY_NAMES_AR[key] if arabic else DAY_NAMES_EN[key]
    return f"{name} {d.day}/{d.month}"


def time_label(t: datetime, arabic: bool = True) -> str:
    """12-hour label: '4:30 م' / '4:30 PM'."""
    h = t.hour % 12 or 12
    if arabic:
        suffix = "ص" if t.hour < 12 else "م"
    else:
        suffix = "AM" if t.hour < 12 else "PM"
    return f"{h}:{t.minute:02d} {suffix}"
