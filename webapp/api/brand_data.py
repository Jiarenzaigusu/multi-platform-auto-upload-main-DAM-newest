from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from webapp.auth.dependencies import require_admin, require_user
from webapp.auth.brands import normalize_brand_name
from webapp.auth.models import User
from webapp.auth.service import AuthenticationError, AuthService, UserNotFoundError
from webapp.mysql_demo import MySQLDatabase, MySQLDemoError


class BrandBindingRequest(BaseModel):
    brand_id: int | None = Field(default=None, gt=0)


def execute_brand_query(database: MySQLDatabase, query: str, parameters: tuple = ()) -> list[tuple]:
    if not database.configured:
        raise HTTPException(status_code=503, detail="请先配置 MySQL 连接")
    try:
        return database.execute(query, parameters)
    except MySQLDemoError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def list_data_brands(database: MySQLDatabase) -> list[dict]:
    rows = execute_brand_query(database, "SELECT id, name FROM brands ORDER BY name, id")
    return [{"id": int(row[0]), "name": str(row[1])} for row in rows]


def match_data_brand(brand_name: str, brands: list[dict]) -> dict | None:
    """Internal testing: grant data access only for one normalized name match."""
    _, key = normalize_brand_name(brand_name)
    if not key:
        return None
    matches = [brand for brand in brands if normalize_brand_name(brand["name"])[1] == key]
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="品牌名对应多个数据品牌，请管理员修正重复品牌名")
    return matches[0] if matches else None


def account_data_brand(database: MySQLDatabase, user: User) -> dict | None:
    """Keep saved brand IDs authoritative; initialize only accounts without a binding."""
    query = (
        "SELECT ub.brand_id, b.name FROM user_brand_bindings AS ub "
        "LEFT JOIN brands AS b ON b.id = ub.brand_id WHERE ub.user_id = %s"
    )
    rows = execute_brand_query(database, query, (user.id,))
    if not rows:
        brand = match_data_brand(user.brand_name, list_data_brands(database))
        if brand is None:
            return None
        # Never replace an existing binding, including one saved concurrently.
        execute_brand_query(
            database,
            "INSERT IGNORE INTO user_brand_bindings (user_id, brand_id) VALUES (%s, %s)",
            (user.id, brand["id"]),
        )
        rows = execute_brand_query(database, query, (user.id,))
        if not rows:
            raise HTTPException(status_code=503, detail="品牌绑定未保存，请重试")
    if rows[0][1] is None:
        raise HTTPException(status_code=403, detail="原绑定品牌不存在，请管理员确认，系统不会自动改绑")
    return {"id": int(rows[0][0]), "name": str(rows[0][1])}


def resolve_data_brand(database: MySQLDatabase, user: User) -> dict:
    brand = account_data_brand(database, user)
    if brand is None:
        raise HTTPException(status_code=403, detail="账户所属品牌未匹配到数据品牌，请核对账号所属品牌")
    return brand


def create_brand_data_router(database: MySQLDatabase, auth_service: AuthService) -> APIRouter:
    router = APIRouter(tags=["brand-data"])

    @router.get("/api/auth/brands")
    def registration_brands() -> dict:
        """Expose only the unambiguous brand catalog needed before registration."""
        if not database.configured:
            return {"configured": False, "brands": []}
        brands = list_data_brands(database)
        keys = [normalize_brand_name(brand["name"])[1] for brand in brands]
        counts = Counter(keys)
        return {
            "configured": True,
            "brands": [brand for brand, key in zip(brands, keys) if key and counts[key] == 1],
        }

    @router.get("/api/brand-access/me")
    def my_brand_access(request: Request) -> dict:
        user = require_user(request)
        if not database.configured:
            return {"configured": False, "brand": None}
        return {
            "configured": True,
            "brand": account_data_brand(database, user),
        }

    @router.get("/api/admin/brand-access")
    def brand_access(request: Request) -> dict:
        require_admin(request)
        if not database.configured:
            return {"configured": False, "brands": [], "bindings": {}}
        brands = list_data_brands(database)
        rows = execute_brand_query(database, "SELECT user_id, brand_id FROM user_brand_bindings")
        bindings = {row[0]: int(row[1]) for row in rows}
        for user in auth_service.list_users():
            if user.id in bindings:
                continue
            try:
                brand = match_data_brand(user.brand_name, brands)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                continue
            if brand:
                bindings[user.id] = brand["id"]
        return {
            "configured": True,
            "brands": brands,
            "bindings": bindings,
        }

    @router.put("/api/admin/users/{user_id}/brand-binding")
    def set_brand_binding(user_id: str, payload: BrandBindingRequest, request: Request) -> dict:
        """Explicit administrator action updates the saved binding and account label."""
        actor = require_admin(request)
        brands = list_data_brands(database)
        if auth_service.store.get_user(user_id) is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        brand = next((brand for brand in brands if brand["id"] == payload.brand_id), None)
        if payload.brand_id is not None and brand is None:
            raise HTTPException(status_code=404, detail="品牌不存在")
        try:
            user = auth_service.update_user(
                actor_user_id=actor.id, user_id=user_id,
                display_name=None, role=None, status=None,
                brand_name=brand["name"] if brand else "",
                ip_address=request.client.host if request.client else "",
            )
        except UserNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AuthenticationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if brand:
            execute_brand_query(
                database,
                "INSERT INTO user_brand_bindings (user_id, brand_id) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE brand_id = %s",
                (user_id, payload.brand_id, payload.brand_id),
            )
        else:
            execute_brand_query(database, "DELETE FROM user_brand_bindings WHERE user_id = %s", (user_id,))
        return {"user_id": user_id, "brand_id": payload.brand_id, "brand_name": user.brand_name, "brand_key": user.brand_key}

    return router
