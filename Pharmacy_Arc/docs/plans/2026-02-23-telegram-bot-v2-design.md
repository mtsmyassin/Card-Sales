# Telegram Bot v2 — Design Document

**Date:** 2026-02-23
**Status:** Approved

## Overview

Improve the Carimas Telegram bot with 7 features: pharmacy knowledge base for the AI assistant, inline keyboards, AI conversation memory, `/last` command, smarter OCR error messages, payout entry flow, and admin broadcast.

## Features

### 1. Pharmacy Knowledge Base

Add a `PHARMACY_CONTEXT` Python constant in `ai_assistant.py` with structured pharmacy operational info (store hours, addresses, phone numbers, policies, procedures, contacts). Injected into the AI system prompt so the assistant can answer questions like "What time does Carimas #2 close?" without needing sales data.

Template provided with placeholders; user fills in real values.

### 2. Inline Keyboards

Replace text-based confirmations with Telegram inline keyboard buttons:

- **Store selection:** 5 inline buttons (one per store) instead of "type 1-5"
- **Date confirmation:** `[OK]` and `[Corregir]` buttons
- **Register confirmation:** `[OK]` and `[Corregir]` buttons
- **Final save:** `[SÍ Guardar]` and `[NO Cancelar]` buttons

Handle `callback_query` updates in `handle_update()`. Each button has a `callback_data` string (e.g., `store:1`, `confirm:yes`). Text-based input still works as fallback — backward compatible.

### 3. AI Conversation Memory

Store last 5 message pairs (user + assistant) per `telegram_id` in memory. Sent as multi-turn messages to Claude on each AI question. History cleared on AI mode exit. Not persisted to DB (ephemeral per AI session).

### 4. `/last` Command

New slash command that queries the most recent audit entry for the user's store. Returns formatted message: date, register, gross, variance, submitted by.

### 5. Smarter OCR Error Messages

Context-specific error hints based on failure type:
- Null fields: name the missing fields, suggest those sections be visible
- Parse error: suggest holding camera directly above receipt
- Total failure: suggest better lighting and full receipt in frame

### 6. Payout Entry

Two new conversation states after register confirmation, before final save:

1. `AWAITING_PAYOUTS` — "How much in payouts?" with `[Sin payouts ($0)]` inline button
2. `AWAITING_ACTUAL_CASH` — "How much cash in register?" with `[Omitir]` inline button

Auto-calculate: `variance = actual_cash - (ocr_cash - payouts)`. Pass to existing `save_audit_entry()` params.

### 7. Admin Broadcast

`/broadcast <message>` command restricted to admin/super_admin roles. Queries all telegram_ids from bot_users, sends message to each. Confirmation inline buttons before sending. Rate limited: 1 per hour.

## Architecture Notes

- All changes in `telegram_bot.py` and `ai_assistant.py` — no new files needed
- Inline keyboards use Telegram's `callback_query` — requires adding `callback_query` to webhook `allowed_updates`
- `answerCallbackQuery` must be called after handling each callback to dismiss loading indicator
- New states: `AWAITING_PAYOUTS`, `AWAITING_ACTUAL_CASH`, `BROADCAST_CONFIRM`
- AI memory: `_ai_history: dict[int, list[dict]]` in-memory dict, same pattern as `bot_state`
