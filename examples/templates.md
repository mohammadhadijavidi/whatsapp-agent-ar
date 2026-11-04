# Message template for reminders (create it in WhatsApp Manager)

Outside the 24-hour customer service window WhatsApp only delivers **approved templates**.
`whatsapp-agent-ar reminders` uses one template with four body variables. Create it in
WhatsApp Manager > Message templates (category **Utility**), then set
`WA_REMINDER_TEMPLATE` and `WA_REMINDER_TEMPLATE_LANG`.

**Name:** `appointment_reminder` | **Language:** Arabic (`ar`) | **Category:** Utility

**Body (Arabic):**

```
مرحباً {{1}}، نذكّرك بموعد {{2}} يوم {{3}} الساعة {{4}}.
للتأجيل أو الإلغاء ردّ على هذه الرسالة.
```

**Body (English, `en`):**

```
Hi {{1}}, this is a reminder of your {{2}} appointment on {{3}} at {{4}}.
Reply to this message to reschedule or cancel.
```

Variables sent by the agent: `{{1}}` customer profile name, `{{2}}` service, `{{3}}` day, `{{4}}` time.
Optional: add Quick Reply buttons; their payloads arrive as `button` messages and are routed like any reply.
Template text and approval are Meta's decision; the wording above is a suggestion only.
