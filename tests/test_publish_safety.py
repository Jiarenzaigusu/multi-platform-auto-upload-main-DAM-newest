from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from patchright.async_api import Error as PlaywrightError

from uploader.errors import PlatformRateLimitedError, PublishResultUncertainError
from uploader.jd_diagnostics import JdBusinessDiagnostics
from uploader.jd_video_uploader.main import (
    JDVideo, JD_PUBLISH_VIDEO_URL, JdFileDeliveryUncertainError,
    JdVideoProcessingStalledError, _set_jd_video_file_and_verify,
)
from uploader.publish_guard import publish_once, save_confirmed_state


class PublishSafetyTests(unittest.IsolatedAsyncioTestCase):
    def button(self):
        return SimpleNamespace(wait_for=AsyncMock(), click=AsyncMock())

    async def test_confirmation_timeout_never_reclicks_or_retries(self):
        button = self.button()
        page = SimpleNamespace(wait_for_url=AsyncMock(side_effect=TimeoutError))
        with self.assertRaises(PublishResultUncertainError):
            await publish_once(page, button, '**/success', logger=Mock())
        button.click.assert_awaited_once()
        page.wait_for_url.assert_awaited_once()

    async def test_click_timeout_and_cancellation_are_uncertain(self):
        for error in (TimeoutError(), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                button = self.button()
                button.click.side_effect = error
                with self.assertRaises(PublishResultUncertainError):
                    await publish_once(Mock(), button, '**/success', logger=Mock())
                button.click.assert_awaited_once()

    async def test_failure_before_submit_is_not_misreported_as_submitted(self):
        button = self.button()
        button.wait_for.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await publish_once(Mock(), button, '**/success', logger=Mock())
        button.click.assert_not_awaited()

    async def test_verification_is_observed_without_repeating_submit(self):
        button = self.button()
        finished = asyncio.Event()

        async def verify():
            finished.set()
            return True

        async def confirm(*_args, **_kwargs):
            await finished.wait()

        page = SimpleNamespace(wait_for_url=confirm)
        observer = AsyncMock(side_effect=verify)
        await publish_once(page, button, '**/success', logger=Mock(), observe=observer)
        button.click.assert_awaited_once()
        observer.assert_awaited_once()

    async def test_credential_save_failure_does_not_invalidate_confirmed_publication(self):
        for error in (OSError('fake'), asyncio.CancelledError()):
            context = SimpleNamespace(storage_state=AsyncMock(side_effect=error))
            self.assertFalse(await save_confirmed_state(context, '/fake/account', Mock()))

    async def test_jd_input_reset_is_not_a_second_submission(self):
        file_input = SimpleNamespace(set_input_files=AsyncMock(), evaluate=AsyncMock(return_value=''))
        await _set_jd_video_file_and_verify(file_input, '/fake/video.mp4')
        file_input.set_input_files.assert_awaited_once()

    async def test_jd_ambiguous_delivery_is_not_safe_to_retry(self):
        file_input = SimpleNamespace(set_input_files=AsyncMock(side_effect=PlaywrightError('fake')))
        with self.assertRaises(JdFileDeliveryUncertainError):
            await _set_jd_video_file_and_verify(file_input, '/fake/video.mp4')
        file_input.set_input_files.assert_awaited_once()

    async def test_jd_processing_stall_after_delivery_does_not_reopen_and_reupload(self):
        uploader = object.__new__(JDVideo)
        uploader.file_path = '/fake/video.mp4'
        page = SimpleNamespace(url=JD_PUBLISH_VIDEO_URL, goto=AsyncMock(), on=Mock(),
                               is_closed=lambda: False, close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        uploader._wait_for_video_uploaded = AsyncMock(side_effect=JdVideoProcessingStalledError('', 'processing'))
        with patch('uploader.jd_video_uploader.main._wait_for_video_upload_surface', new=AsyncMock()), patch(
            'uploader.jd_video_uploader.main._choose_jd_video_file', new=AsyncMock()
        ) as deliver:
            with self.assertRaises(JdVideoProcessingStalledError):
                await uploader._open_page_and_upload_video(context)
        deliver.assert_awaited_once()
        context.new_page.assert_awaited_once()

    async def test_visible_rate_limit_precedes_stall_and_does_not_trigger_retry(self):
        uploader = object.__new__(JDVideo)
        with patch('uploader.jd_video_uploader.main._visible_text', new=AsyncMock(return_value='上传操作过快，请稍后重试')):
            with self.assertRaises(PlatformRateLimitedError):
                await uploader._wait_for_video_uploaded(Mock(), timeout_seconds=1, stall_seconds=0)

    async def test_http_200_rate_limit_stops_the_current_jd_context(self):
        context, logger = Mock(), Mock()
        diagnostics = JdBusinessDiagnostics(context, logger)
        item = SimpleNamespace(url='https://api.m.jd.com/client.action?functionId=getVideoUploadSign',
            request=SimpleNamespace(resource_type='xhr', post_data=None), status=200,
            headers={'content-type':'application/json'},
            json=AsyncMock(return_value={'success':False,'message':'上传操作过快'}))
        await diagnostics.observe(item)
        self.assertTrue(diagnostics.rate_limited)

    async def test_tracking_rate_limit_does_not_pause_business_uploads(self):
        diagnostics = JdBusinessDiagnostics(Mock(), Mock())
        item = SimpleNamespace(url='https://dig.jd.com/report',
            request=SimpleNamespace(resource_type='xhr', post_data=None), status=429,
            headers={'content-type':'application/json'}, json=AsyncMock(return_value={'code':429}))
        await diagnostics.observe(item)
        self.assertFalse(diagnostics.rate_limited)
