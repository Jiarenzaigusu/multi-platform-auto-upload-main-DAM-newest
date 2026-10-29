"""Submit a browser form once; uncertainty never authorizes a second click."""
from __future__ import annotations

import asyncio

from uploader.errors import PublishResultUncertainError


async def publish_once(page, button, success_url: str, *, logger, timeout_seconds=60, observe=None):
    await button.wait_for(state="visible", timeout=10_000)
    logger.info("发布进入提交阶段；从本次点击开始，结果不明确时只等待核对，不自动重发")
    pending = []
    try:
        # A click timeout can occur after the page has already received the
        # event. Treat cancellation/failure during click as uncertain too.
        await button.click()
        confirmation = asyncio.create_task(
            page.wait_for_url(success_url, timeout=timeout_seconds * 1000)
        )
        pending.append(confirmation)
        if observe is not None:
            async def watch():
                while True:
                    if await observe():
                        return
                    await asyncio.sleep(0.5)
            watcher = asyncio.create_task(watch())
            pending.append(watcher)
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            if confirmation not in done:
                await watcher
            await confirmation
        else:
            await confirmation
    except (Exception, asyncio.CancelledError) as exc:
        raise PublishResultUncertainError(
            "发布已尝试提交，但未取得明确成功确认；已停止自动重发，请到平台后台核对"
        ) from exc
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def save_confirmed_state(context, account_file, logger) -> bool:
    """Credential maintenance must not turn a confirmed publication into failure."""
    try:
        await context.storage_state(path=account_file)
        return True
    except (Exception, asyncio.CancelledError):
        logger.warning("平台已确认发布成功，但登录状态未能保存；下次任务需重新校验登录")
        return False
