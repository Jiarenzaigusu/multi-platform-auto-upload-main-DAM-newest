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
    try:
        select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
        await page.keyboard.press(select_all)
        # 在浏览器编辑器中，右方向键会把一个非折叠选区收起到右端。这两步
        # 都是可信键盘事件，仓颉不会再恢复 editor.click() 的中间位置。
        await page.keyboard.press("ArrowRight")
        await asyncio.sleep(0.1)
        selection_ok = await editor.evaluate(
            r"""element => {
                const selection = window.getSelection();
                if (!selection || selection.rangeCount !== 1
                    || !selection.isCollapsed
                    || !element.contains(selection.anchorNode)) return false;
                // 不只检查“在编辑器内”，还要确认光标之后没有任何可见文本。
                // 若仓颉恢复到正文中间或某个结构化标签之前，tail.toString()
                // 会包含后续正文/标签文字，必须判定失败。
                const tail = document.createRange();
                tail.selectNodeContents(element);
                tail.setStart(selection.anchorNode, selection.anchorOffset);
                // Range.toString() 会为块级节点边界和末尾 <br> 生成换行；这些
                // 不是可见正文，长文自动分段时尤其常见，不能据此误判光标未
                // 到末尾。只要尾部没有非空白、非零宽字符即可。
                return tail.toString().replace(/[\s\u200B-\u200D\uFEFF]/g, '') === '';
            }"""
        )
        if selection_ok is False:
            raise RuntimeError("无法将天猫文案光标定位到真实末尾")
    except (AttributeError, TypeError):
        # Older wrappers/test doubles may not expose locator.evaluate.
        raise RuntimeError("当前浏览器接口无法校验天猫文案光标位置")
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

    # Cangjie may convert the label before the next DOM sample. Space closes
    # the current label mode, so a second DOM transition is not required.
    await asyncio.sleep(0.5)
    await page.keyboard.press("Space")
    await asyncio.sleep(0.5)


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
