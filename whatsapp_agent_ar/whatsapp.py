"""Official WhatsApp Cloud API (Meta Graph API) helpers.

Covers exactly what the agent needs, following Meta's documented contract:

* Webhook verification handshake (GET ``hub.mode`` / ``hub.verify_token`` / ``hub.challenge``).
* ``X-Hub-Signature-256`` check: HMAC-SHA256 of the *raw* request body with the App Secret.
* Parsing inbound ``messages`` and delivery ``statuses`` from webhook payloads.
* Builders for text, reply-button, list and template messages, enforcing Meta's
  documented size limits so a request is never rejected for a too-long title.
* The 24-hour customer service window: free-form messages are only allowed within
  24 hours of the customer's last message; outside it only approved templates.
* A tiny client for ``POST /{phone-number-id}/messages`` with a dry-run mode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ---- Documented limits (WhatsApp Cloud API interactive / text messages) ----
TEXT_MAX = 4096
INTERACTIVE_BODY_MAX = 1024
BUTTON_TITLE_MAX = 20
BUTTON_ID_MAX = 256
MAX_BUTTONS = 3
LIST_BUTTON_MAX = 20
LIST_ROW_TITLE_MAX = 24
LIST_ROW_DESC_MAX = 72
LIST_SECTION_TITLE_MAX = 24
LIST_MAX_ROWS = 10
HEADER_TEXT_MAX = 60
FOOTER_MAX = 60

SERVICE_WINDOW = timedelta(hours=24)

# Error codes worth explaining to staff in the dashboard.
KNOWN_ERRORS = {
    131047: "Re-engagement message: more than 24 hours since the customer's last message. Send an approved template.",
    131026: "Message undeliverable (number not on WhatsApp, old app version, or the customer blocked you).",
    131051: "Unsupported message type.",
    132000: "Template parameter count does not match the approved template.",
    132001: "Template does not exist in this language or is not approved.",
    130429: "Rate limit hit (Cloud API throughput). Retry later.",
    131056: "Too many messages to the same user in a short time (pair rate limit).",
    190: "Access token expired or invalid.",
}


class WhatsAppError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


# --------------------------------------------------------------------------- webhook security
def verify_subscription(params: dict, verify_token: str) -> str | None:
    """Return ``hub.challenge`` if Meta's verification request is valid, else None."""
    if not verify_token:
        return None
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token") or ""
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and challenge is not None and hmac.compare_digest(str(token), verify_token):
        return str(challenge)
    return None


