# Design: Telegram OCR Bot + Z Report Viewer
**Date:** 2026-02-20
**Status:** Approved

---

## Overview

Staff at Farmacia Carimas photograph the register's Z Report (batch close printout) and send it to a Telegram bot. The bot uses Claude Vision API to extract sales figures, shows a confirmation preview in Spanish, and on approval saves the entry to Supabase. The original photo is stored in Supabase Storage and linked to the audit entry so managers can view it in the web platform's history page.

---

## Architecture

Everything runs inside the existing Flask app on Railway. No second service.

```
Telegram ──photo──► POST /api/telegram/webhook (new Flask route)
                         │
                    In-memory bot state dict (keyed by telegram_id)
                         │
              ┌──────────┴──────────┐
              │                     │
         Unregistered            Registered
              │                     │
       Ask username            Download photo from Telegram
       Ask password            Send to Claude Vision API
       bcrypt verify               (claude-haiku-4-5)
       against users table              │
       Store telegram_id          Returns structured JSON
       + store in bot_users       (all 10 payment fields +
                                   register #, date, over/short)
                                        │
                                 Any null fields?
                                   YES → ask retry
                                   NO  → send preview
                                        │
                              "¿Guardar? Responde SI o NO"
                                        │
                            SI ─────────┴───────── NO
                             │                      │
                      Upload photo to          "Cancelado."
                      Supabase Storage
                      bucket: z-reports
                             │
                      Save to audits table
                      payload includes:
                        z_report_image_url
                        source: "telegram_bot"
                             │
                      "✅ Guardado. Reg #X — $XXX.XX neto."
```

---

## Section 1: New Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather on Telegram |
| `ANTHROPIC_API_KEY` | For Claude Vision API (claude-haiku-4-5) |

No new PIN variable — auth reuses the existing `users` table.

---

## Section 2: Bot Registration Flow

Registration uses the staff member's existing web platform credentials (username + bcrypt password from the `users` table). Store is read from their `users.store` field — no manual selection needed.

```
User:  [any message or photo]
Bot:   Hola! Para registrarte, introduce tu usuario:
User:  maria
Bot:   Introduce tu contraseña:
User:  ••••••
       [bcrypt.verify against users table]
Bot:   ✅ Registrada. Tienda: Carimas #2. Ya puedes enviar fotos del Reporte Z.
```

Wrong credentials: "Usuario o contraseña incorrectos. Intenta de nuevo."
After 3 failed attempts: 10-minute lockout (mirrors existing web app lockout).

Registered users are stored in a new `bot_users` Supabase table.
On re-registration (already registered): "Ya estás registrado en Carimas #2."

---

## Section 3: Z Report Submission Flow

```
User:  [sends photo]
Bot:   Procesando... ⏳
       [Claude Vision API extracts fields from (close) column]

— Happy path (all fields readable) —
Bot:   📋 Reporte extraído:
       Registro: #3  |  Fecha: 13/07/2026
       ─────────────────────────────
       Efectivo:        $356.85
       ATH:             $434.89
       ATH Móvil:         $0.00
       VISA:             $97.50
       Master Card:     $102.95
       American Exp:      $0.00
       Discover:          $0.00
       WIC/EBT:           $0.00
       MCS OTC:           $0.00
       Triple-S OTC:      $0.00
       Over/Short:      ($19.31)
       ─────────────────────────────
       ¿Guardar este reporte? Responde SI o NO

User:  SI
Bot:   ✅ Guardado. Reg #3 — $991.55 neto.

— Partial read (some fields null) —
Bot:   No pude leer algunos campos: Master Card, WIC.
       Toma la foto más cerca y con mejor iluminación e intenta de nuevo.
       (Intento 1 de 2)

— Two consecutive failures —
Bot:   No se pudo procesar la foto después de 2 intentos.
       Por favor ingresa este reporte manualmente en el sistema.
```

**Field mapping — Z Report label → app field:**
| Printout label | App field |
|---|---|
| CASH (close column) | cash |
| ATH (close column) | ath |
| ATH MOVIL (close column) | athm |
| VISA (close column) | visa |
| MASTER CARD (close column) | mc |
| AMERICAN EXPRESS (close column) | amex |
| DISCOVER (close column) | disc |
| EBT FOOD (close column) | wic |
| MCS OTC (close column) | mcs |
| TRIPLE-S OTC (close column) | sss |
| Over / Short | variance |
| Register # (header) | reg |
| Date (header) | date |

Claude is explicitly instructed to extract from the **(close)** column, not (shift) or (even).

---

## Section 4: Database & Storage Changes

### New table: `bot_users`
```sql
create table bot_users (
  telegram_id   bigint primary key,
  username      text not null,       -- links to users.username
  store         text not null,       -- copied from users.store at registration
  registered_at timestamp default now(),
  active        boolean default true
);
```

### Supabase Storage bucket: `z-reports` (private)
- File path: `{store}/{YYYY-MM-DD}/reg{N}_{unix_timestamp}.jpg`
- A short-lived signed URL (1 hour) is generated when the web platform requests the image for display.

### Existing `audits` table — no schema change
Two new keys added inside the existing `payload` JSONB on bot-submitted entries:
```json
{
  "source": "telegram_bot",
  "submitted_by_telegram": "maria",
  "z_report_image_url": "https://...supabase.../z-reports/..."
}
```
Manual web entries continue to have no `source` key (or `source: "web"`).

---

## Section 5: Web Platform — History Page Changes

For every row in the history table where `payload.z_report_image_url` exists, a camera icon button (📷) is shown alongside the existing Print and Edit buttons.

```
| Date       | Store      | Reg  | Net      | Actions          |
|------------|------------|------|----------|------------------|
| 13/07/2026 | Carimas #2 | Reg3 | $991.55  | [🖨] [✏] [📷]  |
| 13/07/2026 | Carimas #2 | Reg1 | $1,204.00| [🖨] [✏]       |  ← manual entry
```

Clicking 📷 opens a full-screen modal/lightbox overlay with the Z report image. Close by clicking X or outside the modal. The image is fetched via a new Flask endpoint that generates a signed Supabase Storage URL on demand (avoids storing long-lived public URLs).

New Flask endpoint: `GET /api/audit/<id>/zreport_image` — auth required, returns `{ "url": "<signed_url>" }`.

---

## Section 6: New Python Dependencies

```
python-telegram-bot==21.*   # Telegram bot webhook handling
anthropic>=0.25             # Claude Vision API
```

No new system packages. Both install cleanly on Railway.

---

## Section 7: Webhook Setup

On app startup, Flask registers the Telegram webhook:
```
POST https://api.telegram.org/bot{TOKEN}/setWebhook
  url = https://carimas.up.railway.app/api/telegram/webhook
```

This is idempotent — safe to call on every deploy.

---

## Out of Scope

- Admin UI for managing bot users (handled via existing user management screen)
- Push notifications to managers when a new Z report is submitted
- Editing OCR-extracted values before saving (use existing web Edit button after the fact)
