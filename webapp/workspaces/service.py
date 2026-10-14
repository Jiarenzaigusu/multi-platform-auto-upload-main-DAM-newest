from __future__ import annotations

from dataclasses import dataclass, field
import threading

from utils.log import UserLogSinks
from webapp.ai_copy.service import AiCopyService
from webapp.api.store import JobStore
from webapp.llm_adapter.registry import LLMAdapterRegistry
from webapp.workspaces.paths import UserDataPaths


@dataclass(slots=True)
class UserWorkspace:
    """Cohesive owner of one user's stateful publishing services."""

    user_id: str
    paths: UserDataPaths
    store: JobStore
    task_manager: object
    llm_registry: LLMAdapterRegistry
    ai_copy_service: AiCopyService
    log_sinks: UserLogSinks
    _closed: bool = False
    _close_lock: threading.Lock = field(default_factory=threading.Lock)
    _dashboard_memory: object | None = None

    @property
    def dashboard_memory(self):
        with self._close_lock:
            if self._closed:
                raise RuntimeError("用户工作区已关闭")
            if self._dashboard_memory is None:
                from webapp.dashboard_memory import BrandMemoryService
                self._dashboard_memory = BrandMemoryService(self.paths.runtime / "dashboard-chat.sqlite3", self.llm_registry)
            return self._dashboard_memory

    def close(self) -> None:
        """Stop browser work before releasing logging resources."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            if self._dashboard_memory is not None:
                self._dashboard_memory.close()
            self.task_manager.shutdown()
        finally:
            self.log_sinks.close()
