"""Use the agent as a library: feed it webhook payloads, read the replies it would send.

    python examples/python_api.py
"""

from whatsapp_agent_ar import Agent, Business, Store
from whatsapp_agent_ar.providers import Mock
from whatsapp_agent_ar.server import simulated_webhook
from whatsapp_agent_ar.whatsapp import WhatsAppClient, summarize

biz = Business.load("examples/clinic/business.json")  # SAMPLE business (fictional clinic)
client = WhatsAppClient(dry_run=True)  # nothing leaves your machine
agent = Agent(biz, Store(":memory:"), client, Mock())

for text, reply_id in [
    ("السلام عليكم", ""),
    ("وين مكانكم؟ وفي باركنج؟", ""),
    ("ابي احجز تنظيف", ""),
]:
    before = len(client.outbox)
    agent.handle_webhook(simulated_webhook("971500000123", "Sample", text, reply_id))
    print(f"\n> {text}")
    for payload in client.outbox[before:]:
        print(summarize(payload))
