"""Independent copy brands and adoption-based writing memory.

Legacy copy_profiles/copy_generations/copy_edits tables are intentionally retained:
their data-brand IDs must never be silently assigned to independent copy brands.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
import unicodedata
from uuid import uuid4

from webapp.ai_copy.contracts import GeneratedCopyDraft, GenerateCopyRequest, GenerateCopyResponse
from webapp.ai_copy.errors import LLMResponseError
from webapp.ai_copy.service import AiCopyService


class CopyHistoryConflict(ValueError):
    pass


class CopyBrandDuplicate(ValueError):
    def __init__(self, brand):
        self.brand = {"id": brand["id"], "name": brand["name"], "enabled": bool(brand["enabled"]), "version": brand["version"]}
        super().__init__("品牌已存在，请直接选择已有品牌" if self.brand["enabled"]
                         else "该品牌已停用，请联系管理员恢复后选择")


@dataclass(frozen=True)
class CopyBrandScope:
    brand_id: str
    brand_name: str
    actor_id: str
    can_moderate: bool = False


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


class BrandCopyHistory:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS copy_brands (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS copy_brand_profiles (
                    brand_id TEXT PRIMARY KEY REFERENCES copy_brands(id), version INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS copy_brand_generations (
                    id TEXT PRIMARY KEY, brand_id TEXT NOT NULL REFERENCES copy_brands(id), owner_id TEXT NOT NULL,
                    brief TEXT NOT NULL, original TEXT NOT NULL, titles TEXT NOT NULL, bodies TEXT NOT NULL,
                    candidate_briefs TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS studio_recent ON copy_brand_generations(brand_id,updated_at DESC);
                CREATE INDEX IF NOT EXISTS studio_usage_date ON copy_brand_generations(julianday(created_at));
                CREATE TABLE IF NOT EXISTS copy_brand_edits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id TEXT NOT NULL REFERENCES copy_brand_generations(id),
                    field TEXT NOT NULL, candidate_index INTEGER NOT NULL, before_text TEXT NOT NULL,
                    after_text TEXT NOT NULL, actor_id TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS copy_feedback (
                    id TEXT PRIMARY KEY, generation_id TEXT NOT NULL REFERENCES copy_brand_generations(id),
                    request_id TEXT NOT NULL, input TEXT NOT NULL, target TEXT NOT NULL,
                    title_index INTEGER NOT NULL, body_index INTEGER NOT NULL,
                    base_version INTEGER NOT NULL, version INTEGER NOT NULL, result TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(generation_id,request_id));
                CREATE TABLE IF NOT EXISTS copy_adoptions (
                    id TEXT PRIMARY KEY, brand_id TEXT NOT NULL REFERENCES copy_brands(id),
                    generation_id TEXT NOT NULL REFERENCES copy_brand_generations(id), actor_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, title_index INTEGER NOT NULL, body_index INTEGER NOT NULL,
                    initial_title TEXT NOT NULL, initial_body TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                    brief TEXT NOT NULL, feedback TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    analysis_status TEXT NOT NULL DEFAULT 'pending', analysis_token TEXT NOT NULL DEFAULT '',
                    analysis_started REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                    UNIQUE(generation_id,revision,title_index,body_index));
                CREATE INDEX IF NOT EXISTS studio_samples ON copy_adoptions(brand_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS copy_batch_feedback (
                    id TEXT PRIMARY KEY, generation_id TEXT NOT NULL REFERENCES copy_brand_generations(id),
                    request_id TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL,
                    version INTEGER NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(generation_id,request_id));
                CREATE TABLE IF NOT EXISTS copy_preferences (
                    id TEXT PRIMARY KEY, brand_id TEXT NOT NULL REFERENCES copy_brands(id),
                    adoption_id TEXT NOT NULL REFERENCES copy_adoptions(id), category TEXT NOT NULL,
                    scope TEXT NOT NULL, text TEXT NOT NULL, source_quote TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', conditions TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(adoption_id,category,scope,text));
                CREATE TABLE IF NOT EXISTS copy_preference_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, preference_id TEXT NOT NULL REFERENCES copy_preferences(id),
                    actor_id TEXT NOT NULL, before_state TEXT NOT NULL, after_state TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            # Forward-compatible additions; legacy data-brand tables stay untouched.
            for table, column, definition in (
                ("copy_preferences", "conditions", "TEXT NOT NULL DEFAULT '{}'"),
                ("copy_adoptions", "analysis_token", "TEXT NOT NULL DEFAULT ''"),
                ("copy_adoptions", "analysis_started", "REAL NOT NULL DEFAULT 0"),
                ("copy_adoptions", "source", "TEXT NOT NULL DEFAULT 'manual'"),
                ("copy_adoptions", "field_scope", "TEXT NOT NULL DEFAULT 'both'"),
                ("copy_adoptions", "platform", "TEXT NOT NULL DEFAULT ''"),
                ("copy_adoptions", "content_type", "TEXT NOT NULL DEFAULT ''"),
            ):
                columns = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def brands(self, actor_id, admin=False):
        # Every copy operator shares the enabled catalog; old membership rows are not ACLs.
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT * FROM copy_brands WHERE enabled=1 OR ? ORDER BY name,id", (admin,)
            ).fetchall()
            return [{**dict(r), "enabled": bool(r["enabled"])} for r in rows]

    @staticmethod
    def _brand_name(name):
        return " ".join(unicodedata.normalize("NFKC", name).split())

    def save_brand(self, actor_id, name, *, brand_id=None, version=0, enabled=True):
        normalized = self._brand_name(name)
        if not normalized or len(normalized) > 80:
            raise ValueError("品牌名称须为一至八十个字符")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if brand_id:
                row = db.execute("SELECT * FROM copy_brands WHERE id=?", (brand_id,)).fetchone()
                if not row:
                    raise LookupError("文案品牌不存在")
                if row["version"] != version:
                    raise CopyHistoryConflict("品牌配置已更新，请刷新")
            # Compare old names too, without merging or rewriting existing records.
            for existing in db.execute("SELECT * FROM copy_brands WHERE id != ?", (brand_id or "",)):
                if self._brand_name(existing["name"]).casefold() == normalized.casefold():
                    raise CopyBrandDuplicate(existing)
            try:
                if brand_id:
                    db.execute("UPDATE copy_brands SET name=?,normalized_name=?,enabled=?,version=version+1 WHERE id=?",
                               (normalized, normalized.casefold(), enabled, brand_id))
                else:
                    brand_id = "copy_" + uuid4().hex
                    db.execute("INSERT INTO copy_brands(id,name,normalized_name,enabled,created_by,created_at) VALUES(?,?,?,?,?,?)",
                               (brand_id, normalized, normalized.casefold(), enabled, actor_id, _now()))
                    db.execute("INSERT INTO copy_brand_profiles(brand_id) VALUES(?)", (brand_id,))
            except sqlite3.IntegrityError as exc:
                raise ValueError("文案品牌名称已存在，请刷新品牌列表后选择") from exc
        return next(b for b in self.brands(actor_id, True) if b["id"] == brand_id)

    def scope(self, actor_id, brand_id, admin=False):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM copy_brands WHERE id=? AND enabled=1", (brand_id,)).fetchone()
            if not row:
                raise PermissionError("文案品牌不存在或已停用，请重新选择")
            return CopyBrandScope(brand_id, row["name"], actor_id, admin)

    @staticmethod
    def _row(db, brand_id, generation_id):
        row = db.execute("SELECT * FROM copy_brand_generations WHERE brand_id=? AND id=?", (brand_id, generation_id)).fetchone()
        if row is None:
            raise LookupError("当前品牌没有这条文案记录")
        return row

    @staticmethod
    def _own(row, scope, version):
        if row["owner_id"] != scope.actor_id:
            raise PermissionError("品牌样本可共享，原稿只能由创建者修改或采用")
        if row["version"] != version:
            raise CopyHistoryConflict("文案已有新修改，请刷新记录后重试")

    @staticmethod
    def _touch(db, brand_id):
        db.execute("UPDATE copy_brand_profiles SET version=version+1 WHERE brand_id=?", (brand_id,))

    @staticmethod
    def learning_issue(field, text):
        try:
            draft = GeneratedCopyDraft(titles=[text] if field == "title" else ["参考"],
                                       bodies=[text] if field == "body" else ["仅用于检查样本的占位文案。"])
            AiCopyService._validate_draft_claims(draft)
        except (ValueError, LLMResponseError):
            return "含禁用数字、风险词或长度不符合要求，不能作为品牌样本"
        return None

    @staticmethod
    def _detail(row):
        original = json.loads(row["original"])
        titles, bodies = json.loads(row["titles"]), json.loads(row["bodies"])
        return {**original, "title": titles[0], "body": bodies[0], "titles": titles, "bodies": bodies,
                "generation_id": row["id"], "brand_id": row["brand_id"], "owner_id": row["owner_id"],
                "revision": row["version"], "brief": json.loads(row["brief"]),
                "candidate_briefs": json.loads(row["candidate_briefs"]),
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def save_generation(self, scope, request: GenerateCopyRequest, response: GenerateCopyResponse, profile_version):
        generation_id, now = uuid4().hex, _now()
        # Persist resolved product facts and writing conditions, never credentials or catalog handles.
        brief = request.model_dump(mode="json", exclude={"product_search", "selling_point_catalog_id", "copy_reference"})
        brief.update(title_max_chars=response.title_max_chars, body_max_chars=response.body_max_chars)
        original = response.model_dump(mode="json")
        original.update(brand_name=scope.brand_name, profile_version=profile_version)
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO copy_brand_generations(id,brand_id,owner_id,brief,original,titles,bodies,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (generation_id, scope.brand_id, scope.actor_id, _json(brief), _json(original), _json(response.titles), _json(response.bodies), now, now))
            return self._detail(self._row(db, scope.brand_id, generation_id))

    def detail(self, brand_id, generation_id):
        with closing(self.connect()) as db:
            detail = self._detail(self._row(db, brand_id, generation_id))
            detail["feedback"] = [dict(r) for r in db.execute(
                "SELECT input,target,title_index,body_index,version FROM copy_feedback WHERE generation_id=? ORDER BY version", (generation_id,))]
            return detail

    def history(self, brand_id, limit=20):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM copy_brand_generations WHERE brand_id=? ORDER BY updated_at DESC LIMIT ?", (brand_id, limit)).fetchall()
            return [self._detail(r) for r in rows]

    def edit(self, scope, generation_id, field, index, text, version):
        maximum = 200 if field == "title" else 2000
        text = text.strip()
        if field not in {"title", "body"} or not text or len(text) > maximum:
            raise ValueError("文案修改字段或长度不符合要求")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope.brand_id, generation_id)
            self._own(row, scope, version)
            column = "titles" if field == "title" else "bodies"
            values = json.loads(row[column])
            if not 0 <= index < len(values):
                raise ValueError("文案候选序号不存在")
            if values[index] != text:
                self._write_edit(db, row, scope.actor_id, field, index, values[index], text, version + 1)
                values[index] = text
                db.execute(f"UPDATE copy_brand_generations SET {column}=?,version=version+1,updated_at=? WHERE id=?", (_json(values), _now(), generation_id))
            return self._detail(self._row(db, scope.brand_id, generation_id))

    @staticmethod
    def _write_edit(db, row, actor_id, field, index, before, after, version):
        db.execute("INSERT INTO copy_brand_edits(generation_id,field,candidate_index,before_text,after_text,actor_id,version,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (row["id"], field, index, before, after, actor_id, version, _now()))

    def feedback_result(self, scope, generation_id, payload):
        with closing(self.connect()) as db:
            row = self._row(db, scope.brand_id, generation_id)
            if row["owner_id"] != scope.actor_id:
                raise PermissionError("只能修改自己的文案")
            saved = db.execute("SELECT * FROM copy_feedback WHERE generation_id=? AND request_id=?", (generation_id, payload.request_id)).fetchone()
            if saved:
                if (saved["input"], saved["target"], saved["title_index"], saved["body_index"], saved["base_version"]) != (
                    payload.message, payload.target, payload.title_index, payload.body_index, payload.version):
                    raise CopyHistoryConflict("请求标识已用于其他修改")
                return json.loads(saved["result"])
            self._own(row, scope, payload.version)
            return None

    def rewrite(self, scope, generation_id, payload, revised):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope.brand_id, generation_id)
            existing = db.execute("SELECT * FROM copy_feedback WHERE generation_id=? AND request_id=?", (generation_id, payload.request_id)).fetchone()
            if existing:
                if (existing["input"], existing["target"], existing["title_index"], existing["body_index"], existing["base_version"]) != (
                    payload.message, payload.target, payload.title_index, payload.body_index, payload.version):
                    raise CopyHistoryConflict("请求标识已用于其他修改")
                return json.loads(existing["result"])
            self._own(row, scope, payload.version)
            briefs = json.loads(row["candidate_briefs"])
            for field, column, index in (("title", "titles", payload.title_index), ("body", "bodies", payload.body_index)):
                values = json.loads(row[column])
                if not 0 <= index < len(values):
                    raise ValueError("文案候选序号不存在")
                if payload.target not in {field, "both"}:
                    continue
                text = revised[field]
                if values[index] != text:
                    self._write_edit(db, row, scope.actor_id, field, index, values[index], text, payload.version + 1)
                values[index] = text
                db.execute(f"UPDATE copy_brand_generations SET {column}=? WHERE id=?", (_json(values), generation_id))
                briefs[f"{field}:{index}"] = {f"{field}_max_chars": revised[f"{field}_max_chars"], "provider": revised.get("provider"), "model": revised.get("model"), "profile_version": revised.get("profile_version")}
            db.execute("UPDATE copy_brand_generations SET candidate_briefs=?,version=version+1,updated_at=? WHERE id=?", (_json(briefs), _now(), generation_id))
            result = self._detail(self._row(db, scope.brand_id, generation_id))
            db.execute("INSERT INTO copy_feedback VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (uuid4().hex, generation_id, payload.request_id, payload.message, payload.target, payload.title_index, payload.body_index,
                        payload.version, payload.version + 1, _json(result), _now()))
            return result

    def batch_feedback_result(self, scope, generation_id, payload):
        with closing(self.connect()) as db:
            row = self._row(db, scope.brand_id, generation_id)
            if row["owner_id"] != scope.actor_id:
                raise PermissionError("只能修改自己的文案")
            saved = db.execute("SELECT * FROM copy_batch_feedback WHERE generation_id=? AND request_id=?",
                               (generation_id, payload.request_id)).fetchone()
            if saved:
                if json.loads(saved["payload"]) != payload.model_dump():
                    raise CopyHistoryConflict("请求标识已用于其他修改")
                return json.loads(saved["result"])
            self._own(row, scope, payload.version)
            return None

    def rewrite_batch(self, scope, generation_id, payload, revised):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope.brand_id, generation_id)
            if row["owner_id"] != scope.actor_id:
                raise PermissionError("只能修改自己的文案")
            saved = db.execute("SELECT * FROM copy_batch_feedback WHERE generation_id=? AND request_id=?",
                               (generation_id, payload.request_id)).fetchone()
            if saved:
                if json.loads(saved["payload"]) != payload.model_dump():
                    raise CopyHistoryConflict("请求标识已用于其他修改")
                return json.loads(saved["result"])
            self._own(row, scope, payload.version)
            briefs = json.loads(row["candidate_briefs"])
            for field, column in (("title", "titles"), ("body", "bodies")):
                values = json.loads(row[column])
                expected = set(range(len(values))) if payload.target in {field, "both"} else set()
                items = revised[column]
                if len(items) != len(expected) or {item["index"] for item in items} != expected:
                    raise ValueError("批量改稿候选标识不完整或重复")
                for item in items:
                    index, text = item["index"], item["text"]
                    if values[index] != text:
                        self._write_edit(db, row, scope.actor_id, field, index, values[index], text, payload.version + 1)
                    values[index] = text
                    briefs[f"{field}:{index}"] = {
                        f"{field}_max_chars": item["reference_chars"], "provider": revised.get("provider"),
                        "model": revised.get("model"), "profile_version": revised.get("profile_version"),
                    }
                db.execute(f"UPDATE copy_brand_generations SET {column}=? WHERE id=?", (_json(values), generation_id))
            db.execute("UPDATE copy_brand_generations SET candidate_briefs=?,version=version+1,updated_at=? WHERE id=?",
                       (_json(briefs), _now(), generation_id))
            result = self._detail(self._row(db, scope.brand_id, generation_id))
            db.execute("INSERT INTO copy_batch_feedback VALUES(?,?,?,?,?,?,?)", (
                uuid4().hex, generation_id, payload.request_id, _json(payload.model_dump()),
                _json(result), payload.version + 1, _now()))
            return result

    def record_import(self, scope, generation_id, payload):
        fields = "title" if payload.platform == "jd" and payload.content_type == "video" else "both"
        return self.adopt(scope, generation_id, payload.version, payload.title_index,
                          payload.body_index if fields == "both" else -1,
                          source="workbench_import", field_scope=fields,
                          platform=payload.platform, content_type=payload.content_type,
                          imported_title=payload.title, imported_body=payload.body)

    def adopt(self, scope, generation_id, version, title_index, body_index, *, source="manual",
              field_scope="both", platform="", content_type="", imported_title=None, imported_body=None):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope.brand_id, generation_id)
            self._own(row, scope, version)
            titles, bodies = json.loads(row["titles"]), json.loads(row["bodies"])
            if not (0 <= title_index < len(titles) and (field_scope == "title" or 0 <= body_index < len(bodies))):
                raise ValueError("文案候选序号不存在")
            selected = {"title": titles[title_index]}
            if field_scope == "both":
                selected["body"] = bodies[body_index]
            if imported_title is not None and (imported_title != selected["title"]
                    or (field_scope == "both" and imported_body != selected["body"])
                    or (field_scope == "title" and imported_body)):
                raise CopyHistoryConflict("导入文本与当前候选不一致，未记录品牌样本")
            for field, text in selected.items():
                if issue := self.learning_issue(field, text):
                    raise ValueError(issue)
            saved = db.execute("SELECT * FROM copy_adoptions WHERE generation_id=? AND revision=? AND title_index=? AND body_index=?",
                               (generation_id, version, title_index, body_index)).fetchone()
            if saved:
                # A repeated implicit event must not undo a deliberate withdrawal.
                if not saved["enabled"] and source == "manual":
                    db.execute("UPDATE copy_adoptions SET enabled=1 WHERE id=?", (saved["id"],))
                    self._touch(db, scope.brand_id)
                    saved = db.execute("SELECT * FROM copy_adoptions WHERE id=?", (saved["id"],)).fetchone()
                return dict(saved)
            original = json.loads(row["original"])
            feedback = []
            for f in db.execute("SELECT input,target,title_index,body_index,version FROM copy_feedback WHERE generation_id=? AND version<=? ORDER BY version", (generation_id, version)):
                applies = [field for field, index in (("title", title_index), ("body", body_index))
                           if field in selected and f["target"] in {field, "both"} and f[field + "_index"] == index]
                if applies:
                    feedback.append({**dict(f), "applies_to": applies})
            for f in db.execute("SELECT payload,version FROM copy_batch_feedback WHERE generation_id=? AND version<=? ORDER BY version",
                                (generation_id, version)):
                batch = json.loads(f["payload"])
                applies = [field for field in selected if batch["target"] in {field, "both"}]
                if applies:
                    feedback.append({"input": batch["message"], "target": batch["target"],
                                     "version": f["version"], "applies_to": applies})
            feedback.sort(key=lambda f: f["version"])
            brief = {"initial": json.loads(row["brief"]), "current": {k: v for k, v in json.loads(row["candidate_briefs"]).items() if k in {f"title:{title_index}", f"body:{body_index}"}},
                     "provider": original["provider"], "model": original["model"], "profile_version": original.get("profile_version", 0)}
            adoption_id = uuid4().hex
            unchanged = (selected["title"] == original["titles"][title_index]
                         and ("body" not in selected or selected["body"] == original["bodies"][body_index]))
            db.execute("INSERT INTO copy_adoptions(id,brand_id,generation_id,actor_id,revision,title_index,body_index,initial_title,initial_body,title,body,brief,feedback,analysis_status,created_at,source,field_scope,platform,content_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (adoption_id, scope.brand_id, generation_id, scope.actor_id, version, title_index, body_index,
                        original["titles"][title_index], original["bodies"][body_index] if "body" in selected else "",
                        selected["title"], selected.get("body", ""), _json(brief), _json(feedback),
                        "complete" if unchanged and not feedback else "pending", _now(), source, field_scope, platform, content_type))
            self._touch(db, scope.brand_id)
            return dict(db.execute("SELECT * FROM copy_adoptions WHERE id=?", (adoption_id,)).fetchone())

    def adoption(self, scope, adoption_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM copy_adoptions WHERE brand_id=? AND id=?", (scope.brand_id, adoption_id)).fetchone()
            if not row:
                raise LookupError("品牌样本不存在")
            return dict(row)

    def claim_analysis(self, scope, adoption_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM copy_adoptions WHERE brand_id=? AND id=?", (scope.brand_id, adoption_id)).fetchone()
            if not row:
                raise LookupError("品牌样本不存在")
            if row["actor_id"] != scope.actor_id and not scope.can_moderate:
                raise PermissionError("只能分析自己采用的样本")
            if not row["enabled"]:
                raise ValueError("样本已撤回")
            if row["analysis_status"] == "complete" or (row["analysis_status"] == "running" and row["analysis_started"] > time.time() - 300):
                return dict(row), False
            db.execute("UPDATE copy_adoptions SET analysis_status='running',analysis_token=?,analysis_started=? WHERE id=?",
                       (uuid4().hex, time.time(), adoption_id))
            return dict(db.execute("SELECT * FROM copy_adoptions WHERE id=?", (adoption_id,)).fetchone()), True

    def analysis_result(self, scope, adoption_id, candidates, failed=False, token=None):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM copy_adoptions WHERE brand_id=? AND id=?", (scope.brand_id, adoption_id)).fetchone()
            if not row:
                raise LookupError("品牌样本不存在")
            if row["actor_id"] != scope.actor_id and not scope.can_moderate:
                raise PermissionError("只能分析自己采用的样本")
            if row["analysis_status"] != "complete" and (token is None or token == row["analysis_token"]):
                for c in candidates if row["enabled"] else []:
                    if row["field_scope"] == "title" and c["scope"] != "title":
                        continue
                    initial = json.loads(row["brief"])["initial"]
                    conditions = {k: initial.get(k) for k in ("scene", "style", "custom_scene", "custom_style")}
                    db.execute("INSERT OR IGNORE INTO copy_preferences(id,brand_id,adoption_id,category,scope,text,source_quote,status,conditions,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                               (uuid4().hex, scope.brand_id, adoption_id, c["category"], c["scope"], c["text"], c["source_quote"], "pending", _json(conditions), _now()))
                db.execute("UPDATE copy_adoptions SET analysis_status=? WHERE id=?", ("failed" if failed else "complete", adoption_id))
                self._touch(db, scope.brand_id)
            return dict(db.execute("SELECT * FROM copy_adoptions WHERE id=?", (adoption_id,)).fetchone())

    def preference(self, scope, preference_id, status, version, text=None, scope_mode=None):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT version FROM copy_brand_profiles WHERE brand_id=?", (scope.brand_id,)).fetchone()[0] != version:
                raise CopyHistoryConflict("品牌画像已更新，请刷新后重试")
            row = db.execute("SELECT * FROM copy_preferences WHERE brand_id=? AND id=?", (scope.brand_id, preference_id)).fetchone()
            if not row:
                raise LookupError("品牌偏好不存在")
            next_text = text.strip() if text is not None else row["text"]
            if not next_text:
                raise ValueError("偏好不能为空")
            conditions = json.loads(row["conditions"])
            if scope_mode == "brand":
                conditions = {}
            elif scope_mode == "source":
                source = db.execute("SELECT brief FROM copy_adoptions WHERE id=?", (row["adoption_id"],)).fetchone()
                initial = json.loads(source[0])["initial"]
                conditions = {k: initial.get(k) for k in ("scene", "style", "custom_scene", "custom_style")}
            if row["status"] == status and next_text == row["text"] and conditions == json.loads(row["conditions"]):
                return
            if status == "active":
                if not db.execute("SELECT 1 FROM copy_adoptions WHERE id=? AND enabled=1", (row["adoption_id"],)).fetchone():
                    raise ValueError("来源样本已撤回，不能启用该偏好")
                conflicts = db.execute("SELECT * FROM copy_preferences WHERE brand_id=? AND status='active' AND category=? AND (scope=? OR scope='both' OR ?='both') AND id!=?",
                                       (scope.brand_id, row["category"], row["scope"], row["scope"], preference_id)).fetchall()
                duplicate = next((r for r in conflicts if r["scope"] == row["scope"] and r["text"] == next_text and json.loads(r["conditions"]) == conditions), None)
                if duplicate:
                    db.execute("UPDATE copy_preferences SET status='merged' WHERE id=?", (preference_id,))
                    db.execute("INSERT INTO copy_preference_events(preference_id,actor_id,before_state,after_state,created_at) VALUES(?,?,?,?,?)",
                               (preference_id, scope.actor_id, _json(dict(row)), _json({"status": "merged", "into": duplicate["id"]}), _now()))
                    self._touch(db, scope.brand_id)
                    return
                def overlaps(other):
                    other = json.loads(other["conditions"])
                    return all(k not in other or k not in conditions or other[k] == conditions[k]
                               for k in other.keys() | conditions.keys())
                if any(r["text"] != next_text and overlaps(r) for r in conflicts):
                    raise CopyHistoryConflict("相同范围已有同类偏好，请先检查并停用被替代的规则")
                active_count = db.execute("SELECT COUNT(*) FROM copy_preferences WHERE brand_id=? AND status='active' AND id!=?", (scope.brand_id, preference_id)).fetchone()[0]
                if active_count >= 24:
                    raise ValueError("生效偏好已达到二十四条，请先合并或停用旧规则")
            db.execute("UPDATE copy_preferences SET status=?,text=?,conditions=? WHERE id=?", (status, next_text, _json(conditions), preference_id))
            db.execute("INSERT INTO copy_preference_events(preference_id,actor_id,before_state,after_state,created_at) VALUES(?,?,?,?,?)",
                       (preference_id, scope.actor_id, _json(dict(row)), _json({"status": status, "text": next_text, "conditions": conditions}), _now()))
            self._touch(db, scope.brand_id)

    def sample_enabled(self, scope, adoption_id, enabled, version):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM copy_adoptions WHERE brand_id=? AND id=?", (scope.brand_id, adoption_id)).fetchone()
            if not row:
                raise LookupError("品牌样本不存在")
            if row["actor_id"] != scope.actor_id and not scope.can_moderate:
                raise PermissionError("只能维护自己采用的样本")
            if db.execute("SELECT version FROM copy_brand_profiles WHERE brand_id=?", (scope.brand_id,)).fetchone()[0] != version:
                raise CopyHistoryConflict("品牌画像已更新，请刷新后重试")
            if bool(row["enabled"]) == enabled:
                return
            db.execute("UPDATE copy_adoptions SET enabled=? WHERE id=?", (enabled, adoption_id))
            if not enabled:
                for preference in db.execute("SELECT * FROM copy_preferences WHERE adoption_id=? AND status IN ('pending','active')", (adoption_id,)).fetchall():
                    db.execute("INSERT INTO copy_preference_events(preference_id,actor_id,before_state,after_state,created_at) VALUES(?,?,?,?,?)",
                               (preference["id"], scope.actor_id, _json(dict(preference)), _json({"status": "disabled", "reason": "source_withdrawn"}), _now()))
                db.execute("UPDATE copy_preferences SET status='disabled' WHERE adoption_id=? AND status IN ('pending','active')", (adoption_id,))
            self._touch(db, scope.brand_id)

    def profile(self, brand_id, request=None):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            version = db.execute("SELECT version FROM copy_brand_profiles WHERE brand_id=?", (brand_id,)).fetchone()
            samples = [dict(r) for r in db.execute("SELECT * FROM copy_adoptions WHERE brand_id=? ORDER BY created_at DESC LIMIT 100", (brand_id,))]
            preferences = [dict(r) for r in db.execute("SELECT * FROM copy_preferences WHERE brand_id=? ORDER BY created_at DESC", (brand_id,))]
            total = db.execute("SELECT COUNT(*) FROM copy_adoptions WHERE brand_id=? AND enabled=1", (brand_id,)).fetchone()[0]
        examples = [s for s in samples if s["enabled"]]
        if request:
            current = request if isinstance(request, dict) else request.model_dump(mode="json")
            examples.sort(key=lambda s: sum(bool(current.get(k)) and current[k] == json.loads(s["brief"])["initial"].get(k)
                                            for k in ("style", "scene", "custom_style", "custom_scene")), reverse=True)
        for p in preferences:
            p["conditions"] = json.loads(p["conditions"])
        applicable = [p for p in preferences if not request or all(current.get(k) == v for k, v in p["conditions"].items())]
        return {"context_preferences": applicable, "brand_id": brand_id, "version": version[0] if version else 0, "sample_count": total,
                "preferences": preferences, "samples": samples[:20], "examples": examples[:3]}

    @staticmethod
    def generation_context(profile):
        # Only confirmed rules and explicitly adopted final text reach generation.
        return {"guidance": [{"scope": p["scope"], "text": p["text"], "source_quote": p["source_quote"]}
                             for p in profile["context_preferences"] if p["status"] == "active"],
                "examples": [{"title": s["title"], **({"body": s["body"]} if s.get("field_scope", "both") == "both" else {})}
                             for s in profile["examples"]]}
