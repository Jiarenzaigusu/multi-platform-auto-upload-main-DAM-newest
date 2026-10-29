from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.files import cleanup_old_files
from webapp.ai_copy.contracts import ProductReference
from webapp.ai_copy.errors import ProductLookupError
from webapp.api.models import PublishRequest
from webapp.api.store import TERMINAL_STATUSES, JobStore, job_queue_order, utc_now
from webapp.api.tasks import RuntimeInstanceLock
from webapp.workspaces.paths import UserDataPaths
from webapp.execution_context import AgentTargetError, verified_agent_id, verified_agent_binding

_UPLOAD_DIRECTORY_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ASSET_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class AgentTaskManager:
    """Persist browser work for an authenticated agent running on the user's PC."""

    remote_execution = True
    browser_runtime = None

    def __init__(
        self,
        store: JobStore,
        *,
        user_id: str,
        paths: UserDataPaths,
        max_workers: int = 1,
        browser_slots=None,
        browser_idle_timeout_seconds: float = 0,
        lease_seconds: int = 45,
        **_unused,
    ) -> None:
        del max_workers, browser_slots, browser_idle_timeout_seconds
        self.store = store
        self.user_id = user_id
        self.paths = paths
        self.managed_upload_root = paths.uploads
        self.job_log_dir = paths.job_logs
        self.lease_seconds = max(30, lease_seconds)
        self._guard = threading.RLock()
        self._job_waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        self._agents: dict[str, dict[str, Any]] = {}
        # 被判离线的代理先暂存而不是直接丢弃。请求本身携带有效设备令牌就足以
        # 证明它还活着（续约晚了往往只是被长任务阻塞），此时可以直接恢复在线，
        # 避免把健康任务误判成失联。
        self._dropped_agents: dict[str, dict[str, Any]] = {}
        self._local_upload_tickets: dict[str, dict[str, Any]] = {}
        self._local_assets: dict[str, dict[str, Any]] = {}
        self._identity_challenges: dict[str, dict[str, Any]] = {}
        self._identity_proofs: dict[str, dict[str, Any]] = {}
        self._known_device_bindings: dict[str, dict[str, Any]] = {}
        self._maintenance_errors: list[str] = []
        self._started = False
        self._closed = False
        self._instance_lock = RuntimeInstanceLock(self.store.data_dir / ".task-manager.lock")

    @property
    def ready(self) -> bool:
        with self._guard:
            return self._started and not self._closed

    @property
    def maintenance_errors(self) -> tuple[str, ...]:
        with self._guard:
            return tuple(self._maintenance_errors)

    def record_maintenance_error(self, error: str) -> None:
        with self._guard:
            if error not in self._maintenance_errors:
                self._maintenance_errors.append(error)

    def start(self) -> None:
        with self._guard:
            if self._started:
                return
            if self._closed:
                raise RuntimeError("本地代理任务管理器已经关闭")
            self._instance_lock.acquire()
            try:
                jobs = self.store.list_jobs(limit=None)
                for job in jobs:
                    if job["status"] in TERMINAL_STATUSES:
                        self._cleanup_managed_upload_safely(job)
                    elif job["status"] in {"running", "cancelling"} and not job.get(
                        "agent_id"
                    ):
                        status = (
                            "cancelled"
                            if job["status"] == "cancelling"
                            else "uncertain"
                            if job["kind"] == "publish"
                            else "failed"
                        )
                        self.store.update_job(
                            job["id"],
                            status=status,
                            message="升级为本地代理执行时收敛了旧的云端运行任务，请人工核对",
                            error="旧任务没有本地代理租约",
                            finished_at=utc_now(),
                        )
                        self._cleanup_managed_upload_safely(job)
                for pruned_job in self.store.prune_terminal_jobs():
                    self.delete_job_artifacts(pruned_job["id"])
                self._cleanup_orphaned_uploads(self.store.list_jobs(limit=None))
                cleanup_old_files(
                    self.paths.media,
                    older_than_days=1,
                    suffixes={".upload"},
                )
                self._started = True
            except Exception:
                self._instance_lock.release()
                raise
        self.reap_expired_jobs()

    def require_target(self, agent_id: str | None = None) -> str:
        selected = agent_id or verified_agent_id.get()
        with self._guard:
            self._drop_offline_agents_locked(time.monotonic())
            if not selected or selected not in self._agents:
                raise AgentTargetError("无法确认目标本机助手，请更新并启动助手，在当前电脑重新验证连接")
            binding = verified_agent_binding.get()
            if binding and self._agents[selected].get("binding_id") != binding:
                raise AgentTargetError("助手配对已变化，请在当前电脑重新验证后提交")
        return selected

    def note_authenticated_device(self, device) -> None:
        """Use server-validated device metadata when renewing after a restart."""
        with self._guard:
            self._known_device_bindings[device.agent_id] = {
                "binding_id": device.created_at, "device_name": device.device_name,
                "system": device.system, "version": device.version,
            }

    def _target_binding(self, agent_id: str) -> str:
        return verified_agent_binding.get() or self._agents[agent_id]["binding_id"]

    def issue_identity_challenge(self, *, origin: str) -> dict:
        status = self.agent_status()
        agents = status["agents"]
        if len(agents) != 1:
            raise AgentTargetError("无法确定目标助手，请先连接当前电脑的助手")
        with self._guard:
            now = time.time()
            self._identity_challenges = {key: value for key, value in self._identity_challenges.items() if value["expires_at"] > now}
            self._identity_proofs = {key: value for key, value in self._identity_proofs.items() if value["expires_at"] > now}
            if len(self._identity_challenges) >= 128:
                raise AgentTargetError("本机验证请求过多，请稍后重试")
            ticket = secrets.token_urlsafe(32)
            self._identity_challenges[ticket] = {
                "agent_id": agents[0]["agent_id"], "origin": origin.rstrip("/"), "expires_at": now + 60,
                "binding_id": agents[0]["binding_id"],
            }
        return {"ticket": ticket, "verify_url": "http://127.0.0.1:48765/v1/identity"}

    def confirm_identity_challenge(self, *, ticket: str, agent_id: str, origin: str) -> dict:
        with self._guard:
            record = self._identity_challenges.get(ticket)
            if not record or record["expires_at"] <= time.time():
                raise AgentTargetError("本机验证票据不存在或已过期")
            if record["agent_id"] != agent_id or record["origin"] != origin.rstrip("/"):
                raise PermissionError("本机助手与网页当前用户、服务或目标设备不匹配")
            self.require_target(agent_id)
            if self._agents[agent_id]["binding_id"] != record["binding_id"]:
                raise AgentTargetError("助手配对已变化，请重新验证")
            self._identity_challenges.pop(ticket)
            proof = secrets.token_urlsafe(32)
            self._identity_proofs[proof] = {**record, "expires_at": time.time() + 60}
            return {"agent_id": agent_id, "proof": proof}

    def verify_identity_proof(self, proof: str, *, origin: str, include_binding: bool = False):
        with self._guard:
            record = self._identity_proofs.get(proof)
            if not record or record["expires_at"] <= time.time() or record["origin"] != origin.rstrip("/"):
                raise AgentTargetError("本机助手验证已失效，请重新验证后再提交")
            selected = self.require_target(record["agent_id"])
            if self._agents[selected]["binding_id"] != record["binding_id"]:
                raise AgentTargetError("助手配对已变化，请重新验证")
            return (selected, record["binding_id"]) if include_binding else selected

    def resume_account(self, platform: str, account: str) -> None:
        self.require_target()
        self.store.resume_account(platform, account)
        self._notify_job_available()

    def submit_account_task(
        self, *, kind: str, platform: str, account: str, headed: bool = True,
        target_agent_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"login", "check", "delete_account"}:
            raise ValueError(f"本地代理不支持账号任务：{kind}")
        self.start()
        target_agent_id = self.require_target(target_agent_id)
        job = self.store.create_job(
            kind=kind,
            platform=platform,
            account=account,
            payload={"headed": headed, "target_agent_id": target_agent_id,
                     "target_binding_id": self._target_binding(target_agent_id)},
            message="任务正在等待用户电脑上的本地执行代理领取",
        )
        self._notify_job_available()
        return job

    def submit_publish_task(
        self,
        request: PublishRequest,
        *,
        batch_id: str | None = None,
        source_row: int | None = None,
        local_assets: dict[str, Any] | None = None,
        target_agent_id: str | None = None,
    ) -> dict[str, Any]:
        return self.submit_publish_tasks(
            [(request, source_row)], batch_id=batch_id, local_assets=local_assets,
            target_agent_id=target_agent_id,
        )[0]

    def submit_publish_tasks(
        self,
        requests: list[tuple[PublishRequest, int | None] | tuple[PublishRequest, int | None, Path | None]],
        *,
        batch_id: str | None = None,
        local_assets: dict[str, Any] | None = None,
        target_agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not requests:
            return []
        self.start()
        asset_target = self._local_asset_agent_id(local_assets) if local_assets else None
        requested_target = target_agent_id or verified_agent_id.get()
        if asset_target and requested_target and asset_target != requested_target:
            raise AgentTargetError("本机素材与目标助手不匹配，请在同一台电脑重新选择素材")
        target_agent_id = self.require_target(requested_target or asset_target)
        definitions: list[dict[str, Any]] = []
        ordered_requests = (
            sorted(
                requests,
                key=lambda item: (
                    item[1] is None,
                    item[1] if item[1] is not None else 0,
                ),
            )
            if batch_id
            else requests
        )
        for item in ordered_requests:
            request, source_row, image_folder_path = (
                (*item, None) if len(item) == 2 else item
            )
            payload = asdict(request)
            payload["target_agent_id"] = target_agent_id
            payload["target_binding_id"] = self._target_binding(target_agent_id)
            payload["video_path"] = str(request.video_path) if request.video_path else None
            payload["image_paths"] = [str(path) for path in request.image_paths]
            payload["image_folder_path"] = (
                str(image_folder_path) if image_folder_path else None
            )
            payload["cover_image_path"] = (
                str(request.cover_image_path) if request.cover_image_path else None
            )
            # Batch image folders carry absolute paths that must be resolved on
            # the paired desktop agent; never make the agent try to download them.
            if image_folder_path:
                payload["managed_upload"] = False
            payload["schedule"] = request.schedule.isoformat() if request.schedule else None
            payload["tags"] = list(request.tags)
            if local_assets:
                payload["video_path"] = None
                payload["image_paths"] = []
                payload["cover_image_path"] = None
                payload["local_assets"] = dict(local_assets)
                payload["target_agent_id"] = target_agent_id
                payload["managed_upload"] = False
            definitions.append(
                {
                    "kind": "publish",
                    "platform": request.platform,
                    "account": request.account,
                    "payload": payload,
                    "batch_id": batch_id,
                    "source_row": source_row,
                    "message": "任务正在等待用户电脑上的本地执行代理领取",
                }
            )
        jobs = self.store.create_jobs(definitions)
        self._notify_job_available()
        return jobs

    def _local_asset_agent_id(self, local_assets: dict[str, Any]) -> str:
        """Derive ownership from verified server records, never caller metadata."""
        assets = [local_assets.get("video"), local_assets.get("cover")]
        assets.extend(local_assets.get("images") or [])
        agent_ids: set[str] = set()
        with self._guard:
            self._drop_expired_local_uploads_locked(time.time())
            for asset in assets:
                if asset is None:
                    continue
                if not isinstance(asset, dict):
                    raise ValueError("本机素材信息无效")
                record = self._local_assets.get(asset.get("asset_id"))
                if not record or not record.get("completed"):
                    raise ValueError("本机素材不存在或已过期，请重新上传")
                if record["user_id"] != self.user_id:
                    raise ValueError("本机素材不属于当前用户")
                agent_ids.add(record["agent_id"])
        if len(agent_ids) != 1:
            raise ValueError("本机素材必须属于同一台本地执行助手")
        return next(iter(agent_ids))

    def retry_failed_batch(self, batch_id: str, *, new_batch_id: str) -> list[dict[str, Any]]:
        """Clone failed workbook rows while retaining their local PC paths."""
        self.start()
        failed = sorted(
            (
                job
                for job in self.store.list_jobs(limit=None)
                if job.get("batch_id") == batch_id
                and job.get("kind") == "publish"
                and job.get("status") == "failed"
            ),
            key=lambda job: (job.get("source_row") or 0, job["id"]),
        )
        if not failed:
            return []
        selected = self.require_target()
        if any(job["payload"].get("target_agent_id") != selected or
               job["payload"].get("target_binding_id") != self._target_binding(selected) for job in failed):
            raise AgentTargetError("失败任务与本机助手不匹配，不能转移到其他电脑重试")
        jobs = self.store.create_jobs(
            [
                {
                    "kind": "publish",
                    "platform": job["platform"],
                    "account": job["account"],
                    "payload": job["payload"],
                    "batch_id": new_batch_id,
                    "source_row": job.get("source_row"),
                    "retry_of": job["id"],
                    "message": "失败任务已重新排队，等待用户电脑上的本地执行代理领取",
                }
                for job in failed
            ]
        )
        self._notify_job_available()
        return jobs

    def issue_local_upload_ticket(
        self,
        *,
        agent_id: str,
        origin: str,
        filename: str,
        size: int,
        kind: str,
        max_size: int,
    ) -> dict[str, Any]:
        """Create a short-lived browser-to-Agent upload ticket."""
        if kind not in {"video", "cover", "article-image"}:
            raise ValueError("素材类型不受支持")
        if not origin or len(origin) > 512:
            raise ValueError("浏览器来源无效")
        if not isinstance(size, int) or size <= 0 or size > max_size:
            raise ValueError("素材大小超过允许范围")
        clean_name = Path(filename or "").name
        if not clean_name or clean_name in {".", ".."}:
            raise ValueError("素材文件名无效")
        suffix = Path(clean_name).suffix.lower()
        allowed = {
            "video": {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"},
            "cover": {".jpg", ".jpeg", ".png", ".webp"},
            "article-image": {".jpg", ".jpeg", ".png", ".webp"},
        }[kind]
        if suffix not in allowed:
            raise ValueError("素材格式不受支持")
        now = time.time()
        with self._guard:
            self._drop_expired_local_uploads_locked(now)
            agent = self._agents.get(agent_id)
            if not agent:
                raise ValueError("本地执行助手未在线")
            ticket = secrets.token_urlsafe(32)
            asset_id = secrets.token_hex(16)
            record = {
                "ticket": ticket,
                "asset_id": asset_id,
                "agent_id": agent_id,
                "user_id": self.user_id,
                "origin": origin.rstrip("/"),
                "filename": clean_name,
                "size": size,
                "kind": kind,
                "expires_at": now + 10 * 60,
                "reserved": False,
                "completed": False,
                "binding_id": agent["binding_id"],
            }
            self._local_upload_tickets[ticket] = record
        return {
            "ticket": ticket,
            "asset_id": asset_id,
            "filename": clean_name,
            "size": size,
            "kind": kind,
            "expires_at": datetime.fromtimestamp(record["expires_at"], timezone.utc).isoformat(),
            "upload_url": "http://127.0.0.1:48765/v1/upload",
        }

    def _drop_expired_local_uploads_locked(self, now: float) -> None:
        for ticket, record in tuple(self._local_upload_tickets.items()):
            expires_at = (
                record.get("completed_at", 0) + 2 * 60 * 60
                if record.get("completed")
                else record["expires_at"]
            )
            if expires_at <= now:
                self._local_upload_tickets.pop(ticket, None)
                self._local_assets.pop(record["asset_id"], None)

    def authorize_local_upload(
        self, *, ticket: str, agent_id: str, origin: str, reserve: bool
    ) -> dict[str, Any]:
        with self._guard:
            self._drop_expired_local_uploads_locked(time.time())
            record = self._local_upload_tickets.get(ticket)
            if not record:
                raise KeyError("上传票据不存在或已过期")
            if record["agent_id"] != agent_id:
                raise PermissionError("上传票据与设备不匹配")
            if self._agents.get(agent_id, {}).get("binding_id") != record.get("binding_id"):
                raise PermissionError("上传票据所属配对已变化，请重新上传")
            if record["origin"] != origin.rstrip("/"):
                raise PermissionError("上传来源不匹配")
            if record["completed"] or (reserve and record["reserved"]):
                raise ValueError("上传票据已经使用")
            if reserve:
                record["reserved"] = True
            return dict(record)

    def complete_local_upload(
        self,
        *,
        ticket: str,
        agent_id: str,
        origin: str,
        sha256: str,
        size: int,
    ) -> dict[str, Any]:
        with self._guard:
            checked = self.authorize_local_upload(
                ticket=ticket, agent_id=agent_id, origin=origin, reserve=False
            )
            if not checked["reserved"]:
                raise ValueError("上传尚未授权")
            if size != checked["size"] or not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ValueError("上传素材校验失败")
            record = self._local_upload_tickets[ticket]
            record["completed"] = True
            record["sha256"] = sha256
            record["completed_at"] = time.time()
            self._local_assets[record["asset_id"]] = dict(record)
            return dict(record)

    def get_local_asset(self, asset_id: str, *, agent_id: str) -> dict[str, Any]:
        if not _ASSET_ID_PATTERN.fullmatch(asset_id):
            raise ValueError("素材 ID 无效")
        with self._guard:
            self._drop_expired_local_uploads_locked(time.time())
            record = self._local_assets.get(asset_id)
            if record and record.get("binding_id") != self._agents.get(agent_id, {}).get("binding_id"):
                raise PermissionError("本机素材所属配对已变化，请重新上传素材")
            if not record or not record.get("completed"):
                raise KeyError("本机素材不存在或已过期")
            if record["agent_id"] != agent_id:
                raise PermissionError("素材与设备不匹配")
            return dict(record)

    def inspect_tmall_product(
        self, product_url: str, *, timeout_seconds: float
    ) -> ProductReference:
        """Queue an authenticated product read on the paired desktop agent."""
        status = self.agent_status()
        if not status["online"]:
            raise ProductLookupError("本地执行助手未在线，无法读取需要登录的天猫商品")
        job = self.store.create_job(
            kind="inspect_product",
            platform="tmall",
            account="product-lookup",
            payload={"product_url": product_url, "headed": False, "target_agent_id": self.require_target(),
                     "target_binding_id": self._target_binding(self.require_target())},
            message="正在等待本地执行助手读取天猫商品",
            remember_account=False,
        )
        self._notify_job_available()
        deadline = time.monotonic() + max(10.0, timeout_seconds)
        terminal: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            current = self.store.get_job(job["id"])
            if current and current["status"] in TERMINAL_STATUSES:
                terminal = current
                break
            time.sleep(0.2)

        if terminal is None:
            try:
                terminal = self.cancel_task(job["id"])
            except (KeyError, ValueError):
                terminal = self.store.get_job(job["id"])
            if terminal and terminal.get("status") in TERMINAL_STATUSES:
                try:
                    self.store.delete_job(job["id"])
                    self.delete_job_artifacts(job["id"])
                except (KeyError, OSError, ValueError):
                    pass
            raise ProductLookupError("本地执行助手读取天猫商品超时，请稍后重试")

        try:
            if terminal["status"] != "succeeded":
                detail = terminal.get("error") or terminal.get("message") or "读取失败"
                raise ProductLookupError(f"本地执行助手无法读取天猫商品：{detail}")
            reference = terminal.get("result", {}).get("reference")
            return ProductReference.model_validate(reference)
        except (TypeError, ValueError) as exc:
            raise ProductLookupError("本地执行助手返回了无效的商品数据") from exc
        finally:
            try:
                self.store.delete_job(job["id"])
                self.delete_job_artifacts(job["id"])
            except (KeyError, OSError, ValueError):
                pass

    def connect_agent(
        self,
        *,
        agent_id: str,
        device_name: str,
        system: str,
        version: str,
        capabilities: list[str] | tuple[str, ...] = (),
        binding_id: str | None = None,
    ) -> dict[str, Any]:
        self.start()
        now = time.monotonic()
        with self._guard:
            self._drop_offline_agents_locked(now)
            other = next(
                (item for key, item in self._agents.items() if key != agent_id), None
            )
            if other is not None:
                raise RuntimeError(
                    f"账号已有在线本地代理：{other['device_name']}；每个应用账号同时只能连接一台电脑"
                )
            connected_at = self._agents.get(agent_id, {}).get(
                "connected_at", datetime.now(timezone.utc).isoformat()
            )
            self._agents[agent_id] = {
                "agent_id": agent_id,
                "binding_id": binding_id or agent_id,
                "device_name": device_name,
                "system": system,
                "version": version,
                "capabilities": list(capabilities)[:20],
                "connected_at": connected_at,
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_monotonic": now,
            }
            connected = self._public_agent(self._agents[agent_id], online=True)
        self._notify_job_available()
        return connected

    def _notify_job_available(self) -> None:
        """Wake async claim requests without creating idle polling traffic."""
        with self._guard:
            waiters = tuple(self._job_waiters)
        for loop, event in waiters:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                continue

    async def wait_for_claimable_job(
        self, agent_id: str, timeout_seconds: float
    ) -> dict[str, Any] | None:
        """Atomically claim now or wait for a new job notification."""
        immediate = self.claim_next_job(agent_id)
        if immediate is not None or timeout_seconds <= 0:
            return immediate

        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        waiter = (loop, event)
        with self._guard:
            self._job_waiters.add(waiter)
        try:
            # Close the registration race: a job may have arrived after the
            # first claim and before this waiter was visible.
            immediate = self.claim_next_job(agent_id)
            if immediate is not None:
                return immediate
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
            except TimeoutError:
                return None
            return self.claim_next_job(agent_id)
        finally:
            with self._guard:
                self._job_waiters.discard(waiter)

    def agent_status(self) -> dict[str, Any]:
        self.start()
        self.reap_expired_jobs()
        with self._guard:
            self._drop_offline_agents_locked(time.monotonic())
            agents = [self._public_agent(item, online=True) for item in self._agents.values()]
        return {
            "execution_mode": "local_agent",
            "online": bool(agents),
            "agents": agents,
            "lease_seconds": self.lease_seconds,
            "offline_after_seconds": self._offline_after_seconds(),
            "paused_accounts": list(self.store.paused_accounts().values()),
        }

    @staticmethod
    def _public_agent(agent: dict[str, Any], *, online: bool) -> dict[str, Any]:
        return {
            key: value
            for key, value in agent.items()
            if key != "last_seen_monotonic"
        } | {"online": online}

    def _drop_offline_agents_locked(self, now: float) -> None:
        cutoff = now - self._offline_after_seconds()
        for agent_id in [
            key
            for key, item in self._agents.items()
            if item["last_seen_monotonic"] < cutoff
        ]:
            self._dropped_agents[agent_id] = self._agents.pop(agent_id)
        # 只保留最近若干个，避免长期运行下无界增长。
        while len(self._dropped_agents) > 8:
            self._dropped_agents.pop(next(iter(self._dropped_agents)), None)

    def _revive_agent_locked(self, agent_id: str) -> None:
        """Restore a dropped agent that just proved it is still alive.

        Callers must hold the guard. Reaching this point already means the
        device token validated, so the agent is authenticated even though its
        presence entry was reaped for a late renewal.
        """
        if agent_id in self._agents:
            return
        previous = self._dropped_agents.pop(agent_id, None) or {}
        previous = {**previous, **self._known_device_bindings.get(agent_id, {})}
        now_iso = datetime.now(timezone.utc).isoformat()
        self._agents[agent_id] = {
            "agent_id": agent_id,
            "binding_id": previous.get("binding_id") or agent_id,
            "device_name": previous.get("device_name") or "本地代理",
            "system": previous.get("system") or "",
            "version": previous.get("version") or "",
            "capabilities": list(previous.get("capabilities") or ()),
            "connected_at": previous.get("connected_at") or now_iso,
            "last_seen_at": now_iso,
            "last_seen_monotonic": 0.0,
        }

    def _offline_after_seconds(self) -> float:
        # Official agents renew presence through a 10-second idle long poll.
        # Two missed renewals plus scheduling margin indicates an abrupt exit.
        return 25.0

    def _touch_agent_locked(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise RuntimeError("本地代理尚未连接，请重新启动代理")
        agent["last_seen_monotonic"] = time.monotonic()
        agent["last_seen_at"] = datetime.now(timezone.utc).isoformat()

    def disconnect_agent(self, agent_id: str) -> None:
        """Forget a disconnected device without changing claimed job leases."""
        with self._guard:
            self._agents.pop(agent_id, None)
            self._identity_challenges = {key: value for key, value in self._identity_challenges.items() if value["agent_id"] != agent_id}
            self._identity_proofs = {key: value for key, value in self._identity_proofs.items() if value["agent_id"] != agent_id}

    def disconnect_all_agents(self) -> None:
        with self._guard:
            self._agents.clear()
            self._identity_challenges.clear()
            self._identity_proofs.clear()
            self._known_device_bindings.clear()

    def claim_next_job(self, agent_id: str) -> dict[str, Any] | None:
        self.start()
        self.reap_expired_jobs()
        with self._guard:
            self._drop_offline_agents_locked(time.monotonic())
            self._revive_agent_locked(agent_id)
            self._touch_agent_locked(agent_id)
            active_jobs = self.store.list_active_jobs()
            if any(job.get("agent_id") == agent_id for job in active_jobs):
                return None
            active_accounts = {
                (job["platform"], job["account"])
                for job in active_jobs
                if job["status"] in {"running", "cancelling"}
            }
            queued = sorted(
                (job for job in active_jobs if job["status"] == "queued"),
                key=lambda item: (
                    item["created_at"],
                    job_queue_order(item),
                    item["id"],
                ),
            )
            job = None
            paused = self.store.paused_accounts()
            for item in queued:
                if item["kind"] == "publish" and f"{item['platform']}:{item['account']}" in paused:
                    continue
                payload = item["payload"]
                target_agent_id = payload.get("target_agent_id")
                if payload.get("local_assets") and not target_agent_id:
                    # Legacy queued jobs omitted ownership. Recover only from
                    # verified records; the currently online PC is not evidence.
                    try:
                        target_agent_id = self._local_asset_agent_id(payload["local_assets"])
                    except ValueError:
                        self.store.update_job(
                            item["id"],
                            status="failed",
                            message="无法确认本机素材所属设备，请重新上传素材并创建任务",
                            error="旧任务缺少目标助手 ID，且素材归属记录不可恢复",
                            finished_at=utc_now(),
                        )
                        continue
                    payload = {**payload, "target_agent_id": target_agent_id}
                    if not payload.get("target_binding_id"):
                        assets = [payload.get("local_assets", {}).get("video"), payload.get("local_assets", {}).get("cover")]
                        assets.extend(payload.get("local_assets", {}).get("images") or [])
                        records = [self._local_assets.get(asset.get("asset_id"), {}) for asset in assets if asset]
                        bindings = {record.get("binding_id") for record in records}
                        if len(bindings) == 1 and None not in bindings:
                            payload["target_binding_id"] = next(iter(bindings))
                    item = self.store.update_job(item["id"], payload=payload)
                if not target_agent_id:
                    self.store.update_job(item["id"], status="failed",
                        message="旧任务缺少可验证的目标设备，请在原电脑重新创建任务",
                        error="任务归属无法确认，已阻止自动分配", finished_at=utc_now())
                    continue
                if target_agent_id and target_agent_id != agent_id:
                    continue
                if not payload.get("target_binding_id"):
                    self.store.update_job(item["id"], status="failed",
                        message="旧任务缺少可验证的设备配对，请在原电脑重新创建任务",
                        error="任务配对归属无法确认", finished_at=utc_now())
                    continue
                if payload.get("target_binding_id") != self._agents[agent_id]["binding_id"]:
                    continue
                if (item["platform"], item["account"]) not in active_accounts:
                    job = item
                    break
            if job is None:
                return None
            now = datetime.now(timezone.utc)
            return self.store.update_job(
                job["id"],
                status="running",
                message=f"本地代理 {self._agents[agent_id]['device_name']} 正在执行",
                agent_id=agent_id,
                claimed_at=now.isoformat(),
                lease_expires_at=(now + timedelta(seconds=self.lease_seconds)).isoformat(),
                started_at=job.get("started_at") or now.isoformat(),
            )

    def heartbeat(self, job_id: str, agent_id: str) -> dict[str, Any]:
        with self._guard:
            self._drop_offline_agents_locked(time.monotonic())
            self._revive_agent_locked(agent_id)
            self._touch_agent_locked(agent_id)
            self._owned_active_job(job_id, agent_id)
            now = datetime.now(timezone.utc)
            updated = self.store.update_job_volatile(
                job_id,
                lease_expires_at=(now + timedelta(seconds=self.lease_seconds)).isoformat(),
            )
        return {
            "cancel_requested": updated["status"] == "cancelling",
            "lease_expires_at": updated["lease_expires_at"],
        }

    def get_claimed_job(self, job_id: str, agent_id: str) -> dict[str, Any]:
        with self._guard:
            return self._owned_active_job(job_id, agent_id)

    def _owned_active_job(self, job_id: str, agent_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job.get("agent_id") != agent_id:
            raise PermissionError("任务不属于当前本地代理")
        if job["status"] not in {"running", "cancelling"}:
            raise ValueError("任务已经结束")
        if not job.get("payload", {}).get("target_agent_id"):
            # A persisted claim is historical ownership evidence. This is only
            # for an already running task, never for an unbound queued task.
            job = self.store.update_job(job_id, payload={**job["payload"], "target_agent_id": agent_id})
        if job.get("payload", {}).get("target_agent_id") != agent_id:
            raise PermissionError("任务目标设备与执行设备不匹配")
        binding = job["payload"].get("target_binding_id")
        current_binding = self._agents.get(agent_id, {}).get("binding_id")
        if not binding:
            # For pre-upgrade running jobs, a pairing created after the claim
            # cannot be the original claimant even if its device ID is equal.
            claimed_at = job.get("claimed_at") or job.get("started_at") or ""
            if current_binding and current_binding[:4].isdigit() and current_binding > claimed_at:
                raise PermissionError("运行任务早于当前配对，请人工核对原设备")
            job = self.store.update_job(job_id, payload={**job["payload"], "target_binding_id": current_binding})
        elif binding != current_binding:
            raise PermissionError("任务绑定的配对与当前助手不匹配")
        return job

    def complete_agent_job(
        self,
        job_id: str,
        agent_id: str,
        *,
        status: str,
        message: str,
        error: str,
        result: dict[str, Any],
        logs: list[str],
    ) -> dict[str, Any]:
        if status not in TERMINAL_STATUSES:
            raise ValueError("本地代理提交了无效的任务状态")
        with self._guard:
            existing = self.store.get_job(job_id)
            if existing and existing["status"] in TERMINAL_STATUSES:
                target = existing.get("payload", {}).get("target_agent_id")
                if target and target != agent_id:
                    raise PermissionError("任务目标设备与执行设备不匹配")
                expected_binding = existing.get("payload", {}).get("target_binding_id")
                current_binding = (self._agents.get(agent_id) or self._known_device_bindings.get(agent_id) or {}).get("binding_id")
                if expected_binding and expected_binding != current_binding:
                    raise PermissionError("任务绑定的配对与当前助手不匹配")
                if (
                    existing.get("agent_id") == agent_id
                    and existing["status"] == status
                ):
                    return existing
                raise ValueError("任务已经由其他结果终结")
            self._touch_agent_locked(agent_id)
            job = self._owned_active_job(job_id, agent_id)
            self._write_agent_logs(job_id, logs)
            if result.get("pause_account") is True and result.get("pause_reason") == "rate_limited":
                self.store.pause_account(job["platform"], job["account"], "平台请求受限，请人工核对后恢复")
            completed = self.store.update_job(
                job_id,
                status=status,
                message=message or "本地代理任务已结束",
                error=error,
                result=result,
                finished_at=utc_now(),
                lease_expires_at=None,
            )
            if job["kind"] == "delete_account" and status == "succeeded":
                try:
                    self.store.delete_account(job["platform"], job["account"])
                except KeyError:
                    pass
            self._cleanup_managed_upload_safely(job)
            return completed

    def _write_agent_logs(self, job_id: str, logs: list[str]) -> None:
        path = self.job_log_path(job_id)
        if path is None or not logs:
            return
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as output:
            for line in logs[-500:]:
                output.write(line.replace("\x00", "")[:4000].rstrip("\r\n") + "\n")
        path.chmod(0o600)

    def reap_expired_jobs(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        expired: list[dict[str, Any]] = []
        with self._guard:
            for job in self.store.list_active_jobs():
                if job["status"] not in {"running", "cancelling"} or not job.get(
                    "agent_id"
                ):
                    continue
                raw_expiry = job.get("lease_expires_at")
                try:
                    lease_expiry = datetime.fromisoformat(raw_expiry) if raw_expiry else now
                except (TypeError, ValueError):
                    lease_expiry = now
                if lease_expiry > now:
                    continue
                status = (
                    "cancelled"
                    if job["status"] == "cancelling"
                    else "uncertain"
                    if job["kind"] == "publish"
                    else "failed"
                )
                completed = self.store.update_job(
                    job["id"],
                    status=status,
                    message=(
                        "本地代理失去连接，发布结果待人工核对"
                        if status == "uncertain"
                        else "本地代理失去连接，任务未完成"
                    ),
                    error="本地代理心跳租约已过期",
                    finished_at=utc_now(),
                    lease_expires_at=None,
                )
                self._cleanup_managed_upload_safely(job)
                expired.append(completed)
        return expired

    def cancel_task(self, job_id: str) -> dict[str, Any]:
        self.start()
        with self._guard:
            job = self.store.get_job(job_id)
            if not job:
                raise KeyError(job_id)
            if job["status"] in TERMINAL_STATUSES:
                raise ValueError("仅排队中或执行中的任务可以中断")
            if job["status"] == "queued":
                cancelled = self.store.update_job(
                    job_id,
                    status="cancelled",
                    message="任务已在本地代理领取前中断",
                    finished_at=utc_now(),
                )
                self._cleanup_managed_upload_safely(job)
                return cancelled
            if job["status"] == "cancelling":
                return job
            return self.store.update_job(
                job_id,
                status="cancelling",
                message="已通知用户电脑上的本地代理中断浏览器任务",
            )

    def cancel_account_tasks(self, platform: str, account: str) -> list[dict[str, Any]]:
        jobs = sorted(
            self.store.list_active_jobs(platform, account),
            key=lambda item: item["created_at"],
            reverse=True,
        )
        return [self.cancel_task(job["id"]) for job in jobs]

    def wait_for_account_idle(self, platform: str, account: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self.store.list_active_jobs(platform, account):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)
        return True

    def job_log_path(self, job_id: str) -> Path | None:
        if not job_id.isalnum():
            return None
        return self.job_log_dir / f"{job_id}.log"

    def delete_job_artifacts(self, job_id: str) -> None:
        path = self.job_log_path(job_id)
        if path:
            path.unlink(missing_ok=True)

    def delete_jobs_artifacts(self, job_ids: list[str]) -> None:
        """Delete per-job logs for a batch task deletion request."""
        first_error: OSError | None = None
        for job_id in job_ids:
            try:
                self.delete_job_artifacts(job_id)
            except OSError as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def close_account_session(self, platform: str, account: str) -> None:
        del platform, account

    def _cleanup_managed_upload(self, job: dict[str, Any]) -> None:
        payload = job.get("payload") or {}
        if not payload.get("managed_upload"):
            return
        source_path = payload.get("video_path") or next(
            iter(payload.get("image_paths") or []), None
        )
        if not source_path:
            raise ValueError("任务没有受管上传素材")
        media_path = Path(source_path).resolve()
        parent = media_path.parent
        if (
            parent.parent != self.managed_upload_root
            or not _UPLOAD_DIRECTORY_PATTERN.fullmatch(parent.name)
            or not media_path.is_relative_to(self.managed_upload_root)
        ):
            raise ValueError("任务中的临时视频路径不属于受管上传目录")
        if parent.exists():
            shutil.rmtree(parent)

    def _cleanup_managed_upload_safely(self, job: dict[str, Any]) -> None:
        try:
            self._cleanup_managed_upload(job)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            self.record_maintenance_error(f"临时视频清理失败：{exc}")

    def _cleanup_orphaned_uploads(self, jobs: list[dict[str, Any]]) -> None:
        self.managed_upload_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        referenced = set()
        for job in jobs:
            payload = job.get("payload") or {}
            source_path = payload.get("video_path") or next(
                iter(payload.get("image_paths") or []), None
            )
            if payload.get("managed_upload") and source_path:
                referenced.add(Path(source_path).resolve().parent)
        for child in self.managed_upload_root.iterdir():
            if (
                child.is_dir()
                and _UPLOAD_DIRECTORY_PATTERN.fullmatch(child.name)
                and child.resolve() not in referenced
            ):
                try:
                    shutil.rmtree(child)
                except OSError as exc:
                    self.record_maintenance_error(f"孤儿上传目录清理失败：{child.name}：{exc}")

    def shutdown(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
            self._agents.clear()
            self._local_upload_tickets.clear()
            self._local_assets.clear()
            self._instance_lock.release()
