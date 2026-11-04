
import pytest

from whatsapp_agent_ar import whatsapp as wa
from whatsapp_agent_ar.agent import Agent, WindowClosed
from whatsapp_agent_ar.providers import Message, Mock
from whatsapp_agent_ar.server import simulated_webhook
from whatsapp_agent_ar.store import Store

from .conftest import Chat, options, text_of


def test_greeting_shows_menu_buttons(chat):
    out = chat.say("السلام عليكم")
    assert len(out) == 1
    p = out[0]
    assert p["type"] == "interactive" and p["interactive"]["type"] == "button"
    assert [i for i, _ in options(p)] == ["menu:book", "menu:faq", "staff:"]
    assert "عيادة نخلة" in p["interactive"]["body"]["text"]


def test_greeting_plus_question_gets_the_answer(chat):
    out = chat.say("مرحبا، بكم تنظيف الاسنان؟")
    assert "250 درهم" in text_of(out[0])


def test_kb_answer_in_arabic_and_english(chat, agent):
    out = chat.say("بكم تبييض الاسنان؟")
    assert "900 درهم" in text_of(out[0])
    msgs = agent.store.messages(chat.wa_id)
    assert msgs[-1]["meta"]["source"] == "kb:prices"
    out = chat.say("Do you accept insurance?")
    assert "insurers" in text_of(out[0])
    assert agent.store.contact(chat.wa_id)["lang"] == "en"


def test_two_questions_in_one_message(chat):
    out = chat.say("وين مكانكم؟ وفي باركنج؟")
    body = text_of(out[0])
    assert "البرشاء" in body and "موقف" in body


def test_full_booking_flow(chat, agent):
    out = chat.say("ابي احجز تنظيف")
    days = options(out[0])
    assert out[0]["interactive"]["type"] == "list"
    assert days[0] == ("day:2026-11-04", "اليوم")
    out = chat.say("بكرة", "day:2026-11-05")
    times = options(out[0])
    assert times[0][0] == "slot:2026-11-05T09:00:00+04:00" and times[0][1] == "9:00 ص"
    assert len(times) == 10 and times[-1][0].startswith("more:")
    out = chat.say(times[1][1], times[1][0])
    body = text_of(out[0])
    assert "تنظيف وتلميع" in body and "9:30 ص" in body and "250 درهم" in body
    out = chat.say("تأكيد", "book:confirm")
    assert "تم الحجز" in text_of(out[0])
    appts = agent.store.appointments(wa_id=chat.wa_id)
    assert len(appts) == 1 and appts[0]["service_id"] == "cleaning"
    assert appts[0]["start"] == "2026-11-05T09:30:00+04:00"
    assert agent.store.contact(chat.wa_id)["state"] == "idle"


def test_more_times_paging(chat):
    chat.say("ابي احجز كشف")
    out = chat.say("", "day:2026-11-05")
    more = options(out[0])[-1][0]
    out = chat.say("", more)
    first = options(out[0])[0]
    assert first[1] == "4:30 م"


def test_booked_slot_disappears_for_next_customer(agent, clock):
    a = Chat(agent, clock, "971500000001")
    b = Chat(agent, clock, "971500000002")
    for c in (a, b):
        c.say("ابي احجز تنظيف")
        c.say("", "day:2026-11-05")
    slot = "slot:2026-11-05T09:00:00+04:00"
    a.say("", slot)
    b.say("", slot)
    a.say("", "book:confirm")
    out = b.say("", "book:confirm")  # b was deciding on the same slot
    assert "انحجز" in text_of(out[0])
    assert all(i != slot for i, _ in options(out[0]))
    assert len(agent.store.appointments()) == 1


def test_my_appointments_and_cancel(chat, agent):
    chat.say("احجز تبييض")
    chat.say("", "day:2026-11-05")
    chat.say("", "slot:2026-11-05T16:00:00+04:00")
    chat.say("", "book:confirm")
    out = chat.say("مواعيدي")
    (bid, title), = options(out[0])
    assert bid.startswith("cancel_appt:") and "تبييض" in text_of(out[0])
    out = chat.say(title, bid)
    assert "تم إلغاء" in text_of(out[0])
    assert agent.store.appointments(wa_id=chat.wa_id) == []


