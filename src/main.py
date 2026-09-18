import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Query
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config import get_settings
from src.database import init_db
from src.exceptions import AppError, app_error_handler
from src.routers import health, projects, documents, auth, patterns, runs, tasks, workflows
from src.middleware.auth import AuthMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db()

    from pathlib import Path
    Path(settings.DATA_ROOT).mkdir(parents=True, exist_ok=True)
    Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)

    logger.info("Seeding patterns...")
    try:
        from src.services.seed_service import seed_patterns
        await seed_patterns()
    except Exception as e:
        logger.warning("Pattern seeding failed: %s", e)

    logger.info("AI Agent Factory v2 started")
    yield

    from src.workflows.checkpointer import close_checkpointer
    await close_checkpointer()
    logger.info("Shutting down")


app = FastAPI(
    title="AI Agent Factory v2",
    description="Document-Driven, Pattern-Aware Code Generator",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)

app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": {"errors": exc.errors()},
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "http_error",
                "message": exc.detail,
            }
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request, exc):
    from fastapi.responses import JSONResponse
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An internal error occurred",
            }
        },
    )


app.include_router(auth.router)
app.include_router(health.router)
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(patterns.router)
app.include_router(runs.router)
app.include_router(tasks.router)
app.include_router(workflows.router)


@app.websocket("/projects/{project_id}/runs/{run_id}/hitl")
async def websocket_hitl(
    websocket: WebSocket,
    project_id: str,
    run_id: str,
    token: str = Query(...),
):
    from src.websockets.hitl import websocket_hitl_endpoint
    await websocket_hitl_endpoint(websocket, project_id, run_id, token)


@app.get("/", tags=["root"])
async def root():
    return {"message": "AI Agent Factory v2", "docs": "/docs", "frontend": "/ui"}


@app.get("/ui", tags=["root"])
async def ui():
    return FileResponse(Path(__file__).parent.parent / "static" / "index.html")
