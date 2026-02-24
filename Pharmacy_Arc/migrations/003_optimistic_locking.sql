-- Migration 002: Optimistic locking via version column
-- Run in Supabase SQL Editor (Dashboard → SQL)

ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
