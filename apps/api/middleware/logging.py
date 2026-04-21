import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("sigma.access")


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Emit one structured JSON log line per request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        record = {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": elapsed_ms,
            "ip": request.client.host if request.client else None,
        }
        logger.info(json.dumps(record))
        return response
