"""Serving the built frontend from the API process, plus the response headers for production.

The app is same-origin (the browser loads the page and calls /api on one host), so there is no
CORS middleware and none is wanted: a cross-origin page cannot call the API from a browser.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Hugging Face shows a Space inside an iframe on huggingface.co, so framing is allowed for
# those hosts only (X-Frame-Options would block it; frame-ancestors is the precise form).
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",  # React and framer-motion write style attributes
        "img-src 'self' data:",
        "font-src 'self' data:",  # self-hosted; Vite inlines small fonts as data:
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self' https://huggingface.co https://*.hf.space",
    ]
)

SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
}


class SecurityHeaders:
    """Pure ASGI middleware (not BaseHTTPMiddleware, which would buffer the SSE streams)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._extra = [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *(h for h in self._extra if h[0] not in present),
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def mount_frontend(app: FastAPI, dist: Path | None) -> bool:
    """Serve `dist` (the Vite build) and fall back to index.html for client-side routes.

    Must be called after the API routers so /api wins. Does nothing, and returns False, when there
    is no build (local development uses the Vite dev server; most tests have no build).
    """
    if dist is None or not (dist / "index.html").is_file():
        return False
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> Response:
        # An unknown API path is a JSON 404, never the HTML shell.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "not found")
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            # Vite names built files by content hash, so they can be cached forever.
            immutable = path.startswith("assets/")
            return FileResponse(
                target,
                headers={
                    "cache-control": "public, max-age=31536000, immutable"
                    if immutable
                    else "no-cache"
                },
            )
        # A path with a file extension that does not exist is a missing file, not a page.
        if Path(path).suffix:
            raise HTTPException(404, "not found")
        # Shared links such as /debate/{id} are routes of the single-page app.
        return FileResponse(index, headers={"cache-control": "no-cache"})

    return True
