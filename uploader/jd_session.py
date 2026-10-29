# -*- coding: utf-8 -*-
"""Shared browser-session pool for all JD Jingmai content types."""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Awaitable, Callable

from patchright.async_api import Browser, Playwright

from uploader.browser_session import BrowserSession, BrowserSessionPool, launch_browser
from uploader.jd_diagnostics import JdBusinessDiagnostics
from utils.log import jd_logger


class JdBrowserSession(BrowserSession):
    """Browser context for one authenticated JD account."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._business_diagnostics: JdBusinessDiagnostics | None = None

    async def ensure_open(self):
        context = await super().ensure_open()
        if self._business_diagnostics is None:
            self._business_diagnostics = JdBusinessDiagnostics(context, self.logger)
            self._business_diagnostics.start()
        return context

    async def close(self) -> None:
        diagnostics, self._business_diagnostics = self._business_diagnostics, None
        try:
            if diagnostics is not None:
                await diagnostics.close()
        finally:
            await super().close()

    def _backup_login_state(self) -> None:
        if not self.account_file.is_file():
            return
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.account_file.name}.backup-",
            suffix=".bak",
            dir=self.account_file.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as target:
                with self.account_file.open("rb") as source:
                    shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise

    @asynccontextmanager
    async def fresh_login(self):
        """Commit a separate blank session only after verified login and saving.

        The canonical state file stays untouched throughout the attempt. Failed
        or cancelled attempts close their browser; a later lease can reopen the
        original file. Backups use .bak so they cannot appear as shop accounts.
        """
        self.account_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._backup_login_state()
        await self.close()
        self.logger.info("京东重新登录：旧状态已保留，正在创建空白浏览器会话")
        with tempfile.TemporaryDirectory(
            prefix=".jd-login-", dir=self.account_file.parent, ignore_cleanup_errors=True
        ) as directory:
            candidate = type(self)(
                self.playwright,
                Path(directory) / "state.json",
                headless=self.headless,
                logger=self.logger,
                platform_label=self.platform_label,
                viewport=self.viewport,
                launcher=self.launcher,
            )
            try:
                await candidate.ensure_open()
                yield candidate
                if candidate.last_auth_result:
                    # storage_state writes atomically inside this private folder;
                    # replace is on the same filesystem as the canonical file.
                    await candidate.save_storage_state()
                    os.replace(candidate.account_file, self.account_file)
                    self.browser, candidate.browser = candidate.browser, None
                    self.context, candidate.context = candidate.context, None
                    self._business_diagnostics = candidate._business_diagnostics
                    candidate._business_diagnostics = None
                    self.mark_authenticated(True)
                    self.logger.info("京东重新登录：账号认证通过，新登录状态已替换旧状态")
                else:
                    self.logger.warning("京东重新登录未成功，原登录状态及备份已保留")
            finally:
                await candidate.close()

    def storage_state_options(self) -> dict[str, object]:
        # Preserve authentication tokens if JD stores them in IndexedDB.
        return {"indexed_db": True}


class JdSessionPool(BrowserSessionPool):
    """Pool shared by current and future JD content publishers."""

    session_class = JdBrowserSession

    def __init__(
        self,
        *,
        idle_timeout_seconds: float = 0,
        max_sessions: int = 2,
        playwright_starter: Callable[[], Awaitable[Playwright]] | None = None,
        launcher: Callable[[Playwright, bool], Awaitable[Browser]] = launch_browser,
        logger: Any = jd_logger,
    ) -> None:
        super().__init__(
            logger=logger,
            platform_label="京东",
            viewport={"width": 1440, "height": 900},
            idle_timeout_seconds=idle_timeout_seconds,
            max_sessions=max_sessions,
            playwright_starter=playwright_starter,
            launcher=launcher,
        )
