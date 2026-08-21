-- AILEN Database Schema - Migration 0002
-- Persistent admin credential for the local web panel.
-- Stores ONLY a KDF-derived hash + random salt. Never plaintext passwords.
-- CHECK (id = 1) enforces a single administrative credential row.

CREATE TABLE IF NOT EXISTS admin_credentials (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL,
    password_hash BLOB NOT NULL,
    salt BLOB NOT NULL,
    kdf TEXT NOT NULL,
    iterations INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
