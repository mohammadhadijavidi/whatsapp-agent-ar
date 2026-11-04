"""WSGI app: WhatsApp webhook + staff dashboard + JSON API.

Runs on the standard library (``wsgiref``) for development and under any WSGI
server (gunicorn, waitress, uWSGI) in production:

    gunicorn 'whatsapp_agent_ar.server:create_app()' -b 0.0.0.0:8000

Routes
------
GET  /webhook                     Meta verification handshake
POST /webhook                     Inbound messages + statuses (X-Hub-Signature-256 required)
GET  /health                      Liveness probe
GET  /                            Dashboard (HTTP Basic auth when DASHBOARD_PASSWORD is set)
GET  /api/stats | /api/conversations | /api/conversations/<wa_id> | /api/appointments
POST /api/conversations/<wa_id>/reply      {"text": ...}           free-form staff reply (24h window)
POST /api/conversations/<wa_id>/template   {"name","lang","params"} template (any time)
POST /api/conversations/<wa_id>/handoff    {"action": "take"|"release"}
POST /api/simulate                {"wa_id","name","text"|"reply_id"}  dry-run only
POST /api/reminders/run           send due reminders
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import time
from datetime import timedelta
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, unquote
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from . import whatsapp as wa
from .agent import Agent, WindowClosed
from .business import Business
from .config import Settings, load_dotenv
from .providers import get_llm
from .store import Store, parse

log = logging.getLogger("whatsapp_agent_ar")
MAX_BODY = 1_000_000  # Meta payloads are small; refuse anything huge
STATIC = Path(__file__).parent / "static"


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


class App:
    def __init__(self, agent: Agent, settings: Settings):
        self.agent = agent
        self.settings = settings

    # -------------------------------------------------------------- WSGI plumbing
    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/") or "/"
        try:
            status, headers, body = self.dispatch(method, path, environ)
        except Exception:  # pragma: no cover - last-resort guard
            log.exception("unhandled error on %s %s", method, path)
            status, headers, body = "500 Internal Server Error", [("Content-Type", "application/json")], b'{"error":"internal"}'
        headers = [*headers, ("Content-Length", str(len(body))), ("X-Content-Type-Options", "nosniff")]
        start_response(status, headers)
        return [body]

    @staticmethod
    def _read(environ) -> bytes:
        try:
            n = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return b""
        if n > MAX_BODY:
            raise ValueError("body too large")
        return environ["wsgi.input"].read(n)

    def _json(self, code: str, obj) -> tuple:
        return code, [("Content-Type", "application/json; charset=utf-8")], _json_bytes(obj)

    def _authorized(self, environ) -> bool:
        if not self.settings.dashboard_password:
            return True
        header = environ.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(user, self.settings.dashboard_user) and hmac.compare_digest(
            pw, self.settings.dashboard_password
        )

    # -------------------------------------------------------------- routing
    def dispatch(self, method: str, path: str, environ) -> tuple:
        if path == "/health":
            return self._json("200 OK", {"ok": True, "dry_run": self.settings.dry_run})
        if path == "/webhook":
            if method == "GET":
                return self.webhook_verify(environ)
            if method == "POST":
                return self.webhook_receive(environ)
            return self._json("405 Method Not Allowed", {"error": "method"})

        # Everything else is the staff dashboard.
        if not self._authorized(environ):
            return "401 Unauthorized", [("WWW-Authenticate", 'Basic realm="whatsapp-agent-ar"'), ("Content-Type", "text/plain")], b"auth required"
        if method == "GET" and path in {"/", "/index.html"}:
            return "200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store")], (STATIC / "dashboard.html").read_bytes()
        if method == "GET" and path.startswith("/static/fonts/"):
            name = Path(path).name
            f = STATIC / "fonts" / name
            if f.is_file() and f.suffix == ".woff2":
                return "200 OK", [("Content-Type", "font/woff2"), ("Cache-Control", "max-age=86400")], f.read_bytes()
            return self._json("404 Not Found", {"error": "not found"})
        if path.startswith("/api/"):
            return self.api(method, path[5:], environ)
        return self._json("404 Not Found", {"error": "not found"})

    # -------------------------------------------------------------- webhook
    def webhook_verify(self, environ) -> tuple:
        params = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        challenge = wa.verify_subscription(params, self.settings.verify_token)
        if challenge is None:
            return "403 Forbidden", [("Content-Type", "text/plain")], b"verification failed"
        return "200 OK", [("Content-Type", "text/plain")], challenge.encode("utf-8")

    def webhook_receive(self, environ) -> tuple:
        try:
            raw = self._read(environ)
        except ValueError:
            return self._json("413 Payload Too Large", {"error": "too large"})
        if not wa.verify_signature(raw, environ.get("HTTP_X_HUB_SIGNATURE_256"), self.settings.app_secret):
            log.warning("rejected webhook with missing/invalid X-Hub-Signature-256")
            return self._json("401 Unauthorized", {"error": "invalid signature"})
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json("400 Bad Request", {"error": "invalid json"})
        result = self.agent.handle_webhook(payload)
        # Always 200 quickly so Meta does not retry; duplicates are de-duplicated by wamid anyway.
        return self._json("200 OK", result)

    # -------------------------------------------------------------- dashboard API
    def _conversation_view(self, c: dict) -> dict:
        now = self.agent.clock()
        last_in = parse(c.get("last_inbound_at"))
        closes = wa.window_closes_at(last_in)
        return {
            "wa_id": c["wa_id"],
            "name": c.get("name") or "",
            "lang": c.get("lang"),
            "state": c.get("state"),
            "handoff": bool(c.get("handoff")),
            "handoff_reason": c.get("handoff_reason") or "",
            "unread": c.get("unread", 0),
            "last_body": c.get("last_body") or "",
            "last_author": c.get("last_author") or "",
            "last_message_at": c.get("last_message_at"),
            "window_open": wa.in_service_window(last_in, now),
            "window_closes_at": closes.isoformat() if closes else None,
            "window_seconds_left": max(0, int((closes - now).total_seconds())) if closes else 0,
        }

    def api(self, method: str, route: str, environ) -> tuple:
        store, agent = self.agent.store, self.agent
        parts = [unquote(p) for p in route.strip("/").split("/") if p]
        body = {}
        if method == "POST":
            try:
                raw = self._read(environ)
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                return self._json("400 Bad Request", {"error": "invalid json"})

        if method == "GET" and parts == ["stats"]:
            now = agent.clock()
            s = store.stats(now - timedelta(days=7))
            s["automation_rate"] = round(s["bot_replies"] / max(1, s["bot_replies"] + s["staff_replies"]), 3)
            return self._json("200 OK", {
                **s,
                "business": agent.biz.name,
                "business_en": agent.biz.name_en,
                "dry_run": self.settings.dry_run,
                "provider": agent.llm.name,
                "config_problems": self.settings.problems(),
                "now": now.isoformat(),
            })
        if method == "GET" and parts == ["conversations"]:
            return self._json("200 OK", [self._conversation_view(c) for c in store.conversations()])
        if method == "GET" and parts == ["appointments"]:
            now = agent.clock()
            out = []
            for a in store.appointments(status="confirmed", since=now):
                svc = agent.biz.service(a["service_id"])
                out.append({**a, "service": svc.name if svc else a["service_id"], "service_en": svc.name_en if svc else ""})
            return self._json("200 OK", out)
        if method == "GET" and parts == ["templates"]:
            return self._json("200 OK", {"reminder": {"name": agent.reminder_template, "lang": agent.reminder_template_lang}})
        if len(parts) >= 2 and parts[0] == "conversations":
            wa_id = parts[1]
            if not wa_id.isdigit():
                return self._json("400 Bad Request", {"error": "wa_id must be digits"})
            if method == "GET" and len(parts) == 2:
                c = next((c for c in store.conversations() if c["wa_id"] == wa_id), None)
                if not c:
                    return self._json("404 Not Found", {"error": "no such conversation"})
                store.mark_seen(wa_id)
                return self._json("200 OK", {**self._conversation_view(c), "messages": store.messages(wa_id)})
            if method == "POST" and len(parts) == 3 and parts[2] == "reply":
                text = (body.get("text") or "").strip()
                if not text:
                    return self._json("400 Bad Request", {"error": "text is required"})
                try:
                    return self._json("200 OK", agent.staff_reply(wa_id, text))
                except WindowClosed:
                    return self._json("409 Conflict", {
                        "error": "outside_24h_window",
                        "message": "More than 24 hours since the customer's last message. WhatsApp only allows an approved template now.",
                    })
            if method == "POST" and len(parts) == 3 and parts[2] == "template":
                name = body.get("name") or agent.reminder_template
                lang = body.get("lang") or agent.reminder_template_lang
                params = [str(p) for p in body.get("params", [])]
                return self._json("200 OK", agent.staff_template(wa_id, name, lang, params))
            if method == "POST" and len(parts) == 3 and parts[2] == "handoff":
                action = body.get("action")
                if action == "take":
                    agent.take_over(wa_id)
                elif action == "release":
                    agent.resolve_handoff(wa_id, notify=bool(body.get("notify")))
                else:
                    return self._json("400 Bad Request", {"error": "action must be take or release"})
                return self._json("200 OK", {"ok": True})
        if method == "POST" and parts == ["reminders", "run"]:
            return self._json("200 OK", agent.send_due_reminders(int(body.get("hours_before", 24))))
        if method == "POST" and parts == ["simulate"]:
            if not self.settings.dry_run:
                return self._json("403 Forbidden", {"error": "simulate is only available in dry-run mode"})
            payload = simulated_webhook(
                body.get("wa_id") or "971500000000", body.get("name") or "", body.get("text") or "",
                body.get("reply_id") or "", self.settings.phone_number_id or "DRYRUN",
            )
            return self._json("200 OK", agent.handle_webhook(payload))
        return self._json("404 Not Found", {"error": "not found"})


_SIM_COUNTER = [0]


def simulated_webhook(wa_id: str, name: str, text: str = "", reply_id: str = "", phone_number_id: str = "DRYRUN", ts: int | None = None) -> dict:
    """Build a payload with the exact shape Meta posts to the webhook (for local testing)."""
    _SIM_COUNTER[0] += 1
    ts = ts or int(time.time())
    msg: dict = {"from": wa_id, "id": f"wamid.SIM{ts}{_SIM_COUNTER[0]:06d}", "timestamp": str(ts)}
    if reply_id:
        kind = "list_reply" if reply_id.split(":", 1)[0] in {"svc", "day", "slot", "faq"} else "button_reply"
        msg.update(type="interactive", interactive={"type": kind, kind: {"id": reply_id, "title": text or reply_id}})
    else:
        msg.update(type="text", text={"body": text})
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "971400000000", "phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": name}, "wa_id": wa_id}],
                    "messages": [msg],
                },
            }],
        }],
    }


def build_agent(settings: Settings) -> Agent:
    biz = Business.load(settings.business_file or None)
    store = Store(settings.db_path)
    client = wa.WhatsAppClient(
        settings.access_token, settings.phone_number_id, settings.graph_version, settings.graph_base, dry_run=settings.dry_run
    )
    return Agent(
        biz, store, client, get_llm(settings.provider, settings.model or None),
        reminder_template=settings.reminder_template, reminder_template_lang=settings.reminder_template_lang,
    )


def create_app(settings: Settings | None = None, agent: Agent | None = None) -> App:
    if settings is None:
        load_dotenv()
        settings = Settings.from_env()
    return App(agent or build_agent(settings), settings)


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):  # keep logs readable; one line per request
        log.info("%s %s", self.address_string(), fmt % args)


def serve(app: App, host: str = "127.0.0.1", port: int = 8000) -> None:
    with make_server(host, port, app, server_class=_ThreadingWSGIServer, handler_class=_QuietHandler) as httpd:
        mode = "DRY-RUN (nothing is sent to WhatsApp)" if app.settings.dry_run else "LIVE"
        print(f"whatsapp-agent-ar on http://{host}:{port}  [{mode}]  webhook: /webhook  dashboard: /")
        for p in app.settings.problems():
            print(f"  ! {p}")
        httpd.serve_forever()
