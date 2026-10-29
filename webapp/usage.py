"""Admin-only usage reporting and minimal, content-free model accounting."""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from webapp.auth.dependencies import require_admin

BEIJING = timezone(timedelta(hours=8))
METRICS = ("login_count", "copy_count", "publish_count", "publish_succeeded", "publish_failed",
           "request_count", "input_tokens", "output_tokens", "total_tokens", "unknown_usage_count")


def read_rows(path: Path, sql: str, params=()):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, params)]


class UsageStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(path, timeout=10)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS usage_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, provider TEXT NOT NULL,
                    model TEXT NOT NULL, feature TEXT NOT NULL, status TEXT NOT NULL,
                    input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
                    cached_input_tokens INTEGER, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS usage_date ON llm_usage(julianday(created_at));
                CREATE INDEX IF NOT EXISTS usage_user_date ON llm_usage(user_id, created_at);
            """)
            db.execute("INSERT OR IGNORE INTO usage_meta VALUES ('collection_started_at', ?)",
                       (datetime.now(timezone.utc).isoformat(),))
        path.chmod(0o600)

    def record(self, *, user_id, provider, model, feature, usage, status):
        usage = usage if isinstance(usage, dict) else {}

        def number(value):
            return value if type(value) is int and 0 <= value <= 2**63 - 1 else None

        input_tokens = number(usage.get("prompt_tokens", usage.get("input_tokens")))
        output_tokens = number(usage.get("completion_tokens", usage.get("output_tokens")))
        total_tokens = number(usage.get("total_tokens"))
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = number(input_tokens + output_tokens)
        details = usage.get("prompt_tokens_details") or {}
        cached = number(details.get("cached_tokens")) if isinstance(details, dict) else None
        if cached is None:
            cached = number(usage.get("prompt_cache_hit_tokens"))
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("""INSERT INTO llm_usage
                (id,user_id,provider,model,feature,status,input_tokens,output_tokens,total_tokens,cached_input_tokens,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                uuid4().hex, user_id, provider, model, feature, status,
                input_tokens, output_tokens, total_tokens, cached,
                datetime.now(timezone.utc).isoformat()))


def build_report(paths, auth_path, copy_path, usage_store, start, end, search, brand, page, page_size):
    lower = datetime.combine(start, time.min, BEIJING).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(end + timedelta(days=1), time.min, BEIJING).astimezone(timezone.utc).isoformat()
    bounds = (lower, upper)
    interval = "julianday(created_at) >= julianday(?) AND julianday(created_at) < julianday(?)"
    users = read_rows(auth_path, "SELECT id,username,display_name,brand_name,role,status,created_at,last_login_at FROM users ORDER BY created_at DESC,id")
    brands = sorted({u["brand_name"] for u in users if u["brand_name"]})
    users = [u for u in users if (not brand or u["brand_name"] == brand) and
             (not search or search.casefold() in (u["username"] + " " + u["display_name"]).casefold())]
    by_user = {u["id"]: dict(u, **dict.fromkeys(METRICS, 0)) for u in users}
    daily = {}
    for offset in range((end - start).days + 1):
        key = (start + timedelta(days=offset)).isoformat()
        daily[key] = dict(date=key, login_users=0, **dict.fromkeys(METRICS, 0))
    login_users = set()

    def add(user_id, day, values):
        if user_id not in by_user or day not in daily:
            return
        for key, value in values.items():
            by_user[user_id][key] += value
            daily[day][key] += value

    for row in read_rows(auth_path, f"""SELECT user_id,date(created_at,'+8 hours') AS day,COUNT(*) AS count
            FROM audit_logs WHERE action='login' AND {interval} GROUP BY user_id,day""", bounds):
        if row["user_id"] in by_user:
            login_users.add(row["user_id"])
            daily[row["day"]]["login_users"] += 1
            add(row["user_id"], row["day"], {"login_count": row["count"]})
    for row in read_rows(copy_path, f"""SELECT owner_id,date(created_at,'+8 hours') AS day,COUNT(*) AS count
            FROM copy_brand_generations WHERE {interval} GROUP BY owner_id,day""", bounds):
        add(row["owner_id"], row["day"], {"copy_count": row["count"]})

    warnings = []
    publish_statuses = {}
    for user_id in by_user:
        # Do not instantiate workspaces: that starts managers and can alter task state.
        path = paths.users / user_id / "runtime" / "state.json"
        if not path.exists():
            continue
        try:
            jobs = json.loads(path.read_text(encoding="utf-8"))["jobs"]
            if not isinstance(jobs, dict):
                raise ValueError("Invalid jobs")
            for job in jobs.values():
                if job.get("kind") != "publish":
                    continue
                timestamp = datetime.fromisoformat(job["created_at"])
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                day = timestamp.astimezone(BEIJING).date().isoformat()
                if day in daily:
                    status = str(job.get("status", "unknown"))
                    publish_statuses[status] = publish_statuses.get(status, 0) + 1
                values = {"publish_count": 1, "publish_succeeded": int(job.get("status") == "succeeded"),
                          "publish_failed": int(job.get("status") == "failed")}
                add(user_id, day, values)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            warnings.append(f"用户 {by_user[user_id]['username']} 的部分发布记录无法读取")

    token_groups = read_rows(usage_store.path, f"""SELECT user_id,date(created_at,'+8 hours') AS day,
        provider,model,feature,COUNT(*) AS request_count,
        COALESCE(SUM(input_tokens),0) AS input_tokens,COALESCE(SUM(output_tokens),0) AS output_tokens,
        COALESCE(SUM(total_tokens),0) AS total_tokens,
        SUM(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL OR total_tokens IS NULL THEN 1 ELSE 0 END) AS unknown_usage_count
        FROM llm_usage WHERE {interval} GROUP BY user_id,day,provider,model,feature""", bounds)
    breakdown = {}
    for row in token_groups:
        if row["user_id"] not in by_user:
            continue
        metrics = {key: row[key] for key in METRICS if key in row}
        add(row["user_id"], row["day"], metrics)
        key = (row["provider"], row["model"], row["feature"])
        item = breakdown.setdefault(key, dict(provider=key[0], model=key[1], feature=key[2],
                                              **dict.fromkeys(metrics, 0)))
        for name, value in metrics.items():
            item[name] += value
    summary = {key: sum(u[key] for u in by_user.values()) for key in METRICS}
    summary.update(user_count=len(users), enabled_users=sum(u["status"] == "active" for u in users),
                   login_users=len(login_users))
    rankings = {key: [dict(id=u["id"], name=u["display_name"] or u["username"], username=u["username"],
                           value=u[key], unknown_usage_count=u["unknown_usage_count"])
                     for u in sorted(by_user.values(), key=lambda u: (-u[key], u["username"]))[:10] if u[key] > 0]
                for key in ("login_count", "publish_count", "copy_count", "total_tokens")}
    return dict(summary=summary, daily=list(daily.values()), users=list(by_user.values())[(page-1)*page_size:page*page_size],
                total=len(users), page=page, page_size=page_size, brands=brands,
                rankings=rankings, publish_statuses=publish_statuses,
                token_breakdown=list(breakdown.values()), warnings=warnings,
                collection_started_at=read_rows(usage_store.path, "SELECT value FROM usage_meta WHERE key='collection_started_at'")[0]["value"],
                start_date=start.isoformat(), end_date=end.isoformat(), timezone="Asia/Shanghai")


