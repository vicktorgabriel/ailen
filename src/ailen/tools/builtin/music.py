"""Music service and tool for AILEN.

Abstract controlled playback service and tool.
No Spotify credentials or arbitrary filesystem scanning.
See ADR-010.
"""

from typing import Any, ClassVar, Protocol, runtime_checkable

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult


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

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        action = validated_args["action"]

        if action == "play":
            query = validated_args.get("query", "")
            if not self.service.play(query):
                msg = "La reproducción de música no está disponible."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
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
