# Contributing

Thanks for helping. Issues and pull requests in Arabic or English are welcome.

```bash
git clone https://github.com/mohammadhadijavidi/whatsapp-agent-ar
cd whatsapp-agent-ar
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
whatsapp-agent-ar chat          # talk to the agent in your terminal (dry-run)
```

Guidelines

- Keep the core dependency-free (standard library only). Optional extras are fine.
- Only the **official WhatsApp Cloud API**. No WhatsApp Web automation or unofficial libraries.
- Any new outgoing message type must respect Meta's documented limits and the 24-hour window;
  add a test in `tests/test_agent.py::test_all_outgoing_payloads_valid_for_cloud_api`.
- New dialect synonyms go in `whatsapp_agent_ar/arabic.py` with a test in `tests/test_knowledge.py`.
- Sample data must be clearly labeled as sample (fictional business, fake numbers).
- To refresh the README images: `whatsapp-agent-ar serve --demo --port 8000` then
  `python scripts/screenshot.py "http://127.0.0.1:8000/?c=971501110001" assets/hero.png` and
  `python scripts/screenshot.py docs/flow.html assets/flow.png` (needs `pip install playwright`).
