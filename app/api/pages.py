"""Server-rendered page routes. Auth is cookie-based; unauthenticated users
hitting a portal page are redirected to login."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user_optional
from app.models.user import User

router = APIRouter(tags=["pages"])
templates: Jinja2Templates | None = None  # injected in main.py


def _tpl() -> Jinja2Templates:
    assert templates is not None, "templates not initialised"
    return templates


def _ctx(request: Request, user: User | None, **extra):
    return {"request": request, "user": user, **extra}


@router.get("/", response_class=HTMLResponse)
def landing(request: Request, user: User | None = Depends(get_current_user_optional)):
    return _tpl().TemplateResponse(request, "landing.html", _ctx(request, user))


@router.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request):
    # single demo, user-flavoured only
    return _tpl().TemplateResponse(request, "demo.html", {"role": "user"})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, role: str = "user"):
    return _tpl().TemplateResponse(request, "auth/login.html", {"role": role})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, role: str = "user"):
    return _tpl().TemplateResponse(request, "auth/register.html", {"role": role})


# --- user portal ---
@router.get("/app", response_class=HTMLResponse)
def user_home(request: Request, user: User | None = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/login?role=user", status_code=302)
    return _tpl().TemplateResponse(request, "user/dashboard.html", _ctx(request, user))


@router.get("/app/{page}", response_class=HTMLResponse)
def user_page(page: str, request: Request,
              user: User | None = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/login?role=user", status_code=302)
    if page not in ("upload", "search", "analytics", "trends", "settings"):
        return RedirectResponse("/app", status_code=302)
    return _tpl().TemplateResponse(request, f"user/{page}.html", _ctx(request, user))


# --- chemist portal ---
@router.get("/chemist", response_class=HTMLResponse)
def chemist_home(request: Request,
                 user: User | None = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/login?role=chemist", status_code=302)
    if user.role != "chemist":
        return RedirectResponse("/app", status_code=302)
    return _tpl().TemplateResponse(request, "chemist/dashboard.html", _ctx(request, user))


@router.get("/chemist/{page}", response_class=HTMLResponse)
def chemist_page(page: str, request: Request,
                 user: User | None = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/login?role=chemist", status_code=302)
    if user.role != "chemist":
        return RedirectResponse("/app", status_code=302)
    if page not in ("upload", "inventory", "demand", "analytics", "settings", "news"):
        return RedirectResponse("/chemist", status_code=302)
    return _tpl().TemplateResponse(request, f"chemist/{page}.html", _ctx(request, user))
