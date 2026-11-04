"""The conversation agent: routing, booking flow, knowledge answers, handoff, reminders."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from . import whatsapp as wa
from .arabic import contains_any, is_arabic, normalize
from .business import Business
from .knowledge import KnowledgeBase
from .providers import LLM, UNKNOWN, Message, Mock, ProviderError
from .scheduling import Busy, available_days, day_label, get_tz, slots_for_day, time_label
from .store import Store, parse
from .texts import BOOK_WORDS, CANCEL_FLOW, GREETINGS, MY_APPTS, t

log = logging.getLogger("whatsapp_agent_ar")

MEDIA_TYPES = {"image", "video", "audio", "document", "sticker", "location", "contacts"}
MEDIA_NAMES_AR = {
    "image": "صورة", "video": "فيديو", "audio": "رسالة صوتية", "document": "ملف", "sticker": "ملصق",
    "location": "موقع", "contacts": "جهة اتصال",
}


class WindowClosed(Exception):
    """Raised when a free-form message is attempted outside the 24-hour window."""


class Agent:
    def __init__(
        self,
        business: Business,
        store: Store,
        client: wa.WhatsAppClient,
        llm: LLM | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        reminder_template: str = "appointment_reminder",
        reminder_template_lang: str = "ar",
        max_misses_before_offer: int = 2,
    ):
        self.biz = business
        self.store = store
        self.client = client
        self.llm = llm or Mock()
        self.kb = KnowledgeBase(business.faq)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.tz = get_tz(business.timezone)
        self.reminder_template = reminder_template
        self.reminder_template_lang = reminder_template_lang
        self.max_misses = max_misses_before_offer

    # ------------------------------------------------------------------ webhook entry
    def handle_webhook(self, payload: dict) -> dict:
        messages, statuses = wa.parse_webhook(payload)
        handled = 0
        for m in messages:
            if self.handle_inbound(m):
                handled += 1
        for s in statuses:
            self.store.update_status_by_wamid(s.wamid, s.status)
        return {"messages": len(messages), "handled": handled, "statuses": len(statuses)}

    def handle_inbound(self, m: wa.Inbound) -> bool:
        now = self.clock()
        if m.wamid and not self.store.mark_processed(m.wamid, now):
            return False  # Meta retried a webhook we already handled
        c = self.store.contact(m.wa_id, now)
        updates: dict = {}
        if m.name and m.name != c.get("name"):
            updates["name"] = m.name
        if m.text and m.type == "text":
            lang = "ar" if is_arabic(m.text) else "en"
            if lang != c.get("lang"):
                updates["lang"] = lang
        if updates:
            self.store.update_contact(m.wa_id, **updates)
        self.store.add_message(m.wa_id, "in", "customer", m.type, m.display, now, payload=m.raw, wamid=m.wamid)
        self.client.mark_read(m.wamid)
        c = self.store.contact(m.wa_id)
        if c["handoff"]:
            return True  # a human owns this chat now; the bot stays quiet
        try:
            self._route(c, m)
        except WindowClosed:  # pragma: no cover - cannot happen right after an inbound message
            log.warning("window closed while replying to %s", m.wa_id)
        return True

    # ------------------------------------------------------------------ sending
    def send(self, wa_id: str, payload: dict, author: str = "bot", meta: dict | None = None) -> dict:
        """Send (or dry-run) one message, enforcing the 24h customer service window."""
        now = self.clock()
        c = self.store.contact(wa_id, now)
        body = wa.summarize(payload)
        if payload.get("type") != "template" and not wa.in_service_window(parse(c.get("last_inbound_at")), now):
            self.store.add_message(
                wa_id, "out", author, payload.get("type", "text"), body, now, payload=payload, status="blocked",
                meta={**(meta or {}), "error": "outside 24h window: send an approved template"},
            )
            raise WindowClosed(wa_id)
        msg_id = self.store.add_message(
            wa_id, "out", author, payload.get("type", "text"), body, now, payload=payload, status="queued", meta=meta
        )
        try:
            res = self.client.send(payload)
        except wa.WhatsAppError as e:
            self.store.set_message_status(msg_id, "failed")
            self.store._exec("UPDATE messages SET meta = json_set(meta, '$.error', ?) WHERE id = ?", (str(e), msg_id))
            log.error("send failed: %s", e)
            return {"id": msg_id, "status": "failed", "error": str(e)}
        self.store.set_message_status(msg_id, res.status, res.wamid)
        return {"id": msg_id, "status": res.status, "wamid": res.wamid}

    def _text(self, c: dict, body: str, **meta) -> None:
        self.send(c["wa_id"], wa.text_message(c["wa_id"], body), meta=meta)

    def _buttons(self, c: dict, body: str, buttons: list[tuple[str, str]], **meta) -> None:
        self.send(c["wa_id"], wa.buttons_message(c["wa_id"], body, buttons), meta=meta)

    def _list(self, c: dict, body: str, button: str, rows: list[tuple[str, str, str]], **meta) -> None:
        self.send(c["wa_id"], wa.list_message(c["wa_id"], body, button, rows), meta=meta)

    # ------------------------------------------------------------------ routing
    def _route(self, c: dict, m: wa.Inbound) -> None:
        lang = c["lang"]
        if m.reply_id:
            return self._on_reply(c, m.reply_id)
        if m.type in MEDIA_TYPES and not m.text:
            kind = MEDIA_NAMES_AR.get(m.type, m.type) if lang == "ar" else m.type
            return self._handoff(c, f"media:{m.type}", t("media", lang, kind=kind))
        text = m.text or ""
        if not text.strip():
            return self._menu(c, t("didnt_get", lang))
        if self.biz.handoff_keywords and contains_any(text, self.biz.handoff_keywords):
            return self._handoff(c, "asked for staff")
        if c["state"].startswith("book_") and contains_any(text, CANCEL_FLOW) and len(normalize(text).split()) <= 3:
            self.store.set_state(c["wa_id"], "idle")
            return self._text(c, t("flow_cancelled", lang), source="flow")
        if contains_any(text, MY_APPTS):
            return self._my_appointments(c)
        if contains_any(text, BOOK_WORDS):
            svc = self.biz.match_service(text)
            return self._choose_day(c, svc.id) if svc else self._choose_service(c)
        hits = self._kb_hits(text)
        if self._is_greeting(text) and not hits:
            return self._welcome(c)
        if hits:
            self.store.update_contact(c["wa_id"], misses=0)
            answer = "\n\n".join(h.faq.answer_en if (lang == "en" and h.faq.answer_en) else h.faq.answer for h in hits)
            return self._text(
                c, answer, source="kb:" + ",".join(h.faq.id for h in hits), score=round(max(h.score for h in hits), 2)
            )
        if c["state"].startswith("book_"):
            return self._repeat_step(c)
        answer = self._llm_answer(text, lang)
        if answer:
            self.store.update_contact(c["wa_id"], misses=0)
            return self._text(c, answer, source=f"llm:{self.llm.name}")
        return self._miss(c)

    def _kb_hits(self, text: str, limit: int = 2) -> list:
        """Best FAQ match per question in the message (customers often ask two at once)."""
        parts = [p for p in re.split(r"[?؟\n]+|\s+(?:و|وكمان|and|also)\s+(?=\S)", text) if p and p.strip()]
        hits, seen = [], set()
        for part in parts if len(parts) > 1 else [text]:
            h = self.kb.best(part)
            if h and h.faq.id not in seen:
                seen.add(h.faq.id)
                hits.append(h)
        if not hits and len(parts) > 1:
            h = self.kb.best(text)
            hits = [h] if h else []
        return hits[:limit]

    @staticmethod
    def _is_greeting(text: str) -> bool:
        norm = normalize(text)
        return len(norm.split()) <= 4 and contains_any(text, GREETINGS)

    def _on_reply(self, c: dict, rid: str) -> None:
        kind, _, arg = rid.partition(":")
        lang = c["lang"]
        if kind == "menu":
            if arg == "book":
                return self._choose_service(c)
            if arg == "faq":
                return self._faq_list(c)
            return self._welcome(c)
        if kind == "staff":
            return self._handoff(c, "button")
        if kind == "faq":
            f = next((f for f in self.biz.faq if f.id == arg), None)
            if f:
                return self._text(c, f.answer_en if lang == "en" and f.answer_en else f.answer, source=f"kb:{f.id}")
        if kind == "svc":
            return self._choose_day(c, arg)
        if kind == "day":
            return self._choose_time(c, c["state_data"].get("service"), date.fromisoformat(arg))
        if kind == "more":
            d, _, off = arg.partition(":")
            return self._choose_time(c, c["state_data"].get("service"), date.fromisoformat(d), offset=int(off or 0))
        if kind == "slot":
            return self._confirm(c, arg)
        if kind == "book" and arg == "confirm":
            return self._finalize(c)
        if kind == "book" and arg == "change":
            return self._choose_day(c, c["state_data"].get("service"))
        if kind == "book" and arg == "cancel":
            self.store.set_state(c["wa_id"], "idle")
            return self._text(c, t("flow_cancelled", lang), source="flow")
        if kind == "cancel_appt":
            return self._cancel_appointment(c, int(arg))
        if kind == "attend":
            return self._text(c, t("attend_ok", lang), source="reminder")
        return self._welcome(c)

    # ------------------------------------------------------------------ menu / faq / misses
    def _welcome(self, c: dict) -> None:
        name = self.biz.name if c["lang"] == "ar" else self.biz.name_en
        self.store.set_state(c["wa_id"], "idle")
        self._menu(c, t("welcome", c["lang"], name=name))

    def _menu(self, c: dict, body: str) -> None:
        lang = c["lang"]
        self._buttons(
            c,
            body,
            [("menu:book", t("menu_book", lang)), ("menu:faq", t("menu_faq", lang)), ("staff:", t("menu_staff", lang))],
            source="menu",
        )

    def _faq_list(self, c: dict) -> None:
        lang = c["lang"]
        rows = []
        for f in self.biz.faq[: wa.LIST_MAX_ROWS]:
            q = next((q for q in f.questions if is_arabic(q) == (lang == "ar")), f.questions[0])
            rows.append((f"faq:{f.id}", q, q if len(q) > wa.LIST_ROW_TITLE_MAX else ""))
        self._list(c, t("faq_intro", lang), t("faq_btn", lang), rows, source="menu")

    def _miss(self, c: dict) -> None:
        misses = int(c.get("misses") or 0) + 1
        self.store.update_contact(c["wa_id"], misses=misses)
        lang = c["lang"]
        if misses >= self.max_misses:
            return self._buttons(
                c, t("offer_staff", lang), [("staff:", t("btn_yes_staff", lang)), ("menu:", t("btn_menu", lang))], source="fallback"
            )
        return self._menu(c, t("didnt_get", lang))

    def _llm_answer(self, question: str, lang: str) -> str | None:
        """Grounded fallback. Returns None when no real model is configured or it says UNKNOWN."""
        facts = "\n".join(f"- {f.answer}" + (f" / {f.answer_en}" if f.answer_en else "") for f in self.biz.faq)
        services = "\n".join(
            f"- {s.name} ({s.name_en}): {s.minutes} min, " + (f"{s.price:g} {self.biz.currency}" if s.price else "free")
            for s in self.biz.services
        )
        system = (
            f"You are the WhatsApp assistant of {self.biz.name_en} ({self.biz.name}) in the UAE. "
            "Answer ONLY from the facts below, in the customer's language and dialect register "
            f"({'Arabic' if lang == 'ar' else 'English'}), in at most 3 short sentences, no markdown. "
            "Never invent prices, times, medical advice or promises. "
            f"If the facts do not answer the question, reply exactly {UNKNOWN}.\n\nFACTS:\n{facts}\n\nSERVICES:\n{services}"
        )
        try:
            out = self.llm.complete([Message("system", system), Message("user", question)]).strip()
        except ProviderError as e:
            log.error("LLM fallback failed: %s", e)
            return None
        if not out or UNKNOWN in out.upper():
            return None
        return out[: wa.TEXT_MAX]

    # ------------------------------------------------------------------ handoff
    def _handoff(self, c: dict, reason: str, message: str | None = None) -> None:
        self.store.update_contact(
            c["wa_id"], handoff=1, handoff_reason=reason, handoff_at=self.clock(), state="idle", state_data={}, misses=0
        )
        self._text(c, message or t("handoff", c["lang"]), source="handoff")

    def resolve_handoff(self, wa_id: str, notify: bool = False) -> None:
        """Staff hands the conversation back to the bot."""
        self.store.update_contact(wa_id, handoff=0, handoff_reason="", misses=0)
        if notify:
            c = self.store.contact(wa_id)
            try:
                self._text(c, t("bot_resumed", c["lang"]), source="handoff")
            except WindowClosed:
                pass

    def take_over(self, wa_id: str) -> None:
        self.store.update_contact(wa_id, handoff=1, handoff_reason="staff took over", handoff_at=self.clock())

    def staff_reply(self, wa_id: str, text: str) -> dict:
        """Free-form reply from the dashboard. Raises WindowClosed outside 24h."""
        self.store.mark_seen(wa_id)
        if not self.store.contact(wa_id)["handoff"]:
            self.take_over(wa_id)
        return self.send(wa_id, wa.text_message(wa_id, text), author="staff", meta={"source": "staff"})

    def staff_template(self, wa_id: str, name: str, lang: str, params: list[str]) -> dict:
        return self.send(wa_id, wa.template_message(wa_id, name, lang, params), author="staff", meta={"source": "template"})

    # ------------------------------------------------------------------ booking flow
    def _busy(self) -> list[Busy]:
        return [Busy(parse(a["start"]), parse(a["end"])) for a in self.store.appointments(status="confirmed")]

    def _choose_service(self, c: dict) -> None:
        lang = c["lang"]
        self.store.set_state(c["wa_id"], "book_service")
        rows = []
        for s in self.biz.services:
            if s.price:
                desc = f"{s.minutes} دقيقة - {s.price:g} درهم" if lang == "ar" else f"{s.minutes} min - AED {s.price:g}"
            else:
                desc = f"{s.minutes} دقيقة - مجاناً" if lang == "ar" else f"{s.minutes} min - free"
            rows.append((f"svc:{s.id}", s.label(lang == "ar"), desc))
        self._list(c, t("choose_service", lang), t("services_btn", lang), rows, source="booking")

    def _choose_day(self, c: dict, service_id: str | None) -> None:
        lang = c["lang"]
        svc = self.biz.service(service_id or "")
        if not svc:
            return self._choose_service(c)
        now = self.clock()
        days = available_days(self.biz, svc.minutes, now, self._busy(), limit=wa.LIST_MAX_ROWS)
        if not days:
            self.store.set_state(c["wa_id"], "idle")
            return self._buttons(
                c, t("no_days", lang), [("staff:", t("btn_yes_staff", lang)), ("menu:", t("btn_menu", lang))], source="booking"
            )
        self.store.set_state(c["wa_id"], "book_day", {"service": svc.id})
        today = now.astimezone(self.tz).date()
        rows = []
        for d in days:
            n = len(slots_for_day(self.biz, d, svc.minutes, now, self._busy()))
            desc = f"{n} وقت متاح" if lang == "ar" else f"{n} slots"
            rows.append((f"day:{d.isoformat()}", day_label(d, today, lang == "ar"), desc))
        self._list(c, t("choose_day", lang, service=svc.label(lang == "ar")), t("days_btn", lang), rows, source="booking")

    def _choose_time(self, c: dict, service_id: str | None, day: date, prefix: str | None = None, offset: int = 0) -> None:
        lang = c["lang"]
        svc = self.biz.service(service_id or "")
        if not svc:
            return self._choose_service(c)
        now = self.clock()
        slots = slots_for_day(self.biz, day, svc.minutes, now, self._busy())
        if not slots:
            return self._choose_day(c, svc.id)
        self.store.set_state(c["wa_id"], "book_time", {"service": svc.id, "day": day.isoformat()})
        # A list holds 10 rows: show 9 times plus a "later times" row when needed.
        if offset >= len(slots):
            offset = 0
        page = slots[offset:]
        more = len(page) > wa.LIST_MAX_ROWS
        page = page[: wa.LIST_MAX_ROWS - 1] if more else page
        rows = []
        for s in page:
            period = ("صباحاً" if s.hour < 12 else "مساءً") if lang == "ar" else ("Morning" if s.hour < 12 else "Evening")
            rows.append((f"slot:{s.isoformat()}", time_label(s, lang == "ar"), period))
        if more:
            nxt = offset + len(page)
            rows.append((f"more:{day.isoformat()}:{nxt}", t("more_times", lang), time_label(slots[nxt], lang == "ar") + " ..."))
        today = now.astimezone(self.tz).date()
        body = t("choose_time", lang, day=day_label(day, today, lang == "ar"))
        if prefix:
            body = f"{prefix}\n{body}"
        self._list(c, body, t("times_btn", lang), rows, source="booking")

    def _confirm(self, c: dict, slot_iso: str) -> None:
        lang = c["lang"]
        svc = self.biz.service(c["state_data"].get("service", ""))
        if not svc:
            return self._choose_service(c)
        start = datetime.fromisoformat(slot_iso).astimezone(self.tz)
        self.store.set_state(c["wa_id"], "book_confirm", {"service": svc.id, "slot": start.isoformat()})
        if svc.price:
            price = t("price_line", lang, price=f"{svc.price:g}")
        else:
            price = t("free_line", lang)
        today = self.clock().astimezone(self.tz).date()
        body = t(
            "confirm", lang, service=svc.label(lang == "ar"), day=day_label(start.date(), today, lang == "ar"),
            time=time_label(start, lang == "ar"), minutes=svc.minutes, price=price,
        )
        self._buttons(
            c, body,
            [("book:confirm", t("btn_confirm", lang)), ("book:change", t("btn_change", lang)), ("book:cancel", t("btn_cancel_flow", lang))],
            source="booking",
        )

    def _finalize(self, c: dict) -> None:
        lang = c["lang"]
        data = c["state_data"]
        svc = self.biz.service(data.get("service", ""))
        if not svc or not data.get("slot") or c["state"] != "book_confirm":
            return self._choose_service(c)
        start = datetime.fromisoformat(data["slot"]).astimezone(self.tz)
        now = self.clock()
        # Re-check: someone else may have taken the slot while this customer was deciding.
        if start not in slots_for_day(self.biz, start.date(), svc.minutes, now, self._busy()):
            return self._choose_time(c, svc.id, start.date(), prefix=t("slot_taken", lang))
        end = start + timedelta(minutes=svc.minutes)
        appt_id = self.store.add_appointment(c["wa_id"], c.get("name") or "", svc.id, start, end, now)
        self.store.set_state(c["wa_id"], "idle")
        today = now.astimezone(self.tz).date()
        self._text(
            c,
            t("booked", lang, id=appt_id, service=svc.label(lang == "ar"), day=day_label(start.date(), today, lang == "ar"),
              time=time_label(start, lang == "ar")),
            source="booking", appointment=appt_id,
        )

    def _repeat_step(self, c: dict) -> None:
        data, state = c["state_data"], c["state"]
        if state == "book_day":
            return self._choose_day(c, data.get("service"))
        if state == "book_time" and data.get("day"):
            return self._choose_time(c, data.get("service"), date.fromisoformat(data["day"]))
        if state == "book_confirm" and data.get("slot"):
            return self._confirm(c, data["slot"])
        return self._choose_service(c)

    def _my_appointments(self, c: dict) -> None:
        lang = c["lang"]
        now = self.clock()
        appts = [a for a in self.store.appointments(wa_id=c["wa_id"]) if parse(a["start"]) > now]
        if not appts:
            return self._menu(c, t("no_appts", lang))
        today = now.astimezone(self.tz).date()
        lines, buttons = [], []
        for a in appts[: wa.MAX_BUTTONS]:
            svc = self.biz.service(a["service_id"])
            start = parse(a["start"]).astimezone(self.tz)
            name = svc.label(lang == "ar") if svc else a["service_id"]
            ref = f"({a['id']})" if lang == "ar" else f"#{a['id']}"
            lines.append(f"{ref} {name} - {day_label(start.date(), today, lang == 'ar')} {time_label(start, lang == 'ar')}")
            buttons.append((f"cancel_appt:{a['id']}", t("btn_cancel_appt", lang, id=a["id"])))
        self._buttons(c, t("your_appts", lang, lines="\n".join(lines)), buttons, source="appointments")

    def _cancel_appointment(self, c: dict, appt_id: int) -> None:
        a = self.store.appointment(appt_id)
        if not a or a["wa_id"] != c["wa_id"] or a["status"] != "confirmed":
            return self._my_appointments(c)
        self.store.cancel_appointment(appt_id)
        self._text(c, t("appt_cancelled", c["lang"], id=appt_id), source="appointments")

    # ------------------------------------------------------------------ reminders
    def send_due_reminders(self, hours_before: int = 24) -> list[dict]:
        """Remind customers of appointments starting within `hours_before` hours.

        Inside the 24h window we send interactive buttons; outside it we must use
        the approved template configured in WA_REMINDER_TEMPLATE.
        """
        now = self.clock()
        out = []
        today = now.astimezone(self.tz).date()
        for a in self.store.appointments(status="confirmed"):
            start = parse(a["start"])
            if a["reminded"] or not (now < start <= now + timedelta(hours=hours_before)):
                continue
            c = self.store.contact(a["wa_id"])
            lang = c["lang"]
            svc = self.biz.service(a["service_id"])
            local = start.astimezone(self.tz)
            fields = dict(
                name=self.biz.name if lang == "ar" else self.biz.name_en,
                service=svc.label(lang == "ar") if svc else a["service_id"],
                day=day_label(local.date(), today, lang == "ar"),
                time=time_label(local, lang == "ar"),
            )
            if wa.in_service_window(parse(c.get("last_inbound_at")), now):
                res = self.send(
                    a["wa_id"],
                    wa.buttons_message(
                        a["wa_id"], t("reminder_text", lang, **fields),
                        [(f"attend:{a['id']}", t("btn_attend", lang)), (f"cancel_appt:{a['id']}", t("btn_cancel_appt", lang, id=a["id"]))],
                    ),
                    meta={"source": "reminder", "appointment": a["id"]},
                )
                res["via"] = "interactive"
            else:
                params = [c.get("name") or "", fields["service"], fields["day"], fields["time"]]
                res = self.send(
                    a["wa_id"],
                    wa.template_message(a["wa_id"], self.reminder_template, self.reminder_template_lang, params),
                    meta={"source": "reminder", "appointment": a["id"]},
                )
                res["via"] = "template"
            if res.get("status") != "failed":
                self.store.mark_reminded(a["id"])
            res["appointment"] = a["id"]
            out.append(res)
        return out
