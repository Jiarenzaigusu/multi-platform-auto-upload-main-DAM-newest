from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from uploader.jd_session import JdSessionPool
from uploader.jd_video_uploader.main import jd_cookie_gen, jd_setup
from webapp.api.platforms import login_jd_account
from webapp.workspaces.paths import UserDataPaths


_sleep = asyncio.sleep
_OLD_STATE = '{"cookies": [], "origins": [], "test": "old-state"}'
_NEW_STATE = {"cookies": [], "origins": [], "test": "fresh-state"}


class LoginContext:
    def __init__(self, *, authenticate=True):
        self.listeners = {}
        self.pages = []
        self.closed = False
        self.authenticate = authenticate
        self.saved_options = []

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    async def new_page(self):
        async def goto(url, **_kwargs):
            page.url = url
            if self.authenticate:
                response = SimpleNamespace(
                    url="https://api.m.jd.com/queryReleaseTalent",
                    status=200,
                    headers={"content-type": "application/json"},
                    request=SimpleNamespace(resource_type="xhr", post_data=None),
                    json=AsyncMock(return_value={"code": 0, "result": {"id": 123}}),
                )
                for callback in list(self.listeners.get("response", [])):
                    callback(response)
                for _ in range(8):
                    await _sleep(0)

        page = SimpleNamespace(url="about:blank", goto=goto, close=AsyncMock())
        self.pages.append(page)
        return page

    async def storage_state(self, *, path, **options):
        self.saved_options.append(options)
        Path(path).write_text(json.dumps(_NEW_STATE), encoding="utf-8")

    async def close(self):
        self.closed = True


class LoginBrowser:
    def __init__(self):
        self.context = LoginContext()
        self.context_options = None
        self.connected = True

    def is_connected(self):
        return self.connected

    async def new_context(self, **options):
        self.context_options = options
        return self.context

    async def close(self):
        self.connected = False
        await self.context.close()


class JdReloginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.paths = UserDataPaths.create(Path(self.directory.name), "a" * 32)
        self.path = self.paths.cookie_file("jd", "shop1")
        self.path.write_text(_OLD_STATE, encoding="utf-8")
        self.browsers = []

        async def launch(_playwright, _headless):
            browser = LoginBrowser()
            self.browsers.append(browser)
            return browser

        self.pool = JdSessionPool(
            playwright_starter=AsyncMock(return_value=SimpleNamespace(stop=AsyncMock())),
            launcher=launch,
        )

    async def asyncTearDown(self):
        await self.pool.close()
        self.directory.cleanup()

    async def login(self):
        with patch("uploader.jd_video_uploader.main.asyncio.sleep", new=AsyncMock()):
            return await login_jd_account(
                "shop1", headless=False, paths=self.paths, session_pool=self.pool
            )

    def assert_old_state_preserved(self):
        self.assertEqual(self.path.read_text(encoding="utf-8"), _OLD_STATE)
        backups = list(self.path.parent.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), _OLD_STATE)
        if os.name != "nt":
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.path.parent.glob(".jd-login-*")), [])
        self.assertEqual(list(self.path.parent.glob("*.json")), [self.path])

    async def test_button_ignores_valid_old_auth_and_commits_verified_blank_session(self):
        with patch("uploader.jd_video_uploader.main.cookie_auth", new=AsyncMock(return_value=True)) as old_auth:
            result = await self.login()
        self.assertTrue(result["success"])
        self.assertEqual(result["account_file"], str(self.path))
        old_auth.assert_not_awaited()
        self.assertEqual(self.browsers[0].context_options["storage_state"], str(self.path))
        self.assertNotIn("storage_state", self.browsers[1].context_options)
        self.assertTrue(self.browsers[0].context.closed)
        self.assertFalse(self.browsers[1].context.closed)
        self.assertEqual(json.loads(self.path.read_text()), _NEW_STATE)
        self.assertEqual(self.browsers[1].context.saved_options[-1], {"indexed_db": True})
        backup = next(self.path.parent.glob("*.bak"))
        self.assertEqual(backup.read_text(), _OLD_STATE)
        async with self.pool.lease(self.path, headless=False) as session:
            self.assertIs(session.context, self.browsers[1].context)
            self.assertEqual(session.key, str(self.path))
            self.assertEqual(len(session.context.listeners["response"]), 1)
        self.assertEqual(list(self.path.parent.glob(".jd-login-*")), [])

    async def test_timeout_preserves_old_file_and_next_lease_restores_it(self):
        async def timeout(account_file, *, session):
            context = await session.ensure_open()
            context.authenticate = False
            return await jd_cookie_gen(account_file, session=session, max_checks=1)

        with patch("uploader.jd_video_uploader.main.jd_cookie_gen", side_effect=timeout):
            result = await self.login()
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "timeout")
        self.assert_old_state_preserved()
        self.assertTrue(self.browsers[1].context.closed)
        async with self.pool.lease(self.path, headless=False) as session:
            self.assertEqual(session.browser.context_options["storage_state"], str(self.path))

    async def test_cancelled_login_cannot_overwrite_original(self):
        with patch("uploader.jd_video_uploader.main.jd_cookie_gen", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.login()
        self.assert_old_state_preserved()
        self.assertTrue(self.browsers[1].context.closed)

    async def test_failed_commit_preserves_original_and_does_not_report_success(self):
        replace = os.replace

        def fail_commit(source, destination):
            if Path(destination) == self.path:
                raise PermissionError("secret-error-detail")
            return replace(source, destination)

        with patch("uploader.jd_session.os.replace", side_effect=fail_commit):
            result = await self.login()
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "relogin_failed")
        self.assertNotIn("secret", result["message"])
        self.assert_old_state_preserved()
        self.assertTrue(self.browsers[1].context.closed)

    async def test_failed_snapshot_is_not_logged_with_raw_exception_or_committed(self):
        async def fail_snapshot(account_file, *, session):
            context = await session.ensure_open()
            context.storage_state = AsyncMock(side_effect=OSError("secret-signed-url"))
            return await jd_cookie_gen(account_file, session=session, max_checks=1)

        with patch("uploader.jd_video_uploader.main.jd_cookie_gen", side_effect=fail_snapshot):
            result = await self.login()
        self.assertFalse(result["success"])
        self.assertNotIn("secret", result["message"])
        self.assert_old_state_preserved()

    async def test_blank_browser_launch_failure_preserves_old_state(self):
        async with self.pool.lease(self.path, headless=False) as session:
            session.launcher = AsyncMock(side_effect=RuntimeError("secret-launch-url"))
        result = await self.login()
        self.assertFalse(result["success"])
        self.assertNotIn("secret", result["message"])
        self.assert_old_state_preserved()

    async def test_first_login_does_not_require_old_file(self):
        self.path.unlink()
        self.assertTrue((await self.login())["success"])
        self.assertEqual(json.loads(self.path.read_text()), _NEW_STATE)
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    async def test_publishing_check_keeps_existing_auth_path(self):
        async with self.pool.lease(self.path, headless=False) as session:
            with patch("uploader.jd_video_uploader.main.cookie_auth", new=AsyncMock(return_value=True)) as verify:
                self.assertTrue(await jd_setup(self.path, handle=False, session=session))
            verify.assert_awaited_once()
        self.assertEqual(len(self.browsers), 1)

    async def test_force_relogin_is_rejected_for_noninteractive_check(self):
        with self.assertRaises(ValueError):
            await jd_setup(self.path, handle=False, session=None, force_relogin=True)
