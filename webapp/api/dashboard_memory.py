"""Authenticated memory management; brand selection remains server controlled."""
from contextlib import closing
from fastapi import APIRouter, HTTPException, Request

from webapp.auth.dependencies import require_operator, require_user
from webapp.dashboard_memory import MemoryConflict, MemoryEdit, MemoryRollback, MemoryVersionRequest, memory_enabled


def create_dashboard_memory_router(resolve_brand, workspace_for_request):
    router = APIRouter(prefix="/api/dashboard/memory")

    def scope(request, write=False):
        user = require_operator(request) if write else require_user(request)
        brand = resolve_brand(user)
        service = workspace_for_request(request).dashboard_memory
        if memory_enabled():
            service.store.bootstrap(brand["id"])
            service.notify()
        return brand, service

    def view(brand, service):
        return {**service.store.view(brand["id"]), "brand_name": brand["name"], "configured": service.registry.snapshot() is not None}

    def mutate(action):
        try:
            return action()
        except MemoryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("")
    def get_memory(request: Request):
        brand, service = scope(request)
        return view(brand, service)

    @router.patch("/items/{item_id}")
    def edit_memory(item_id: str, payload: MemoryEdit, request: Request):
        brand, service = scope(request, True)
        mutate(lambda: service.store.edit(brand["id"], item_id, payload))
        return view(brand, service)

    @router.delete("/items/{item_id}")
    def retract_memory(item_id: str, payload: MemoryVersionRequest, request: Request):
        brand, service = scope(request, True)
        mutate(lambda: service.store.edit(brand["id"], item_id, payload, retract=True))
        return view(brand, service)

    @router.get("/revisions")
    def revisions(request: Request):
        brand, service = scope(request)
        return {"version": service.store.profile(brand["id"])["version"], "revisions": service.store.revisions(brand["id"])}

    @router.post("/rollback")
    def rollback(payload: MemoryRollback, request: Request):
        brand, service = scope(request, True)
        mutate(lambda: service.store.rollback(brand["id"], payload))
        return view(brand, service)

    @router.post("/retry")
    def retry(request: Request):
        brand, service = scope(request, True)
        with closing(service.store.connect()) as db, db:
            db.execute("UPDATE brand_memory_jobs SET state='pending',attempts=0,available_at=0,error=NULL WHERE brand_id=? AND state='failed' AND generation=(SELECT generation FROM brand_profiles WHERE brand_id=?)", (brand["id"], brand["id"]))
        service.notify()
        return view(brand, service)

    return router
