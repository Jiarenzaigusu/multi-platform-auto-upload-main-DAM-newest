from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from uploader.jd_auth import JdAuthProbe, JdAuthVerificationError
from uploader.jd_video_uploader.main import (
    JD_POST_CENTER_URL,
    _cookie_auth_in_context,
    _is_logged_in,
    cookie_auth,
    jd_cookie_gen,
    jd_setup,
)


def account_response(payload=None, *, status=200, url="https://api.m.jd.com/queryReleaseTalent", body=""):
    return SimpleNamespace(
        url=url,
        status=status,
        request=SimpleNamespace(post_data=body),
        json=AsyncMock(return_value=payload),
    )


class AuthContext:
    def __init__(self, response=None, *, url=JD_POST_CENTER_URL):
        self.listeners = []
        self.response = response
        self.page = SimpleNamespace(url=url, goto=AsyncMock(side_effect=self.goto), close=AsyncMock())
        self.pages = []
        self.new_page = AsyncMock(side_effect=self.create_page)

    def on(self, name, callback):
        self.listeners.append(callback)

    def remove_listener(self, name, callback):
        self.listeners.remove(callback)

    async def create_page(self):
        self.pages.append(self.page)
        return self.page

    async def goto(self, *_args, **_kwargs):
        if self.response is not None:
            for callback in self.listeners:
                callback(self.response)
        # Give the event listener's JSON read a chance to finish, as navigation
        # and the real polling sleeps do in a browser.
        for _ in range(8):
            await _real_sleep(0)


_real_sleep = asyncio.sleep


class JdAuthProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_shell_and_title_are_not_login_evidence(self):
        probe = JdAuthProbe(Mock())
        page = SimpleNamespace(url=JD_POST_CENTER_URL, title=AsyncMock(return_value="京麦"), evaluate=AsyncMock(return_value=600_000))
        self.assertFalse(await _is_logged_in(page, probe))
        page.evaluate.assert_not_awaited()

    async def test_requires_successful_account_response_and_identity(self):
        cases = [
            ({"code": 0, "busiCode": 0, "result": {"id": 123}}, True),
            ({"success": True, "result": {"id": "123"}}, True),
            ({"isSuccess": True, "data": {"id": 123}}, True),
            ({"result_code": 0, "result": {"id": 123}}, True),
            ({"code": 0, "result": {}}, False),
            ({"code": 0, "result": {"id": 0}}, False),
            ({"code": 0, "result": {"id": True}}, False),
            ({"result": {"id": 123}}, False),
            ({"success": False, "code": 0, "result": {"id": 123}}, False),
            ({"code": 1, "success": True, "result": {"id": 123}}, False),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                probe = JdAuthProbe(Mock())
                await probe.observe(account_response(payload))
                self.assertEqual(probe.authenticated, expected)

    async def test_http_200_denials_are_not_mistaken_for_login_success(self):
        for payload, status in [
            ({"code": 1}, "login_required"),
            ({"code": "3"}, "login_required"),
            ({"code": 0, "busiCode": -16}, "access_denied"),
            ({"code": 0, "busiCode": "69"}, "account_restricted"),
            ({"success": True, "busiCode": 7, "result": {"id": 123}}, "account_restricted"),
        ]:
            with self.subTest(payload=payload):
                probe = JdAuthProbe(Mock())
                await probe.observe(account_response(payload))
                self.assertFalse(probe.authenticated)
                self.assertEqual(probe.error.status, status)

    async def test_http_errors_have_separate_fixed_diagnostics(self):
        for http_status, status in [(401, "login_required"), (403, "access_denied"), (429, "rate_limited"), (503, "auth_unverified")]:
            with self.subTest(http_status=http_status):
                probe = JdAuthProbe(Mock())
                response = account_response({"message": "secret-cookie-and-identity"}, status=http_status)
                await probe.observe(response)
                self.assertFalse(probe.authenticated)
                self.assertEqual(probe.error.status, status)
                self.assertNotIn("secret", str(probe.error))
                response.json.assert_not_awaited()

    async def test_ignores_unrelated_endpoints_and_lookalike_hosts(self):
        for url in [
            "https://api.m.jd.com/queryPublicConfig",
            "https://api.m.jd.com.attacker.test/queryReleaseTalent",
            "https://static.jd.com/queryReleaseTalent",
        ]:
            with self.subTest(url=url):
                probe = JdAuthProbe(Mock())
                response = account_response({"success": True, "result": {"id": 123}}, url=url)
                await probe.observe(response)
                response.json.assert_not_awaited()
                self.assertFalse(probe.authenticated)

    async def test_understands_account_function_in_gateway_query_and_body(self):
        for url, body in [
            ("https://api.m.jd.com/client.action?functionId=queryReleaseTalent", ""),
            ("https://api.m.jd.com/client.action", "functionId=queryReleaseTalent&body=%7B%7D"),
            ("https://api.m.jd.com/client.action", '{"functionId":"queryReleaseTalent"}'),
        ]:
            probe = JdAuthProbe(Mock())
            await probe.observe(account_response({"success": True, "result": {"id": 123}}, url=url, body=body))
            self.assertTrue(probe.authenticated)

    async def test_invalid_json_does_not_authenticate_or_expose_response(self):
        probe = JdAuthProbe(Mock())
        response = account_response()
        response.json.side_effect = ValueError("secret-response")
        await probe.observe(response)
        self.assertFalse(probe.authenticated)
        self.assertNotIn("secret", str(probe.error))

    async def test_relogin_can_recover_an_expired_profile(self):
        probe = JdAuthProbe(Mock())
        await probe.observe(account_response({"code": 3}))
        await probe.observe(account_response({"code": 0, "result": {"id": 123}}))
        self.assertTrue(probe.authenticated)
        self.assertIsNone(probe.error)

    async def test_slow_old_success_cannot_overwrite_new_login_failure(self):
        probe = JdAuthProbe(Mock())
        started = asyncio.Event()
        finish = asyncio.Event()

        async def delayed_profile():
            started.set()
            await finish.wait()
            return {"code": 0, "result": {"id": 123}}

        old_response = account_response()
        old_response.json.side_effect = delayed_profile
        old_task = asyncio.create_task(probe.observe(old_response))
        await started.wait()
        await probe.observe(account_response({"code": 3}))
        finish.set()
        await old_task
        self.assertFalse(probe.authenticated)
        self.assertEqual(probe.error.status, "login_required")

    async def test_listener_cancels_pending_reads_on_exit(self):
        context = AuthContext()
        response = account_response()
        started = asyncio.Event()

        async def waiting_response():
            started.set()
            await asyncio.Event().wait()

        response.json.side_effect = waiting_response
        async with JdAuthProbe(context) as probe:
            context.listeners[0](response)
            await started.wait()
        self.assertFalse(probe.authenticated)
        self.assertEqual(context.listeners, [])
        self.assertEqual(probe._tasks, set())


class JdAuthFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_waits_for_account_confirmation_and_cleans_up(self):
        context = AuthContext(account_response({"code": 0, "result": {"id": 123}}))
        with patch("uploader.jd_video_uploader.main.asyncio.sleep", new=AsyncMock()):
            self.assertTrue(await _cookie_auth_in_context(context))
        context.page.close.assert_awaited_once()
        self.assertEqual(context.listeners, [])
        context.page.goto.assert_awaited_once_with(JD_POST_CENTER_URL, wait_until="domcontentloaded")

    async def test_page_without_account_response_fails_closed(self):
        context = AuthContext()
        with patch("uploader.jd_video_uploader.main.asyncio.sleep", new=AsyncMock()):
            with self.assertRaisesRegex(JdAuthVerificationError, "未取得京东账号接口"):
                await _cookie_auth_in_context(context)
        context.page.close.assert_awaited_once()
        self.assertEqual(context.listeners, [])

    async def test_denied_account_stops_check_with_specific_reason(self):
        context = AuthContext(account_response({"code": 0, "busiCode": -16}))
        with patch("uploader.jd_video_uploader.main.asyncio.sleep", new=AsyncMock()):
            with self.assertRaisesRegex(JdAuthVerificationError, "未授权"):
                await _cookie_auth_in_context(context)
        self.assertEqual(context.listeners, [])

    async def test_login_redirect_is_not_an_authenticated_account(self):
        context = AuthContext(url="https://passport.shop.jd.com/login/index.action")
        with patch("uploader.jd_video_uploader.main.asyncio.sleep", new=AsyncMock()):
            self.assertFalse(await _cookie_auth_in_context(context))

    async def test_fresh_cache_does_not_skip_actual_account_verification(self):
        session = SimpleNamespace(
            auth_is_fresh=Mock(return_value=True),
            ensure_open=AsyncMock(return_value=object()),
            mark_authenticated=Mock(),
        )
        with patch("uploader.jd_video_uploader.main._cookie_auth_in_context", new=AsyncMock(return_value=False)) as verify:
            self.assertFalse(await cookie_auth("jd.json", session=session, max_age_seconds=300))
        verify.assert_awaited_once()
        session.mark_authenticated.assert_called_once_with(False)

    async def test_restricted_setup_does_not_start_relogin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jd.json"
            path.write_text("{}")
            with patch("uploader.jd_video_uploader.main.cookie_auth", new=AsyncMock(side_effect=JdAuthVerificationError("京东账号受限", "account_restricted"))), patch("uploader.jd_video_uploader.main.jd_cookie_gen", new=AsyncMock()) as login:
                result = await jd_setup(path, handle=True, return_detail=True, session=Mock())
            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "account_restricted")
            login.assert_not_awaited()

    async def test_manual_login_saves_state_only_after_api_confirmation(self):
        for payload, expected in [({"code": 0, "result": {"id": 123}}, True), (None, False)]:
            with self.subTest(payload=payload):
                context = AuthContext(account_response(payload) if payload else None)
                session = SimpleNamespace(ensure_open=AsyncMock(return_value=context), save_storage_state=AsyncMock(), mark_authenticated=Mock())
                with patch("uploader.jd_video_uploader.main.asyncio.sleep", new=AsyncMock()):
                    result = await jd_cookie_gen("jd.json", session=session, max_checks=1)
                self.assertEqual(result["success"], expected)
                self.assertEqual(session.save_storage_state.await_count, int(expected))
                session.mark_authenticated.assert_called_once_with(expected)
                self.assertEqual(context.listeners, [])

    async def test_verification_failure_invalidates_previous_authentication(self):
        session = SimpleNamespace(ensure_open=AsyncMock(return_value=object()), mark_authenticated=Mock())
        with patch("uploader.jd_video_uploader.main._cookie_auth_in_context", new=AsyncMock(side_effect=JdAuthVerificationError("拒绝访问", "access_denied"))):
            with self.assertRaisesRegex(JdAuthVerificationError, "拒绝访问"):
                await cookie_auth("jd.json", session=session)
        session.mark_authenticated.assert_called_once_with(False)

    async def test_late_login_expiry_is_not_saved_as_success(self):
        context = AuthContext(account_response({"code": 0, "result": {"id": 123}}))
        session = SimpleNamespace(
            ensure_open=AsyncMock(return_value=context),
            save_storage_state=AsyncMock(),
            mark_authenticated=Mock(),
        )

        async def settle(seconds):
            if seconds == 3:
                context.listeners[0](account_response({"code": 3}))
                for _ in range(8):
                    await _real_sleep(0)

        with patch("uploader.jd_video_uploader.main.asyncio.sleep", new=settle):
            result = await jd_cookie_gen("jd.json", session=session, max_checks=1)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "login_required")
        session.save_storage_state.assert_not_awaited()
        session.mark_authenticated.assert_called_once_with(False)
