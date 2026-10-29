"""Bounded, redacted observations of JD business responses, including HTTP 200."""
from __future__ import annotations

import asyncio
from contextvars import Context, copy_context
import json
import re
from urllib.parse import parse_qs, urlparse
from weakref import WeakKeyDictionary

from uploader.errors import PlatformRateLimitedError


_MAX_BODY_BYTES = 256 * 1024
_MAX_PENDING = 16
_SUCCESS_CODES = {"0", "200", "SUCCESS", "OK"}
_NAMED_CODES = _SUCCESS_CODES | {
    "FAIL", "FAILED", "ERROR", "NOT_LOGIN", "LOGIN_REQUIRED", "UNAUTHORIZED",
    "FORBIDDEN", "ACCESS_DENIED", "RISK_CONTROL", "TOO_MANY_REQUESTS",
}
_CODE_KEYS = ("code", "busiCode", "resultCode", "result_code", "errorCode", "error_code")


def check_jd_rate_limit(text="", context=None) -> None:
    diagnostics = getattr(context, "_jd_business_diagnostics", None)
    limited = isinstance(diagnostics, JdBusinessDiagnostics) and diagnostics.rate_limited
    if limited or any(word in text for word in ("上传操作过快", "上传过快", "操作过快", "操作频繁", "请求频繁", "访问频繁")):
        raise PlatformRateLimitedError("jd", "京东提示操作过快或请求受限，已停止重传并暂停该店铺发布，请人工核对后恢复")


