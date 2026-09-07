"""Shared Tmall editor label-panel automation."""
from __future__ import annotations

import asyncio


async def select_tmall_label_suggestion(
    frame, *, toolbar_label: str, value: str
) -> str:
    """Search a Tmall editor label panel and click a matching suggestion."""
    triggers = frame.get_by_text(toolbar_label, exact=True)
    trigger = None
    for _ in range(20):
        for index in range(await triggers.count()):
            candidate = triggers.nth(index)
            if await candidate.is_visible():
                trigger = candidate
                break
        if trigger is not None:
            break
        await asyncio.sleep(0.25)
    if trigger is None:
        raise RuntimeError(f"未找到可点击的“{toolbar_label}”入口")
    editor = frame.locator('div[data-cangjie-content="true"]').first
    before_editor_html = await editor.inner_html()
    await trigger.click()

    async def visible_search_input():
        searches = frame.locator(
            'input:not([type="hidden"])[placeholder*="检索"], '
            'input:not([type="hidden"])[placeholder*="搜索"], '
            'input:not([type="hidden"])[placeholder*="输入"], '
            'textarea[placeholder*="检索"], textarea[placeholder*="搜索"], '
            '[contenteditable="true"][data-placeholder*="检索"], '
            '[contenteditable="true"][aria-label*="检索"]'
        )
        for index in range(await searches.count()):
            candidate = searches.nth(index)
            if await candidate.is_visible():
                return candidate
        return None

    selected_search = await visible_search_input()
    if selected_search is None:
        search_entry = frame.get_by_text("输入文本检索更多", exact=True)
        for index in range(await search_entry.count()):
            candidate = search_entry.nth(index)
            if await candidate.is_visible():
                await candidate.click()
                break
        else:
            raise RuntimeError(f"打开“{toolbar_label}”后未找到标签检索入口")
        for _ in range(20):
            selected_search = await visible_search_input()
            if selected_search is not None:
                break
            await asyncio.sleep(0.25)
        if selected_search is None:
            raise RuntimeError(f"点击“{toolbar_label}”检索入口后未出现搜索框")

    await selected_search.click()
    await selected_search.fill(value)

    selection = None
    visible_candidates: list[str] = []
    for _ in range(20):
        result = await selected_search.evaluate(
            r"""(input, expected) => {
              const visible = (element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0;
              };
              const textOf = (element) => (element.innerText || element.textContent || '')
                .replace(/\s+/g, ' ').trim();
              const normalizedExpected = expected.replace(/\s+/g, '').toLocaleLowerCase();
              const overlay = input.closest(
                '.next-overlay-wrapper, [role="dialog"], [role="listbox"], '
                '[class*="popover"], [class*="dropdown"]'
              );
              const candidatesIn = (root) => [...root.querySelectorAll('*')]
                .filter((element) => visible(element)
                  && !element.closest('[data-cangjie-content="true"]')
                  && !element.matches('input, textarea, script, style, svg, path')
                  && !element.querySelector('input, textarea'));
              const matchesExpected = (element) => textOf(element)
                .replace(/\s+/g, '').toLocaleLowerCase().includes(normalizedExpected);
              let root = overlay || input.parentElement;
              let candidates = [];
              let matching = [];
              while (root) {
                candidates = candidatesIn(root);
                matching = candidates.filter(matchesExpected);
                if (matching.length || root === document.body || overlay) break;
                root = root.parentElement;
              }
              if (!matching.length) {
                return {
                  selection: null,
                  candidates: candidates.map(textOf).filter(Boolean).slice(0, 12),
                };
              }
              const target = matching.sort((a, b) => {
                const textA = textOf(a).replace(/\s+/g, '').toLocaleLowerCase();
                const textB = textOf(b).replace(/\s+/g, '').toLocaleLowerCase();
                const exactA = textA === normalizedExpected ? 0 : 1;
                const exactB = textB === normalizedExpected ? 0 : 1;
                return exactA - exactB
                  || a.querySelectorAll('*').length - b.querySelectorAll('*').length;
              })[0];
              target.scrollIntoView({ block: 'center' });
              target.click();
              return {
                selection: textOf(target),
                candidates: candidates.map(textOf).filter(Boolean).slice(0, 12),
              };
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
        if await editor.inner_html() != before_editor_html:
            return selection
        await asyncio.sleep(0.25)
    raise RuntimeError(f"已点击{toolbar_label}“{selection}”，但标签没有写入文案编辑器")


__all__ = ["select_tmall_label_suggestion"]
