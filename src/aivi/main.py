import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from aivi.api.routes import router
from aivi.config import Settings, get_settings
from aivi.db import init_database
from aivi.llm import LLMNotConfigured, LLMProvider
from aivi.llm.router import LLMRouter
from aivi.security.policy import NotFound, WriteDenied

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, llm: LLMProvider | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    resolved = settings or get_settings()
    app = FastAPI(title="AI_VI", version="0.1.0")
    app.state.settings = resolved
    app.state.session_factory = init_database(resolved)
    app.state.llm = llm or LLMRouter(resolved)
    app.include_router(router)

    @app.exception_handler(WriteDenied)
    async def denied(_request, exc: WriteDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(NotFound)
    async def missing(_request, exc: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(LLMNotConfigured)
    async def unconfigured(_request, exc: LLMNotConfigured) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def bad_request(_request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app
