"""MediScript application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import account_api, auth, chemist_api, guest_api, pages, user_api
from app.core.config import settings
from app.core.database import init_db

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mediscript")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialised (%s)", settings.sqlalchemy_url.split("://")[0])
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.origins_list,
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )

    # templates + static
    tpl = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    pages.templates = tpl
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # routers
    app.include_router(pages.router)
    app.include_router(auth.router)
    app.include_router(user_api.router)
    app.include_router(chemist_api.router)
    app.include_router(account_api.router)
    app.include_router(guest_api.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
