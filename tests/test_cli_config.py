import json

import pytest

from whatsapp_agent_ar import whatsapp as wa
from whatsapp_agent_ar.business import Business
from whatsapp_agent_ar.cli import main
from whatsapp_agent_ar.config import Settings, load_dotenv
from whatsapp_agent_ar.demo import seed
from whatsapp_agent_ar.providers import Anthropic, Mock, OpenAICompatible, ProviderError, get_llm
from whatsapp_agent_ar.store import Store


def test_chat_cli_runs_booking(capsys):
    assert main(["chat", "-m", "مرحبا", "-m", "ابي احجز تنظيف", "-m", "2", "-m", "1", "-m", "1"]) == 0
    out = capsys.readouterr().out
    assert "حجز موعد" in out and "تأكيد الحجز" in out and "تم الحجز" in out


def test_chat_cli_json(capsys):
    main(["chat", "--json", "-m", "hi"])
    out = capsys.readouterr().out
    assert '"messaging_product": "whatsapp"' in out


def test_sign_cli(tmp_path, capsys):
    f = tmp_path / "p.json"
    f.write_bytes(b'{"a":1}')
    assert main(["sign", str(f), "--secret", "s"]) == 0
    assert capsys.readouterr().out.strip() == wa.sign(b'{"a":1}', "s")


def test_check_cli(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for k in ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WA_DRY_RUN"]:
        monkeypatch.delenv(k, raising=False)
    assert main(["check"]) == 0
    assert "dry-run" in capsys.readouterr().out


def test_settings_default_to_dry_run_without_token(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WA_DRY_RUN", raising=False)
    assert Settings.from_env().dry_run is True
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "EAAG...")
    assert Settings.from_env().dry_run is False
    monkeypatch.setenv("WA_DRY_RUN", "1")
    assert Settings.from_env().dry_run is True


def test_load_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("WA_TEST_X", raising=False)
    (tmp_path / ".env").write_text('# c\nWA_TEST_X="hello"\n')
    load_dotenv(tmp_path / ".env")
    import os

    assert os.environ["WA_TEST_X"] == "hello"


def test_get_llm(monkeypatch):
    for k in ["WA_LLM_PROVIDER", "WA_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "WA_LLM_BASE_URL"]:
        monkeypatch.delenv(k, raising=False)
    assert isinstance(get_llm(), Mock)
    assert isinstance(get_llm("ollama"), OpenAICompatible)
    with pytest.raises(ProviderError):
        get_llm("openai")
    with pytest.raises(ProviderError):
        get_llm("anthropic")
    monkeypatch.setenv("WA_LLM_API_KEY", "k")
    g = get_llm("groq")
    assert g.base_url == "https://api.groq.com/openai/v1"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert isinstance(get_llm("anthropic"), Anthropic)
    with pytest.raises(ProviderError):
        get_llm("nope")


def test_business_validation():
    with pytest.raises(ValueError):
        Business.from_dict({"name": "x", "hours": {"monday": ["09:00-10:00"]}})
    with pytest.raises(ValueError):
        Business.from_dict({"name": "x", "hours": {"mon": ["10:00-09:00"]}})
    b = Business.load("examples/clinic/business.json")
    assert b.match_service("ابي احجز تنظيف").id == "cleaning"
    assert b.match_service("موعد للتبييض").id == "whitening"
    assert b.match_service("hello") is None


def test_demo_seed_produces_realistic_state():
    store = Store(":memory:")
    seed(store)
    convs = {c["wa_id"]: c for c in store.conversations()}
    assert len(convs) == 4
    assert convs["971551110002"]["handoff"] == 1
    assert store.messages("971551110002")[-1]["author"] == "staff"
    assert len(store.appointments(wa_id="971501110001")) == 1
    sources = [m["meta"].get("source") for m in store.messages("971521110004") if m["direction"] == "out"]
    assert all(s and s.startswith("kb:") for s in sources)
    json.dumps(store.stats(__import__("datetime").datetime(2000, 1, 1)))


def test_bundled_sample_matches_example_file():
    from pathlib import Path

    import whatsapp_agent_ar

    bundled = Path(whatsapp_agent_ar.__file__).parent / "data" / "clinic.json"
    assert bundled.read_text(encoding="utf-8") == Path("examples/clinic/business.json").read_text(encoding="utf-8")
