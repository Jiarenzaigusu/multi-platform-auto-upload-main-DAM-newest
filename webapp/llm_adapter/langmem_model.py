"""LangChain bridge using the application's existing credential-isolated provider."""
from __future__ import annotations

import json
import threading
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field, PrivateAttr

from webapp.llm_adapter.provider import ChatProvider


class ProviderChatModel(BaseChatModel):
    provider: Any = Field(exclude=True, repr=False)
    stopped: Any = Field(default=None, exclude=True, repr=False)
    max_calls: int = 4
    _calls: int = PrivateAttr(default=0)
    _lock: Any = PrivateAttr(default_factory=threading.Lock)

    @property
    def _llm_type(self) -> str:
        return "mpau-langmem"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        converted = [convert_to_openai_tool(tool) for tool in tools]
        if tool_choice in ("any", "required", True):
            tool_choice = "required"
        elif isinstance(tool_choice, str) and tool_choice not in ("auto", "none"):
            tool_choice = {"type": "function", "function": {"name": tool_choice}}
        return self.bind(tools=converted, tool_choice=tool_choice)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        with self._lock:
            if (self.stopped and self.stopped.is_set()) or self._calls >= self.max_calls:
                raise RuntimeError("记忆提取已停止或超过调用预算")
            self._calls += 1
        provider: ChatProvider = self.provider
        reply = provider.chat(
            convert_to_openai_messages(messages),
            tools=kwargs.get("tools"),
            tool_choice=kwargs.get("tool_choice"),
            temperature=0,
        )
        calls = []
        for call in reply.get("tool_calls") or []:
            function = call["function"]
            arguments = json.loads(function.get("arguments") or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("记忆工具参数必须是对象")
            calls.append({"name": function["name"], "args": arguments, "id": call["id"], "type": "tool_call"})
        if kwargs.get("tools") and not calls:
            raise ValueError("模型没有返回 LangMem 所需的工具调用")
        message = AIMessage(content=reply.get("content") or "", tool_calls=calls)
        return ChatResult(generations=[ChatGeneration(message=message)])
