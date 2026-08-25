"""Unit tests for builtin tools: Clock, Timer, Volume, Music, SystemStatus."""

import subprocess
from datetime import UTC, datetime

import ailen.tools.builtin.music as music_module
from ailen.domain.enums import ErrorCode
from ailen.tools.builtin.clock import ClockTool
from ailen.tools.builtin.music import LocalMusicService, MprisMusicService, MusicTool
from ailen.tools.builtin.system_status import SystemStatusTool
from ailen.tools.builtin.timer import TimerService, TimerTool
from ailen.tools.builtin.volume import (
    FakeAudioVolumeService,
    VolumeTool,
)
from ailen.tools.contracts import ToolContext


def test_clock_tool_time_provider() -> None:
    fixed_time = datetime(2026, 8, 23, 15, 30, 45, tzinfo=UTC)
    clock = ClockTool(time_provider=lambda: fixed_time)

    res_time = clock.execute({"format": "time"}, ToolContext())
    assert res_time.success is True
    assert res_time.data["formatted"] == "15:30"
    assert "Son las 15:30" in res_time.message

    res_iso = clock.execute({"format": "iso"}, ToolContext())
    assert "2026-08-23T15:30:45+00:00" in res_iso.data["iso"]

    res_date = clock.execute({"format": "date"}, ToolContext())
    assert "23/08/2026" in res_date.message


def test_timer_service_and_tool() -> None:
    service = TimerService()
    tool = TimerTool(service=service)

    # Create timer
    res_create = tool.execute({"action": "create", "seconds": 120, "label": "Pasta"}, ToolContext())
    assert res_create.success is True
    assert "timer_id" in res_create.data
    timer_id = res_create.data["timer_id"]

    # List timers
    res_list = tool.execute({"action": "list"}, ToolContext())
    assert res_list.success is True
    assert res_list.data["count"] == 1
    assert res_list.data["timers"][0]["timer_id"] == timer_id

    # Cancel timer
    res_cancel = tool.execute({"action": "cancel", "timer_id": timer_id}, ToolContext())
    assert res_cancel.success is True
    assert res_cancel.data["cancelled"] is True

    # List after cancel
    res_list2 = tool.execute({"action": "list"}, ToolContext())
    assert res_list2.data["count"] == 0


def test_volume_tool_with_fake_service() -> None:
    fake_service = FakeAudioVolumeService(initial_level=40)
    tool = VolumeTool(service=fake_service)

    # Get
    res_get = tool.execute({"action": "get"}, ToolContext())
    assert res_get.success is True
    assert res_get.data["level"] == 40

    # Set
    res_set = tool.execute({"action": "set", "level": 75}, ToolContext())
    assert res_set.success is True
    assert fake_service.get_volume() == 75

    # Step up
    res_up = tool.execute({"action": "step_up", "step": 15}, ToolContext())
    assert res_up.success is True
    assert fake_service.get_volume() == 90

    # Step down
    res_down = tool.execute({"action": "step_down", "step": 30}, ToolContext())
    assert res_down.success is True
    assert fake_service.get_volume() == 60

    # Mute
    res_mute = tool.execute({"action": "mute"}, ToolContext())
    assert res_mute.success is True
    assert fake_service.get_volume() == 0


def test_volume_tool_unavailable_reporting() -> None:
    unavailable_service = FakeAudioVolumeService(available=False)
    tool = VolumeTool(service=unavailable_service)

    res = tool.execute({"action": "get"}, ToolContext())
    assert res.success is False
    assert res.status_code == "UNAVAILABLE"
    assert res.error_code == ErrorCode.TOOL_UNAVAILABLE
    assert "no está disponible" in res.message


