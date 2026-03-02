"""ASGI middleware that sets trace_id and request_id on every request.

Uses pure ASGI (not Starlette BaseHTTPMiddleware) to avoid known issues
with streaming responses and request body consumption.
"""
import uuid

from app.services.billing_context import init_trace, set_session_id, set_trace_id


class RequestContextMiddleware:
    """Set correlation IDs for every request and echo them in response headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Extract or generate trace_id
        headers = dict(scope.get("headers", []))
        incoming_trace = headers.get(b"x-trace-id", b"").decode() or None
        if incoming_trace:
            set_trace_id(incoming_trace)
            trace_id = incoming_trace
        else:
            trace_id = init_trace()

        # Extract session_id from frontend
        incoming_session = headers.get(b"x-session-id", b"").decode() or None
        if incoming_session:
            set_session_id(incoming_session)

        # Always generate a fresh request_id
        request_id = uuid.uuid4().hex

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-trace-id", trace_id.encode()))
                response_headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            # Clean up context to avoid leaking between requests
            set_trace_id(None)
            set_session_id(None)
