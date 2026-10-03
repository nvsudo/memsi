"""Local dashboard. Every write goes through MemoryService, source = dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..backend import Filters
from ..core import MemoryError, MemoryService, get_service
from ..models import SENSITIVITIES, TYPES

VIA = "dashboard"


def create_app(service: Optional[MemoryService] = None) -> FastAPI:
    app = FastAPI(title="memsi")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    state = {"svc": service}

    def svc() -> MemoryService:
        if state["svc"] is None:
            state["svc"] = get_service()
        return state["svc"]

    def render(request: Request, name: str, **ctx):
        s = svc()
        base = {
            "request": request,
            "owner": s.settings.owner,
            "pending_count": s.backend.count(Filters(status=["pending"])),
            "types": TYPES,
            "sensitivities": SENSITIVITIES,
            "flash": request.query_params.get("flash"),
            "error": request.query_params.get("error"),
        }
        base.update(ctx)
        return templates.TemplateResponse(request, name, base)

    def back(url: str, flash: Optional[str] = None, error: Optional[str] = None) -> RedirectResponse:
        q = []
        if flash:
            q.append(f"flash={flash}")
        if error:
            q.append(f"error={error}")
        return RedirectResponse(url + ("?" + "&".join(q) if q else ""), status_code=303)

    # ------------------------------------------------------------- inbox
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/inbox", status_code=307)

    @app.get("/inbox", response_class=HTMLResponse)
    def inbox(request: Request):
        items = svc().pending()
        return render(request, "inbox.html", items=items, clean_count=sum(1 for i in items if i.clean), active="inbox")

    @app.post("/inbox/{id}/decide")
    def decide(
        id: str,
        action: str = Form(...),
        quote: str = Form(""),
        content: str = Form(""),
        supersedes_id: str = Form(""),
    ):
        s = svc()
        try:
            if action == "reject":
                s.confirm(id, "reject", user_quote=quote or None, via=VIA)
                return back("/inbox", flash="Rejected.")
            if action == "supersede":
                if not supersedes_id:
                    return back("/inbox", error="Pick which memory this replaces.")
                s.confirm(id, "supersede", user_quote=quote or "approved in dashboard", via=VIA, supersedes_id=supersedes_id, edited_content=content or None)
                return back("/inbox", flash="Approved and superseded the older memory.")
            s.confirm(id, "approve", user_quote=quote or "approved in dashboard", via=VIA, edited_content=content or None)
            return back("/inbox", flash="Approved.")
        except MemoryError as e:
            return back("/inbox", error=str(e))

    @app.post("/inbox/approve-clean")
    def approve_clean():
        s = svc()
        n = 0
        for item in s.pending():
            if item.clean:
                s.confirm(item.memory.id, "approve", user_quote="bulk approved in dashboard (no neighbours)", via=VIA)
                n += 1
        return back("/inbox", flash=f"Approved {n} clean proposals.")

    # ------------------------------------------------------------ digest
    @app.get("/digest", response_class=HTMLResponse)
    def digest(request: Request, scope: str = "", budget: int = 0, app_name: str = ""):
        s = svc()
        d = s.recall(scope=scope or None, budget_tokens=budget or None, app=app_name or None)
        return render(
            request,
            "digest.html",
            digest=d,
            scope=scope,
            budget=budget or s.settings.recall.budget_tokens,
            app_name=app_name,
            apps=sorted(s.settings.read_filters.keys()),
            active="digest",
        )

    # ------------------------------------------------------------ browse
    @app.get("/browse", response_class=HTMLResponse)
    def browse(request: Request, q: str = "", status: str = "approved", scope: str = "", type: str = ""):
        s = svc()
        rows = []
        if q:
            rows = [(m, sim) for m, sim in s.search(q, k=25, scope=[scope] if scope else None, type=[type] if type else None, include_pending=(status != "approved"))]
        else:
            f = Filters(status=[status] if status else None, scope=[scope] if scope else None, type=[type] if type else None)
            rows = [(m, None) for m in s.browse(f, limit=200)]
        return render(request, "browse.html", rows=rows, q=q, status=status, scope=scope, type=type, active="browse")

    @app.post("/memory/{id}/retract")
    def retract(id: str, reason: str = Form("")):
        svc().retract(id, reason=reason or None, via=VIA)
        return back("/browse", flash="Retracted.")

    @app.post("/memory/{id}/edit")
    def edit(id: str, content: str = Form(...), type: str = Form(...), scope: str = Form(...), subject: str = Form(""), sensitivity: str = Form(...)):
        try:
            svc().edit(id, via=VIA, content=content, type=type, scope=scope, subject=subject or None, sensitivity=sensitivity)
        except MemoryError as e:
            return back("/browse", error=str(e))
        return back("/browse", flash="Saved.")

    # ---------------------------------------------------------- timeline
    @app.get("/timeline", response_class=HTMLResponse)
    def timeline(request: Request, limit: int = 100):
        s = svc()
        events = s.audit(limit)
        ids = {e.memory_id for e in events if e.memory_id}
        mems = {i: s.get(i) for i in ids}
        return render(request, "timeline.html", events=events, mems=mems, active="timeline")

    # ------------------------------------------------------------ health
    @app.get("/api/health")
    def health():
        return JSONResponse(svc().stats())

    @app.get("/api/digest")
    def api_digest(scope: str = "", budget: int = 0, app_name: str = ""):
        d = svc().recall(scope=scope or None, budget_tokens=budget or None, app=app_name or None)
        return {"text": d.text, "used_tokens": d.used_tokens, "budget_tokens": d.budget_tokens, "included": len(d.included), "excluded": len(d.excluded)}

    return app
