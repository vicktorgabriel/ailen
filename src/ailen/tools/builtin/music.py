"""Music service and tool for AILEN.

Abstract controlled playback service and tool.
No Spotify credentials or arbitrary filesystem scanning.
See ADR-010.
"""

import logging
import shutil
import subprocess
from typing import Any, ClassVar, Protocol, runtime_checkable

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult

logger = logging.getLogger("ailen.tools.music")


@runtime_checkable
class MusicService(Protocol):
    """Protocol for music playback controllers."""

    def play(self, track_or_query: str = "") -> bool:
        """Start or resume playback."""
        ...

    def pause(self) -> bool:
        """Pause playback."""
        ...

    def resume(self) -> bool:
        """Resume paused playback."""
        ...

    def next_track(self) -> bool:
        """Skip to next track."""
        ...

    def stop(self) -> bool:
        """Stop playback completely."""
        ...

    def get_status(self) -> dict[str, Any]:
        """Return structured playback status."""
        ...


class UnavailableMusicService:
    """Fail-closed placeholder until a real playback backend is configured."""

    def play(self, track_or_query: str = "") -> bool:
        return False

    def pause(self) -> bool:
        return False

    def resume(self) -> bool:
        return False

    def next_track(self) -> bool:
        return False

    def stop(self) -> bool:
        return False

    def get_status(self) -> dict[str, Any]:
        return {"state": "UNAVAILABLE", "current_track": None}


class MprisMusicService:
    """Real local MPRIS transport using the lightweight ``playerctl`` CLI.

    AILEN only controls an already configured desktop/appliance media player. It
    does not scan the filesystem, launch arbitrary commands, or interpret a text
    query as a file/URL. Text search remains a separate provider/catalog concern.
    """

    def __init__(self, player: str | None = None, binary: str | None = None) -> None:
        self._binary = binary or shutil.which("playerctl")
        self._player = player.strip() if player else None

    @property
    def is_available(self) -> bool:
        return bool(self._binary)

    def _argv(self, *args: str) -> list[str]:
        if not self._binary:
            return []
        argv = [self._binary]
        if self._player:
            argv.extend(["--player", self._player])
        argv.extend(args)
        return argv

    def _run(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        argv = self._argv(*args)
        if not argv:
            return None
        try:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                shell=False,
                timeout=2.0,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("MPRIS command failed: %s", exc)
            return None

    def play(self, track_or_query: str = "") -> bool:
        # Generic MPRIS transport cannot safely map free text to a local track.
        if track_or_query.strip():
            return False
        return self._run("play") is not None

    def pause(self) -> bool:
        return self._run("pause") is not None

    def resume(self) -> bool:
        return self._run("play") is not None

    def next_track(self) -> bool:
        return self._run("next") is not None

    def stop(self) -> bool:
        return self._run("stop") is not None

    def get_status(self) -> dict[str, Any]:
        if not self._binary:
            return {
                "state": "UNAVAILABLE",
                "current_track": None,
                "backend": "mpris-playerctl",
                "query_supported": False,
            }

        status_result = self._run("status")
        if status_result is None:
            return {
                "state": "UNAVAILABLE",
                "current_track": None,
                "backend": "mpris-playerctl",
                "query_supported": False,
            }

        raw_state = status_result.stdout.strip().upper()
        state = raw_state if raw_state in {"PLAYING", "PAUSED", "STOPPED"} else "UNKNOWN"
        current_track: str | None = None

        metadata_result = self._run("metadata", "--format", "{{artist}}\t{{title}}")
        if metadata_result is not None:
            raw = metadata_result.stdout.strip()
            if raw:
                artist, _, title = raw.partition("\t")
                artist = artist.strip()
                title = title.strip()
                if artist and title:
                    current_track = f"{artist} - {title}"
                else:
                    current_track = title or artist or None

        return {
            "state": state,
            "current_track": current_track,
            "backend": "mpris-playerctl",
            "query_supported": False,
        }


class LocalMusicService:
    """In-memory controlled music service state machine."""

    def __init__(self) -> None:
        self.state: str = "STOPPED"  # "STOPPED", "PLAYING", "PAUSED"
        self.current_track: str | None = None
        self.playlist: list[str] = [
            "Pista 1 - Ambiente Taller",
            "Pista 2 - Sintetizadores Relajantes",
            "Pista 3 - Ritmos Acústicos",
        ]
        self._track_index: int = 0

    def play(self, track_or_query: str = "") -> bool:
        if track_or_query.strip():
            self.current_track = track_or_query.strip()
        elif not self.current_track:
            self.current_track = self.playlist[self._track_index]
        self.state = "PLAYING"
        return True

    def pause(self) -> bool:
        if self.state == "PLAYING":
            self.state = "PAUSED"
            return True
        return False

    def resume(self) -> bool:
        if self.state == "PAUSED":
            self.state = "PLAYING"
            return True
        if self.state == "STOPPED":
            return self.play()
        return False

    def next_track(self) -> bool:
        self._track_index = (self._track_index + 1) % len(self.playlist)
        self.current_track = self.playlist[self._track_index]
        self.state = "PLAYING"
        return True

    def stop(self) -> bool:
        self.state = "STOPPED"
        self.current_track = None
        return True

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "current_track": self.current_track,
            "track_index": self._track_index,
        }


