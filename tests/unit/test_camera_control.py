"""Tests for generic camera control and the NC250 protocol boundary."""

import json

from ailen.tools.builtin.camera import CameraTool
from ailen.tools.contracts import ToolContext
from ailen.vision.control import CameraControlStatus, TpLinkNc250CameraControl


class FakeCameraControl:
    def __init__(self) -> None:
        self.mode = "auto"
        self.is_available = True
        self.is_configured = True

    def capabilities(self):  # type: ignore[no-untyped-def]
        return []

    def get_status(self) -> CameraControlStatus:
        return CameraControlStatus(daynight_mode=self.mode)

    def set_daynight_mode(self, mode: str) -> CameraControlStatus:
        self.mode = mode
        return self.get_status()


def test_camera_tool_controls_generic_daynight_mode() -> None:
    control = FakeCameraControl()
    tool = CameraTool(control)

    result = tool.execute(
        {"action": "set_daynight", "mode": "night"},
        ToolContext(),
    )

    assert result.success is True
    assert control.mode == "night"
    assert result.data["daynight_mode"] == "night"
    assert "infrarrojo" in result.message


def test_camera_tool_fails_closed_without_control_driver() -> None:
    tool = CameraTool(None)
    result = tool.execute({"action": "status"}, ToolContext())
    assert result.success is False
    assert result.status_code == "UNAVAILABLE"


def test_nc250_driver_maps_generic_modes_to_device_values(monkeypatch) -> None:
    driver = TpLinkNc250CameraControl(
        host="camera.local",
        username="admin",
        password="secret",
    )
    calls: list[tuple[str, dict[str, str]]] = []

    mode = "auto"

    def fake_authorized_post(path: str, fields=None):  # type: ignore[no-untyped-def]
        nonlocal mode
        calls.append((path, dict(fields or {})))
        if path == "/daynightconf.fcgi":
            mode = {"1": "auto", "2": "day", "3": "night"}[fields["daynightmode"]]
        return {"errorCode": "0", "daynightmode": {"auto": "1", "day": "2", "night": "3"}[mode]}

    monkeypatch.setattr(driver, "_authorized_post", fake_authorized_post)

    status = driver.set_daynight_mode("night")
    assert status.daynight_mode == "night"
    assert calls == [
        ("/daynightconf.fcgi", {"daynightmode": "3"}),
        ("/daynightconfsettinginit.fcgi", {}),
    ]
    assert driver.is_available is True


def test_nc250_driver_accepts_string_zero_error_code(monkeypatch) -> None:
    driver = TpLinkNc250CameraControl(
        host="camera.local",
        username="admin",
        password="secret",
    )

    class Response:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            del args
            return False

        def read(self) -> bytes:
            return json.dumps({"errorCode": "0", "daynightmode": "3"}).encode()

    monkeypatch.setattr(driver._opener, "open", lambda *args, **kwargs: Response())

    payload = driver._post("/daynightconfsettinginit.fcgi", {})

    assert payload["errorCode"] == "0"


def test_nc250_driver_parses_fcgi_json_chain_and_refreshes_token(monkeypatch) -> None:
    driver = TpLinkNc250CameraControl(
        host="camera.local",
        username="admin",
        password="secret",
    )

    class Response:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            del args
            return False

        def read(self) -> bytes:
            return (
                b'{"errorCode":"0","daynightmode":"3"}'
                b'&&{"token":"refreshed-session"}'
            )

    monkeypatch.setattr(driver._opener, "open", lambda *args, **kwargs: Response())

    payload = driver._post("/daynightconf.fcgi", {"daynightmode": "3"})

    assert payload["daynightmode"] == "3"
    assert driver._token == "refreshed-session"
