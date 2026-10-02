from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from webapp.auth.dependencies import require_admin, require_user
from webapp.auth.service import AuthService
from webapp.mysql_demo import MySQLDatabase, MySQLDemoError


class BrandBindingRequest(BaseModel):
    brand_id: int | None = Field(default=None, gt=0)


def create_brand_data_router(database: MySQLDatabase, auth_service: AuthService) -> APIRouter:
    router = APIRouter(tags=["brand-data"])

    def execute(query: str, parameters: tuple = ()) -> list[tuple]:
        try:
            return database.execute(query, parameters)
        except MySQLDemoError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def require_database() -> None:
        if not database.configured:
            raise HTTPException(status_code=503, detail="请先配置 MySQL 连接")

    @router.get("/api/brand-access/me")
    def my_brand_access(request: Request) -> dict:
        user = require_user(request)
        if not database.configured:
            return {"configured": False, "brand": None}
        rows = execute(
            "SELECT b.id, b.name FROM user_brand_bindings AS ub "
            "JOIN brands AS b ON b.id = ub.brand_id WHERE ub.user_id = %s",
            (user.id,),
        )
        return {
            "configured": True,
            "brand": {"id": rows[0][0], "name": rows[0][1]} if rows else None,
        }

    @router.get("/api/admin/brand-access")
    def brand_access(request: Request) -> dict:
        require_admin(request)
        if not database.configured:
            return {"configured": False, "brands": [], "bindings": {}}
        brands = execute("SELECT id, name FROM brands ORDER BY name, id")
        bindings = execute("SELECT user_id, brand_id FROM user_brand_bindings")
        return {
            "configured": True,
            "brands": [{"id": row[0], "name": row[1]} for row in brands],
            "bindings": {row[0]: row[1] for row in bindings},
        }

    @router.put("/api/admin/users/{user_id}/brand-binding")
    def set_brand_binding(user_id: str, payload: BrandBindingRequest, request: Request) -> dict:
        require_admin(request)
        require_database()
        if auth_service.store.get_user(user_id) is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if payload.brand_id is None:
            execute("DELETE FROM user_brand_bindings WHERE user_id = %s", (user_id,))
            return {"user_id": user_id, "brand_id": None}
        brand = execute("SELECT id FROM brands WHERE id = %s", (payload.brand_id,))
        if not brand:
            raise HTTPException(status_code=404, detail="品牌不存在")
        execute(
            "INSERT INTO user_brand_bindings (user_id, brand_id) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE brand_id = %s",
            (user_id, payload.brand_id, payload.brand_id),
        )
        return {"user_id": user_id, "brand_id": payload.brand_id}

    return router