def test_cannot_cancel_someone_elses_appointment(agent, clock):
    a = Chat(agent, clock, "971500000001")
    a.say("احجز كشف")
    a.say("", "day:2026-11-05")
    a.say("", "slot:2026-11-05T09:00:00+04:00")
    a.say("", "book:confirm")
    appt = agent.store.appointments()[0]
    Chat(agent, clock, "971500000009").say("", f"cancel_appt:{appt['id']}")
    assert agent.store.appointment(appt["id"])["status"] == "confirmed"


def test_cancel_word_exits_booking_flow(chat, agent):
    chat.say("ابي موعد")
    out = chat.say("الغاء")
    assert "تم إلغاء عملية الحجز" in text_of(out[0])
    assert agent.store.contact(chat.wa_id)["state"] == "idle"


def test_handoff_keyword_silences_bot(chat, agent):
    out = chat.say("ابي اكلم موظف لو سمحت")
    assert "فريق الاستقبال" in text_of(out[0])
    c = agent.store.contact(chat.wa_id)
    assert c["handoff"] == 1 and c["handoff_reason"] == "asked for staff"
    assert chat.say("بكم التنظيف؟") == []  # human owns the chat now
    agent.resolve_handoff(chat.wa_id)
    assert chat.say("بكم التنظيف؟") != []


def test_media_triggers_handoff(agent, clock):
    payload = simulated_webhook("971500000003", "Ali", "x")
    m = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    m.pop("text")
    m.update(type="image", image={"id": "MID", "mime_type": "image/jpeg"})
    agent.handle_webhook(payload)
    assert agent.store.contact("971500000003")["handoff"] == 1
    assert "صورة" in text_of(agent.client.outbox[-1])


def test_unknown_twice_offers_staff(chat):
    out = chat.say("شو رايك في الطقس")
    assert [i for i, _ in options(out[0])] == ["menu:book", "menu:faq", "staff:"]
    out = chat.say("من فاز بالمباراة امس")
    assert [i for i, _ in options(out[0])] == ["staff:", "menu:"]


def test_duplicate_webhook_is_processed_once(agent, clock):
    payload = simulated_webhook("971500000004", "Dup", "مرحبا", ts=int(clock().timestamp()))
    agent.handle_webhook(payload)
    agent.handle_webhook(payload)  # Meta retry
    assert len([m for m in agent.store.messages("971500000004") if m["direction"] == "in"]) == 1
    assert len(agent.client.outbox) == 1


def test_status_updates_progress_and_never_downgrade(chat, agent):
    chat.say("مرحبا")
    out_msg = agent.store.messages(chat.wa_id)[-1]
    wamid = out_msg["wamid"]

    def status(s):
        return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
            "statuses": [{"id": wamid, "status": s, "timestamp": "1", "recipient_id": chat.wa_id}]}}]}]}

    agent.handle_webhook(status("read"))
    agent.handle_webhook(status("delivered"))  # arrives late
    assert agent.store.messages(chat.wa_id)[-1]["status"] == "read"


def test_staff_reply_blocked_after_24h(chat, agent, clock):
    chat.say("مرحبا")
    clock.advance(hours=23)
    assert agent.staff_reply(chat.wa_id, "أهلاً، كيف أخدمك؟")["status"] == "dry_run"
    assert agent.store.contact(chat.wa_id)["handoff"] == 1  # staff took over
    clock.advance(hours=2)
    with pytest.raises(WindowClosed):
        agent.staff_reply(chat.wa_id, "متأخر")
    assert agent.store.messages(chat.wa_id)[-1]["status"] == "blocked"
    # Templates are allowed outside the window
    assert agent.staff_template(chat.wa_id, "appointment_reminder", "ar", ["x"])["status"] == "dry_run"


def test_reminders_use_interactive_inside_window_and_template_outside(agent, clock):
    a = Chat(agent, clock, "971500000005", "سارة")
    a.say("احجز كشف")
    a.say("", "day:2026-11-05")
    a.say("", "slot:2026-11-05T17:00:00+04:00")
    a.say("", "book:confirm")
    clock.advance(hours=12)  # still inside 24h, appointment within 24h
    res = agent.send_due_reminders(24)
    assert [r["via"] for r in res] == ["interactive"]
    assert "تذكير" in text_of(agent.client.outbox[-1])
    assert agent.send_due_reminders(24) == []  # only once

    b = Chat(agent, clock, "971500000006", "Omar")
    b.say("book")
    b.say("Check-up", "svc:checkup")
    b.say("", "day:2026-11-06")
    b.say("", "slot:2026-11-06T20:00:00+04:00")
    b.say("", "book:confirm")
    clock.advance(hours=25)  # b's last message is 25h old; appointment is 21h away
    res = agent.send_due_reminders(24)
    assert [r["via"] for r in res] == ["template"]
    tpl = agent.client.outbox[-1]
    assert tpl["type"] == "template" and tpl["template"]["name"] == "appointment_reminder"
    assert tpl["template"]["components"][0]["parameters"][0]["text"] == "Omar"


