"""FastAPI application entrypoint."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.router import api_router
from app.core.config import get_settings


settings = get_settings()
APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API for League of Legends team matchup comparison and predictions.",
)

app.mount(
    "/static",
    StaticFiles(directory=str(APP_DIR / "static")),
    name="static",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root(request: Request) -> HTMLResponse:
    """Render the initial server-side application page.

    Args:
        request: Current HTTP request.

    Returns:
        Rendered HTML landing page.
    """
    return templates.TemplateResponse(
        request=request,
        name="pages/index.html",
        context={"app_name": settings.app_name, "environment": settings.environment},
    )


@app.get("/ui/partials/health", response_class=HTMLResponse, include_in_schema=False)
def health_partial(request: Request) -> HTMLResponse:
    """Render a small HTMX health-status partial.

    Args:
        request: Current HTTP request.

    Returns:
        Rendered HTML status fragment.
    """
    return templates.TemplateResponse(
        request=request,
        name="partials/health_status.html",
        context={"status": "online", "service": settings.app_name},
    )
