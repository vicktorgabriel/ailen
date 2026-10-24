"""Supervised, bounded lifecycle for Core agent tasks (ADR-014 §4)."""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from ailen.core.agent_loop import AgentLoop, AgentRun, AgentRunStatus
from ailen.core.confirmation import ConfirmationService, ConfirmationState
from ailen.domain.enums import SocialMode
from ailen.tools.contracts import ToolContext


class AgentTaskStatus(StrEnum):
    RUNNING = "RUNNING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class AgentTaskHandle:
    id: str
    status: AgentTaskStatus
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AgentTaskView:
    id: str
    task: str
    status: AgentTaskStatus
    steps: int
    confirmation_id: str | None
    summary: str


@dataclass
class _TaskRecord:
    id: str
    task: str
    status: AgentTaskStatus
    cancel_event: threading.Event
    reason: str | None = None
    run: AgentRun | None = None
    thread: threading.Thread | None = None


class AgentService:
    """Run one supervised task at a time by default; no autonomous scheduling.

    ``on_event`` receives a fixed event name and an immutable, redacted view.
    Tool arguments and tool results are never included in service views/events.
    """

    _ACTIVE: ClassVar[frozenset[AgentTaskStatus]] = frozenset({
        AgentTaskStatus.RUNNING, AgentTaskStatus.AWAITING_CONFIRMATION,
    })
    _RUN_STATUS: ClassVar[dict[AgentRunStatus, AgentTaskStatus]] = {
        AgentRunStatus.RUNNING: AgentTaskStatus.RUNNING,
        AgentRunStatus.COMPLETED: AgentTaskStatus.COMPLETED,
        AgentRunStatus.CANCELLED: AgentTaskStatus.CANCELLED,
        AgentRunStatus.BUDGET_EXCEEDED: AgentTaskStatus.BUDGET_EXCEEDED,
        AgentRunStatus.FAILED: AgentTaskStatus.FAILED,
        AgentRunStatus.AWAITING_CONFIRMATION: AgentTaskStatus.AWAITING_CONFIRMATION,
    }
    _CONFIRMATION_DENIED = "La acción fue denegada por la persona."
    _CONFIRMATION_EXPIRED = "La confirmación venció antes de ejecutar la acción."
    _CONFIRMATION_MISSING = "La confirmación ya no está disponible."
    _CANCELLED = "La tarea fue cancelada."
    _GENERIC_FAILURE = "Tarea finalizada con error."

    def __init__(
        self,
        loop_factory: Callable[[threading.Event], AgentLoop],
        confirmations: ConfirmationService,
        max_concurrent: int = 1,
        history_limit: int = 20,
        *,
        on_event: Callable[[str, AgentTaskView], None] | None = None,
        confirmation_poll_interval: float = 0.05,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int) or not 1 <= max_concurrent <= 16:
            raise ValueError("max_concurrent debe estar entre 1 y 16")
        if isinstance(history_limit, bool) or not isinstance(history_limit, int) or not max_concurrent <= history_limit <= 1000:
            raise ValueError("history_limit debe ser al menos max_concurrent y como máximo 1000")
        if (
            isinstance(confirmation_poll_interval, bool)
            or not isinstance(confirmation_poll_interval, (int, float))
            or not math.isfinite(confirmation_poll_interval)
            or not 0.005 <= confirmation_poll_interval <= 1.0
        ):
            raise ValueError("confirmation_poll_interval debe estar entre 0.005 y 1 segundo")
        self._loop_factory = loop_factory
        self.confirmations = confirmations
        self.max_concurrent = max_concurrent
        self.history_limit = history_limit
        self._on_event = on_event
        self._poll_interval = float(confirmation_poll_interval)
        self._clock = clock
        self._lock = threading.RLock()
        self._tasks: dict[str, _TaskRecord] = {}

    def submit(self, task: str, *, mode: SocialMode) -> AgentTaskHandle:
        """Validate and launch a bounded task on a daemon worker thread."""
        safe_task = task[:80] if isinstance(task, str) else ""
        reason: str | None = None
        if not isinstance(task, str) or not task.strip() or len(task) > 500:
            reason = "La tarea debe tener entre 1 y 500 caracteres."
        elif not isinstance(mode, SocialMode):
            reason = "El modo social de la tarea no es válido."
        elif mode in {SocialMode.SHOP, SocialMode.PUBLIC}:
            reason = "El agente no está disponible en modo SHOP o PUBLIC."

        task_id = secrets.token_urlsafe(18)
        cancel_event = threading.Event()
        with self._lock:
            if reason is None and self._active_count() >= self.max_concurrent:
                reason = "Ya hay una tarea del agente en curso."
            record = _TaskRecord(
                id=task_id,
                task=safe_task,
                status=AgentTaskStatus.REJECTED if reason else AgentTaskStatus.RUNNING,
                cancel_event=cancel_event,
                reason=reason,
            )
            self._tasks[task_id] = record
            if reason is None:
                thread = threading.Thread(
                    target=self._worker,
                    args=(record, task.strip(), mode),
                    name=f"ailen-agent-{task_id[:8]}",
                    daemon=True,
                )
                record.thread = thread
            self._prune()
        self._emit("TASK_REJECTED" if reason else "TASK_SUBMITTED", record)
        if reason is not None:
            return AgentTaskHandle(task_id, AgentTaskStatus.REJECTED, reason)
        assert record.thread is not None
        try:
            record.thread.start()
        except RuntimeError:
            with self._lock:
                record.status = AgentTaskStatus.FAILED
                record.reason = self._GENERIC_FAILURE
            self._emit("TASK_FAILED", record)
            return AgentTaskHandle(task_id, AgentTaskStatus.FAILED, self._GENERIC_FAILURE)
        return AgentTaskHandle(task_id, AgentTaskStatus.RUNNING)

    def cancel(self, task_id: str) -> bool:
        """Set cancellation once; repeated calls for a known ID remain successful."""
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return False
            record.cancel_event.set()
            active = record.status in self._ACTIVE
        if active:
            self._emit("TASK_CANCEL_REQUESTED", record)
        return True

    def cancel_all(self) -> int:
        """Signal cancellation to every currently running or supervised task."""
        with self._lock:
            records = [record for record in self._tasks.values() if record.status in self._ACTIVE]
            for record in records:
                record.cancel_event.set()
        for record in records:
            self._emit("TASK_CANCEL_REQUESTED", record)
        return len(records)

    def status(self, task_id: str) -> AgentTaskView | None:
        with self._lock:
            record = self._tasks.get(task_id)
            return self._view(record) if record is not None else None

    def recent(self) -> tuple[AgentTaskView, ...]:
        with self._lock:
            records = list(self._tasks.values())[-self.history_limit:]
            return tuple(self._view(record) for record in reversed(records))

    def shutdown(self, timeout: float) -> bool:
        """Cancel work and join daemon threads within one shared time budget."""
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 <= timeout <= 300
        ):
            raise ValueError("timeout debe estar entre 0 y 300 segundos")
        self.cancel_all()
        with self._lock:
            threads = [record.thread for record in self._tasks.values() if record.thread is not None]
        deadline = self._clock() + timeout
        current = threading.current_thread()
        for thread in threads:
            if thread is current or not thread.is_alive():
                continue
            thread.join(max(0.0, deadline - self._clock()))
        return all(thread is current or not thread.is_alive() for thread in threads)

    def _worker(self, record: _TaskRecord, task: str, mode: SocialMode) -> None:
        try:
            loop = self._loop_factory(record.cancel_event)
            original_context_factory = loop.context_factory

            def mode_context() -> ToolContext:
                context = original_context_factory()
                if not isinstance(context, ToolContext):
                    return context
                restricted = {SocialMode.SHOP, SocialMode.PUBLIC}
                if mode in restricted or context.mode in restricted:
                    # Live or submitted mode is public: stop the task and keep the stricter mode.
                    record.cancel_event.set()
                    return replace(context, mode=context.mode if context.mode in restricted else mode)
                return context

            loop.context_factory = mode_context
            run = loop.run(task)
            self._record_run(record, run)
            while run.status is AgentRunStatus.AWAITING_CONFIRMATION:
                confirmation_id = run.confirmation_id
                if not confirmation_id:
                    run.status = AgentRunStatus.FAILED
                    run.error = self._CONFIRMATION_MISSING
                    run.confirmation_id = None
                    break
                run = self._wait_for_confirmation(loop, run, confirmation_id, record.cancel_event)
                self._record_run(record, run)
            self._finish(record, run)
        except Exception:  # noqa: BLE001 - worker boundary must retain service availability.
            with self._lock:
                record.status = AgentTaskStatus.FAILED
                record.reason = self._GENERIC_FAILURE
            self._emit("TASK_FAILED", record)

    def _wait_for_confirmation(
        self,
        loop: AgentLoop,
        run: AgentRun,
        confirmation_id: str,
        cancel_event: threading.Event,
    ) -> AgentRun:
        while True:
            if cancel_event.is_set():
                return loop.resume(run, confirmation_id)
            request = self.confirmations.status(confirmation_id)
            if request is None or request.state in {
                ConfirmationState.APPROVED,
                ConfirmationState.DENIED,
                ConfirmationState.EXPIRED,
            }:
                return loop.resume(run, confirmation_id)
            remaining = (request.expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                # Ask the confirmation authority to materialize expiry first.
                request = self.confirmations.status(confirmation_id)
                if request is None or request.state is not ConfirmationState.PENDING:
                    return loop.resume(run, confirmation_id)
                if not run._lock.acquire(blocking=False):
                    return run
                try:
                    run.status = AgentRunStatus.FAILED
                    run.error = self._CONFIRMATION_EXPIRED
                    run.confirmation_id = None
                    run._pending_call = None
                finally:
                    run._lock.release()
                return run
            cancel_event.wait(min(self._poll_interval, remaining))

    def _record_run(self, record: _TaskRecord, run: AgentRun) -> None:
        with self._lock:
            record.run = run
            record.status = (
                AgentTaskStatus.AWAITING_CONFIRMATION
                if run.status is AgentRunStatus.AWAITING_CONFIRMATION
                else AgentTaskStatus.RUNNING
            )
            record.reason = None
        self._emit(
            "TASK_AWAITING_CONFIRMATION"
            if run.status is AgentRunStatus.AWAITING_CONFIRMATION else "TASK_RESUMED",
            record,
        )

    def _finish(self, record: _TaskRecord, run: AgentRun) -> None:
        with self._lock:
            record.run = run
            record.status = self._RUN_STATUS[run.status]
            record.reason = None
        event = {
            AgentTaskStatus.COMPLETED: "TASK_COMPLETED",
            AgentTaskStatus.CANCELLED: "TASK_CANCELLED",
            AgentTaskStatus.BUDGET_EXCEEDED: "TASK_BUDGET_EXCEEDED",
            AgentTaskStatus.FAILED: "TASK_FAILED",
        }.get(record.status, "TASK_FINISHED")
        self._emit(event, record)

    def _active_count(self) -> int:
        return sum(record.status in self._ACTIVE for record in self._tasks.values())

    def _prune(self) -> None:
        while len(self._tasks) > self.history_limit:
            removable = next(
                (task_id for task_id, record in self._tasks.items() if record.status not in self._ACTIVE),
                None,
            )
            if removable is None:
                return
            del self._tasks[removable]

    @classmethod
    def _view(cls, record: _TaskRecord) -> AgentTaskView:
        run = record.run
        steps = len(run.steps) if run is not None else 0
        confirmation_id = (
            run.confirmation_id
            if run is not None and record.status is AgentTaskStatus.AWAITING_CONFIRMATION
            else None
        )
        if record.status is AgentTaskStatus.REJECTED:
            summary = record.reason or "Tarea rechazada."
        elif record.status is AgentTaskStatus.COMPLETED:
            summary = "Tarea completada."
        elif record.status is AgentTaskStatus.CANCELLED:
            summary = cls._CANCELLED
        elif record.status is AgentTaskStatus.BUDGET_EXCEEDED:
            summary = "Se agotó el presupuesto de la tarea."
        elif record.status is AgentTaskStatus.AWAITING_CONFIRMATION:
            summary = "Esperando confirmación humana."
        elif record.status is AgentTaskStatus.RUNNING:
            summary = "Tarea en curso."
        elif record.reason:
            summary = record.reason
        elif run is not None and run.error in {
            cls._CONFIRMATION_DENIED, cls._CONFIRMATION_EXPIRED, cls._CONFIRMATION_MISSING,
        }:
            summary = run.error
        else:
            summary = cls._GENERIC_FAILURE
        return AgentTaskView(
            id=record.id,
            task=record.task[:80],
            status=record.status,
            steps=steps,
            confirmation_id=confirmation_id,
            summary=summary[:300],
        )

    def _emit(self, event_name: str, record: _TaskRecord) -> None:
        callback = self._on_event
        if callback is None:
            return
        with self._lock:
            view = self._view(record)
        try:
            callback(event_name, view)
        except Exception:  # noqa: BLE001 - observers cannot interrupt task execution.
            return
