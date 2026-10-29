"""Observe JD's own account requests without issuing additional API calls."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse


# These account functions are used by Jingmai's public frontend. In particular,
# queryReleaseTalent supplies the signed-in author's result.id. A successful
# analytics/static request or an empty application shell is not authentication.
_ACCOUNT_FUNCTIONS = frozenset({"queryReleaseTalent"})
_ACCOUNT_API_HOSTS = frozenset({"api.m.jd.com", "plat-gw.jd.com"})


class JdAuthVerificationError(RuntimeError):
    """Account verification failed; the status distinguishes expiry and denial."""

    def __init__(self, message: str, status: str = "auth_unverified") -> None:
        super().__init__(message)
        self.status = status


def _account_function(response) -> str:
    parsed = urlparse(response.url)
    if parsed.hostname not in _ACCOUNT_API_HOSTS:
        return ""
    function = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if function in _ACCOUNT_FUNCTIONS:
        return function
    function = parse_qs(parsed.query).get("functionId", [""])[0]
    if function in _ACCOUNT_FUNCTIONS:
        return function
    if parsed.path.rstrip("/") != "/client.action":
        return ""
    body = response.request.post_data or ""
    if not isinstance(body, str):
        return ""
    try:
        parameters = json.loads(body)
    except (ValueError, TypeError):
        parameters = parse_qs(body)
    if not isinstance(parameters, dict):
        return ""
    function = parameters.get("functionId", "")
    if isinstance(function, list):
        function = function[0] if function else ""
    return function if isinstance(function, str) and function in _ACCOUNT_FUNCTIONS else ""


def _code(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if str(value).lstrip("-").isdigit() else None
    except (TypeError, ValueError):
        return None


def _profile_error(status: int, payload) -> JdAuthVerificationError | None:
    # Fixed diagnostics deliberately exclude URLs, response text and identities:
    # JD errors can contain redirect tokens and account information.
    if status == 401:
        return JdAuthVerificationError("京东账号接口要求重新登录（HTTP 401）", "login_required")
    if status == 403:
        return JdAuthVerificationError("京东账号接口拒绝访问（HTTP 403），请核对账号权限或完成平台验证", "access_denied")
    if status == 429:
        return JdAuthVerificationError("京东账号接口请求受限（HTTP 429），已停止认证检测，请稍后复核", "rate_limited")
    if not 200 <= status < 300:
        return JdAuthVerificationError(f"京东账号接口返回 HTTP {status}，暂时无法确认登录状态")
    if not isinstance(payload, dict):
        return JdAuthVerificationError("京东账号接口没有返回可识别的认证信息")
    code = _code(payload.get("code"))
    business_code = _code(payload.get("busiCode"))
    if business_code in {7, 69}:
        return JdAuthVerificationError("京东账号接口返回账号受限状态，请到京麦后台核对平台提示", "account_restricted")
    if business_code == -16:
        return JdAuthVerificationError("京东账号接口返回未授权状态，请确认账号及店铺访问权限", "access_denied")
    if code in {1, 3}:
        return JdAuthVerificationError("京东账号接口返回登录失效，请重新登录", "login_required")
    explicit_failure = (
        payload.get("success") is False
        or payload.get("isSuccess") is False
        or ("code" in payload and code != 0)
        or ("busiCode" in payload and business_code != 0)
        or ("result_code" in payload and _code(payload["result_code"]) != 0)
    )
    explicit_success = (
        payload.get("success") is True
        or payload.get("isSuccess") is True
        or code == 0
        or _code(payload.get("result_code")) == 0
    )
    if explicit_failure or not explicit_success:
        return JdAuthVerificationError("京东账号接口未确认认证成功，请重新登录或检查账号权限")
    profile = payload.get("result", payload.get("data"))
    identity = profile.get("id") if isinstance(profile, dict) else None
    if (
        isinstance(identity, bool)
        or not isinstance(identity, (str, int))
        or not str(identity).strip()
        or (isinstance(identity, int) and identity <= 0)
        or str(identity).strip() == "0"
    ):
        return JdAuthVerificationError("京东账号接口未返回有效账号身份，不能确认登录成功")
    return None


class JdAuthProbe:
    """Collect account evidence from requests made naturally by the JD page."""

    def __init__(self, context) -> None:
        self.context = context
        self.authenticated = False
        self.error: JdAuthVerificationError | None = None
        self._tasks: set[asyncio.Task] = set()
        self._generation = 0

    async def __aenter__(self):
        self.context.on("response", self._on_response)
        return self

    async def __aexit__(self, *_args):
        self.context.remove_listener("response", self._on_response)
        pending = list(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _on_response(self, response) -> None:
        if not _account_function(response):
            return
        generation = self._begin_response()
        task = asyncio.create_task(self._inspect(response, generation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def observe(self, response) -> None:
        if not _account_function(response):
            return
        await self._inspect(response, self._begin_response())

    def _begin_response(self) -> int:
        self._generation += 1
        self.authenticated = False
        self.error = None
        return self._generation

    async def _inspect(self, response, generation: int) -> None:
        payload = None
        try:
            if 200 <= response.status < 300:
                payload = await asyncio.wait_for(response.json(), timeout=5)
            error = _profile_error(response.status, payload)
        except Exception:
            error = JdAuthVerificationError("京东账号接口响应无法解析，暂时无法确认登录状态")
        # Slow JSON reads from an older response must not overwrite a later
        # login failure (or a successful reauthentication).
        if generation != self._generation:
            return
        self.error = error
        self.authenticated = error is None

    def require_no_denial(self) -> None:
        if self.error is not None and self.error.status in {
            "access_denied", "account_restricted", "rate_limited",
        }:
            raise self.error

    def failure(self) -> JdAuthVerificationError:
        return self.error or JdAuthVerificationError(
            "未取得京东账号接口的认证确认；后台页面已打开不代表登录有效，请重新登录后复核"
        )
