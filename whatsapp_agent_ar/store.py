"""SQLite persistence: contacts, messages, appointments, webhook de-duplication."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    wa_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    lang TEXT DEFAULT 'ar',
    state TEXT DEFAULT 'idle',
    state_data TEXT DEFAULT '{}',
    handoff INTEGER DEFAULT 0,
    handoff_reason TEXT DEFAULT '',
    handoff_at TEXT,
    misses INTEGER DEFAULT 0,
    last_inbound_at TEXT,
    last_message_at TEXT,
    unread INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_id TEXT NOT NULL,
    direction TEXT NOT NULL,          -- in | out
    author TEXT NOT NULL,             -- customer | bot | staff | system
    kind TEXT NOT NULL,               -- text | interactive | template | image | audio | ...
    body TEXT NOT NULL,
    payload TEXT,                     -- JSON sent to / received from Meta
    wamid TEXT,
    status TEXT DEFAULT '',           -- queued | dry_run | sent | delivered | read | failed | blocked
    meta TEXT DEFAULT '{}',           -- e.g. {"source": "kb:prices"}
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_wa ON messages (wa_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_wamid ON messages (wamid);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_id TEXT NOT NULL,
    name TEXT DEFAULT '',
    service_id TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT DEFAULT 'confirmed',  -- confirmed | cancelled
    reminded INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processed (
    wamid TEXT PRIMARY KEY,
    at TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


class Store:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---------- helpers ----------
    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self._all(sql, args)
        return rows[0] if rows else None

    # ---------- de-duplication (Meta retries webhooks) ----------
    def mark_processed(self, wamid: str, now: datetime) -> bool:
        """Return True the first time a message id is seen, False for duplicates."""
        with self._lock:
            try:
                self.db.execute("INSERT INTO processed (wamid, at) VALUES (?, ?)", (wamid, iso(now)))
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    # ---------- contacts ----------
    def contact(self, wa_id: str, now: datetime | None = None) -> dict:
        row = self._one("SELECT * FROM contacts WHERE wa_id = ?", (wa_id,))
        if row is None:
            self._exec(
                "INSERT INTO contacts (wa_id, created_at) VALUES (?, ?)", (wa_id, iso(now or utcnow()))
            )
            row = self._one("SELECT * FROM contacts WHERE wa_id = ?", (wa_id,))
        row["state_data"] = json.loads(row.get("state_data") or "{}")
        return row

    def update_contact(self, wa_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "state_data" in fields and not isinstance(fields["state_data"], str):
            fields["state_data"] = json.dumps(fields["state_data"], ensure_ascii=False)
        for k, v in list(fields.items()):
            if isinstance(v, datetime):
                fields[k] = iso(v)
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE contacts SET {cols} WHERE wa_id = ?", (*fields.values(), wa_id))

    def set_state(self, wa_id: str, state: str, data: dict | None = None) -> None:
        self.update_contact(wa_id, state=state, state_data=data or {})

    def conversations(self) -> list[dict]:
        rows = self._all(
            """SELECT c.*, (SELECT body FROM messages m WHERE m.wa_id = c.wa_id ORDER BY m.id DESC LIMIT 1) AS last_body,
                      (SELECT author FROM messages m WHERE m.wa_id = c.wa_id ORDER BY m.id DESC LIMIT 1) AS last_author
               FROM contacts c ORDER BY c.handoff DESC, c.last_message_at DESC"""
        )
        for r in rows:
            r["state_data"] = json.loads(r.get("state_data") or "{}")
        return rows

    # ---------- messages ----------
    def add_message(
        self,
        wa_id: str,
        direction: str,
        author: str,
        kind: str,
        body: str,
        now: datetime,
        payload: dict | None = None,
        wamid: str | None = None,
        status: str = "",
        meta: dict | None = None,
    ) -> int:
        cur = self._exec(
            """INSERT INTO messages (wa_id, direction, author, kind, body, payload, wamid, status, meta, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                wa_id,
                direction,
                author,
                kind,
                body,
                json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                wamid,
                status,
                json.dumps(meta or {}, ensure_ascii=False),
                iso(now),
            ),
        )
        fields: dict[str, Any] = {"last_message_at": now}
        if direction == "in":
            fields["last_inbound_at"] = now
        self.update_contact(wa_id, **fields)
        if direction == "in":
            self._exec("UPDATE contacts SET unread = unread + 1 WHERE wa_id = ?", (wa_id,))
        return int(cur.lastrowid)

    def set_message_status(self, msg_id: int, status: str, wamid: str | None = None) -> None:
        if wamid:
            self._exec("UPDATE messages SET status = ?, wamid = ? WHERE id = ?", (status, wamid, msg_id))
        else:
            self._exec("UPDATE messages SET status = ? WHERE id = ?", (status, msg_id))

    def update_status_by_wamid(self, wamid: str, status: str) -> bool:
        order = ["", "queued", "sent", "delivered", "read"]
        row = self._one("SELECT id, status FROM messages WHERE wamid = ?", (wamid,))
        if not row:
            return False
        cur = row["status"] or ""
        # statuses can arrive out of order; never downgrade read -> delivered
        if status == "failed" or cur not in order or status not in order or order.index(status) > order.index(cur):
            self.set_message_status(row["id"], status)
        return True

    def messages(self, wa_id: str, limit: int = 200) -> list[dict]:
        rows = self._all(
            "SELECT * FROM (SELECT * FROM messages WHERE wa_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id", (wa_id, limit)
        )
        for r in rows:
            r["meta"] = json.loads(r.get("meta") or "{}")
            r["payload"] = json.loads(r["payload"]) if r.get("payload") else None
        return rows

    def mark_seen(self, wa_id: str) -> None:
        self.update_contact(wa_id, unread=0)

    # ---------- appointments ----------
    def add_appointment(self, wa_id: str, name: str, service_id: str, start: datetime, end: datetime, now: datetime) -> int:
        cur = self._exec(
            "INSERT INTO appointments (wa_id, name, service_id, start, end, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (wa_id, name, service_id, iso(start), iso(end), iso(now)),
        )
        return int(cur.lastrowid)

    def appointments(self, *, wa_id: str | None = None, status: str | None = "confirmed", since: datetime | None = None) -> list[dict]:
        sql, args = "SELECT * FROM appointments WHERE 1=1", []
        if wa_id:
            sql += " AND wa_id = ?"
            args.append(wa_id)
        if status:
            sql += " AND status = ?"
            args.append(status)
        rows = self._all(sql + " ORDER BY start", tuple(args))
        if since is not None:
            rows = [r for r in rows if parse(r["end"]) > since]
        return rows

    def appointment(self, appt_id: int) -> dict | None:
        return self._one("SELECT * FROM appointments WHERE id = ?", (appt_id,))

    def cancel_appointment(self, appt_id: int) -> None:
        self._exec("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appt_id,))

    def mark_reminded(self, appt_id: int) -> None:
        self._exec("UPDATE appointments SET reminded = 1 WHERE id = ?", (appt_id,))

    # ---------- stats ----------
    def stats(self, since: datetime) -> dict:
        s = iso(since)
        one = lambda sql, a=(): (self._one(sql, a) or {}).get("n", 0)  # noqa: E731
        inbound = one("SELECT COUNT(*) n FROM messages WHERE direction='in' AND created_at >= ?", (s,))
        bot = one("SELECT COUNT(*) n FROM messages WHERE author='bot' AND created_at >= ?", (s,))
        staff = one("SELECT COUNT(*) n FROM messages WHERE author='staff' AND created_at >= ?", (s,))
        kb = one("SELECT COUNT(*) n FROM messages WHERE author='bot' AND meta LIKE '%\"source\": \"kb:%' AND created_at >= ?", (s,))
        return {
            "conversations": one("SELECT COUNT(*) n FROM contacts"),
            "inbound": inbound,
            "bot_replies": bot,
            "staff_replies": staff,
            "kb_answers": kb,
            "waiting_for_staff": one("SELECT COUNT(*) n FROM contacts WHERE handoff = 1"),
            "appointments": one("SELECT COUNT(*) n FROM appointments WHERE status='confirmed' AND created_at >= ?", (s,)),
        }
