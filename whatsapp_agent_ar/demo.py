"""Seed a local database with SAMPLE conversations by driving the real agent.

Customer messages are hand-written examples (fictional people, fake +971 5x
numbers); every bot reply, booking and handoff is produced by the actual agent
code in dry-run mode. Nothing is sent to WhatsApp.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import whatsapp as wa
from .agent import Agent
from .business import Business
from .providers import Mock
from .scheduling import get_tz
from .server import simulated_webhook
from .store import Store

# (minutes offset from the scenario start, wa_id, name, text, reply_id)
Script = list[tuple[int, str, str, str, str]]


def _anchor(now: datetime, tz) -> datetime:
    """Latest moment <= now inside clinic hours (so the sample chats look like a real day)."""
    local = now.astimezone(tz)
    if 9 <= local.hour < 21:
        return now
    evening = local.replace(hour=20, minute=0, second=0, microsecond=0)
    if evening > local:
        evening -= timedelta(days=1)
    return evening.astimezone(timezone.utc)


def _scenarios(today: datetime, tz) -> list[tuple[timedelta, Script]]:
    tomorrow = (today.astimezone(tz) + timedelta(days=1)).date().isoformat()
    return [
        # Old conversation: last message 30 hours ago -> 24h window closed.
        (timedelta(hours=-30), [
            (0, "971501110003", "Omar Haddad", "Do you treat children?", ""),
            (1, "971501110003", "Omar Haddad", "Is there parking?", ""),
        ]),
        # Insurance question then the customer asks for a person -> handoff.
        (timedelta(hours=-3), [
            (0, "971551110002", "فاطمة المنصوري", "السلام عليكم", ""),
            (1, "971551110002", "فاطمة المنصوري", "تقبلون تأمين ضمان؟", ""),
            (3, "971551110002", "فاطمة المنصوري", "ابي اكلم موظف عشان التغطية لو سمحت", ""),
        ]),
        # Prices then full booking via interactive lists and buttons.
        (timedelta(minutes=-40), [
            (0, "971501110001", "سارة الكتبي", "مرحبا، بكم تبييض الاسنان عندكم؟", ""),
            (1, "971501110001", "سارة الكتبي", "ابي احجز تبييض", ""),
            (2, "971501110001", "سارة الكتبي", "بكرة", f"day:{tomorrow}"),
            (3, "971501110001", "سارة الكتبي", "", "__first_slot__"),
            (4, "971501110001", "سارة الكتبي", "تأكيد", "book:confirm"),
        ]),
        # Emirati dialect location question, still open.
        (timedelta(minutes=-12), [
            (0, "971521110004", "خالد النعيمي", "وين مكانكم بالضبط؟ وفي باركنج؟", ""),
            (1, "971521110004", "خالد النعيمي", "اوكي ومتى تسكرون اليوم؟", ""),
        ]),
    ]


def seed(store: Store, business: Business | None = None, now: datetime | None = None) -> Agent:
    biz = business or Business.load()
    now = now or datetime.now(timezone.utc)
    now = _anchor(now, get_tz(biz.timezone))
    clock_box = [now]
    agent = Agent(biz, store, wa.WhatsAppClient(dry_run=True), Mock(), clock=lambda: clock_box[0])
    for offset, script in _scenarios(now, get_tz(biz.timezone)):
        base = now + offset
        for minutes, wa_id, name, text, reply_id in script:
            clock_box[0] = base + timedelta(minutes=minutes)
            if reply_id == "__first_slot__":
                last = store.messages(wa_id)[-1]
                rows = last["payload"]["interactive"]["action"]["sections"][0]["rows"]
                reply_id, text = rows[min(2, len(rows) - 1)]["id"], rows[min(2, len(rows) - 1)]["title"]
            agent.handle_webhook(simulated_webhook(wa_id, name, text, reply_id, ts=int(clock_box[0].timestamp())))
    # A sample staff reply from the dashboard on the handed-off chat (dry-run).
    clock_box[0] = now + timedelta(hours=-3, minutes=9)
    agent.staff_reply("971551110002", "أهلاً فاطمة، معك ريم من الاستقبال. أرسلي لنا صورة بطاقة التأمين من الجهتين ونتأكد لك من التغطية خلال دقائق.")
    clock_box[0] = now
    agent.clock = lambda: datetime.now(timezone.utc)
    return agent
