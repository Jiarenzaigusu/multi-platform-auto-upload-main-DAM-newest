from __future__ import annotations

import asyncio
from unittest.mock import Mock

from uploader.jd_label_selector import select_jd_tag


class _EmptyLocator:
    async def count(self):
        return 0


class _FakeLocator:
    def __init__(self, name, box, *, on_click=None, parent=None, frame=None):
        self.name = name
        self._box = box
        self._on_click = on_click
        self._parent = parent
        self._frame = frame
        self.clicks = []
        self.hovers = 0

    async def count(self):
        return 1

    def nth(self, _index):
        return self

    async def is_visible(self):
        if self.name in {"兴趣标签", "居家", "健康环保家居"}:
            return self._frame.menu_open
        return True

    async def bounding_box(self):
        return self._box

    async def scroll_into_view_if_needed(self):
        return None

    async def hover(self):
        self.hovers += 1
        if self._frame is not None:
            self._frame.hovered.append(self.name)

    async def click(self, **kwargs):
        self.clicks.append(kwargs)
        if self._on_click is not None:
            self._on_click(self, kwargs)

    async def press(self, key):
        if key == "Escape" and self._frame is not None:
            self._frame.menu_open = False

    def locator(self, selector):
        if self._parent is not None and "ancestor::*[@role='menuitem']" in selector:
            return self._parent
        if self.name == "trigger":
            return self._frame.container
        return _EmptyLocator()


class _FakeCollection:
    def __init__(self, items):
        self.items = items

    async def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _FakeFrame:
    def __init__(self):
        self.stage = 0
        self.menu_open = False
        self.click_order = []
        self.hovered = []
        self.trigger = _FakeLocator(
            "trigger",
            {"x": 90, "y": 0, "width": 556, "height": 32},
            on_click=self._open,
            frame=self,
        )
        self.container = _FakeLocator(
            "arrow-container",
            {"x": 90, "y": 0, "width": 556, "height": 32},
            on_click=self._open,
            frame=self,
        )
        self.body = _FakeLocator(
            "body",
            {"x": 0, "y": 0, "width": 800, "height": 500},
            on_click=self._close,
            frame=self,
        )

    def _open(self, _locator, _kwargs):
        self.stage = 1
        self.menu_open = True
        self.click_order.append("arrow")

    def _close(self, _locator, _kwargs):
        self.menu_open = False
        self.click_order.append("blank")

    def _choose(self, value):
        def on_click(_locator, _kwargs):
            self.click_order.append(value)
            self.stage += 1

        return on_click

    def locator(self, selector):
        if selector == "body":
            return self.body
        if "placeholder" in selector:
            return _FakeCollection([self.trigger])
        raise AssertionError(f"unexpected frame selector: {selector}")

    def get_by_text(self, value, *, exact):
        assert exact is True
        options = {
            1: ("兴趣标签", 20),
            2: ("居家", 132),
            3: ("健康环保家居", 244),
        }
        expected = options.get(self.stage)
        if expected is None or expected[0] != value:
            return _FakeCollection([])
        x = expected[1]
        parent = _FakeLocator(
            value,
            {"x": x, "y": 20, "width": 100, "height": 32},
            on_click=self._choose(value),
            frame=self,
        )
        candidate = _FakeLocator(
            f"text:{value}",
            {"x": x + 10, "y": 20, "width": 80, "height": 20},
            parent=parent,
            frame=self,
        )
        return _FakeCollection([candidate])


def test_jd_tag_selector_follows_three_cascader_columns():
    frame = _FakeFrame()
    log = Mock()

    asyncio.run(
        select_jd_tag(
            frame,
            tag_path="兴趣标签 / 居家 / 健康环保家居",
            logger=log,
        )
    )

    assert frame.click_order == [
        "arrow",
        "兴趣标签",
        "居家",
        "健康环保家居",
        "blank",
    ]
    assert frame.hovered == ["兴趣标签", "居家", "健康环保家居"]
    assert frame.container.clicks[0]["position"]["x"] == 540
    assert frame.body.clicks[0]["position"] == {"x": 670, "y": 16}
    assert frame.menu_open is False
    log.success.assert_called_once_with("🏷️ 京东标签已选择: 兴趣标签 / 居家 / 健康环保家居")
