"""User-facing strings (Arabic first, English second). Edit freely per business."""

from __future__ import annotations

T = {
    "welcome": {
        "ar": "أهلاً وسهلاً في {name}. أنا المساعد الآلي، أقدر أساعدك في الحجز والإجابة عن أسئلتك، وأحولك لموظف متى ما احتجت.",
        "en": "Welcome to {name}. I'm the automated assistant: I can book appointments, answer questions, and connect you to our team any time.",
    },
    "menu_book": {"ar": "حجز موعد", "en": "Book appointment"},
    "menu_faq": {"ar": "أسئلة شائعة", "en": "FAQ"},
    "menu_staff": {"ar": "التحدث مع موظف", "en": "Talk to staff"},
    "choose_service": {"ar": "اختر الخدمة المطلوبة:", "en": "Which service would you like?"},
    "services_btn": {"ar": "الخدمات", "en": "Services"},
    "choose_day": {"ar": "تمام، {service}. اختر اليوم المناسب:", "en": "Great, {service}. Pick a day:"},
    "days_btn": {"ar": "الأيام المتاحة", "en": "Available days"},
    "choose_time": {"ar": "الأوقات المتاحة ({day}):", "en": "Available times ({day}):"},
    "more_times": {"ar": "أوقات لاحقة", "en": "Later times"},
    "times_btn": {"ar": "الأوقات", "en": "Times"},
    "no_days": {
        "ar": "للأسف ما في مواعيد متاحة خلال الأيام القادمة. تحب أحولك لموظف الاستقبال؟",
        "en": "Sorry, there are no free slots in the coming days. Shall I connect you to reception?",
    },
    "slot_taken": {"ar": "هذا الوقت انحجز قبل لحظات. اختر وقتاً آخر:", "en": "That time was just taken. Please pick another:"},
    "confirm": {
        "ar": "تأكيد الحجز:\nالخدمة: {service}\nالموعد: {day} الساعة {time}\nالمدة: {minutes} دقيقة{price}",
        "en": "Please confirm:\nService: {service}\nWhen: {day} at {time}\nDuration: {minutes} min{price}",
    },
    "price_line": {"ar": "\nالسعر: {price} درهم", "en": "\nPrice: AED {price}"},
    "free_line": {"ar": "\nالسعر: مجاناً", "en": "\nPrice: free"},
    "btn_confirm": {"ar": "تأكيد", "en": "Confirm"},
    "btn_change": {"ar": "تغيير الوقت", "en": "Change time"},
    "btn_cancel_flow": {"ar": "إلغاء", "en": "Cancel"},
    "booked": {
        "ar": "تم الحجز. رقم الحجز: {id}\n{service} - {day} الساعة {time}\nبنرسل لك تذكير قبل الموعد. لعرض أو إلغاء موعدك اكتب «مواعيدي».",
        "en": "Booked. Reference #{id}\n{service} - {day} at {time}\nWe'll remind you before the visit. Type \"my appointments\" to view or cancel.",
    },
    "flow_cancelled": {"ar": "تم إلغاء عملية الحجز. أقدر أساعدك بشي ثاني؟", "en": "Booking cancelled. Anything else I can help with?"},
    "no_appts": {"ar": "ما عندك مواعيد قادمة حالياً.", "en": "You have no upcoming appointments."},
    "your_appts": {"ar": "مواعيدك القادمة:\n{lines}", "en": "Your upcoming appointments:\n{lines}"},
    "btn_cancel_appt": {"ar": "إلغاء الحجز {id}", "en": "Cancel #{id}"},
    "appt_cancelled": {"ar": "تم إلغاء الحجز رقم {id}. نتمنى نشوفك قريباً.", "en": "Appointment #{id} cancelled. Hope to see you soon."},
    "handoff": {
        "ar": "حاضر، حولت محادثتك لفريق الاستقبال وبيردون عليك هنا في أقرب وقت (خلال ساعات الدوام).",
        "en": "Sure, I've passed your chat to our reception team. They'll reply here as soon as possible (during opening hours).",
    },
    "didnt_get": {
        "ar": "عذراً، ما فهمت سؤالك تماماً. تقدر تختار من القائمة أو تكتب سؤالك بطريقة ثانية.",
        "en": "Sorry, I didn't quite get that. Pick an option below or rephrase your question.",
    },
    "offer_staff": {
        "ar": "يبدو أن سؤالك يحتاج موظف. تحب أحولك لفريق الاستقبال؟",
        "en": "It looks like a person should answer this. Shall I connect you to reception?",
    },
    "btn_yes_staff": {"ar": "نعم، موظف", "en": "Yes, staff"},
    "btn_menu": {"ar": "القائمة", "en": "Menu"},
    "media": {
        "ar": "وصلتنا رسالتك ({kind}). حولتها لفريق الاستقبال ليطلعوا عليها ويردون عليك.",
        "en": "We received your {kind}. I've forwarded it to reception and they'll get back to you.",
    },
    "faq_intro": {"ar": "اختر سؤالاً:", "en": "Pick a question:"},
    "faq_btn": {"ar": "الأسئلة", "en": "Questions"},
    "reminder_text": {
        "ar": "تذكير بموعدك في {name}: {service} يوم {day} الساعة {time}. هل ستحضر؟",
        "en": "Reminder from {name}: {service} on {day} at {time}. Will you make it?",
    },
    "btn_attend": {"ar": "سأحضر", "en": "I'll be there"},
    "attend_ok": {"ar": "ممتاز، بانتظارك.", "en": "Great, see you then."},
    "bot_resumed": {"ar": "رجعت لك المساعد الآلي. اكتب «القائمة» في أي وقت.", "en": "The assistant is back. Type \"menu\" any time."},
}

GREETINGS = [
    "مرحبا", "مرحبتين", "هلا", "هلا والله", "اهلا", "السلام عليكم", "سلام عليكم", "السلام", "صباح الخير",
    "مساء الخير", "هاي", "القائمه", "قائمه", "البدايه", "ابدا", "start", "menu", "hi", "hello", "hey", "salam",
]
BOOK_WORDS = [
    "حجز", "احجز", "ابي احجز", "ابغى احجز", "موعد", "ابي موعد", "حجز موعد", "اخذ موعد", "book", "booking",
    "appointment", "schedule",
]
MY_APPTS = ["مواعيدي", "موعدي", "حجوزاتي", "حجزي", "my appointments", "my appointment", "my booking", "my bookings"]
CANCEL_FLOW = ["الغاء", "وقف", "خلاص", "cancel", "stop"]


def t(key: str, lang: str, **kw) -> str:
    s = T[key]["en" if lang == "en" else "ar"]
    return s.format(**kw) if kw else s
