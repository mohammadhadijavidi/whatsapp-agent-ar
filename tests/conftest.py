from datetime import datetime, timedelta, timezone

import pytest

from whatsapp_agent_ar import whatsapp as wa
from whatsapp_agent_ar.agent import Agent
from whatsapp_agent_ar.business import Business
from whatsapp_agent_ar.providers import Mock
from whatsapp_agent_ar.server import simulated_webhook
from whatsapp_agent_ar.store import Store

# Wednesday 4 Nov 2026, 10:00 in Dubai (UTC+4)
NOW = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def biz():
    return Business.load()


@pytest.fixture
def agent(biz, clock):
    return Agent(biz, Store(":memory:"), wa.WhatsAppClient(dry_run=True), Mock(), clock=clock)


class Chat:
    """Drive the agent through real webhook payloads and inspect the replies."""

    def __init__(self, agent, clock, wa_id="971501234567", name="Test"):
        self.agent, self.clock, self.wa_id, self.name = agent, clock, wa_id, name

    def say(self, text="", reply_id=""):
        before = len(self.agent.client.outbox)
        self.agent.handle_webhook(
            simulated_webhook(self.wa_id, self.name, text, reply_id, ts=int(self.clock().timestamp()))
        )
        return self.agent.client.outbox[before:]

    def last(self):
        return self.agent.client.outbox[-1]


def options(payload):
    inter = payload["interactive"]
    if inter["type"] == "button":
        return [(b["reply"]["id"], b["reply"]["title"]) for b in inter["action"]["buttons"]]
    return [(r["id"], r["title"]) for s in inter["action"]["sections"] for r in s["rows"]]


def text_of(payload):
    return wa.summarize(payload)


@pytest.fixture
def chat(agent, clock):
    return Chat(agent, clock)
