"""Camera-control contracts and explicit device drivers.

Vision analysis and camera management are separate capabilities. Device-specific
HTTP protocols live behind this boundary; conversational tools only see generic
operations such as day/night mode.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import ClassVar, Protocol, runtime_checkable

from ailen.core.capabilities import CapabilityDescriptor


@dataclass(frozen=True)
class CameraControlStatus:
    daynight_mode: str


@runtime_checkable
class CameraControl(Protocol):
    @property
    def is_configured(self) -> bool:
        ...

    @property
    def is_available(self) -> bool:
        ...

    def capabilities(self) -> list[CapabilityDescriptor]:
        ...

    def get_status(self) -> CameraControlStatus:
        ...

    def set_daynight_mode(self, mode: str) -> CameraControlStatus:
        ...


class CameraControlError(RuntimeError):
    """Expected management/protocol failure from a camera-control driver."""


class CameraSessionExpired(CameraControlError):
    """NC250 management token is no longer valid."""


class TpLinkNc250CameraControl:
    """NC250 management driver using the camera's own FCGI Web-UI protocol."""

    _MODE_TO_DEVICE: ClassVar[dict[str, int]] = {"auto": 1, "day": 2, "night": 3}
    _DEVICE_TO_MODE: ClassVar[dict[int, str]] = {
        value: key for key, value in _MODE_TO_DEVICE.items()
    }

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 80,
        timeout_seconds: float = 3.0,
    ) -> None:
        self.host = host.strip()
        self.username = username.strip()
        self._password = password
        self.port = int(port)
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self._token = ""
        self._verified = False
        self._cookies = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cookies))

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.username and self._password and 1 <= self.port <= 65535)

    @property
    def is_available(self) -> bool:
        """Return true only after a real management request succeeded."""
        return self.is_configured and self._verified

    def capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                key="camera.daynight",
                description="consultar y cambiar la cámara entre modo automático, día y noche/infrarrojo",
                available=self.is_available,
                source="camera_control",
            )
        ]

    @property
    def _base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _post(self, path: str, fields: dict[str, str]) -> dict[str, object]:
        encoded = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            method="POST",
        )
        with self._opener.open(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="replace")
        parsed: dict[str, object] = {}
        fragments = [fragment.strip() for fragment in payload.split("&&") if fragment.strip()]
        if not fragments:
            raise CameraControlError("NC250 returned an empty management response")
        for fragment in fragments:
            try:
                document = json.loads(fragment)
            except json.JSONDecodeError as exc:
                raise CameraControlError("NC250 returned malformed management JSON") from exc
            if not isinstance(document, dict):
                raise CameraControlError("NC250 returned an invalid management response")
            parsed.update(document)
        new_token = parsed.get("token")
        if isinstance(new_token, str) and new_token:
            self._token = new_token
        error_code_raw = parsed.get("errorCode", 0)
        if not isinstance(error_code_raw, (str, int)) or isinstance(error_code_raw, bool):
            self._verified = False
            raise CameraControlError(
                f"NC250 returned an invalid management error code: {error_code_raw!r}"
            )
        try:
            error_code = int(error_code_raw)
        except (TypeError, ValueError) as exc:
            self._verified = False
            raise CameraControlError(
                f"NC250 returned an invalid management error code: {error_code_raw!r}"
            ) from exc
        if error_code == 902:
            self._verified = False
            raise CameraSessionExpired("NC250 management session expired")
        if error_code != 0:
            self._verified = False
            raise CameraControlError(f"NC250 management request failed with code {error_code}")
        return parsed

    def _login(self) -> None:
        if not self.is_configured:
            raise CameraControlError("NC250 management credentials are unavailable")
        password_b64 = base64.b64encode(self._password.encode("utf-8")).decode("ascii")
        payload = self._post(
            "/login.fcgi",
            {"Username": self.username, "Password": password_b64},
        )
        if not self._token:
            token = payload.get("token")
            if not isinstance(token, str) or not token:
                raise CameraControlError("NC250 login did not return an authorization token")
            self._token = token

    def _authorized_post(self, path: str, fields: dict[str, str] | None = None) -> dict[str, object]:
        if not self._token:
            self._login()
        request_fields = dict(fields or {})
        request_fields["token"] = self._token
        try:
            return self._post(path, request_fields)
        except CameraSessionExpired:
            # The camera explicitly reports that its management token expired.
            self._token = ""
            self._login()
            request_fields["token"] = self._token
            return self._post(path, request_fields)

    def get_status(self) -> CameraControlStatus:
        try:
            payload = self._authorized_post("/daynightconfsettinginit.fcgi")
            raw_mode = payload.get("daynightmode")
            if not isinstance(raw_mode, (str, int)) or isinstance(raw_mode, bool):
                raise CameraControlError(f"NC250 returned unknown day/night mode: {raw_mode!r}")
            try:
                mode = self._DEVICE_TO_MODE[int(raw_mode)]
            except (KeyError, TypeError, ValueError) as exc:
                raise CameraControlError(
                    f"NC250 returned unknown day/night mode: {raw_mode!r}"
                ) from exc
            self._verified = True
            return CameraControlStatus(daynight_mode=mode)
        except Exception:
            self._verified = False
            raise

    def set_daynight_mode(self, mode: str) -> CameraControlStatus:
        normalized = mode.strip().lower()
        if normalized not in self._MODE_TO_DEVICE:
            raise ValueError("day/night mode must be one of: auto, day, night")
        try:
            self._authorized_post(
                "/daynightconf.fcgi",
                {"daynightmode": str(self._MODE_TO_DEVICE[normalized])},
            )
            verified = self.get_status()
            if verified.daynight_mode != normalized:
                raise CameraControlError(
                    "NC250 did not retain the requested day/night mode "
                    f"({normalized} requested, {verified.daynight_mode} reported)"
                )
            return verified
        except Exception:
            self._verified = False
            raise

def create_camera_control(
    driver: str,
    *,
    host: str,
    username: str,
    password: str,
    port: int = 80,
    timeout_seconds: float = 3.0,
) -> CameraControl | None:
    """Build the explicitly configured camera driver; never auto-detect a protocol."""
    normalized = driver.strip().lower()
    if normalized == "none":
        return None
    if normalized == "tp_link_nc250":
        return TpLinkNc250CameraControl(
            host=host,
            username=username,
            password=password,
            port=port,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported camera control driver: {driver}")
