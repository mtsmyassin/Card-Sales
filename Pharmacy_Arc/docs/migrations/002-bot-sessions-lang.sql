-- Migration 002: Add language preference to bot_sessions
-- Run in Supabase SQL editor
ALTER TABLE bot_sessions ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'es';
