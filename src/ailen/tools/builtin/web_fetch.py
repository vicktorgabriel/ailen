"""Web fetch security policy and tool for AILEN.

Provides strictly controlled web extraction with anti-SSRF protections,
private IP blocking, maximum payload size limits, and Content-Type filtering.
See ADR-010.
"""

import ipaddress
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, ClassVar

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult

logger = logging.getLogger("ailen.tools.web_fetch")

# Max payload: 256 KiB
DEFAULT_MAX_BYTES: int = 256 * 1024
DEFAULT_MAX_REDIRECTS: int = 3

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "text/html",
    "text/plain",
    "text/markdown",
    "text/xml",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
})


class WebFetchPolicy:
    """SSRF and payload security validator for web fetch operations."""

    @staticmethod
    def is_ip_allowed(ip_str: str) -> tuple[bool, str]:
        """Check if an IP address is a publicly routable, safe destination."""
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Dirección IP no válida: {ip_str}"

        if ip.is_loopback:
            return False, "Dirección de loopback (localhost) bloqueada."
        if ip.is_private:
            return False, "Dirección de red privada (RFC1918) bloqueada."
        if ip.is_link_local:
            return False, "Dirección link-local bloqueada."
        if ip.is_multicast:
            return False, "Dirección multicast bloqueada."
        if ip.is_reserved:
            return False, "Dirección reservada bloqueada."
        if ip.is_unspecified:
            return False, "Dirección no especificada bloqueada."

        # Extra explicit check for Cloud Metadata endpoint 169.254.169.254
        if str(ip) == "169.254.169.254":
            return False, "Endpoint de metadata cloud bloqueado."

        return True, "ALLOWED"

    @classmethod
    def validate_url(cls, url: str) -> tuple[bool, str]:
        """Validate URL scheme and resolved host IP addresses against SSRF policies."""
        if not url or not isinstance(url, str):
            return False, "URL vacía o no válida."

        try:
            parsed = urllib.parse.urlsplit(url.strip())
        except Exception as exc:  # noqa: BLE001
            return False, f"URL malformada: {exc}"

        # 1. HTTPS only by default. Cleartext HTTP is not permitted for fetched content.
        if parsed.scheme.lower() != "https":
            return False, f"Esquema no permitido: {parsed.scheme} (sólo https)."

        host = parsed.hostname
        if not host:
            return False, "La URL no contiene un nombre de host."
        if parsed.username is not None or parsed.password is not None:
            return False, "Credenciales embebidas en URL no permitidas."

        if host.lower() in {"localhost", "localhost.localdomain", "metadata.google.internal"}:
            return False, "Host local o metadata bloqueado."

        # 2. Resolve DNS and validate each destination IP
        try:
            port = parsed.port or 443
        except ValueError as exc:
            return False, f"Puerto inválido en URL: {exc}"
        try:
            addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            if not addr_info:
                return False, f"No se pudo resolver el host: {host}"

            for item in addr_info:
                sockaddr = item[4]
                ip_addr = str(sockaddr[0])
                allowed, reason = cls.is_ip_allowed(ip_addr)
                if not allowed:
                    return False, f"Host '{host}' resuelve a IP bloqueada ({ip_addr}): {reason}"

        except socket.gaierror as exc:
            return False, f"Fallo en resolución DNS para {host}: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Error validando host {host}: {exc}"

        return True, "ALLOWED"


