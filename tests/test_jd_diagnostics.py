from __future__ import annotations

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from uploader.jd_diagnostics import JdBusinessDiagnostics


def response(payload=None, *, status=200, url=None, body="", headers=None, resource_type="xhr"):
    return SimpleNamespace(
        url=url or "https://api.m.jd.com/client.action?functionId=queryGoods&token=secret-token",
        status=status,
        request=SimpleNamespace(resource_type=resource_type, post_data=body),
        headers=headers if headers is not None else {"content-type": "application/json"},
        json=AsyncMock(return_value=payload),
    )


class JdDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = Mock()
        self.logger = Mock()
        self.diagnostics = JdBusinessDiagnostics(self.context, self.logger)

    async def asyncTearDown(self):
        await self.diagnostics.close()

    def output(self):
        return "\n".join(str(call.args[0]) for call in self.logger.method_calls)

    async def test_http_200_business_denial_is_logged_without_response_or_query_secrets(self):
        await self.diagnostics.observe(response({
            "code": 0,
            "data": {"busiCode": -16, "msg": "未授权 pin=secret-account https://jd.com/?token=secret-token"},
            "cookies": "secret-cookie",
        }))
        output = self.output()
        self.assertIn("HTTP=200", output)
        self.assertIn("busiCode=-16", output)
        self.assertIn("访问被拒绝", output)
        self.assertIn("范围=商品查询", output)
        self.assertNotIn("secret", output)
        self.assertNotIn("https://", output)

    async def test_successful_empty_query_is_distinct_from_denied_query(self):
        await self.diagnostics.observe(response({"code": 0, "result": {"goodsList": []}}))
        self.assertIn("状态=业务响应成功", self.output())
        self.assertIn("结果条数=0", self.output())
        self.logger.warning.assert_not_called()

    async def test_empty_optional_error_fields_do_not_turn_success_into_failure(self):
        await self.diagnostics.observe(response({"code": "0000", "errorCode": None, "result": {"list": []}}))
        self.assertIn("状态=业务响应成功", self.output())
        self.logger.warning.assert_not_called()

    async def test_result_count_does_not_expose_products(self):
        await self.diagnostics.observe(response({"success": True, "data": [{"name": "secret-product"}]}))
        self.assertIn("结果条数=1", self.output())
        self.assertNotIn("secret-product", self.output())

    async def test_upload_rate_limit_is_recognized_even_with_success_code(self):
        await self.diagnostics.observe(response(
            {"code": 0, "success": False, "message": "上传操作过快，请稍后再试 token=secret-token"},
            url="https://api.m.jd.com/client.action?functionId=getVideoUploadSign",
        ))
        self.assertIn("范围=上传", self.output())
        self.assertIn("状态=频率限制", self.output())
        self.assertNotIn("secret", self.output())

    async def test_unknown_business_codes_are_redacted(self):
        await self.diagnostics.observe(response({"code": "secret-cookie-value", "msg": "secret-message"}))
        self.assertIn("code=已隐藏", self.output())
        self.assertNotIn("secret", self.output())

    async def test_http_errors_are_classified_without_parsing_html(self):
        for status, label in [(401, "认证失败"), (403, "访问被拒绝"), (429, "频率限制")]:
            with self.subTest(status=status):
                item = response(status=status, headers={"content-type": "text/html"})
                await self.diagnostics.observe(item)
                self.assertIn(label, self.output())
                item.json.assert_not_awaited()

    async def test_function_from_form_or_json_body_is_identified_without_logging_body(self):
        for body in [
            "functionId=queryProduct&pin=secret-account",
            '{"functionId":"queryProduct","pin":"secret-account"}',
        ]:
            item = response({"code": -1}, url="https://api.m.jd.com/client.action", body=body)
            await self.diagnostics.observe(item)
        self.assertIn("api.m.jd.com/queryProduct", self.output())
        self.assertNotIn("secret", self.output())

    async def test_oversized_responses_and_opaque_dynamic_paths_are_not_read_or_logged(self):
        item = response(
            url="https://dr.jd.com/api/upload/secret-account?token=secret-token",
            headers={"content-type": "application/json", "content-length": "999999"},
        )
        await self.diagnostics.observe(item)
        item.json.assert_not_awaited()
        self.assertIn("响应过大", self.output())
        self.assertNotIn("secret", self.output())

    async def test_parse_failure_does_not_expose_exception_or_interrupt_task(self):
        item = response()
        item.json.side_effect = ValueError("secret-response-content")
        await self.diagnostics.observe(item)
        self.assertIn("响应无法解析", self.output())
        self.assertNotIn("secret", self.output())

    async def test_http_rate_limit_survives_invalid_json(self):
        item = response(status=429)
        item.json.side_effect = ValueError("secret-response-content")
        await self.diagnostics.observe(item)
        self.assertIn("频率限制", self.output())
        self.assertNotIn("secret", self.output())

    async def test_old_page_logs_keep_their_owner_and_manual_pages_have_no_stale_job(self):
        job = ContextVar("jd_diagnostic_test_job", default="manual")
        emitted = []
        self.logger.warning.side_effect = lambda _message: emitted.append(job.get())
        first_page, second_page = Mock(), Mock()
        job.set("first-job")
        self.diagnostics.track_page(first_page)
        job.set("second-job")
        self.diagnostics.track_page(second_page)
        # Simulate transport callbacks carrying an unrelated old task context.
        job.set("transport-job")
        for page in (first_page, second_page, Mock()):
            item = response({"code": -1})
            item.request.frame = SimpleNamespace(page=page)
            self.diagnostics._on_response(item)
        await asyncio.gather(*list(self.diagnostics._tasks))
        self.assertCountEqual(emitted, ["first-job", "second-job", "manual"])

    async def test_unrelated_hosts_and_documents_are_ignored(self):
        for url, resource_type in [
            ("https://api.m.jd.com.evil.test/queryGoods", "xhr"),
            ("https://example.com/queryGoods", "fetch"),
            ("https://dr.jd.com/jm/queryGoods", "document"),
        ]:
            item = response({"code": -1}, url=url, resource_type=resource_type)
            await self.diagnostics.observe(item)
            item.json.assert_not_awaited()
        self.assertEqual(self.output(), "")

    async def test_listener_is_unique_and_pending_reads_are_bounded_and_cancelled(self):
        self.diagnostics.start()
        self.diagnostics.start()
        self.context.on.assert_called_once()
        started = asyncio.Event()

        async def blocked_json():
            started.set()
            await asyncio.Event().wait()

        item = response()
        item.json.side_effect = blocked_json
        for _ in range(100):
            self.diagnostics._on_response(item)
        self.assertEqual(len(self.diagnostics._tasks), 16)
        await started.wait()
        await self.diagnostics.close()
        self.context.remove_listener.assert_called_once()
        self.assertEqual(self.diagnostics._tasks, set())
