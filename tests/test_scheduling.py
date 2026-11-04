from datetime import date, datetime, timedelta

from whatsapp_agent_ar.scheduling import Busy, available_days, day_label, get_tz, slots_for_day, time_label

from .conftest import NOW

DXB = get_tz("Asia/Dubai")


def test_slots_respect_hours_and_notice(biz):
    # Now is 10:00 Dubai, notice 60 min -> first slot 11:00; morning shift ends 13:00
    slots = slots_for_day(biz, date(2026, 11, 4), 30, NOW)
    labels = [s.strftime("%H:%M") for s in slots]
    assert labels[0] == "11:00"
    assert "12:30" in labels and "13:00" not in labels
    assert labels[labels.index("12:30") + 1] == "16:00"
    assert labels[-1] == "20:30"


def test_long_service_must_fit_before_close(biz):
    slots = slots_for_day(biz, date(2026, 11, 5), 60, NOW)
    labels = [s.strftime("%H:%M") for s in slots]
    assert "12:00" in labels and "12:30" not in labels and "20:00" in labels and "20:30" not in labels


def test_friday_evening_only_and_closed_dates(biz):
    fri = [s.strftime("%H:%M") for s in slots_for_day(biz, date(2026, 11, 6), 30, NOW)]
    assert fri[0] == "16:00"
    assert slots_for_day(biz, date(2026, 12, 2), 30, NOW) == []


def test_busy_slots_are_excluded(biz):
    start = datetime(2026, 11, 5, 9, 0, tzinfo=DXB)
    busy = [Busy(start, start + timedelta(minutes=45))]
    labels = [s.strftime("%H:%M") for s in slots_for_day(biz, date(2026, 11, 5), 30, NOW, busy)]
    assert "09:00" not in labels and "09:30" not in labels and "10:00" in labels


def test_available_days_skip_closed(biz):
    now = datetime(2026, 12, 1, 18, 0, tzinfo=DXB)  # evening, Dec 2-3 closed
    days = available_days(biz, 30, now, limit=3)
    assert date(2026, 12, 2) not in days and date(2026, 12, 3) not in days
    assert days[0] == date(2026, 12, 1)


def test_labels_fit_whatsapp_rows():
    today = date(2026, 11, 4)
    assert day_label(today, today) == "اليوم"
    assert day_label(today + timedelta(days=1), today) == "بكرة"
    assert day_label(date(2026, 11, 8), today) == "الأحد 8/11"
    assert day_label(date(2026, 11, 8), today, arabic=False) == "Sun 8/11"
    assert time_label(datetime(2026, 1, 1, 16, 30)) == "4:30 م"
    assert time_label(datetime(2026, 1, 1, 0, 5), arabic=False) == "12:05 AM"