def _endpoint(response) -> tuple[str, str, str] | None:
    parsed = urlparse(response.url)
    host = parsed.hostname or ""
    if not (host == "jd.com" or host.endswith((".jd.com", ".jdcloudcs.com"))):
        return None
    request = response.request
    if request.resource_type not in {"xhr", "fetch"}:
        return None
    function = parse_qs(parsed.query).get("functionId", [""])[0]
    if not function and parsed.path.rstrip("/") == "/client.action":
        body = request.post_data or ""
        if isinstance(body, str) and len(body) <= 64_000:
            try:
                parameters = json.loads(body)
            except (ValueError, TypeError):
                parameters = parse_qs(body)
            if isinstance(parameters, dict):
                function = parameters.get("functionId", "")
                if isinstance(function, list):
                    function = function[0] if function else ""
    # Only API names are retained. Never log a URL, query, body or dynamic path.
    if not isinstance(function, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", function):
        function = ""
    hint = f"{parsed.path} {function}".lower()
    if any(word in hint for word in ("goods", "product", "sku", "ware")):
        scope = "商品查询"
    elif any(word in hint for word in ("upload", "video", "image", "sign")) or host.endswith(".jdcloudcs.com"):
        scope = "上传"
    elif any(word in hint for word in ("talent", "login", "auth")):
        scope = "账号"
    else:
        scope = "业务"
    return host, function or "未命名接口", scope


def _safe_code(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return "已隐藏"
    value = str(value)
    if re.fullmatch(r"-?\d{1,8}", value) or value in _NAMED_CODES:
        return value
    return "已隐藏"


def _envelopes(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    result = [payload]
    for key in ("result", "data", "error"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            result.append(nested)
    return result


def _business_status(payload, http_status: int) -> tuple[str, str]:
    envelopes = _envelopes(payload)
    codes = []
    named_codes = set()
    failed = False
    succeeded = False
    messages = []
    for envelope in envelopes:
        for key in _CODE_KEYS:
            if key in envelope and envelope[key] not in (None, ""):
                value = _safe_code(envelope[key])
                codes.append(f"{key}={value}")
                named_codes.add(value)
                success = value in _SUCCESS_CODES or (
                    re.fullmatch(r"-?\d{1,8}", value) is not None and int(value) in {0, 200}
                )
                failed |= not success
                succeeded |= success
        for key in ("success", "isSuccess"):
            failed |= envelope.get(key) is False
            succeeded |= envelope.get(key) is True
        for key in ("message", "msg", "errorMessage", "errorMsg", "subMsg"):
            value = envelope.get(key)
            if isinstance(value, str):
                messages.append(value[:2000].lower())
    # Convert messages to fixed categories; raw text can contain signed URLs,
    # account identifiers, phone numbers or entire serialized requests.
    message = " ".join(messages)
    if http_status == 429 or "TOO_MANY_REQUESTS" in named_codes or any(word in message for word in (
        "操作过快", "上传过快", "上传操作过快", "频繁", "限流", "too many", "rate limit",
    )):
        status = "频率限制"
    elif http_status == 401 or any(word in message for word in (
        "未登录", "请登录", "重新登录", "登录失效", "登录过期", "登录已过期", "not login", "login required",
    )):
        status = "认证失败"
    elif http_status == 403 or any(word in message for word in (
        "无权限", "未授权", "没有权限", "forbidden", "unauthorized", "access denied",
    )):
        status = "访问被拒绝"
    elif any(word in message for word in ("风控", "账号受限", "安全验证", "risk control", "captcha")):
        status = "平台限制或验证"
    elif http_status >= 400 or failed:
        status = "业务失败（含义待核对）"
    elif succeeded:
        status = "业务响应成功"
    else:
        status = "业务状态未识别"
    return status, ",".join(codes) or "未提供"


def _result_count(payload) -> int | None:
    candidates = [payload] + _envelopes(payload)
    if isinstance(payload, dict):
        candidates.extend(payload.get(key) for key in ("data", "result"))
    for candidate in candidates:
        if isinstance(candidate, list):
            return len(candidate)
        if isinstance(candidate, dict):
            for key in ("list", "items", "records", "goodsList", "skuList", "products"):
                if isinstance(candidate.get(key), list):
                    return len(candidate[key])
    return None


class JdBusinessDiagnostics:
    """One listener per JD context, also covering manually opened tabs/iframes."""

    def __init__(self, context, logger) -> None:
        self.context = context
        self.logger = logger
        self._tasks: set[asyncio.Task] = set()
        self._started = False
        self._page_contexts = WeakKeyDictionary()
        self.rate_limited = False

    def start(self) -> None:
        if not self._started:
            self.context.on("response", self._on_response)
            self.context._jd_business_diagnostics = self
            self._started = True

    def track_page(self, page) -> None:
        try:
            self._page_contexts[page] = copy_context()
        except TypeError:
            # Lightweight test doubles need not support weak references.
            pass

    async def close(self) -> None:
        if self._started:
            self.context.remove_listener("response", self._on_response)
            self.context._jd_business_diagnostics = None
            self._started = False
        self._page_contexts.clear()
        pending = list(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _on_response(self, response) -> None:
        try:
            endpoint = _endpoint(response)
        except Exception:
            return
        if endpoint is None or len(self._tasks) >= _MAX_PENDING:
            return
        # Playwright's event dispatcher may still carry the context of the job
        # that launched it. Bind each observation to its actual owning page.
        log_context = None
        try:
            log_context = self._page_contexts.get(response.request.frame.page)
        except Exception:
            pass
        task = (log_context or Context()).run(
            asyncio.create_task, self.observe(response, endpoint)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def observe(self, response, endpoint=None) -> None:
        """Inspect a response without retaining payloads or raising into publishing."""
        try:
            endpoint = endpoint or _endpoint(response)
            if endpoint is None:
                return
            host, function, scope = endpoint
            if response.status == 429 and scope in {"上传", "商品查询", "账号"}:
                self.rate_limited = True
            headers = response.headers
            content_type = headers.get("content-type", "").lower()
            raw_length = headers.get("content-length", "")
            length = int(raw_length) if raw_length.isdigit() else 0
            if "json" not in content_type:
                if response.status < 400 and scope == "业务":
                    return
                status, codes = _business_status(None, response.status)
                if response.status < 400:
                    status = "响应非JSON，业务状态未确认"
                count = None
            elif length > _MAX_BODY_BYTES:
                status, codes, count = "响应过大，未解析业务状态", "未读取", None
            else:
                try:
                    payload = await asyncio.wait_for(response.json(), timeout=3)
                except Exception:
                    status, codes = _business_status(None, response.status)
                    if response.status < 400:
                        status = "响应无法解析，业务状态未确认"
                    codes, count = "未读取", None
                else:
                    status, codes = _business_status(payload, response.status)
                    count = _result_count(payload) if scope == "商品查询" else None
                    if scope == "业务" and status in {"业务响应成功", "业务状态未识别"}:
                        return
            if status == "频率限制" and scope in {"上传", "商品查询", "账号"}:
                self.rate_limited = True
            result = f"；结果条数={count}" if count is not None else ""
            summary = (
                f"京东接口诊断：范围={scope}；接口={host}/{function}；"
                f"HTTP={response.status}；状态={status}；错误码={codes}{result}"
            )
            if status == "业务响应成功":
                self.logger.info(summary)
            else:
                self.logger.warning(summary)
        except Exception:
            # Observation must not break a task or print exception text/secrets.
            self.logger.debug("京东接口诊断未完成（未输出原始请求或响应）")


def track_jd_page(context, page) -> None:
    """Associate a task-created page with its current user/job log context."""
    diagnostics = getattr(context, "_jd_business_diagnostics", None)
    if isinstance(diagnostics, JdBusinessDiagnostics):
        diagnostics.track_page(page)