def sign(body: bytes, app_secret: str) -> str:
    """Compute the ``X-Hub-Signature-256`` header value Meta would send for ``body``."""
    return "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    """Constant-time check of ``X-Hub-Signature-256`` against the raw body.

    Fails closed: no secret configured or no/malformed header means *reject*.
    """
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(sign(body, app_secret), header.strip())


# --------------------------------------------------------------------------- inbound parsing
@dataclass
class Inbound:
    wa_id: str
    wamid: str
    timestamp: datetime
    type: str
    text: str = ""
    reply_id: str = ""  # interactive button/list id, or template quick-reply payload
    name: str = ""
    phone_number_id: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def display(self) -> str:
        if self.text:
            return self.text
        return f"[{self.type}]"


@dataclass
class StatusUpdate:
    wamid: str
    status: str  # sent | delivered | read | failed
    recipient: str
    timestamp: datetime
    errors: list = field(default_factory=list)


def _ts(raw) -> datetime:
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def parse_webhook(payload: dict) -> tuple[list[Inbound], list[StatusUpdate]]:
    """Extract messages and statuses from a WhatsApp Business Account webhook."""
    messages: list[Inbound] = []
    statuses: list[StatusUpdate] = []
    if payload.get("object") != "whatsapp_business_account":
        return messages, statuses
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            pnid = (value.get("metadata") or {}).get("phone_number_id", "")
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in value.get("contacts", []) or []}
            for m in value.get("messages", []) or []:
                mtype = m.get("type", "unknown")
                text, reply_id = "", ""
                if mtype == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif mtype == "interactive":
                    inter = m.get("interactive") or {}
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    reply_id, text = reply.get("id", ""), reply.get("title", "")
                elif mtype == "button":  # quick-reply button on a template
                    btn = m.get("button") or {}
                    reply_id, text = btn.get("payload", ""), btn.get("text", "")
                elif mtype in {"image", "video", "document", "audio", "sticker"}:
                    text = (m.get(mtype) or {}).get("caption", "")
                elif mtype == "location":
                    loc = m.get("location") or {}
                    text = loc.get("name") or loc.get("address") or ""
                messages.append(
                    Inbound(
                        wa_id=m.get("from", ""),
                        wamid=m.get("id", ""),
                        timestamp=_ts(m.get("timestamp")),
                        type=mtype,
                        text=text,
                        reply_id=reply_id,
                        name=names.get(m.get("from"), ""),
                        phone_number_id=pnid,
                        raw=m,
                    )
                )
            for s in value.get("statuses", []) or []:
                statuses.append(
                    StatusUpdate(
                        wamid=s.get("id", ""),
                        status=s.get("status", ""),
                        recipient=s.get("recipient_id", ""),
                        timestamp=_ts(s.get("timestamp")),
                        errors=s.get("errors", []) or [],
                    )
                )
    return messages, statuses


# --------------------------------------------------------------------------- 24h window
def in_service_window(last_inbound: datetime | None, now: datetime) -> bool:
    """True if a free-form (non-template) message may be sent right now."""
    if last_inbound is None:
        return False
    return now - last_inbound < SERVICE_WINDOW


def window_closes_at(last_inbound: datetime | None) -> datetime | None:
    return last_inbound + SERVICE_WINDOW if last_inbound else None


# --------------------------------------------------------------------------- message builders
def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _base(to: str, mtype: str) -> dict:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": mtype}


def text_message(to: str, body: str, preview_url: bool = False) -> dict:
    msg = _base(to, "text")
    msg["text"] = {"body": _clip(body, TEXT_MAX), "preview_url": preview_url}
    return msg


def buttons_message(to: str, body: str, buttons: list[tuple[str, str]], footer: str = "") -> dict:
    """Reply buttons: up to 3, each (id, title<=20 chars)."""
    if not 1 <= len(buttons) <= MAX_BUTTONS:
        raise ValueError(f"Reply buttons need 1-{MAX_BUTTONS} buttons, got {len(buttons)}")
    msg = _base(to, "interactive")
    inter = {
        "type": "button",
        "body": {"text": _clip(body, INTERACTIVE_BODY_MAX)},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": bid[:BUTTON_ID_MAX], "title": _clip(title, BUTTON_TITLE_MAX)}}
                for bid, title in buttons
            ]
        },
    }
    if footer:
        inter["footer"] = {"text": _clip(footer, FOOTER_MAX)}
    msg["interactive"] = inter
    return msg


def list_message(
    to: str,
    body: str,
    button: str,
    rows: list[tuple[str, str, str]],
    section_title: str = "",
    header: str = "",
    footer: str = "",
) -> dict:
    """Single-section list: rows of (id, title<=24, description<=72), max 10 rows."""
    if not rows:
        raise ValueError("A list message needs at least one row")
    rows = rows[:LIST_MAX_ROWS]
    msg = _base(to, "interactive")
    section: dict = {
        "rows": [
            {k: v for k, v in {"id": rid[:200], "title": _clip(t, LIST_ROW_TITLE_MAX), "description": _clip(d, LIST_ROW_DESC_MAX)}.items() if v}
            for rid, t, d in rows
        ]
    }
    if section_title:
        section["title"] = _clip(section_title, LIST_SECTION_TITLE_MAX)
    inter: dict = {
        "type": "list",
        "body": {"text": _clip(body, TEXT_MAX)},
        "action": {"button": _clip(button, LIST_BUTTON_MAX), "sections": [section]},
    }
    if header:
        inter["header"] = {"type": "text", "text": _clip(header, HEADER_TEXT_MAX)}
    if footer:
        inter["footer"] = {"text": _clip(footer, FOOTER_MAX)}
    msg["interactive"] = inter
    return msg


def template_message(to: str, name: str, lang: str, body_params: list[str] | None = None) -> dict:
    """Pre-approved template (the only thing allowed outside the 24h window)."""
    msg = _base(to, "template")
    tpl: dict = {"name": name, "language": {"code": lang}}
    if body_params:
        tpl["components"] = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in body_params]}]
    msg["template"] = tpl
    return msg


def read_receipt(wamid: str) -> dict:
    return {"messaging_product": "whatsapp", "status": "read", "message_id": wamid}


def summarize(payload: dict) -> str:
    """Human-readable text of an outgoing payload (stored in the conversation log)."""
    t = payload.get("type")
    if t == "text":
        return payload["text"]["body"]
    if t == "interactive":
        inter = payload["interactive"]
        body = inter["body"]["text"]
        if inter["type"] == "button":
            opts = " | ".join(b["reply"]["title"] for b in inter["action"]["buttons"])
        else:
            opts = " | ".join(r["title"] for s in inter["action"]["sections"] for r in s["rows"])
        return f"{body}\n[{opts}]"
    if t == "template":
        tpl = payload["template"]
        params = [p["text"] for c in tpl.get("components", []) for p in c.get("parameters", [])]
        return f"[template: {tpl['name']} ({tpl['language']['code']})] " + " / ".join(params)
    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- client
@dataclass
class SendResult:
    wamid: str
    status: str  # sent | dry_run
    response: dict = field(default_factory=dict)


class WhatsAppClient:
    def __init__(
        self,
        access_token: str = "",
        phone_number_id: str = "",
        graph_version: str = "v23.0",
        base_url: str = "https://graph.facebook.com",
        dry_run: bool = True,
        timeout: float = 15.0,
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.graph_version = graph_version
        self.base_url = base_url.rstrip("/")
        self.dry_run = dry_run
        self.timeout = timeout
        self.outbox: list[dict] = []  # every payload, sent or dry-run (handy for tests)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/{self.graph_version}/{self.phone_number_id}/messages"

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(raw).get("error", {})
            except ValueError:
                err = {"message": raw[:300]}
            code = err.get("code")
            hint = KNOWN_ERRORS.get(code, "")
            msg = f"WhatsApp API {e.code}: {err.get('message', '')} (code {code}). {hint}".strip()
            raise WhatsAppError(msg, code=code, status=e.code) from e
        except urllib.error.URLError as e:
            raise WhatsAppError(f"Cannot reach {self.endpoint}: {e.reason}") from e

    def send(self, payload: dict) -> SendResult:
        self.outbox.append(payload)
        if self.dry_run:
            return SendResult(wamid=f"dryrun.{uuid.uuid4().hex[:16]}", status="dry_run")
        data = self._post(payload)
        wamid = ((data.get("messages") or [{}])[0]).get("id", "")
        return SendResult(wamid=wamid, status="sent", response=data)

    def mark_read(self, wamid: str) -> None:
        if self.dry_run or not wamid:
            return
        try:
            self._post(read_receipt(wamid))
        except WhatsAppError:
            pass  # read receipts are best-effort
