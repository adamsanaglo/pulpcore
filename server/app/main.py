import logging
import logging.config
import time
from typing import Any, Awaitable, Callable, Dict

import fastapi_microsoft_identity
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError as ValidationError
from fastapi.requests import Request
from fastapi.responses import RedirectResponse, Response
from httpx import HTTPStatusError, RequestError
from sqlalchemy.exc import IntegrityError

from api.routes.api import router as api_router
from core.config import settings
from core.exception import (
    exception_handler,
    httpx_exception_handler,
    integrity_error_handler,
    pulp_exception_handler,
    validation_exception_handler,
)
from core.log_config import DEFAULT_LOG_CONFIG

# setup loggers
if settings.LOGGING_CONFIG:
    LOG_CONFIG = settings.LOGGING_CONFIG
    logging.config.fileConfig(settings.LOGGING_CONFIG, disable_existing_loggers=False)
else:
    LOG_CONFIG = DEFAULT_LOG_CONFIG
    logging.config.dictConfig(DEFAULT_LOG_CONFIG)

logger = logging.getLogger(__name__)

root_router = APIRouter()
app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)
fastapi_microsoft_identity.initialize(settings.TENANT_ID, settings.APP_CLIENT_ID)


UNAUTHENTICATED_ROUTES = ("/", "/api/", "/redoc", "/openapi.json")


@fastapi_microsoft_identity.requires_auth  # type: ignore
async def authenticate(request: Request) -> None:
    """Does nothing but trigger requires_auth. The request arg must be passed as a kwarg."""
    return


@app.middleware("http")
async def log_requests_and_authenticate(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Any:
    logger.info(
        f"request from {request.client.host}:{request.client.port} - "
        f"'{request.method} {request.url.path}'."
    )
    start_time = time.time()

    unauthenticated_response = None
    if request.get("path") not in UNAUTHENTICATED_ROUTES:
        unauthenticated_response = await authenticate(request=request)

    if unauthenticated_response:
        response = unauthenticated_response
    else:
        response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    formatted_process_time = "{0:.2f}".format(process_time)
    logger.info(
        f"request completed_in={formatted_process_time}ms status_code={response.status_code}."
    )

    return response


@root_router.get("/", response_class=RedirectResponse, status_code=302)
def root() -> str:
    logger.info("root request")
    return "/api/"


@root_router.get("/api/", status_code=200)
def api(request: Request) -> Dict[str, Any]:
    return {
        "server": {"version": settings.VERSION},
        "versions": {"v4": "v4/"},
    }


app.include_router(api_router, prefix=settings.API_PREFIX)
app.include_router(root_router)
app.add_middleware(CorrelationIdMiddleware, header_name="X-Correlation-ID")

app.add_exception_handler(HTTPStatusError, pulp_exception_handler)
app.add_exception_handler(RequestError, httpx_exception_handler)
app.add_exception_handler(ValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_error_handler)
app.add_exception_handler(Exception, exception_handler)

if __name__ == "__main__":
    # Use this for debugging purposes only
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.DEBUG,
        log_config=LOG_CONFIG,
    )
