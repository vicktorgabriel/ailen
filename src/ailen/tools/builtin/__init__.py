"""Builtin allowlisted tools for AILEN Core."""

from ailen.tools.builtin.camera import CameraTool
from ailen.tools.builtin.clock import ClockTool
from ailen.tools.builtin.face_expression import FaceExpressionTool
from ailen.tools.builtin.music import (
    DesktopMusicService,
    LocalMusicService,
    MprisMusicService,
    MusicService,
    MusicTool,
)
from ailen.tools.builtin.notes import NotesTool
from ailen.tools.builtin.reminders import ReminderService, RemindersTool
from ailen.tools.builtin.system_status import SystemStatusTool
from ailen.tools.builtin.timer import TimerEntry, TimerService, TimerTool
from ailen.tools.builtin.volume import (
    AudioVolumeService,
    FakeAudioVolumeService,
    SystemAudioVolumeService,
    VolumeTool,
)
from ailen.tools.builtin.web_fetch import WebFetchPolicy, WebFetchTool
from ailen.tools.builtin.web_search import (
    FakeWebSearchProvider,
    UnconfiguredWebSearchProvider,
    WebSearchProvider,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
    WebSearchTool,
)

__all__ = [
    "AudioVolumeService",
    "CameraTool",
    "ClockTool",
    "DesktopMusicService",
    "FaceExpressionTool",
    "FakeAudioVolumeService",
    "FakeWebSearchProvider",
    "LocalMusicService",
    "MprisMusicService",
    "MusicService",
    "MusicTool",
    "NotesTool",
    "ReminderService",
    "RemindersTool",
    "SystemAudioVolumeService",
    "SystemStatusTool",
    "TimerEntry",
    "TimerService",
    "TimerTool",
    "UnconfiguredWebSearchProvider",
    "VolumeTool",
    "WebFetchPolicy",
    "WebFetchTool",
    "WebSearchProvider",
    "WebSearchRequest",
    "WebSearchResponse",
    "WebSearchResult",
    "WebSearchTool",
]
