# -*- coding: utf-8 -*-
"""京麦发布页标签类型选择。"""
from __future__ import annotations

import asyncio
import re


JD_TAG_TYPES = ("兴趣标签", "体验标签")


def _split_tag_path(tag_path: str, tag_type: str) -> tuple[str, ...]:
    value = (tag_path or "").strip()
    if value:
        parts = tuple(
            part.strip()
            for part in re.split(r"\s*(?:[/／>＞,，|\n])\s*", value)
            if part.strip()
        )
        if len(parts) == 1:
            spaced_parts = tuple(value.split())
            if len(spaced_parts) == 3:
                parts = spaced_parts
        if len(parts) != 3:
            raise ValueError("京东标签路径必须包含一级类型、二级分类和标签名称")
        if parts[0] not in JD_TAG_TYPES:
            raise ValueError(f"不支持的京东标签类型：{parts[0]}")
        return parts
    normalized_type = (tag_type or "").strip()
    if normalized_type and normalized_type not in JD_TAG_TYPES:
        raise ValueError(f"不支持的京东标签类型：{normalized_type}")
    return (normalized_type,) if normalized_type else ()


async def _visible_exact_text(frame, value: str):
    """选择当前级联菜单中可见的精确文本节点。"""
    candidates = frame.get_by_text(value, exact=True)
    for index in range(await candidates.count() - 1, -1, -1):
        candidate = candidates.nth(index)
        if await candidate.is_visible():
            return candidate
    return None


async def select_jd_tag(
    frame,
    *,
    tag_path: str = "",
    tag_type: str = "",
    logger,
) -> None:
    """在京麦标签级联菜单中按三级路径逐级匹配并选择。

    京麦的视频和图文发布页共用这套标签控件，但页面版本会把触发器渲染成
    ``input`` 或可点击文本，因此这里同时兼容两种结构。选择一级类型后，
    继续点击二级分类和末级标签；旧任务只传一级类型时仍保持兼容。
    """
    parts = _split_tag_path(tag_path, tag_type)
    if not parts:
        return

    trigger = None
    for selector in (
        '[placeholder="请选择标签"]',
        'input[placeholder*="请选择标签"]',
    ):
        candidates = frame.locator(selector)
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if await candidate.is_visible():
                trigger = candidate
                break
        if trigger is not None:
            break
    if trigger is None:
        candidate = frame.get_by_text("请选择标签", exact=True).first
        if await candidate.count() and await candidate.is_visible():
            trigger = candidate
    if trigger is None:
        raise RuntimeError("未找到京东“标签”选择控件，页面结构可能已变化")

    await trigger.scroll_into_view_if_needed()
    await trigger.click()
    await asyncio.sleep(0.5)

    for index, part in enumerate(parts):
        option = None
        for _ in range(20):
            option = await _visible_exact_text(frame, part)
            if option is not None:
                break
            await asyncio.sleep(0.2)
        if option is None:
            raise RuntimeError(f"京东标签控件中未找到第 {index + 1} 级“{part}”")
        await option.click()
        await asyncio.sleep(0.5)

    if len(parts) == 3:
        logger.success(f"🏷️ 京东标签已选择: {' / '.join(parts)}")
    else:
        logger.success(f"🏷️ 京东标签类型已选择: {parts[0]}")


async def select_jd_tag_type(frame, tag_type: str, logger) -> None:
    """兼容旧调用方：只选择京东标签一级类型。"""
    await select_jd_tag(frame, tag_type=tag_type, logger=logger)
