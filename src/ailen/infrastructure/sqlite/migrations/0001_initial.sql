-- AILEN Database Schema - Migration 0001
-- Initial baseline schema for modular memory and audit

-- 1. Conversation Sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    mode TEXT NOT NULL DEFAULT 'WORKSHOP',
    participant_hint TEXT,
    source_node_id TEXT NOT NULL DEFAULT 'local'
);

CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);

-- 2. Conversational Messages
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL, -- 'user', 'assistant', 'system', 'tool'
    content TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'WORKSHOP',
    created_at TEXT NOT NULL,
    token_count INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

-- 3. Long-term Memories
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'general',
    content TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 1.0,
    scope TEXT NOT NULL DEFAULT 'PRIVATE', -- 'PUBLIC', 'RESTRICTED', 'PRIVATE'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);

-- 4. Business Knowledge / Facts
CREATE TABLE IF NOT EXISTS business_facts (
    fact_id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'general',
    value TEXT NOT NULL,
    is_public INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_business_facts_key ON business_facts(key);

-- 5. User & System Preferences
CREATE TABLE IF NOT EXISTS preferences (
    pref_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    updated_at TEXT NOT NULL,
    UNIQUE(category, key)
);

-- 6. Personality Simulation State
CREATE TABLE IF NOT EXISTS personality_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_id TEXT NOT NULL,
    trait_name TEXT NOT NULL,
    trait_value REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(identity_id, trait_name)
);

-- 7. Personality Delta Events Audit
CREATE TABLE IF NOT EXISTS personality_events (
    event_id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    delta REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 8. Tool Execution Audit
CREATE TABLE IF NOT EXISTS tool_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    arguments_redacted TEXT NOT NULL,
    result_summary TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 1,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_events_created ON tool_events(created_at);

-- 9. AI Resource Usage Tracking
CREATE TABLE IF NOT EXISTS ai_usage (
    usage_id TEXT PRIMARY KEY,
    session_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL DEFAULT 0.0,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at);

-- 10. Operational System Events
CREATE TABLE IF NOT EXISTS system_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO',
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_events_created ON system_events(created_at);
