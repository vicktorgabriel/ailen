"""Bounded local file tool for AILEN (ADR-014 autonomy level N2).

Only paths that resolve inside one of the administrator-authorized roots are
reachable. Every request is checked with ``Path.resolve(strict=False)`` plus
``is_relative_to`` so ``..`` traversal and symlinks that escape a root fail
closed. Special files (FIFOs, sockets, devices), NUL bytes in paths, oversized
files and oversized listings are rejected. There is no delete, move, chmod or
shell action; overwrite and append on an existing file back up its opened
descriptor to a unique sibling ``<name>.ailen-bak-<timestamp>-<nonce>`` first.
Final files use O_NOFOLLOW and fstat (regular, exactly one hardlink), and are
never reopened by path after validation. Residual limit: a hostile process can
still replace a parent directory between resolution and open; these roots must
not have parent directories writable by untrusted users. A future dir_fd walk
is required to eliminate that parent-directory race.
"""

from __future__ import annotations

import errno
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any, BinaryIO, ClassVar, cast

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import AutonomyLevel, ToolContext, ToolResult

MAX_READ_BYTES = 64 * 1024
MAX_LIST_ENTRIES = 200
BACKUP_INFIX = ".ailen-bak-"


class _FilesError(Exception):
    """Internal fail-closed error carrying the public result metadata."""

    def __init__(self, status_code: str, message: str, error_code: ErrorCode) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_code = error_code

    def to_result(self, tool_name: str) -> ToolResult:
        return ToolResult(
            success=False,
            tool_name=tool_name,
            status_code=self.status_code,
            message=self.message,
            error_code=self.error_code,
        )


