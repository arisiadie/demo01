from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Callable) -> None:
        super().__init__(app)
        self.window_seconds = 60
        self.limit = settings.rate_limit_per_minute
        self.buckets: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/static") or request.url.path == "/":
            return await call_next(request)

        actor = request.headers.get("X-User-Id") or request.client.host if request.client else "anonymous"
        now = time.time()
        bucket = self.buckets[actor]
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()

        if len(bucket) >= self.limit:
            return Response("Rate limit exceeded", status_code=429)

        bucket.append(now)
        return await call_next(request)

