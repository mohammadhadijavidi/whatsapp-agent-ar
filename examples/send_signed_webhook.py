"""Post a correctly signed webhook to a local server, exactly like Meta does.

    whatsapp-agent-ar serve --dry-run          # with WHATSAPP_APP_SECRET set in .env
    python examples/send_signed_webhook.py "ابي احجز تبييض"

The payload shape matches the WhatsApp Cloud API webhook; the signature is
HMAC-SHA256 of the raw body with your App Secret (X-Hub-Signature-256).
"""

import json
import os
import sys
import time
import urllib.request

from whatsapp_agent_ar.config import load_dotenv
from whatsapp_agent_ar.server import simulated_webhook
from whatsapp_agent_ar.whatsapp import sign

load_dotenv()
secret = os.environ.get("WHATSAPP_APP_SECRET")
if not secret:
    sys.exit("Set WHATSAPP_APP_SECRET (same value the server uses).")

text = sys.argv[1] if len(sys.argv) > 1 else "مرحبا"
url = os.environ.get("WEBHOOK_URL", "http://127.0.0.1:8000/webhook")
body = json.dumps(simulated_webhook("971500000123", "Sample Customer", text, ts=int(time.time())), ensure_ascii=False).encode()
req = urllib.request.Request(
    url, data=body, method="POST",
    headers={"Content-Type": "application/json", "X-Hub-Signature-256": sign(body, secret)},
)
with urllib.request.urlopen(req) as r:
    print(r.status, r.read().decode())
print("Open the dashboard to see the agent's reply (dry-run: nothing was sent to WhatsApp).")
