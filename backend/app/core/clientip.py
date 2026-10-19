"""One-off diagnostics for the client-IP setting (TRUSTED_PROXY).

How many proxies Hugging Face puts in front of the app is not known, so for the first few real
requests the app logs what it saw: the socket peer, the X-Forwarded-For entries and the address
that TRUSTED_PROXY resolves to. Every address is masked (IPv4 last octet, IPv6 all but the first
three groups) so the log can tell devices apart without keeping a full visitor address.
"""

import ipaddress
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.ratelimit import client_ip

log = logging.getLogger("app.clientip")

CHECKED_REQUESTS = 5
_SKIP_PATHS = {"/api/health"}  # the container health check always comes from localhost


def mask_ip(value: str | None) -> str:
    if not value:
        return "-"
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return "<invalid>"
    if isinstance(ip, ipaddress.IPv4Address):
        return ".".join(value.strip().split(".")[:3] + ["0"])
    return ":".join(ip.exploded.split(":")[:3]) + "::"


class ClientIpProbe:
    """Pure ASGI middleware: logs the client-IP evidence for the first few requests, then idles."""

    def __init__(self, app: ASGIApp, *, trusted_hops: int) -> None:
        self.app = app
        self.trusted_hops = trusted_hops
        self._left = CHECKED_REQUESTS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._left > 0 and scope["type"] == "http" and scope["path"] not in _SKIP_PATHS:
            self._left -= 1
            peer = scope["client"][0] if scope.get("client") else None
            xff = next(
                (v.decode("latin-1") for k, v in scope["headers"] if k == b"x-forwarded-for"), None
            )
            entries = [p.strip() for p in xff.split(",")] if xff else []
            log.info(
                "client-ip check",
                extra={
                    "peer": mask_ip(peer),
                    "xff_entries": len(entries),
                    "xff": [mask_ip(e) for e in entries],
                    "trusted_proxy": self.trusted_hops,
                    "resolved": mask_ip(client_ip(peer, xff, self.trusted_hops)),
                },
            )
        await self.app(scope, receive, send)
