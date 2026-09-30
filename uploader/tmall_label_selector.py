"""Shared Tmall editor label-panel automation."""
from __future__ import annotations

import asyncio
import sys


async def focus_tmall_editor_end(frame, page):
    """Put the Cangjie caret at the editor's actual DOM end.

    仓颉不会可靠保存脚本创建的 DOM Range。使用原生“全选后向右收起”把
    选区折叠到编辑器末尾，使其内部缓存和浏览器可见光标保持一致。
    """
    editor = frame.locator('div[data-cangjie-content="true"]').first
    await editor.wait_for(state="visible", timeout=10000)

    # A previous label interaction can leave a text range selected (or leave
    # the caret inside a structured label node).  Clear that state before
    # placing the caret; otherwise Cangjie may report that there is no valid
    # label insertion position.
    await page.keyboard.press("Escape")
    await editor.click()
    select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
    await page.keyboard.press(select_all)
    # 在浏览器编辑器中，右方向键会把非折叠选区收起到右端。仓颉末尾可能
    # 存在不可见辅助 DOM，不能再用 Range.toString() 判断视觉光标位置；
    # 标签插入是否成功由后续 HTML/文本变化单独校验。
    await page.keyboard.press("ArrowRight")
    await asyncio.sleep(0.1)
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


async def _editor_has_structured_tag(editor, tag: str) -> bool:
    """Return whether *tag* is represented by a non-text label node.

    Cangjie implementations have changed their generated class names several
    times.  The stable signals are a tag/label/topic data marker, a
    non-editable inline node, or a link-like inline node inside the editor.
    Checking this after the input is committed prevents a plain-text write from
    being reported as a successful content-label insertion.
    """
    try:
        return bool(
            await editor.evaluate(
                r"""(root, expected) => {
                  const normalize = (value) => (value || '')
                    .replace(/^#\s*/, '')
                    .replace(/\s+/g, '')
                    .toLocaleLowerCase();
                  const wanted = normalize(expected);
                  return [...root.querySelectorAll('*')].some((node) => {
                    const text = normalize(node.textContent);
                    if (text !== wanted) return false;
                    const attrs = [...node.attributes].map((attr) =>
                      `${attr.name}=${attr.value}`.toLocaleLowerCase()
                    ).join(' ');
                    const className = typeof node.className === 'string'
                      ? node.className.toLocaleLowerCase() : '';
                    return node.getAttribute('contenteditable') === 'false'
                      || node.getAttribute('role') === 'link'
                      || node.tagName === 'A'
                      || /(tag|topic|label|hashtag|cangjie)/i.test(`${attrs} ${className}`);
                  });
                }""",
                tag,
            )
        )
    except Exception:
        # Older wrappers/test doubles may not support evaluate.  The caller
        # still performs the independent tail-position check below.
        return False


async def type_tmall_content_tag(frame, page, tag: str) -> None:
    """Enter one custom tag through Cangjie's content-label mode."""
    for attempt in range(3):
        editor = await focus_tmall_editor_end(frame, page)
        before_editor_html = await editor.inner_html()
        before_editor_text = await editor.inner_text()
        trigger = await _visible_toolbar_trigger(frame, "内容标签")
        # The panel animation sometimes completes after the click promise. Give
        # Cangjie time to restore the editor selection before sending text.
        await trigger.click()
        await asyncio.sleep(0.75)
        await page.keyboard.type(tag, delay=150)

        current_html = before_editor_html
        current_text = before_editor_text
        for _ in range(12):
            current_html = await editor.inner_html()
            current_text = await editor.inner_text()
            if (
                current_html != before_editor_html
                and current_text.count(tag) > before_editor_text.count(tag)
            ):
                break
            await asyncio.sleep(0.25)
        else:
            # Retry only when the editor is completely untouched. A partial
            # write cannot be retried safely without risking duplicate copy.
            if (
                attempt < 2
                and current_html == before_editor_html
                and current_text == before_editor_text
            ):
                continue
            raise RuntimeError(f"进入“内容标签”后无法输入“{tag}”")
        break

    # Space commits the current label mode.  Verify both that the label is at
    # the editor tail (the original bug was insertion at a stale caret) and
    # that Cangjie created a structured label node rather than plain text.
    await asyncio.sleep(0.5)
    await page.keyboard.press("Space")
    for _ in range(12):
        final_text = await editor.inner_text()
        if final_text.rstrip().endswith(tag):
            if await _editor_has_structured_tag(editor, tag):
                return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"内容标签“{tag}”未提交到文案末尾或未转换为标签节点")


async def select_tmall_label_suggestion(
    frame, page, *, toolbar_label: str, value: str
) -> str:
    """Enter label mode, type in the editor, and click a matching suggestion."""
    # Establish a fresh insertion point before opening the toolbar mode.  The
    # toolbar click preserves the current Cangjie selection, so doing this
    # afterwards would cancel the mode and typing would land in plain text.
    editor = await focus_tmall_editor_end(frame, page)
    trigger = await _visible_toolbar_trigger(frame, toolbar_label)

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
