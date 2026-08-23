-- AILEN Database Schema - Migration 0003
-- Table for explicit notes tool persistence

CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at);
