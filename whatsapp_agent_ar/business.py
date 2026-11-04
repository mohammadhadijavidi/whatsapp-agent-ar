"""Business profile: name, opening hours, services, FAQ knowledge base."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .arabic import normalize

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # matches date.weekday()
DAY_NAMES_AR = {
    "mon": "الاثنين",
    "tue": "الثلاثاء",
    "wed": "الأربعاء",
    "thu": "الخميس",
    "fri": "الجمعة",
    "sat": "السبت",
    "sun": "الأحد",
}
DAY_NAMES_EN = {k: k.capitalize() for k in DAY_KEYS}

EXAMPLE_FILE = Path(__file__).parent / "data" / "clinic.json"


@dataclass
class Service:
    id: str
    name: str
    name_en: str
    minutes: int
    price: float | None = None
    keywords: list[str] = field(default_factory=list)

    def label(self, arabic: bool = True) -> str:
        return self.name if arabic else self.name_en


@dataclass
class FAQ:
    id: str
    questions: list[str]
    answer: str
    answer_en: str = ""


@dataclass
class Business:
    name: str
    name_en: str
    timezone: str = "Asia/Dubai"
    currency: str = "AED"
    slot_step_minutes: int = 30
    min_notice_minutes: int = 60
    booking_horizon_days: int = 14
    hours: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # day -> [(start_min, end_min)]
    closed_dates: set[date] = field(default_factory=set)
    services: list[Service] = field(default_factory=list)
    faq: list[FAQ] = field(default_factory=list)
    handoff_keywords: list[str] = field(default_factory=list)

    def service(self, service_id: str) -> Service | None:
        return next((s for s in self.services if s.id == service_id), None)

    def match_service(self, text: str) -> Service | None:
        """Find a service mentioned in free text (e.g. 'ابي احجز تنظيف')."""
        from .arabic import stem

        words = re.findall(r"[\w\u0600-\u06FF]+", normalize(text))
        norm = f" {' '.join(words)} "
        stems = {stem(w) for w in words} | {w[1:] for w in words if w[:1] == "ل" and len(w) > 4}
        stems |= {stem(w) for w in stems}
        for s in self.services:
            for kw in [s.name, s.name_en, *s.keywords]:
                k = normalize(kw)
                if not k:
                    continue
                if f" {k} " in norm or (" " not in k and stem(k) in stems):
                    return s
        return None

    @classmethod
    def from_dict(cls, data: dict) -> "Business":
        def parse_range(r: str) -> tuple[int, int]:
            a, b = r.split("-")
            ha, ma = map(int, a.split(":"))
            hb, mb = map(int, b.split(":"))
            start, end = ha * 60 + ma, hb * 60 + mb
            if end <= start:
                raise ValueError(f"Invalid opening range {r!r} (end must be after start, same day)")
            return start, end

        hours = {}
        for day, ranges in (data.get("hours") or {}).items():
            if day not in DAY_KEYS:
                raise ValueError(f"Unknown day key {day!r}; use one of {DAY_KEYS}")
            hours[day] = sorted(parse_range(r) for r in ranges)
        services = [
            Service(
                id=s["id"],
                name=s["name"],
                name_en=s.get("name_en", s["name"]),
                minutes=int(s.get("minutes", 30)),
                price=s.get("price"),
                keywords=list(s.get("keywords", [])),
            )
            for s in data.get("services", [])
        ]
        faq = [
            FAQ(id=f.get("id", str(i)), questions=list(f["questions"]), answer=f["answer"], answer_en=f.get("answer_en", ""))
            for i, f in enumerate(data.get("faq", []))
        ]
        return cls(
            name=data["name"],
            name_en=data.get("name_en", data["name"]),
            timezone=data.get("timezone", "Asia/Dubai"),
            currency=data.get("currency", "AED"),
            slot_step_minutes=int(data.get("slot_step_minutes", 30)),
            min_notice_minutes=int(data.get("min_notice_minutes", 60)),
            booking_horizon_days=int(data.get("booking_horizon_days", 14)),
            hours=hours,
            closed_dates={date.fromisoformat(d) for d in data.get("closed_dates", [])},
            services=services,
            faq=faq,
            handoff_keywords=list(data.get("handoff_keywords", [])),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Business":
        p = Path(path) if path else EXAMPLE_FILE
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