def test_music_service_state_machine() -> None:
    service = LocalMusicService()
    tool = MusicTool(service=service)

    # Initial status
    assert service.state == "STOPPED"

    # Play
    res_play = tool.execute({"action": "play", "query": "Jazz Nocturno"}, ToolContext())
    assert res_play.success is True
    assert service.state == "PLAYING"
    assert service.current_track == "Jazz Nocturno"

    # Pause
    res_pause = tool.execute({"action": "pause"}, ToolContext())
    assert res_pause.success is True
    assert service.state == "PAUSED"

    # Resume
    res_resume = tool.execute({"action": "resume"}, ToolContext())
    assert res_resume.success is True
    assert service.state == "PLAYING"

    # Next track
    res_next = tool.execute({"action": "next"}, ToolContext())
    assert res_next.success is True
    assert service.state == "PLAYING"

    # Stop
    res_stop = tool.execute({"action": "stop"}, ToolContext())
    assert res_stop.success is True
    assert service.state == "STOPPED"
    assert service.current_track is None


def test_mpris_music_service_unavailable_without_playerctl(monkeypatch) -> None:
    monkeypatch.setattr(music_module.shutil, "which", lambda _name: None)
    service = MprisMusicService()

    assert service.is_available is False
    assert service.play() is False
    assert service.get_status()["state"] == "UNAVAILABLE"


def test_mpris_music_service_controls_existing_player(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if argv[-1] == "status":
            return subprocess.CompletedProcess(argv, 0, stdout="Playing\n", stderr="")
        if "metadata" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="Banda\tTema\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(music_module.subprocess, "run", fake_run)
    service = MprisMusicService(player="spotify", binary="/usr/bin/playerctl")

    assert service.play() is True
    assert service.pause() is True
    assert service.resume() is True
    assert service.next_track() is True
    assert service.stop() is True
    status = service.get_status()

    assert status["state"] == "PLAYING"
    assert status["current_track"] == "Banda - Tema"
    assert status["backend"] == "mpris-playerctl"
    assert status["query_supported"] is False
    assert all(call[:3] == ["/usr/bin/playerctl", "--player", "spotify"] for call in calls)


def test_mpris_music_service_rejects_free_text_query(monkeypatch) -> None:
    def fake_run(argv, **_kwargs):
        if argv[-1] == "status":
            return subprocess.CompletedProcess(argv, 0, stdout="Paused\n", stderr="")
        if "metadata" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="Artista\tActual\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(music_module.subprocess, "run", fake_run)
    service = MprisMusicService(binary="/usr/bin/playerctl")
    tool = MusicTool(service=service)

    result = tool.execute({"action": "play", "query": "Jazz Nocturno"}, ToolContext())

    assert result.success is False
    assert result.status_code == "UNSUPPORTED_QUERY"
    assert "búsqueda por nombre" in result.message
    assert result.data["state"] == "PAUSED"


def test_system_status_tool_sanitization() -> None:
    tool = SystemStatusTool()
    result = tool.execute({"detailed": True}, ToolContext())

    assert result.success is True
    assert result.status_code == "OK"
    assert "cpu_cores" in result.data
    assert "ram_total_gb" in result.data

    # Ensure no secrets or home directory subpaths in detailed disks
    if "disks" in result.data:
        for disk in result.data["disks"]:
            assert not disk["mount_point"].startswith("/home/")


def test_music_tool_default_backend_is_unavailable() -> None:
    tool = MusicTool()
    result = tool.execute({"action": "play", "query": "Jazz"}, ToolContext())
    assert result.success is False
    assert result.status_code == "UNAVAILABLE"
    assert result.error_code == ErrorCode.TOOL_UNAVAILABLE


def test_system_status_detailed_does_not_expose_disk_path() -> None:
    tool = SystemStatusTool()
    result = tool.execute({"detailed": True}, ToolContext())
    assert result.success is True
    if "disk" in result.data:
        assert "path" not in result.data["disk"]


def test_volume_step_unavailable_does_not_guess_current_level() -> None:
    unavailable_service = FakeAudioVolumeService(available=False)
    tool = VolumeTool(service=unavailable_service)
    result = tool.execute({"action": "step_up", "step": 10}, ToolContext())
    assert result.success is False
    assert result.status_code == "UNAVAILABLE"
