"""HTTP server for the AILEN web panel.

Stdlib-only (http.server). Sin dependencias externas: apropiado para el
hardware objetivo mientras ADR-006 queda pendiente de benchmark.

Hardening baseline:

- límite de tamaño de body (413 si se excede);
- métodos permitidos explícitos (405 para el resto);
- Content-Type ``application/x-www-form-urlencoded`` exigido en POST de
  formularios;
- headers de seguridad básicos (nosniff, frame-deny, CSP, referrer-policy);
- timeout de socket por conexión.

Sin HTTPS artesanal: la exposición LAN productiva se resuelve en despliegue
(reverse proxy/túnel), no acá.
"""

import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from ailen.web.app import AILENWebApp, WebRequest, WebResponse

logger = logging.getLogger("ailen.web.server")

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB alcanza sobrado para formularios del panel
_SOCKET_TIMEOUT_S = 30.0


class _Handler(BaseHTTPRequestHandler):
    """Thin bridge between http.server and AILENWebApp."""

    app: AILENWebApp  # inyectado por create_server

    server_version = "AILENWeb/0.1"

    def setup(self) -> None:
        super().setup()
        self.request.settimeout(_SOCKET_TIMEOUT_S)

    def _dispatch(self) -> None:
        parsed = urlsplit(self.path)
        raw_length = self.headers.get("Content-Length")
        length = 0
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                self._send(WebResponse(status=400, body=b"Content-Length invalido"))
                return
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(WebResponse(status=413, body=b"Body demasiado grande"))
                return
        if self.command == "POST":
            content_type = self.headers.get("Content-Type", "")
            if content_type and "application/x-www-form-urlencoded" not in content_type:
                self._send(WebResponse(status=415, body=b"Content-Type no soportado"))
                return
        body = self.rfile.read(length) if length > 0 else b""
        request = WebRequest(
            method=self.command,
            path=parsed.path,
            headers={k.lower(): v for k, v in self.headers.items()},
            body=body,
            remote_addr=self.client_address[0] if self.client_address else "unknown",
        )
        try:
            response = self.app.handle(request)
        except Exception:
            logger.exception("Error no controlado en %s %s", self.command, parsed.path)
            response = WebResponse(status=500, body=b"Error interno")
        self._send(response)

    def _send(self, response: WebResponse) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        if "Cache-Control" not in response.headers:
            # HTML dinámico nunca cacheable; estáticos definen su propia política.
            self.send_header("Cache-Control", "no-store")
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if response.body and self.command != "HEAD":
            self.wfile.write(response.body)

    do_GET = _dispatch
    do_POST = _dispatch
    do_HEAD = _dispatch

    def _method_not_allowed(self) -> None:
        self._send(WebResponse.json({"error": "método no permitido"}, status=405))

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed

    def log_message(self, fmt: str, *args: object) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)


def create_server(
    app: AILENWebApp,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """Create the panel server. Bind LAN queda a decisión de despliegue."""
    handler = type("AILENHandler", (_Handler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)


def serve(app: AILENWebApp, host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run the panel server until interrupted."""
    server = create_server(app, host, port)
    logger.info("Panel AILEN en http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
