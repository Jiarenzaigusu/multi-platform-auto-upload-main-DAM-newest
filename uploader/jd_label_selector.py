# -*- coding: utf-8 -*-
"""京麦发布页三级级联标签选择。"""
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


async def _first_visible(locator):
    """返回 locator 集合中的第一个可见节点。"""
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        if await candidate.is_visible():
            return candidate
    return None


async def _menu_click_target(candidate):
    """把文本节点提升到真正负责点击的级联菜单项。"""
    # 先取明确的菜单项，避免级联菜单嵌在外层表单 label 时误点整行。
    for selector in (
        "xpath=ancestor::*[@role='option'][1]",
        "xpath=ancestor::*[@role='menuitem'][1]",
        "xpath=ancestor::*[contains(@class, 'jd-cascader-menu-item')][1]",
        "xpath=ancestor::*[contains(@class, 'cascader-menu-item')][1]",
        "xpath=ancestor::*[contains(@class, 'jd-select-item-option')][1]",
        "xpath=ancestor::*[contains(@class, 'menu-item')][1]",
        "xpath=ancestor::li[1]",
    ):
        target = candidate.locator(selector)
        if await target.count() and await target.is_visible():
            return target

    # 末级 checkbox 在部分版本由 label 承担点击事件；只在该 label 确实
    # 包含 checkbox 结构时使用它，不把外层的“京东标签”表单 label 当成选项。
    label = candidate.locator("xpath=ancestor::label[1]")
    if await label.count() and await label.is_visible():
        checkbox = label.locator(
            'input[type="checkbox"], [role="checkbox"], [class*="checkbox"]'
        )
        if await checkbox.count():
            return label
    return candidate


async def _visible_exact_menu_item(frame, value: str, *, minimum_x: float | None = None):
    """在当前级联列中找精确文本，并返回可点击的菜单项。

    不能只使用 ``frame.get_by_text`` 的最后一个匹配项：京麦会把级联菜单
    渲染到 portal，页面其它区域也可能存在同名文字。截图中的三级菜单从左
    到右展开，所以用上一级菜单项的横坐标作为下一列的下界。
    """
    candidates = frame.get_by_text(value, exact=True)
    visible_candidates = []
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        if await candidate.is_visible():
            target = await _menu_click_target(candidate)
            box = await target.bounding_box()
            if not box:
                continue
            if minimum_x is not None and box["x"] + box["width"] < minimum_x:
                continue
            visible_candidates.append((box["x"], index, target, box))

    if not visible_candidates:
        return None, None

    # 同名节点优先选择级联菜单中最靠左的一个；下一列会通过 minimum_x
    # 排除前一列及表单其它区域。
    _, _, target, box = min(visible_candidates, key=lambda item: (item[0], item[1]))
    return target, box


async def _find_tag_trigger(frame):
    """定位标签控件的输入框或文本触发器。"""
    for selector in (
        'input[placeholder="请选择标签"]',
        'input[placeholder*="请选择标签"]',
        '[placeholder="请选择标签"]',
    ):
        trigger = await _first_visible(frame.locator(selector))
        if trigger is not None:
            return trigger

    candidates = frame.get_by_text("请选择标签", exact=True)
    return await _first_visible(candidates)


async def _click_tag_trigger(trigger, *, prefer_input: bool = False) -> None:
    """点击标签控件最右侧的下拉箭头区域。

    标签控件的 input 在部分京麦版本只负责显示值，真正的展开热区是右侧
    箭头。优先在 select/combobox 容器的右侧点击，退化时再点击输入框右侧，
    与截图中的人工操作位置保持一致。
    """
    await trigger.scroll_into_view_if_needed()

    trigger_box = await trigger.bounding_box()
    containers = []
    for selector in (
        "xpath=ancestor::*[@role='combobox'][1]",
        "xpath=ancestor::*[contains(@class, 'jd-select-selector')][1]",
        "xpath=ancestor::*[contains(@class, 'jd-cascader')][1]",
        "xpath=parent::*",
    ):
        container = trigger.locator(selector)
        if await container.count() and await container.is_visible():
            box = await container.bounding_box()
            if box and box["width"] >= 24 and box["height"] >= 12:
                containers.append(container)

    # 先尝试最接近完整选择框的祖先容器；DOM 结构不稳定时使用 input 本身。
    click_targets = ([trigger] + containers) if prefer_input else (containers + [trigger])
    for target in click_targets:
        box = await target.bounding_box()
        if not box:
            continue
        try:
            await target.click(
                position={
                    "x": max(1, box["width"] - min(16, box["width"] / 3)),
                    "y": box["height"] / 2,
                }
            )
            return
        except Exception:
            # 某些版本的祖先节点只是布局容器，继续尝试下一层。
            continue

    if trigger_box:
        await trigger.click(
            position={
                "x": max(1, trigger_box["width"] - min(16, trigger_box["width"] / 3)),
                "y": trigger_box["height"] / 2,
            }
        )
    else:
        await trigger.click()


async def _wait_for_menu_item(frame, value: str, *, minimum_x: float | None = None):
    """等待菜单列出现目标项。"""
    for _ in range(25):
        target, box = await _visible_exact_menu_item(
            frame,
            value,
            minimum_x=minimum_x,
        )
        if target is not None:
            return target, box
        await asyncio.sleep(0.2)
    return None, None


async def select_jd_tag(
    frame,
    *,
    tag_path: str = "",
    tag_type: str = "",
    logger,
) -> None:
    """在京麦标签级联菜单中按三级路径逐级匹配并选择。

    京麦的视频和图文发布页共用这套标签控件，但页面版本会把触发器渲染成
    ``input`` 或可点击文本，因此这里同时兼容两种结构。控件按截图中的三列
    级联菜单逐级选择，末级项通过包含 checkbox 的菜单项点击；旧任务只传
    一级类型时仍保持兼容。
    """
    parts = _split_tag_path(tag_path, tag_type)
    if not parts:
        return

    trigger = await _find_tag_trigger(frame)
    if trigger is None:
        raise RuntimeError("未找到京东“标签”选择控件，页面结构可能已变化")

    await _click_tag_trigger(trigger)
    await asyncio.sleep(0.5)

    minimum_x = None
    for index, part in enumerate(parts):
        option, box = await _wait_for_menu_item(
            frame,
            part,
            minimum_x=minimum_x,
        )
        if option is None and index == 0:
            # 带 role/class 的外层容器在少数版本只有布局作用，首次点击
            # 没有展开时改点 input 的右侧热区再等待一次。
            await _click_tag_trigger(trigger, prefer_input=True)
            await asyncio.sleep(0.3)
            option, box = await _wait_for_menu_item(frame, part, minimum_x=minimum_x)
        if option is None:
            raise RuntimeError(f"京东标签控件中未找到第 {index + 1} 级“{part}”")
        await option.scroll_into_view_if_needed()
        # 京麦级联菜单部分版本通过 hover 展开下一列；点击前先悬停，
        # 保证与截图中高亮一级/二级菜单项的交互一致。
        await option.hover()
        await option.click()
        await asyncio.sleep(0.5)
        if box:
            minimum_x = box["x"] + max(20, box["width"] * 0.6)

    if len(parts) == 3:
        logger.success(f"🏷️ 京东标签已选择: {' / '.join(parts)}")
    else:
        logger.success(f"🏷️ 京东标签类型已选择: {parts[0]}")


async def select_jd_tag_type(frame, tag_type: str, logger) -> None:
    """兼容旧调用方：只选择京东标签一级类型。"""
    await select_jd_tag(frame, tag_type=tag_type, logger=logger)
