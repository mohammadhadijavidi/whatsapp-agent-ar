import base64
import io
import json

import pytest

from whatsapp_agent_ar import whatsapp as wa
from whatsapp_agent_ar.config import Settings
from whatsapp_agent_ar.server import App, simulated_webhook

SECRET = "test-app-secret"


def call(app, method, path, body=b"", headers=None, query=""):
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    out = {}

    def start_response(status, hdrs):
        out["status"], out["headers"] = status, dict(hdrs)

    data = b"".join(app(env, start_response))
    return int(out["status"].split()[0]), out["headers"], data


def jbody(obj):
    return json.dumps(obj, ensure_ascii=False).encode()


@pytest.fixture
def settings():
    return Settings(verify_token="vtok", app_secret=SECRET, dry_run=True)


@pytest.fixture
def app(agent, settings):
    return App(agent, settings)


def post_webhook(app, payload, secret=SECRET):
    raw = jbody(payload)
    return call(app, "POST", "/webhook", raw, {"X-Hub-Signature-256": wa.sign(raw, secret)})


def test_webhook_verification(app):
    code, _, body = call(app, "GET", "/webhook", query="hub.mode=subscribe&hub.verify_token=vtok&hub.challenge=987654")
    assert code == 200 and body == b"987654"
    code, _, _ = call(app, "GET", "/webhook", query="hub.mode=subscribe&hub.verify_token=nope&hub.challenge=1")
    assert code == 403


def test_webhook_rejects_bad_or_missing_signature(app, agent):
    raw = jbody(simulated_webhook("971500000001", "x", "مرحبا"))
    assert call(app, "POST", "/webhook", raw)[0] == 401
    assert call(app, "POST", "/webhook", raw, {"X-Hub-Signature-256": wa.sign(raw, "other")})[0] == 401
    assert agent.client.outbox == []


def test_webhook_rejects_when_secret_not_configured(agent):
    app = App(agent, Settings(verify_token="v", app_secret="", dry_run=True))
    raw = jbody(simulated_webhook("971500000001", "x", "مرحبا"))
    assert call(app, "POST", "/webhook", raw, {"X-Hub-Signature-256": wa.sign(raw, "")})[0] == 401


def test_webhook_signed_message_is_answered(app, agent):
    code, _, body = post_webhook(app, simulated_webhook("971500000001", "سارة", "بكم الكشف؟"))
    assert code == 200 and json.loads(body)["handled"] == 1
    assert "150 درهم" in wa.summarize(agent.client.outbox[-1])


def test_webhook_bad_json_after_valid_signature(app):
    raw = b"not json"
    assert call(app, "POST", "/webhook", raw, {"X-Hub-Signature-256": wa.sign(raw, SECRET)})[0] == 400


def test_dashboard_and_api(app):
    post_webhook(app, simulated_webhook("971500000001", "سارة", "مرحبا"))
    code, headers, html = call(app, "GET", "/")
    assert code == 200 and "text/html" in headers["Content-Type"] and 'dir="rtl"' in html.decode()
    code, _, data = call(app, "GET", "/api/conversations")
    convs = json.loads(data)
    assert convs[0]["wa_id"] == "971500000001" and convs[0]["window_open"]
    code, _, data = call(app, "GET", "/api/conversations/971500000001")
    detail = json.loads(data)
    assert [m["direction"] for m in detail["messages"]] == ["in", "out"]
    stats = json.loads(call(app, "GET", "/api/stats")[2])
    assert stats["conversations"] == 1 and stats["dry_run"] is True and stats["provider"] == "mock"
    assert call(app, "GET", "/static/fonts/Vazirmatn-Regular.woff2")[0] == 200
    assert call(app, "GET", "/static/fonts/../../server.py")[0] == 404


def test_staff_reply_and_handoff_api(app, agent, clock):
    post_webhook(app, simulated_webhook("971500000001", "سارة", "مرحبا", ts=int(clock().timestamp())))
    code, _, data = call(app, "POST", "/api/conversations/971500000001/reply", jbody({"text": "أهلاً سارة"}))
    assert code == 200 and json.loads(data)["status"] == "dry_run"
    assert agent.store.contact("971500000001")["handoff"] == 1
    assert call(app, "POST", "/api/conversations/971500000001/handoff", jbody({"action": "release"}))[0] == 200
    assert agent.store.contact("971500000001")["handoff"] == 0
    clock.advance(hours=25)
    code, _, data = call(app, "POST", "/api/conversations/971500000001/reply", jbody({"text": "late"}))
    assert code == 409 and json.loads(data)["error"] == "outside_24h_window"
    code, _, data = call(app, "POST", "/api/conversations/971500000001/template", jbody({"params": ["سارة"]}))
    assert code == 200 and agent.client.outbox[-1]["type"] == "template"


def test_dashboard_basic_auth(agent):
    app = App(agent, Settings(verify_token="v", app_secret=SECRET, dashboard_user="admin", dashboard_password="pw"))
    assert call(app, "GET", "/")[0] == 401
    assert call(app, "GET", "/api/stats")[0] == 401
    good = "Basic " + base64.b64encode(b"admin:pw").decode()
    bad = "Basic " + base64.b64encode(b"admin:no").decode()
    assert call(app, "GET", "/", headers={"Authorization": bad})[0] == 401
    assert call(app, "GET", "/", headers={"Authorization": good})[0] == 200
    # The webhook must stay reachable for Meta without dashboard credentials
    assert call(app, "GET", "/webhook", query="hub.mode=subscribe&hub.verify_token=v&hub.challenge=5")[0] == 200


def test_simulate_only_in_dry_run(app, agent):
    code, _, data = call(app, "POST", "/api/simulate", jbody({"wa_id": "971500000009", "text": "مرحبا"}))
    assert code == 200 and json.loads(data)["handled"] == 1
    live = App(agent, Settings(verify_token="v", app_secret=SECRET, dry_run=False, access_token="t", phone_number_id="p"))
    assert call(live, "POST", "/api/simulate", jbody({"text": "x"}))[0] == 403


def test_health_and_404(app):
    assert json.loads(call(app, "GET", "/health")[2])["ok"] is True
    assert call(app, "GET", "/nope")[0] == 404
    assert call(app, "GET", "/api/conversations/abc")[0] == 400
