"""Reliable helpers for Jingmai's date-time picker."""
from __future__ import annotations

import asyncio


async def select_jd_time_value(column, value: int, label: str) -> None:
    """Select one hour/minute option using exact attributes and exact text fallback."""
    candidates = column.locator(
        ", ".join(
            (
                f'li.jd-picker-time-panel-cell[title="{value}"]',
                f'li.jd-picker-time-panel-cell[title="{value:02d}"]',
            )
        )
    )
    if not await candidates.count():
        candidates = column.get_by_text(f"{value:02d}", exact=True)
    if not await candidates.count():
        candidates = column.get_by_text(str(value), exact=True)
    if not await candidates.count():
        raise RuntimeError(f"京东时间面板中未找到{label}选项 {value:02d}")

    option = candidates.first
    await option.scroll_into_view_if_needed()
    await asyncio.sleep(0.15)
    await option.click()
    await asyncio.sleep(0.35)
