"""Generalforsamling Live – FastAPI-applikation."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import csvio, services
from . import state as st
from .auth import (
    STAGE_USERNAME,
    authenticate,
    can_view,
    ensure_users,
    require_actor,
    require_client_header,
    session_actor,
)
from .config import Settings, load_settings
from .db import Database
from .models import utcnow
from .realtime import Connection, ConnectionManager
from .schemas import ActionRequest, ItemCreate, ItemUpdate, MoveRequest
from .seed import seed
from .services import Actor, ServiceError

log = logging.getLogger("live")

BASE_DIR = Path(__file__).resolve().parent


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.database_path)
    manager = ConnectionManager()
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    def bootstrap() -> None:
        db.create_all()
        services.init_meta(db)
        ensure_users(db, settings)
        if settings.seed_demo_data:
            n = seed(db)
            if n:
                log.info("Indlæste %d eksempelpunkter", n)

    # Klargør databasen med det samme, så appen er brugbar også uden lifespan
    # (f.eks. i tests).
    bootstrap()
    for warning in settings.warnings:
        log.warning(warning)

    async def ping_loop() -> None:
        while True:
            await asyncio.sleep(settings.ping_interval)
            manager.broadcast({"type": "ping", "server_time": services.iso(utcnow())})

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(ping_loop())
        try:
            yield
        finally:
            task.cancel()
            db.dispose()

    app = FastAPI(title="Generalforsamling Live", lifespan=lifespan, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.db = db
    app.state.manager = manager
    app.state.settings = settings

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.resolve_secret_key(),
        session_cookie="live_session",
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=False,
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    # ------------------------------------------------------------ hjælpere

    async def broadcast_state() -> dict[str, Any]:
        snap = await run_in_threadpool(services.snapshot, db)
        manager.broadcast(snap)
        return snap

    @app.exception_handler(ServiceError)
    async def _service_error(_request: Request, exc: ServiceError):
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=exc.status_code)

    def page(request: Request, template: str, page_name: str, **extra: Any) -> HTMLResponse:
        actor = session_actor(request)
        ctx = {
            "event_name": settings.event_name,
            "page": page_name,
            "actor": actor,
            "status_labels": st.STATUS_LABELS,
            "item_types": st.ITEM_TYPES,
            **extra,
        }
        return templates.TemplateResponse(request, template, ctx)

    def login_redirect(next_url: str) -> RedirectResponse:
        return RedirectResponse(f"/login?next={next_url}", status_code=303)

    foh_only = require_actor(st.ROLE_FOH)
    foh_or_stage = require_actor(st.ROLE_FOH, st.ROLE_STAGE, st.ROLE_DEVICE,
                                 device_token=settings.device_token)
    foh_or_device = require_actor(st.ROLE_FOH, st.ROLE_DEVICE, device_token=settings.device_token)
    write_guard = [Depends(require_client_header)]

    # ------------------------------------------------------------ sider

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return page(request, "index.html", "index")

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, next: str = "/foh"):
        return page(request, "login.html", "login", next=_safe_next(next), error=None,
                    mode="stage" if _safe_next(next) == "/stage" else "foh")

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        mode: str = Form("foh"),
        username: str = Form(""),
        password: str = Form(""),
        next: str = Form("/foh"),
    ):
        next_url = _safe_next(next)
        if mode == "stage":
            username = STAGE_USERNAME
        user = await run_in_threadpool(authenticate, db, username.strip(), password)
        if user is None or (mode == "stage" and user.role != st.ROLE_STAGE):
            resp = page(request, "login.html", "login", next=next_url, mode=mode,
                        error="Forkert brugernavn eller adgangskode.")
            resp.status_code = 401
            return resp
        request.session.clear()
        request.session["role"] = user.role
        request.session["user"] = user.username
        if not can_view(Actor(user.role, user.username), next_url.strip("/").split("/")[0]):
            next_url = "/stage" if user.role == st.ROLE_STAGE else "/foh"
        return RedirectResponse(next_url, status_code=303)

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/foh", response_class=HTMLResponse)
    async def foh_page(request: Request):
        if not can_view(session_actor(request), "foh"):
            return login_redirect("/foh")
        return page(request, "foh.html", "foh")

    @app.get("/stage", response_class=HTMLResponse)
    async def stage_page(request: Request):
        if not can_view(session_actor(request), "stage"):
            return login_redirect("/stage")
        return page(request, "stage.html", "stage")

    @app.get("/monitor", response_class=HTMLResponse)
    async def monitor_page(request: Request):
        return page(request, "monitor.html", "monitor")

    # ------------------------------------------------------------ API: læsning

    @app.get("/api/health")
    async def health():
        snap = await run_in_threadpool(services.snapshot, db)
        return {"status": "ok", "revision": snap["revision"], "clients": manager.count}

    @app.get("/api/state")
    async def get_state():
        return await run_in_threadpool(services.snapshot, db)

    @app.get("/api/me")
    async def me(request: Request):
        actor = session_actor(request)
        return {"role": actor.role if actor else "monitor",
                "username": actor.username if actor else None}

    @app.get("/api/device/state")
    async def get_device_state(_actor: Actor = Depends(foh_or_device)):
        """Kompakt tilstand til Presto og andre små enheder."""
        return await run_in_threadpool(services.device_state, db)

    @app.get("/api/events")
    async def get_events(limit: int = 300, _actor: Actor = Depends(foh_only)):
        limit = max(1, min(limit, 2000))
        return {"events": await run_in_threadpool(services.list_events, db, limit)}

    # ------------------------------------------------------------ API: skrivning

    # ------------------------------------------------------------ CSV

    @app.get("/api/export.csv")
    async def export_csv(skabelon: bool = False, _actor: Actor = Depends(foh_only)):
        if skabelon:
            body, name = csvio.template_csv(), "program-skabelon.csv"
        else:
            snap = await run_in_threadpool(services.snapshot, db)
            body = csvio.export_csv(snap["items"], settings.timezone)
            from datetime import datetime
            from zoneinfo import ZoneInfo
            stamp = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d_%H%M")
            name = f"program-{stamp}.csv"
        return Response(
            content=body.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/api/import", dependencies=write_guard)
    async def import_csv(
        file: UploadFile = File(...),
        mode: str = Form("append"),
        actor: Actor = Depends(foh_only),
    ):
        if mode not in ("append", "replace"):
            return JSONResponse({"detail": "Ukendt importtype."}, status_code=400)
        data = await file.read(csvio.MAX_BYTES + 1)
        if len(data) > csvio.MAX_BYTES:
            return JSONResponse({"detail": "Filen er for stor (højst 1 MB)."}, status_code=413)
        try:
            rows = csvio.parse_csv(csvio.decode(data))
        except csvio.CsvImportError as exc:
            return JSONResponse({"detail": exc.message, "errors": exc.errors}, status_code=422)
        result = await run_in_threadpool(services.import_items, db, rows, mode == "replace", actor)
        snap = await broadcast_state()
        return {**result, "state": snap}

    @app.post("/api/items", status_code=201, dependencies=write_guard)
    async def create_item(data: ItemCreate, actor: Actor = Depends(foh_only)):
        item = await run_in_threadpool(services.create_item, db, data, actor)
        snap = await broadcast_state()
        return {"item": item, "changed": True, "state": snap}

    @app.patch("/api/items/{item_id}", dependencies=write_guard)
    async def update_item(item_id: int, data: ItemUpdate, actor: Actor = Depends(foh_only)):
        item = await run_in_threadpool(services.update_item, db, item_id, data, actor)
        snap = await broadcast_state()
        return {"item": item, "state": snap}

    @app.delete("/api/items/{item_id}", dependencies=write_guard)
    async def delete_item(item_id: int, actor: Actor = Depends(foh_only)):
        await run_in_threadpool(services.delete_item, db, item_id, actor)
        snap = await broadcast_state()
        return {"deleted": item_id, "state": snap}

    @app.post("/api/items/{item_id}/actions/{action}", dependencies=write_guard)
    async def item_action(
        item_id: int,
        action: str,
        body: Optional[ActionRequest] = None,
        actor: Actor = Depends(foh_or_stage),
    ):
        expected = body.expected_status if body else None
        item, changed = await run_in_threadpool(
            services.apply_action, db, item_id, action, actor, expected
        )
        snap = await broadcast_state() if changed else await run_in_threadpool(services.snapshot, db)
        return {"item": item, "changed": changed, "state": snap}

    @app.post("/api/items/{item_id}/move", dependencies=write_guard)
    async def move_item(item_id: int, body: MoveRequest, actor: Actor = Depends(foh_only)):
        changed = await run_in_threadpool(services.move_item, db, item_id, body.direction, actor)
        snap = await broadcast_state() if changed else await run_in_threadpool(services.snapshot, db)
        return {"changed": changed, "state": snap}

    # ------------------------------------------------------------ WebSocket

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        conn = Connection(ws)
        snap = await run_in_threadpool(services.snapshot, db)
        conn.offer(json.dumps(snap, ensure_ascii=False))
        manager.add(conn)

        async def reader() -> None:
            # Kanalen er envejs; vi læser kun for at opdage afbrydelser.
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return

        writer_task = asyncio.create_task(conn.writer())
        reader_task = asyncio.create_task(reader())
        try:
            _done, pending = await asyncio.wait(
                {writer_task, reader_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
        except Exception:  # pragma: no cover
            writer_task.cancel()
            reader_task.cancel()
        finally:
            manager.remove(conn)
            try:
                await ws.close()
            except Exception:
                pass

    return app


def _safe_next(url: str) -> str:
    if not url.startswith("/") or url.startswith("//") or "\\" in url:
        return "/foh"
    return url


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build() -> FastAPI:
    """Indgang for uvicorn:  uvicorn --factory app.main:build"""
    _configure_logging()
    return create_app()