class WebFetchTool:
    """Safe web content extractor tool protected against SSRF."""

    name: str = "web_fetch"
    description: str = "Descarga y extrae contenido de texto público de una URL de forma segura."
    intent_hints = ("url", "enlace", "página", "pagina", "sitio web", "abrí", "abre")
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "url": {
                "type": "str",
                "required": True,
                "min_len": 8,
                "max_len": 500,
            },
        },
    }
    permissions: ClassVar[list[str]] = ["web.fetch"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = True
    destructive: bool = False
    timeout_seconds: float = 6.0

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.max_bytes = max_bytes

    def is_side_effecting(self, arguments: dict[str, Any]) -> bool:
        del arguments
        return False

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        url = validated_args["url"].strip()

        # 1. Pre-validation of target URL
        is_safe, reason = WebFetchPolicy.validate_url(url)
        if not is_safe:
            msg = f"URL bloqueada por política de seguridad: {reason}"
            logger.warning("WebFetch blocked SSRF: %s -> %s", url, reason)
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="SSRF_BLOCKED",
                message=msg,
                summary=msg,
                error_code=ErrorCode.TOOL_SSRF_BLOCKED,
                requires_llm_summary=False,
            )

        # 2. Controlled request execution with redirect inspection
        current_url = url
        redirects_followed = 0

        while redirects_followed <= DEFAULT_MAX_REDIRECTS:
            try:
                req = urllib.request.Request(
                    current_url,
                    headers={
                        "User-Agent": "AILEN-Agent/0.1 (Appliance-Safe-Fetch)",
                        "Accept": "text/html, text/plain, application/json;q=0.9",
                    },
                )

                # Custom non-redirecting opener or validation loop
                class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
                        return None  # Prevent automatic redirect

                opener = urllib.request.build_opener(NoRedirectHandler)
                timeout = min(context.timeout_seconds, self.timeout_seconds)

                with opener.open(req, timeout=timeout) as response:
                    # Check Content-Type allowlist
                    content_type_header = response.headers.get("Content-Type", "").lower()
                    base_content_type = content_type_header.split(";")[0].strip()

                    if not base_content_type or base_content_type not in ALLOWED_CONTENT_TYPES:
                        shown_type = base_content_type or "<ausente>"
                        msg = f"Tipo de contenido no permitido: {shown_type}"
                        return ToolResult(
                            success=False,
                            tool_name=self.name,
                            status_code="DISALLOWED_CONTENT_TYPE",
                            message=msg,
                            summary=msg,
                            error_code=ErrorCode.TOOL_DENIED,
                            requires_llm_summary=False,
                        )

                    # Check Content-Length if present
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            if int(content_length) > self.max_bytes:
                                msg = f"Contenido excede el límite máximo permitido ({self.max_bytes} bytes)."
                                return ToolResult(
                                    success=False,
                                    tool_name=self.name,
                                    status_code="PAYLOAD_TOO_LARGE",
                                    message=msg,
                                    summary=msg,
                                    error_code=ErrorCode.TOOL_PAYLOAD_TOO_LARGE,
                                    requires_llm_summary=False,
                                )
                        except ValueError:
                            pass

                    # Read body with hard cap
                    raw_data = response.read(self.max_bytes + 1)
                    if len(raw_data) > self.max_bytes:
                        msg = f"El cuerpo descargado excede el tamaño máximo permitido de {self.max_bytes} bytes."
                        return ToolResult(
                            success=False,
                            tool_name=self.name,
                            status_code="PAYLOAD_TOO_LARGE",
                            message=msg,
                            summary=msg,
                            error_code=ErrorCode.TOOL_PAYLOAD_TOO_LARGE,
                            requires_llm_summary=False,
                        )

                    charset = response.headers.get_content_charset() or "utf-8"
                    try:
                        text_content = raw_data.decode(charset, errors="replace")
                    except Exception:  # noqa: BLE001
                        text_content = raw_data.decode("utf-8", errors="replace")

                    # Basic text sanitization
                    clean_text = " ".join(text_content.split())
                    summary_preview = clean_text[:200] + "..." if len(clean_text) > 200 else clean_text

                    return ToolResult(
                        success=True,
                        tool_name=self.name,
                        status_code="OK",
                        message=f"Contenido obtenido ({len(clean_text)} caracteres): {summary_preview}",
                        summary=f"Contenido obtenido de {current_url}",
                        data={
                            "url": current_url,
                            "content_type": base_content_type,
                            "length_bytes": len(raw_data),
                            "text": clean_text[:4000],  # Bound text passed to context
                        },
                        requires_llm_summary=True,
                    )

            except urllib.error.HTTPError as exc:
                try:
                    if exc.code in {301, 302, 303, 307, 308}:
                        new_url = exc.headers.get("Location")
                        if not new_url:
                            return ToolResult(
                                success=False,
                                tool_name=self.name,
                                status_code="REDIRECT_ERROR",
                                message="Redirección HTTP sin cabecera Location.",
                                error_code=ErrorCode.UNKNOWN_ERROR,
                            )
                        # Resolve relative redirect URLs
                        new_url = urllib.parse.urljoin(current_url, new_url)

                        # Validate redirect target against SSRF policy
                        safe_redirect, redirect_reason = WebFetchPolicy.validate_url(new_url)
                        if not safe_redirect:
                            msg = f"Destino de redirección bloqueado por SSRF ({new_url}): {redirect_reason}"
                            return ToolResult(
                                success=False,
                                tool_name=self.name,
                                status_code="SSRF_BLOCKED",
                                message=msg,
                                summary=msg,
                                error_code=ErrorCode.TOOL_SSRF_BLOCKED,
                            )

                        current_url = new_url
                        redirects_followed += 1
                        continue

                    msg = f"Error HTTP {exc.code} al obtener {current_url}: {exc.reason}"
                    return ToolResult(
                        success=False,
                        tool_name=self.name,
                        status_code=f"HTTP_{exc.code}",
                        message=msg,
                        summary=msg,
                        error_code=ErrorCode.UNKNOWN_ERROR,
                    )
                finally:
                    exc.close()

            except urllib.error.URLError as exc:
                msg = f"Fallo de conexión al obtener {current_url}: {exc.reason}"
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="NETWORK_ERROR",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.CLOUD_OFFLINE,
                )

            except TimeoutError:
                msg = f"Tiempo de espera agotado al conectar a {current_url}"
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="TIMEOUT",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.TOOL_TIMEOUT,
                )

        msg = f"Se superó el límite máximo de {DEFAULT_MAX_REDIRECTS} redirecciones."
        return ToolResult(
            success=False,
            tool_name=self.name,
            status_code="MAX_REDIRECTS_EXCEEDED",
            message=msg,
            summary=msg,
            error_code=ErrorCode.UNKNOWN_ERROR,
        )
