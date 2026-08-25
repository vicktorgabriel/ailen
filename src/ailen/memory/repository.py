"""Domain memory and data access repository for AILEN."""

import logging
import uuid

from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.domain.models import (
    AiUsageRecord,
    BusinessFact,
    ConversationSession,
    MemoryItem,
    Message,
    NoteItem,
    ReminderItem,
    SystemEventRecord,
    ToolEvent,
    utc_now_iso,
)
from ailen.infrastructure.sqlite.connection import SQLiteManager

logger = logging.getLogger("ailen.memory.repository")


class MemoryRepository:
    """Repository wrapping SQLite access and returning domain models."""

    def __init__(self, db_manager: SQLiteManager):
        self.db_manager = db_manager

    # -------------------------------------------------------------------------
    # Sessions & Messages
    # -------------------------------------------------------------------------

    def create_session(
        self,
        mode: SocialMode = SocialMode.WORKSHOP,
        participant_hint: str | None = None,
        source_node_id: str = "local",
    ) -> ConversationSession:
        """Create and store a new conversation session."""
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessions (session_id, started_at, mode, participant_hint, source_node_id)
                VALUES (?, ?, ?, ?, ?);
                """,
                (session_id, now, mode.value, participant_hint, source_node_id),
            )
        return ConversationSession(
            session_id=session_id,
            started_at=now,
            mode=mode,
            participant_hint=participant_hint,
            source_node_id=source_node_id,
        )

    def end_session(self, session_id: str) -> None:
        """Mark a conversation session as ended."""
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET ended_at = ? WHERE session_id = ?;",
                (now, session_id),
            )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        mode: SocialMode = SocialMode.WORKSHOP,
        token_count: int | None = None,
    ) -> Message:
        """Store a message in a conversation session."""
        msg_id = f"msg-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content, mode, created_at, token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (msg_id, session_id, role, content, mode.value, now, token_count),
            )
        return Message(
            message_id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            mode=mode,
            created_at=now,
            token_count=token_count,
        )

    def get_session_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        """Fetch recent messages for a given session."""
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT message_id, session_id, role, content, mode, created_at, token_count
                FROM (
                    SELECT message_id, session_id, role, content, mode, created_at, token_count, rowid AS row_id
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                ) recent
                ORDER BY created_at ASC, row_id ASC;
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()
            return [
                Message(
                    message_id=r["message_id"],
                    session_id=r["session_id"],
                    role=r["role"],
                    content=r["content"],
                    mode=SocialMode(r["mode"]),
                    created_at=r["created_at"],
                    token_count=r["token_count"],
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Long-term Memories
    # -------------------------------------------------------------------------

    def add_memory(
        self,
        content: str,
        category: str = "general",
        importance: float = 1.0,
        scope: PrivacyLevel = PrivacyLevel.PRIVATE,
        expires_at: str | None = None,
    ) -> MemoryItem:
        """Store a new long-term memory entry."""
        mem_id = f"mem-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (memory_id, category, content, importance, scope, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (mem_id, category, content, importance, scope.value, now, now, expires_at),
            )
        return MemoryItem(
            memory_id=mem_id,
            category=category,
            content=content,
            importance=importance,
            scope=scope,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

    def search_memories(
        self,
        query: str,
        scope: PrivacyLevel | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Search stored memories by keyword query with optional privacy scope filter."""
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            pattern = f"%{query}%"
            if scope:
                cursor.execute(
                    """
                    SELECT memory_id, category, content, importance, scope, created_at, updated_at, expires_at
                    FROM memories
                    WHERE content LIKE ? AND scope = ?
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?;
                    """,
                    (pattern, scope.value, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT memory_id, category, content, importance, scope, created_at, updated_at, expires_at
                    FROM memories
                    WHERE content LIKE ?
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?;
                    """,
                    (pattern, limit),
                )
            rows = cursor.fetchall()
            return [
                MemoryItem(
                    memory_id=r["memory_id"],
                    category=r["category"],
                    content=r["content"],
                    importance=r["importance"],
                    scope=PrivacyLevel(r["scope"]),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    expires_at=r["expires_at"],
                )
                for r in rows
            ]

    def get_recent_memories(self, limit: int = 10, scope: PrivacyLevel | None = None) -> list[MemoryItem]:
        """Fetch most recently stored memories."""
        return self.search_memories(query="", scope=scope, limit=limit)

    # -------------------------------------------------------------------------
    # Business Facts
    # -------------------------------------------------------------------------

    def set_business_fact(
        self,
        key: str,
        value: str,
        category: str = "general",
        is_public: bool = True,
    ) -> BusinessFact:
        """Insert or update a business fact."""
        fact_id = f"fact-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO business_facts (fact_id, key, category, value, is_public, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    is_public = excluded.is_public,
                    updated_at = excluded.updated_at;
                """,
                (fact_id, key, category, value, 1 if is_public else 0, now, now),
            )
        return BusinessFact(
            fact_id=fact_id,
            key=key,
            category=category,
            value=value,
            is_public=is_public,
            created_at=now,
            updated_at=now,
        )

    def get_business_facts(self, only_public: bool = False) -> list[BusinessFact]:
        """Fetch all business facts with optional public filter."""
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            if only_public:
                cursor.execute(
                    """
                    SELECT fact_id, key, category, value, is_public, created_at, updated_at
                    FROM business_facts
                    WHERE is_public = 1
                    ORDER BY category, key;
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT fact_id, key, category, value, is_public, created_at, updated_at
                    FROM business_facts
                    ORDER BY category, key;
                    """
                )
            rows = cursor.fetchall()
            return [
                BusinessFact(
                    fact_id=r["fact_id"],
                    key=r["key"],
                    category=r["category"],
                    value=r["value"],
                    is_public=bool(r["is_public"]),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Audit & Telemetry Logging
    # -------------------------------------------------------------------------

    def log_system_event(
        self,
        event_type: str,
        severity: str,
        component: str,
        message: str,
        payload_json: str | None = None,
    ) -> SystemEventRecord:
        """Log an operational system event for auditing."""
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO system_events (event_id, event_type, severity, component, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (event_id, event_type, severity, component, message, payload_json, now),
            )
        return SystemEventRecord(
            event_id=event_id,
            event_type=event_type,
            severity=severity,
            component=component,
            message=message,
            payload_json=payload_json,
            created_at=now,
        )

    def log_tool_event(
        self,
        tool_name: str,
        arguments_redacted: str,
        result_summary: str,
        success: bool,
        latency_ms: float,
        session_id: str | None = None,
    ) -> ToolEvent:
        """Log a tool execution event."""
        event_id = f"tool-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tool_events (event_id, session_id, tool_name, arguments_redacted, result_summary, success, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (event_id, session_id, tool_name, arguments_redacted, result_summary, 1 if success else 0, latency_ms, now),
            )
        return ToolEvent(
            event_id=event_id,
            session_id=session_id,
            tool_name=tool_name,
            arguments_redacted=arguments_redacted,
            result_summary=result_summary,
            success=success,
            latency_ms=latency_ms,
            created_at=now,
        )

    def log_ai_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost: float,
        latency_ms: float,
        session_id: str | None = None,
    ) -> AiUsageRecord:
        """Log AI tokens and cost usage."""
        usage_id = f"ai-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ai_usage (usage_id, session_id, provider, model, input_tokens, output_tokens, estimated_cost, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (usage_id, session_id, provider, model, input_tokens, output_tokens, estimated_cost, latency_ms, now),
            )
        return AiUsageRecord(
            usage_id=usage_id,
            session_id=session_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            latency_ms=latency_ms,
            created_at=now,
        )

    def get_ai_usage_totals(self, since_iso: str | None = None) -> tuple[int, int, float]:
        """Return total (input_tokens, output_tokens, estimated_cost) since given ISO timestamp."""
        query = "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), COALESCE(SUM(estimated_cost), 0.0) FROM ai_usage"
        params: list[str] = []
        if since_iso:
            query += " WHERE created_at >= ?"
            params.append(since_iso)

        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            if row:
                return int(row[0]), int(row[1]), float(row[2])
            return 0, 0, 0.0

    # -------------------------------------------------------------------------
    # Notes Persistence
    # -------------------------------------------------------------------------

    def create_note(self, content: str) -> NoteItem:
        """Create and store a new user note."""
        note_id = f"note-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO notes (note_id, content, created_at, updated_at)
                VALUES (?, ?, ?, ?);
                """,
                (note_id, content.strip(), now, now),
            )
        return NoteItem(
            note_id=note_id,
            content=content.strip(),
            created_at=now,
            updated_at=now,
        )

    def list_notes(self, limit: int = 50) -> list[NoteItem]:
        """Fetch all stored notes sorted from newest to oldest."""
        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT note_id, content, created_at, updated_at
                FROM notes
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                NoteItem(
                    note_id=r["note_id"],
                    content=r["content"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    def search_notes(self, query: str, limit: int = 50) -> list[NoteItem]:
        """Search notes by phrase first, then by all meaningful query tokens."""
        clean_query = " ".join(query.strip().split())
        if not clean_query:
            return []

        def escape_like(value: str) -> str:
            return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        with self.db_manager.connection() as conn:
            cursor = conn.cursor()
            phrase_pattern = f"%{escape_like(clean_query)}%"
            cursor.execute(
                """
                SELECT note_id, content, created_at, updated_at
                FROM notes
                WHERE content LIKE ? ESCAPE '\\'
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (phrase_pattern, limit),
            )
            rows = cursor.fetchall()

            if not rows:
                stopwords = {
                    "que", "qué", "cual", "cuál", "cosa", "tengo", "tenia", "tenía",
                    "de", "del", "la", "el", "los", "las", "un", "una", "para", "por",
                }
                tokens = [
                    token
                    for token in clean_query.lower().split()
                    if len(token) >= 3 and token not in stopwords
                ][:8]
                if tokens:
                    clauses = " AND ".join("LOWER(content) LIKE ? ESCAPE '\\'" for _ in tokens)
                    params = [f"%{escape_like(token)}%" for token in tokens]
                    cursor.execute(
                        f"""
                        SELECT note_id, content, created_at, updated_at
                        FROM notes
                        WHERE {clauses}
                        ORDER BY created_at DESC
                        LIMIT ?;
                        """,
                        (*params, limit),
                    )
                    rows = cursor.fetchall()

            return [
                NoteItem(
                    note_id=r["note_id"],
                    content=r["content"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Persistent Reminders
    # -------------------------------------------------------------------------

    def create_reminder(
        self,
        content: str,
        due_at: str,
        recurrence: str | None = None,
    ) -> ReminderItem:
        """Create a pending reminder. ``due_at`` must be an ISO UTC timestamp."""
        reminder_id = f"rem-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        clean_content = content.strip()
        with self.db_manager.connection() as conn:
            conn.execute(
                """
                INSERT INTO reminders
                    (reminder_id, content, due_at, recurrence, status, created_at, notified_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?, NULL);
                """,
                (reminder_id, clean_content, due_at, recurrence, now),
            )
        return ReminderItem(
            reminder_id=reminder_id,
            content=clean_content,
            due_at=due_at,
            recurrence=recurrence,
            status="PENDING",
            created_at=now,
        )

    def list_reminders(self, status: str | None = None, limit: int = 50) -> list[ReminderItem]:
        """List reminders ordered by due time, optionally filtered by status."""
        with self.db_manager.connection() as conn:
            if status is None:
                rows = conn.execute(
                    """
                    SELECT reminder_id, content, due_at, recurrence, status, created_at, notified_at
                    FROM reminders ORDER BY due_at ASC LIMIT ?;
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT reminder_id, content, due_at, recurrence, status, created_at, notified_at
                    FROM reminders WHERE status = ? ORDER BY due_at ASC LIMIT ?;
                    """,
                    (status, limit),
                ).fetchall()
        return [self._reminder_from_row(row) for row in rows]

    def list_due_reminders(self, now_iso: str, limit: int = 50) -> list[ReminderItem]:
        """Return pending reminders due at or before the supplied UTC boundary."""
        with self.db_manager.connection() as conn:
            rows = conn.execute(
                """
                SELECT reminder_id, content, due_at, recurrence, status, created_at, notified_at
                FROM reminders
                WHERE status = 'PENDING' AND due_at <= ?
                ORDER BY due_at ASC
                LIMIT ?;
                """,
                (now_iso, limit),
            ).fetchall()
        return [self._reminder_from_row(row) for row in rows]

    def cancel_reminder(self, reminder_id: str | None = None) -> bool:
        """Cancel a pending reminder, or the most recently created pending one."""
        with self.db_manager.connection() as conn:
            target_id = reminder_id
            if target_id is None:
                row = conn.execute(
                    """
                    SELECT reminder_id FROM reminders
                    WHERE status = 'PENDING'
                    ORDER BY created_at DESC, rowid DESC LIMIT 1;
                    """
                ).fetchone()
                if row is None:
                    return False
                target_id = str(row["reminder_id"])
            cursor = conn.execute(
                "UPDATE reminders SET status = 'CANCELLED' WHERE reminder_id = ? AND status = 'PENDING';",
                (target_id,),
            )
            return cursor.rowcount > 0

    def mark_reminder_notified(self, reminder_id: str, notified_at: str | None = None) -> bool:
        """Mark one pending reminder as notified."""
        notified = notified_at or utc_now_iso()
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE reminders
                SET status = 'NOTIFIED', notified_at = ?
                WHERE reminder_id = ? AND status = 'PENDING';
                """,
                (notified, reminder_id),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _reminder_from_row(row: object) -> ReminderItem:
        # sqlite3.Row is mapping-like but intentionally kept out of the domain API.
        r = row  # type: ignore[assignment]
        return ReminderItem(
            reminder_id=r["reminder_id"],  # type: ignore[index]
            content=r["content"],  # type: ignore[index]
            due_at=r["due_at"],  # type: ignore[index]
            recurrence=r["recurrence"],  # type: ignore[index]
            status=r["status"],  # type: ignore[index]
            created_at=r["created_at"],  # type: ignore[index]
            notified_at=r["notified_at"],  # type: ignore[index]
        )