def test_english_customer_gets_english_flow(agent, clock):
    c = Chat(agent, clock, "971500000007", "Omar")
    out = c.say("hi")
    assert "Welcome" in text_of(out[0])
    out = c.say("I want to book an appointment")
    assert out[0]["interactive"]["action"]["button"] == "Services"
    assert ("svc:whitening", "Teeth whitening") in options(out[0])


class EchoLLM:
    name = "fake"
    model = "fake-1"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def complete(self, messages, **kw):
        self.prompts.append(messages)
        return self.reply


def test_llm_fallback_is_grounded_and_labeled(biz, clock):
    llm = EchoLLM("ما عندي معلومة عن الواي فاي، لكن نقدر نحولك للاستقبال.")
    agent = Agent(biz, Store(":memory:"), wa.WhatsAppClient(dry_run=True), llm, clock=clock)
    c = Chat(agent, clock)
    out = c.say("عندكم واي فاي مجاني في صالة الانتظار؟")
    assert len(llm.prompts) == 1
    system = llm.prompts[0][0].content
    assert "Answer ONLY from the facts" in system and "UNKNOWN" in system
    assert "900 AED" in system  # services and prices are passed as grounding
    assert text_of(out[0]).startswith("ما عندي معلومة")
    assert agent.store.messages(c.wa_id)[-1]["meta"]["source"] == "llm:fake"


def test_llm_not_called_when_kb_matches(biz, clock):
    llm = EchoLLM("should not be used")
    agent = Agent(biz, Store(":memory:"), wa.WhatsAppClient(dry_run=True), llm, clock=clock)
    Chat(agent, clock).say("بكم التنظيف؟")
    assert llm.prompts == []


def test_llm_unknown_falls_back_to_menu(biz, clock):
    llm = EchoLLM("UNKNOWN")
    agent = Agent(biz, Store(":memory:"), wa.WhatsAppClient(dry_run=True), llm, clock=clock)
    out = Chat(agent, clock).say("من فاز بكأس العالم؟")
    assert len(llm.prompts) == 1
    assert [i for i, _ in options(out[0])] == ["menu:book", "menu:faq", "staff:"]


def test_mock_provider_never_answers():
    assert Mock().complete([Message("user", "x")]) == "UNKNOWN"


def test_all_outgoing_payloads_valid_for_cloud_api(agent, clock):
    """Every message the agent produced in a long conversation respects Meta limits."""
    c = Chat(agent, clock)
    for text, rid in [("مرحبا", ""), ("", "menu:faq"), ("", "faq:prices"), ("", "menu:book"), ("", "svc:braces"),
                      ("", "day:2026-11-06"), ("", "slot:2026-11-06T16:00:00+04:00"), ("", "book:change"),
                      ("مواعيدي", "")]:
        c.say(text, rid)
    for p in agent.client.outbox:
        assert p["messaging_product"] == "whatsapp"
        if p["type"] == "text":
            assert len(p["text"]["body"]) <= wa.TEXT_MAX
        if p["type"] == "interactive":
            it = p["interactive"]
            if it["type"] == "button":
                assert 1 <= len(it["action"]["buttons"]) <= 3
                assert len(it["body"]["text"]) <= wa.INTERACTIVE_BODY_MAX
                for b in it["action"]["buttons"]:
                    assert len(b["reply"]["title"]) <= wa.BUTTON_TITLE_MAX
                ids = [b["reply"]["id"] for b in it["action"]["buttons"]]
                assert len(ids) == len(set(ids))
            else:
                rows = [r for s in it["action"]["sections"] for r in s["rows"]]
                assert 1 <= len(rows) <= 10
                assert all(len(r["title"]) <= 24 for r in rows)
                assert len({r["id"] for r in rows}) == len(rows)
