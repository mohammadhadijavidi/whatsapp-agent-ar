"""Command line: serve, chat (terminal simulator), demo, reminders, sign, check."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import __version__
from . import whatsapp as wa
from .config import Settings, load_dotenv


def _settings(args) -> Settings:
    load_dotenv(getattr(args, "env_file", ".env") or ".env")
    s = Settings.from_env()
    if getattr(args, "business", None):
        s.business_file = args.business
    if getattr(args, "db", None):
        s.db_path = args.db
    if getattr(args, "provider", None):
        s.provider = args.provider
    return s


def cmd_serve(args) -> int:
    from .server import create_app, serve

    s = _settings(args)
    if args.dry_run:
        s.dry_run = True
    app = create_app(s)
    if args.demo:
        from .demo import seed

        if not s.dry_run:
            print("--demo requires dry-run mode", file=sys.stderr)
            return 2
        seed(app.agent.store, app.agent.biz)
        print("Seeded SAMPLE conversations (fictional customers, real agent replies, dry-run).")
    serve(app, args.host, args.port)
    return 0


def cmd_demo(args) -> int:
    from .demo import seed
    from .store import Store

    s = _settings(args)
    store = Store(s.db_path)
    seed(store)
    print(f"Seeded SAMPLE conversations into {s.db_path} (dry-run, nothing sent).")
    return 0


def cmd_chat(args) -> int:
    """Talk to the agent in the terminal. Uses dry-run, prints the exact payloads."""
    from .agent import Agent
    from .business import Business
    from .providers import get_llm
    from .server import simulated_webhook
    from .store import Store

    s = _settings(args)
    biz = Business.load(s.business_file or None)
    client = wa.WhatsAppClient(dry_run=True)
    agent = Agent(biz, Store(":memory:"), client, get_llm(s.provider, s.model or None))
    wa_id = args.wa_id
    print(f"Chatting with {biz.name} / {biz.name_en} (dry-run). Reply ids: type '#<id>' e.g. #menu:book. Ctrl-D to quit.")
    lines = args.message or None
    pending_rows: list[tuple[str, str]] = []
    while True:
        if lines is not None:
            if not lines:
                break
            text = lines.pop(0)
            print(f"\n> {text}")
        else:
            try:
                text = input("\n> ")
            except EOFError:
                break
        reply_id, body = "", text
        if text.startswith("#"):
            reply_id, body = text[1:].strip(), ""
        elif text.strip().isdigit() and pending_rows:
            i = int(text.strip()) - 1
            if 0 <= i < len(pending_rows):
                reply_id, body = pending_rows[i]
        before = len(client.outbox)
        agent.handle_webhook(simulated_webhook(wa_id, args.name, body, reply_id))
        pending_rows = []
        for p in client.outbox[before:]:
            if args.json:
                print(json.dumps(p, ensure_ascii=False, indent=2))
                continue
            print(wa.summarize(p).split("\n[")[0])
            if p["type"] == "interactive":
                inter = p["interactive"]
                opts = (
                    [(b["reply"]["id"], b["reply"]["title"]) for b in inter["action"]["buttons"]]
                    if inter["type"] == "button"
                    else [(r["id"], r["title"]) for sec in inter["action"]["sections"] for r in sec["rows"]]
                )
                for n, (rid, title) in enumerate(opts, 1):
                    print(f"   {n}. {title}    (#{rid})")
                pending_rows = opts
        if agent.store.contact(wa_id)["handoff"]:
            print("   [handed off to staff: the bot stays silent until released in the dashboard]")
    return 0


def cmd_reminders(args) -> int:
    from .server import build_agent

    s = _settings(args)
    agent = build_agent(s)
    res = agent.send_due_reminders(args.hours)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_sign(args) -> int:
    """Print the X-Hub-Signature-256 for a file, to test the webhook with curl."""
    s = _settings(args)
    secret = args.secret or s.app_secret
    if not secret:
        print("Provide --secret or set WHATSAPP_APP_SECRET", file=sys.stderr)
        return 2
    with open(args.file, "rb") as fh:
        print(wa.sign(fh.read(), secret))
    return 0


def cmd_check(args) -> int:
    s = _settings(args)
    from .business import Business

    biz = Business.load(s.business_file or None)
    print(f"Business: {biz.name} / {biz.name_en}  ({len(biz.services)} services, {len(biz.faq)} FAQ entries)")
    print(f"Mode: {'dry-run' if s.dry_run else 'LIVE'}   Graph API: {s.graph_version}   LLM fallback: {s.provider}")
    problems = s.problems()
    for p in problems:
        print(f"  ! {p}")
    if not problems:
        print("  Configuration looks complete.")
    return 1 if problems and not s.dry_run else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="whatsapp-agent-ar", description="Arabic AI agent on the official WhatsApp Cloud API")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--business", help="business JSON file (default: bundled sample clinic)")
        sp.add_argument("--db", help="SQLite path (default: WA_DB_PATH or whatsapp_agent.db)")
        sp.add_argument("--provider", help="LLM fallback provider (mock, openai, openrouter, groq, ollama, lmstudio, anthropic)")
        sp.add_argument("--env-file", default=".env")

    sp = sub.add_parser("serve", help="run webhook + dashboard")
    common(sp)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--dry-run", action="store_true", help="never call Meta, log payloads only")
    sp.add_argument("--demo", action="store_true", help="seed SAMPLE conversations (dry-run only)")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("chat", help="chat with the agent in the terminal (dry-run)")
    common(sp)
    sp.add_argument("--wa-id", default="971500000001")
    sp.add_argument("--name", default="Test")
    sp.add_argument("--json", action="store_true", help="print raw Cloud API payloads")
    sp.add_argument("-m", "--message", action="append", help="send these messages non-interactively")
    sp.set_defaults(func=cmd_chat)

    sp = sub.add_parser("demo", help="seed SAMPLE conversations into the database")
    common(sp)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("reminders", help="send reminders for appointments in the next N hours (run from cron)")
    common(sp)
    sp.add_argument("--hours", type=int, default=24)
    sp.set_defaults(func=cmd_reminders)

    sp = sub.add_parser("sign", help="compute X-Hub-Signature-256 for a payload file")
    sp.add_argument("file")
    sp.add_argument("--secret")
    sp.add_argument("--env-file", default=".env")
    sp.set_defaults(func=cmd_sign)

    sp = sub.add_parser("check", help="validate configuration and business file")
    common(sp)
    sp.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