def create_usage_router(paths, auth_store, copy_history, usage_store):
    router = APIRouter()

    @router.get("/api/admin/usage/requests")
    def requests(user_id: str = Query(min_length=32, max_length=32),
                 start_date: date = Query(), end_date: date = Query(),
                 page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
                 _=Depends(require_admin)):
        if start_date < date(1970, 1, 1) or end_date < start_date or (end_date-start_date).days >= 366 or end_date == date.max:
            raise HTTPException(status_code=422, detail="请选择不超过 366 天的有效日期范围")
        if not auth_store.get_user(user_id):
            raise HTTPException(status_code=404, detail="用户不存在")
        lower = datetime.combine(start_date, time.min, BEIJING).astimezone(timezone.utc).isoformat()
        upper = datetime.combine(end_date + timedelta(days=1), time.min, BEIJING).astimezone(timezone.utc).isoformat()
        where = "user_id=? AND julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?)"
        params = (user_id, lower, upper)
        try:
            rows = read_rows(usage_store.path, f"SELECT * FROM llm_usage WHERE {where} ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                             (*params, page_size, (page-1)*page_size))
            total = read_rows(usage_store.path, f"SELECT COUNT(*) AS count FROM llm_usage WHERE {where}", params)[0]["count"]
            return dict(items=rows, total=total, page=page)
        except sqlite3.Error:
            raise HTTPException(status_code=503, detail="用量明细暂时无法读取，请稍后重试")

    @router.get("/api/admin/usage")
    def usage(_=Depends(require_admin), start_date: date | None = None, end_date: date | None = None,
              search: str = Query(default="", max_length=100), brand: str = Query(default="", max_length=120),
              page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
        end = end_date or datetime.now(BEIJING).date()
        start = start_date or end - timedelta(days=29)
        if start < date(1970, 1, 1) or end < start or (end-start).days >= 366 or end == date.max:
            raise HTTPException(status_code=422, detail="请选择不超过 366 天的有效日期范围")
        try:
            return build_report(paths, auth_store.path, copy_history.path, usage_store,
                                start, end, search.strip(), brand, page, page_size)
        except (sqlite3.Error, OSError):
            logging.getLogger(__name__).error("Admin usage reporting unavailable")
            raise HTTPException(status_code=503, detail="使用统计暂时无法读取，请稍后重试")

    return router