class FilesTool:
    """Read/write files only inside explicit, administrator-authorized roots."""

    name: str = "files"
    description: str = (
        "Lista, lee, crea, agrega o sobrescribe archivos de texto dentro de las "
        "raíces autorizadas. Sobrescribir guarda una copia de respaldo."
    )
    intent_hints = (
        "archivo", "archivos", "carpeta", "leer archivo", "listar archivos",
        "crear archivo", "guardar archivo", "sobrescribir",
    )
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {
                "type": "str",
                "required": True,
                "enum": ["list", "read", "create", "append", "overwrite"],
            },
            "path": {
                "type": "str",
                "required": False,
                "default": ".",
                "max_len": 4096,
            },
            "content": {
                "type": "str",
                "required": False,
                "max_len": MAX_READ_BYTES,
            },
        },
    }
    permissions: ClassVar[list[str]] = ["files.read", "files.write"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 5.0
    autonomy_level: AutonomyLevel = AutonomyLevel.N2

    def __init__(self, roots: list[str] | None = None) -> None:
        self.roots: tuple[Path, ...] = self._normalize_roots(roots or [])

    @staticmethod
    def _normalize_roots(roots: list[str]) -> tuple[Path, ...]:
        """Keep only absolute, NUL-free roots; resolve once at construction."""
        normalized: list[Path] = []
        for raw in roots:
            if not isinstance(raw, str):
                continue
            candidate = raw.strip()
            if not candidate or "\x00" in candidate:
                continue
            path = Path(candidate).expanduser()
            if not path.is_absolute():
                continue
            resolved = path.resolve(strict=False)
            if resolved not in normalized:
                normalized.append(resolved)
        return tuple(normalized)

    @property
    def is_available(self) -> bool:
        return bool(self.roots)

    def is_side_effecting(self, arguments: dict[str, Any]) -> bool:
        return arguments.get("action") in {"create", "append", "overwrite"}

    def requires_confirmation(self, arguments: dict[str, Any]) -> bool:
        """Overwrite and append to a safely opened existing file need approval."""
        if arguments.get("action") == "overwrite":
            return True
        if arguments.get("action") != "append":
            return False
        target = self._resolve(arguments.get("path") or ".")
        try:
            with self._open_regular(target, os.O_RDONLY, "rb"):
                return True
        except FileNotFoundError:
            return False

    def confirmation_summary(self, arguments: dict[str, Any]) -> str:
        """Describe the action and root-relative target; never include content."""
        target = self._resolve(arguments.get("path") or ".")
        root = next(root for root in self.roots if target.is_relative_to(root))
        action = {
            "overwrite": "Sobrescribir", "append": "Agregar contenido a",
            "create": "Crear", "read": "Leer", "list": "Listar",
        }.get(str(arguments.get("action", "")), "Operar sobre")
        return f"{action} «{target.relative_to(root)}» en la raíz autorizada."

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        if not self.is_available:
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="UNAVAILABLE",
                message="No hay raíces de archivos autorizadas por el administrador.",
                error_code=ErrorCode.TOOL_UNAVAILABLE,
            )

        action = validated_args.get("action")
        try:
            if action == "list":
                return self._list(validated_args)
            if action == "read":
                return self._read(validated_args)
            if action == "create":
                return self._create(validated_args)
            if action == "append":
                return self._append(validated_args, context)
            if action == "overwrite":
                return self._overwrite(validated_args, context)
        except _FilesError as exc:
            return exc.to_result(self.name)
        except FileNotFoundError:
            return _FilesError(
                "NOT_FOUND", "La ruta no existe.", ErrorCode.TOOL_ARGS_INVALID,
            ).to_result(self.name)
        except (OSError, ValueError) as exc:
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="IO_ERROR",
                message=f"No se pudo completar la operación de archivos: {exc}",
                error_code=ErrorCode.UNKNOWN_ERROR,
            )

        return ToolResult(
            success=False,
            tool_name=self.name,
            status_code="INVALID_ARGS",
            message=f"Acción de archivos desconocida: {action}",
            error_code=ErrorCode.TOOL_ARGS_INVALID,
        )

    def _resolve(self, raw_path: str) -> Path:
        """Resolve a request path and require it to stay inside an authorized root."""
        if not isinstance(raw_path, str):
            raise _FilesError(
                "INVALID_ARGS", "La ruta debe ser texto.", ErrorCode.TOOL_ARGS_INVALID
            )
        if not raw_path.strip() or "\x00" in raw_path:
            raise _FilesError(
                "INVALID_ARGS", "Ruta inválida o vacía.", ErrorCode.TOOL_ARGS_INVALID
            )
        try:
            candidate = Path(raw_path).expanduser()
        except (OSError, ValueError) as exc:
            raise _FilesError(
                "PATH_DENIED", f"Ruta inválida: {exc}", ErrorCode.TOOL_DENIED
            ) from exc

        if not candidate.is_absolute():
            candidate = self.roots[0] / candidate

        resolved = candidate.resolve(strict=False)
        if not any(resolved.is_relative_to(root) for root in self.roots):
            raise _FilesError(
                "PATH_DENIED",
                "La ruta queda fuera de las raíces autorizadas.",
                ErrorCode.TOOL_DENIED,
            )
        return resolved

    @staticmethod
    def _stat_path(path: Path) -> os.stat_result:
        try:
            return path.stat()
        except FileNotFoundError as exc:
            raise _FilesError(
                "NOT_FOUND", "La ruta no existe.", ErrorCode.TOOL_ARGS_INVALID
            ) from exc
        except OSError as exc:
            raise _FilesError(
                "PATH_DENIED", f"No se pudo inspeccionar la ruta: {exc}", ErrorCode.TOOL_DENIED
            ) from exc

    @staticmethod
    def _validate_descriptor(descriptor: int) -> os.stat_result:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _FilesError(
                "UNSAFE_PATH",
                "Sólo se permiten archivos regulares con un único enlace.",
                ErrorCode.TOOL_DENIED,
            )
        return info

    @classmethod
    @contextmanager
    def _open_regular(cls, path: Path, flags: int, mode: str) -> Iterator[BinaryIO]:
        """Validate the opened inode before I/O, without a truncating open."""
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise _FilesError(
                "UNSAFE_PATH", "La plataforma no permite apertura segura O_NOFOLLOW.",
                ErrorCode.TOOL_DENIED,
            )
        try:
            descriptor = os.open(
                path, flags | nofollow | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR}:
                raise _FilesError(
                    "UNSAFE_PATH", "La ruta final no es un archivo regular seguro.",
                    ErrorCode.TOOL_DENIED,
                ) from exc
            raise
        try:
            cls._validate_descriptor(descriptor)
            handle = cast(BinaryIO, os.fdopen(descriptor, mode))
        except BaseException:
            os.close(descriptor)
            raise
        with handle:
            yield handle

    @classmethod
    def _require_directory(cls, path: Path) -> os.stat_result:
        info = cls._stat_path(path)
        if not stat.S_ISDIR(info.st_mode):
            raise _FilesError(
                "UNSAFE_PATH", "La ruta no es un directorio.", ErrorCode.TOOL_DENIED
            )
        return info

    @staticmethod
    def _content(arguments: dict[str, Any], *, current_size: int = 0) -> tuple[str, bytes]:
        content = arguments.get("content")
        if not isinstance(content, str):
            raise _FilesError(
                "INVALID_ARGS",
                "La acción requiere el argumento 'content' de texto.",
                ErrorCode.TOOL_ARGS_INVALID,
            )
        payload = content.encode("utf-8")
        if current_size + len(payload) > MAX_READ_BYTES:
            raise _FilesError(
                "PAYLOAD_TOO_LARGE",
                f"El contenido supera el máximo de {MAX_READ_BYTES} bytes.",
                ErrorCode.TOOL_PAYLOAD_TOO_LARGE,
            )
        return content, payload

    def _list(self, arguments: dict[str, Any]) -> ToolResult:
        target = self._resolve(arguments.get("path") or ".")
        self._require_directory(target)
        try:
            entries = sorted(
                islice(target.iterdir(), MAX_LIST_ENTRIES + 1), key=lambda item: item.name,
            )
        except OSError as exc:
            raise _FilesError(
                "IO_ERROR", f"No se pudo listar el directorio: {exc}", ErrorCode.UNKNOWN_ERROR
            ) from exc
        if len(entries) > MAX_LIST_ENTRIES:
            raise _FilesError(
                "TOO_MANY_ENTRIES",
                f"El directorio supera el máximo de {MAX_LIST_ENTRIES} entradas.",
                ErrorCode.TOOL_PAYLOAD_TOO_LARGE,
            )

        items: list[dict[str, Any]] = []
        for entry in entries:
            try:
                info = entry.lstat()
            except OSError:
                items.append({"name": entry.name, "type": "unknown", "size": 0})
                continue
            mode = info.st_mode
            if stat.S_ISLNK(mode):
                kind = "link"
            elif stat.S_ISDIR(mode):
                kind = "dir"
            elif stat.S_ISREG(mode):
                kind = "file"
            else:
                kind = "special"
            items.append({"name": entry.name, "type": kind, "size": info.st_size})

        message = f"Listado de {target.name or target}: {len(items)} entradas."
        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=message,
            summary=message,
            data={"path": str(target), "count": len(items), "entries": items},
            requires_llm_summary=False,
        )

    def _read(self, arguments: dict[str, Any]) -> ToolResult:
        target = self._resolve(arguments.get("path") or ".")
        with self._open_regular(target, os.O_RDONLY, "rb") as handle:
            raw = self._read_bounded(handle)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _FilesError(
                "INVALID_ENCODING",
                "El archivo no es texto UTF-8 válido.",
                ErrorCode.TOOL_ARGS_INVALID,
            ) from exc

        message = f"Leído {target.name or target} ({len(raw)} bytes)."
        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=message,
            summary=message,
            data={"path": str(target), "content": text, "size": len(raw)},
            requires_llm_summary=False,
        )

    def _create(self, arguments: dict[str, Any]) -> ToolResult:
        target = self._resolve(arguments.get("path") or ".")
        _content, payload = self._content(arguments)
        try:
            with self._open_regular(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, "wb",
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise _FilesError(
                "ALREADY_EXISTS",
                f"El archivo '{target.name}' ya existe; usá append u overwrite.",
                ErrorCode.TOOL_ARGS_INVALID,
            ) from exc

        message = f"Archivo creado: {target.name or target}."
        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=message,
            summary=message,
            data={"path": str(target), "size": len(payload)},
            requires_llm_summary=False,
        )

    def _append(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        target = self._resolve(arguments.get("path") or ".")
        with ExitStack() as stack:
            try:
                handle = stack.enter_context(
                    self._open_regular(target, os.O_RDWR | os.O_APPEND, "r+b"),
                )
            except FileNotFoundError:
                # Catch only a missing initial open, never a missing backup or
                # later I/O failure. O_EXCL rejects a concurrently created path.
                return self._create(arguments)
            info = self._validate_descriptor(handle.fileno())
            self._require_approval(context)
            _content, payload = self._content(arguments, current_size=info.st_size)
            backup = self._backup(target, handle)
            self._validate_descriptor(handle.fileno())
            handle.seek(0, os.SEEK_END)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        total = info.st_size + len(payload)
        message = f"Contenido agregado a {target.name or target} ({total} bytes)."
        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=message,
            summary=message,
            data={"path": str(target), "size": total, "backup_path": str(backup)},
            requires_llm_summary=False,
        )

    def _overwrite(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        target = self._resolve(arguments.get("path") or ".")
        _content, payload = self._content(arguments)
        with self._open_regular(target, os.O_RDWR, "r+b") as handle:
            self._require_approval(context)
            backup = self._backup(target, handle)
            self._validate_descriptor(handle.fileno())
            handle.seek(0)
            handle.truncate(0)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        message = f"Archivo sobrescrito: {target.name or target}. Respaldo: {backup.name}."
        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=message,
            summary=message,
            data={
                "path": str(target),
                "backup_path": str(backup),
                "size": len(payload),
            },
            requires_llm_summary=False,
        )

    @classmethod
    def _read_bounded(cls, handle: BinaryIO) -> bytes:
        info = cls._validate_descriptor(handle.fileno())
        if info.st_size > MAX_READ_BYTES:
            raise _FilesError(
                "PAYLOAD_TOO_LARGE", "El archivo supera el tamaño máximo permitido.",
                ErrorCode.TOOL_PAYLOAD_TOO_LARGE,
            )
        raw = handle.read(MAX_READ_BYTES + 1)
        if len(raw) > MAX_READ_BYTES:
            raise _FilesError(
                "PAYLOAD_TOO_LARGE", "El archivo supera el tamaño máximo permitido.",
                ErrorCode.TOOL_PAYLOAD_TOO_LARGE,
            )
        return raw

    @staticmethod
    def _require_approval(context: ToolContext) -> None:
        # Core forwards this ID only after consuming its approval. In
        # particular, append-to-missing cannot become an unapproved mutation
        # if another process creates the file after the policy check.
        if context.confirmation_id is None:
            raise _FilesError(
                "CONFIRMATION_REQUIRED", "Modificar un archivo existente requiere confirmación humana.",
                ErrorCode.TOOL_DENIED,
            )

    def _backup(self, target: Path, source: BinaryIO) -> Path:
        """Copy only from the validated descriptor into a unique exclusive file."""
        source.seek(0)
        original = self._read_bounded(source)
        backup = target.with_name(
            f"{target.name}{BACKUP_INFIX}{self._backup_timestamp()}-{secrets.token_hex(6)}"
        )
        try:
            with self._open_regular(
                backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, "wb",
            ) as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise _FilesError(
                "BACKUP_FAILED", "Ya existe el respaldo; la operación fue cancelada.",
                ErrorCode.TOOL_DENIED,
            ) from exc
        return backup

    @staticmethod
    def _backup_timestamp() -> str:
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
