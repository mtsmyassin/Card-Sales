# Z Report Review & Approval — Design Document
Date: 2026-02-21

## Approach: Hybrid
- `audits` table = Z Report record (unchanged structurally, +`review_status` column)
- `z_report_reviews` table = manager approval history (one row per approval action)
- `z_report_audit_log` table = append-only change log

## Key Decisions
- `audits.id` is INTEGER — all FKs use INTEGER
- No numeric user IDs — username TEXT is the identity key
- All payment fields live in `payload.breakdown` jsonb — server recalculates at approval
- `opening_float` = `payload.breakdown.float` (default 100.00)
- `IN_REVIEW` lock: `review_locked_by` + `review_locked_at` on `audits` row
- Version chain: every approval increments `version`; `is_current=true` on latest only
- Amendment: sets current row `action='AMENDED'`, reopens audit to `PENDING_REVIEW`

## States
NEEDS_ASSIGNMENT → PENDING_REVIEW → IN_REVIEW → FINAL_APPROVED
                                              ↘ REJECTED
FINAL_APPROVED → AMENDED → PENDING_REVIEW (admin only)

## Formulas (from pharmacy-sales-math skill)
gross    = cash + ath + athm + visa + mc + amex + disc + wic + mcs + sss
net      = gross - payouts_total
variance = (cash_actual - opening_float) - (cash - payouts_total)

## Tables Added
1. ALTER audits: +review_status, +review_locked_by, +review_locked_at
2. CREATE z_report_reviews (see migration SQL)
3. CREATE z_report_audit_log (see migration SQL)

## Migration SQL
See full document in conversation / apply via Supabase SQL Editor.

## API Endpoints
POST /api/z-reports/<id>/lock
POST /api/z-reports/<id>/approve
POST /api/z-reports/<id>/reject
POST /api/z-reports/<id>/amend  (admin only)
POST /api/z-reports/<id>/assign (admin only)
GET  /api/z-reports
GET  /api/z-reports/<id>
GET  /api/z-reports/<id>/history
GET  /api/z-reports/<id>/audit-log
GET  /api/z-reports/export