class MusicTool:
    """Controlled music playback tool."""

    name: str = "music"
    description: str = "Controla la reproducción de música (reproducir, pausar, reanudar, siguiente, parar, estado)."
    intent_hints = ("música", "musica", "canción", "cancion", "pausa", "siguiente", "reproducir", "poné música", "pone musica")
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {
                "type": "str",
                "required": True,
                "enum": ["play", "pause", "resume", "next", "stop", "status"],
            },
            "query": {
                "type": "str",
                "required": False,
                "max_len": 100,
            },
        },
    }
    permissions: ClassVar[list[str]] = ["media.playback"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def __init__(self, service: MusicService | None = None) -> None:
        self.service = service if service is not None else UnavailableMusicService()

    @property
    def is_available(self) -> bool:
        """Whether a real playback target is currently reachable."""
        try:
            return self.service.get_status().get("state") != "UNAVAILABLE"
        except Exception:  # noqa: BLE001
            return False

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        action = validated_args["action"]

        if action == "play":
            query = validated_args.get("query", "")
            if not self.service.play(query):
                status = self.service.get_status()
                unsupported_query = bool(
                    query.strip()
                    and status.get("state") != "UNAVAILABLE"
                    and status.get("query_supported") is False
                )
                msg = (
                    "El reproductor actual permite controlar música, pero la búsqueda por nombre "
                    "todavía no está configurada."
                    if unsupported_query
                    else "La reproducción de música no está disponible."
                )
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNSUPPORTED_QUERY" if unsupported_query else "UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    data=status,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                )
            status = self.service.get_status()
            track = status.get("current_track", "música")
            msg = f"Reproduciendo {track}."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data=status,
                requires_llm_summary=False,
            )

        if action == "pause":
            ok = self.service.pause()
            msg = "Música pausada." if ok else "No hay música reproduciéndose para pausar."
            return ToolResult(
                success=ok,
                tool_name=self.name,
                status_code="OK" if ok else "NOOP",
                message=msg,
                summary=msg,
                data=self.service.get_status(),
                requires_llm_summary=False,
            )

        if action == "resume":
            ok = self.service.resume()
            status = self.service.get_status()
            track = status.get("current_track", "música")
            msg = f"Reanudando {track}." if ok else "No hay música pausada."
            return ToolResult(
                success=ok,
                tool_name=self.name,
                status_code="OK" if ok else "NOOP",
                message=msg,
                summary=msg,
                data=status,
                requires_llm_summary=False,
            )

        if action == "next":
            if not self.service.next_track():
                msg = "No se pudo avanzar a la siguiente pista."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                )
            status = self.service.get_status()
            track = status.get("current_track", "siguiente pista")
            msg = f"Reproduciendo siguiente tema: {track}."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data=status,
                requires_llm_summary=False,
            )

        if action == "stop":
            if not self.service.stop():
                msg = "No se pudo detener la música."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                )
            msg = "Música detenida."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data=self.service.get_status(),
                requires_llm_summary=False,
            )

        if action == "status":
            status = self.service.get_status()
            st = status.get("state", "STOPPED")
            track = status.get("current_track")
            if st == "PLAYING" and track:
                msg = f"Reproduciendo: {track}."
            elif st == "PAUSED" and track:
                msg = f"Pausado en: {track}."
            elif st == "UNAVAILABLE":
                msg = "El backend de reproducción de música no está configurado."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    data=status,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                    requires_llm_summary=False,
                )
            else:
                msg = "No hay música en reproducción."

            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data=status,
                requires_llm_summary=False,
            )

        return ToolResult(
            success=False,
            tool_name=self.name,
            status_code="INVALID_ARGS",
            message=f"Acción de música desconocida: {action}",
            error_code=ErrorCode.TOOL_ARGS_INVALID,
        )
