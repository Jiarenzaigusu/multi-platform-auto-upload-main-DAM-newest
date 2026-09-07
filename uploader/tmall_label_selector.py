"""Shared Tmall editor label-panel automation."""
from __future__ import annotations

import asyncio
import re
import sys


async def focus_tmall_editor_end(frame, page):
    """Use native pointer/key events to put the Cangjie caret at the end."""
    editor = frame.locator('div[data-cangjie-content="true"]').first
    await editor.wait_for(state="visible", timeout=10000)
    await editor.click()
    shortcut = "Meta+ArrowDown" if sys.platform == "darwin" else "Control+End"
    await page.keyboard.press(shortcut)
    return editor


async def _visible_toolbar_trigger(frame, toolbar_label: str):
    triggers = frame.get_by_text(toolbar_label, exact=True)
    for _ in range(20):
        for index in range(await triggers.count()):
            candidate = triggers.nth(index)
            if await candidate.is_visible():
                return candidate
        await asyncio.sleep(0.25)
    raise RuntimeError(f"未找到可点击的“{toolbar_label}”入口")


def _html_without_spacing(value: str) -> str:
    """Ignore the separator inserted by Space when checking tag conversion."""
    return re.sub(r"(?:&nbsp;|&#160;|\u00a0|\s)+", "", value)


async def type_tmall_content_tag(frame, page, tag: str) -> None:
    """Enter one custom tag through Cangjie's content-label mode."""
    editor = await focus_tmall_editor_end(frame, page)
    before_editor_html = await editor.inner_html()
    trigger = await _visible_toolbar_trigger(frame, "内容标签")
    # Clicking the toolbar after focusing the editor preserves the native
    # selection and enters label mode without relying on a literal '#'.
    await trigger.click()
    await page.keyboard.type(tag, delay=100)
    query_editor_html = before_editor_html
    for _ in range(10):
        query_editor_html = await editor.inner_html()
        if query_editor_html != before_editor_html:
            break
        await asyncio.sleep(0.2)
    else:
        raise RuntimeError(f"进入“内容标签”后无法输入“{tag}”")

    await page.keyboard.press("Space")
    for _ in range(10):
        confirmed_html = await editor.inner_html()
        if _html_without_spacing(confirmed_html) != _html_without_spacing(
            query_editor_html
        ):
            return
        await asyncio.sleep(0.2)
    raise RuntimeError(f"内容标签“{tag}”输入后未完成标签转换")


async def select_tmall_label_suggestion(
    frame, page, *, toolbar_label: str, value: str
) -> str:
    """Enter label mode, type in the editor, and click a matching suggestion."""
    trigger = await _visible_toolbar_trigger(frame, toolbar_label)

    editor = frame.locator('div[data-cangjie-content="true"]').first
    before_editor_html = await editor.inner_html()
    await trigger.click()
    # The toolbar handler restores the editor selection and enters the requested
    # label mode. Clicking the editor again would cancel that mode on Tmall.
    await page.keyboard.type(value)
    query_editor_html = before_editor_html
    for _ in range(10):
        query_editor_html = await editor.inner_html()
        if query_editor_html != before_editor_html:
            break
        await asyncio.sleep(0.2)
    else:
        raise RuntimeError(f"进入“{toolbar_label}”后无法输入检索文本")

    selection = None
    visible_candidates: list[str] = []
    for _ in range(20):
        result = await frame.evaluate(
            r"""(expected) => {
              const visible = (element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0;
              };
              const textOf = (element) => (element.innerText || element.textContent || '')
                .replace(/\s+/g, ' ').trim();
              const normalizedExpected = expected.replace(/\s+/g, '').toLocaleLowerCase();
              const editor = document.querySelector('[data-cangjie-content="true"]');
              const selectable = [...document.querySelectorAll('*')].filter((element) => {
                if (!visible(element) || element === editor || editor?.contains(element)) return false;
                if (element.matches('html, body, input, textarea, script, style, svg, path')) return false;
                if (element.querySelector('input, textarea, [data-cangjie-content="true"]')) return false;
                const role = element.getAttribute('role') || '';
                const className = typeof element.className === 'string' ? element.className : '';
                const looksSelectable = getComputedStyle(element).cursor === 'pointer'
                  || ['option', 'button', 'menuitem'].includes(role)
                  || ['BUTTON', 'LI', 'A'].includes(element.tagName)
                  || /(option|item|suggest|result|tag|brand|topic)/i.test(className);
                return looksSelectable && !!textOf(element);
              });
              const candidates = selectable.filter((element) => textOf(element)
                .replace(/\s+/g, '').toLocaleLowerCase().includes(normalizedExpected));
              const labels = selectable.map(textOf).filter(Boolean).slice(0, 20);
              if (!candidates.length) return { selection: null, candidates: labels };
              const target = candidates.sort((a, b) => {
                const textA = textOf(a).replace(/\s+/g, '').toLocaleLowerCase();
                const textB = textOf(b).replace(/\s+/g, '').toLocaleLowerCase();
                const exactA = textA === normalizedExpected ? 0 : 1;
                const exactB = textB === normalizedExpected ? 0 : 1;
                const pointerA = getComputedStyle(a).cursor === 'pointer' ? 0 : 1;
                const pointerB = getComputedStyle(b).cursor === 'pointer' ? 0 : 1;
                return pointerA - pointerB || exactA - exactB
                  || a.querySelectorAll('*').length - b.querySelectorAll('*').length;
              })[0];
              target.scrollIntoView({ block: 'center' });
              target.click();
              return { selection: textOf(target), candidates: labels };
            }""",
            value,
        )
        selection = result["selection"]
        visible_candidates = result["candidates"]
        if selection:
            break
        await asyncio.sleep(0.5)
    if not selection:
        candidates = "、".join(visible_candidates) or "无"
        raise ValueError(
            f"{toolbar_label}“{value}”没有匹配候选（当前候选：{candidates}）"
        )

    for _ in range(20):
        if await editor.inner_html() != query_editor_html:
            return selection
        await asyncio.sleep(0.25)
    raise RuntimeError(f"已点击{toolbar_label}“{selection}”，但检索文本未转换为标签")


__all__ = [
    "focus_tmall_editor_end",
    "select_tmall_label_suggestion",
    "type_tmall_content_tag",
]
