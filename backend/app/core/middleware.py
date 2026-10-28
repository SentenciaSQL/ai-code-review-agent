from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestSizeLimitMiddleware:
    """Reject request bodies larger than the configured limit before they are parsed."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body exceeds the configured limit of {self.max_bytes} bytes."
                        ),
                        "code": "request_too_large",
                    },
                )
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        sent = False

        async def replay() -> dict:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
