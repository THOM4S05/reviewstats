"""Request diagnostics that omit raw paths, query strings, bodies and credentials."""

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request

logger = logging.getLogger("reviewstats.requests")


def install_request_logging(app: FastAPI) -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("reviewstats").setLevel(logging.INFO)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            logger.error("request_failed request_id=%s error_type=%s", request_id, type(exc).__name__)
            raise
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            logger.log(
                logging.WARNING if status >= 500 else logging.INFO,
                "request_completed request_id=%s method=%s route=%s status=%s duration_ms=%.2f",
                request_id, request.method, route, status, (perf_counter() - started) * 1000,
            )
