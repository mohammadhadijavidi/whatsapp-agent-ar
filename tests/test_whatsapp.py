import json
from datetime import timedelta

import pytest

from whatsapp_agent_ar import whatsapp as wa

from .conftest import NOW


def test_verify_subscription_ok_and_fail():
    ok = {"hub.mode": "subscribe", "hub.verify_token": "s3cret", "hub.challenge": "1158201444"}
    assert wa.verify_subscription(ok, "s3cret") == "1158201444"
    assert wa.verify_subscription({**ok, "hub.verify_token": "wrong"}, "s3cret") is None
    assert wa.verify_subscription({**ok, "hub.mode": "unsubscribe"}, "s3cret") is None
    assert wa.verify_subscription(ok, "") is None  # unconfigured token never verifies


def test_signature_matches_meta_algorithm():
    body = b'{"object":"whatsapp_business_account"}'
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    assert wa.sign(body, "appsecret") == expected
    assert wa.verify_signature(body, expected, "appsecret")


@pytest.mark.parametrize(
    "header,secret",
    [(None, "appsecret"), ("", "appsecret"), ("sha1=abc", "appsecret"), ("sha256=deadbeef", "appsecret"), ("x", "")],
)
def test_signature_fails_closed(header, secret):
    assert not wa.verify_signature(b"{}", header, secret)


def test_signature_detects_tampering():
    body = '{"text":"مرحبا"}'.encode()
    sig = wa.sign(body, "k")
    assert not wa.verify_signature(body.replace("مرحبا".encode(), "اهلا".encode()), sig, "k")


def _payload(messages=None, statuses=None, field="messages"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": field, "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "971400000000", "phone_number_id": "PNID"},
            "contacts": [{"profile": {"name": "سارة"}, "wa_id": "971501234567"}],
            **({"messages": messages} if messages else {}),
            **({"statuses": statuses} if statuses else {}),
        }}]}],
    }


def test_parse_text_interactive_button_and_media():
    msgs, _ = wa.parse_webhook(_payload(messages=[
        {"from": "971501234567", "id": "wamid.1", "timestamp": "1793772000", "type": "text", "text": {"body": "مرحبا"}},
        {"from": "971501234567", "id": "wamid.2", "timestamp": "1793772001", "type": "interactive",
         "interactive": {"type": "list_reply", "list_reply": {"id": "svc:cleaning", "title": "تنظيف"}}},
        {"from": "971501234567", "id": "wamid.3", "timestamp": "1793772002", "type": "button",
         "button": {"payload": "attend:4", "text": "سأحضر"}},
        {"from": "971501234567", "id": "wamid.4", "timestamp": "1793772003", "type": "image",
         "image": {"id": "MEDIA", "mime_type": "image/jpeg"}},
    ]))
    assert [m.type for m in msgs] == ["text", "interactive", "button", "image"]
    assert msgs[0].text == "مرحبا" and msgs[0].name == "سارة" and msgs[0].phone_number_id == "PNID"
    assert msgs[1].reply_id == "svc:cleaning"
    assert msgs[2].reply_id == "attend:4"
    assert msgs[3].display == "[image]"


def test_parse_statuses_and_ignore_other_objects():
    _, st = wa.parse_webhook(_payload(statuses=[
        {"id": "wamid.X", "status": "read", "timestamp": "1793772000", "recipient_id": "971501234567"}]))
    assert st[0].status == "read" and st[0].wamid == "wamid.X"
    assert wa.parse_webhook({"object": "page", "entry": []}) == ([], [])
    assert wa.parse_webhook(_payload(field="account_update")) == ([], [])


def test_service_window():
    assert wa.in_service_window(NOW - timedelta(hours=23, minutes=59), NOW)
    assert not wa.in_service_window(NOW - timedelta(hours=24), NOW)
    assert not wa.in_service_window(None, NOW)


def test_builders_respect_documented_limits():
    b = wa.buttons_message("1", "x" * 2000, [("a", "عنوان طويل جداً أكثر من عشرين حرفاً"), ("b", "ok")])
    assert len(b["interactive"]["body"]["text"]) <= wa.INTERACTIVE_BODY_MAX
    assert all(len(x["reply"]["title"]) <= wa.BUTTON_TITLE_MAX for x in b["interactive"]["action"]["buttons"])
    with pytest.raises(ValueError):
        wa.buttons_message("1", "x", [("a", "1"), ("b", "2"), ("c", "3"), ("d", "4")])
    rows = [(f"r{i}", "عنوان صف طويل جداً يتجاوز الحد", "و" * 100) for i in range(15)]
    lst = wa.list_message("1", "body", "زر طويل جداً أكثر من عشرين", rows)
    sec = lst["interactive"]["action"]["sections"][0]
    assert len(sec["rows"]) == wa.LIST_MAX_ROWS
    assert all(len(r["title"]) <= 24 and len(r["description"]) <= 72 for r in sec["rows"])
    assert len(lst["interactive"]["action"]["button"]) <= 20


def test_template_payload_shape():
    p = wa.template_message("971501234567", "appointment_reminder", "ar", ["سارة", "تنظيف"])
    assert p["type"] == "template"
    assert p["template"]["language"] == {"code": "ar"}
    assert p["template"]["components"][0]["parameters"][1] == {"type": "text", "text": "تنظيف"}
    assert p["messaging_product"] == "whatsapp"


def test_client_dry_run_and_endpoint():
    c = wa.WhatsAppClient("tok", "123", "v23.0", dry_run=True)
    assert c.endpoint == "https://graph.facebook.com/v23.0/123/messages"
    r = c.send(wa.text_message("9715", "hi"))
    assert r.status == "dry_run" and r.wamid.startswith("dryrun.")
    assert c.outbox[-1]["text"]["body"] == "hi"


def test_client_live_posts_to_graph_api(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"messaging_product": "whatsapp", "messages": [{"id": "wamid.LIVE"}]}).encode()

    def fake_urlopen(req, timeout):
        seen["url"], seen["auth"], seen["body"] = req.full_url, req.headers["Authorization"], json.loads(req.data)
        return Resp()

    monkeypatch.setattr(wa.urllib.request, "urlopen", fake_urlopen)
    c = wa.WhatsAppClient("TOKEN", "PNID", "v23.0", dry_run=False)
    r = c.send(wa.text_message("971501234567", "مرحبا"))
    assert r.wamid == "wamid.LIVE" and r.status == "sent"
    assert seen["url"].endswith("/v23.0/PNID/messages")
    assert seen["auth"] == "Bearer TOKEN"
    assert seen["body"]["text"]["body"] == "مرحبا"


def test_client_maps_131047_error(monkeypatch):
    import io
    import urllib.error

    def fake_urlopen(req, timeout):
        body = json.dumps({"error": {"message": "Re-engagement message", "code": 131047}}).encode()
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(body))

    monkeypatch.setattr(wa.urllib.request, "urlopen", fake_urlopen)
    c = wa.WhatsAppClient("T", "P", dry_run=False)
    with pytest.raises(wa.WhatsAppError) as e:
        c.send(wa.text_message("1", "x"))
    assert e.value.code == 131047 and "template" in str(e.value)
