-- AILEN Database Schema - Migration 0004
-- Persistent scheduled reminders, stored in UTC.

CREATE TABLE IF NOT EXISTS reminders (
    reminder_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    due_at TEXT NOT NULL,
    recurrence TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'NOTIFIED', 'CANCELLED')),
    created_at TEXT NOT NULL,
    notified_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_reminders_due_pending
    ON reminders(status, due_at);
CREATE INDEX IF NOT EXISTS idx_reminders_created
    ON reminders(created_at);
