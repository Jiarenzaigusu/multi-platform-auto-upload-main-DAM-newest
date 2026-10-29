from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from webapp.auth.service import AuthService
from webapp.execution_context import AgentTargetError, verified_agent_id, verified_agent_binding

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_EXEMPT_PATHS = {
    "/api/auth/bootstrap",
    "/api/auth/login",
    "/api/auth/register",
    "/api/agent/pair",
}
_SESSION_COOKIE = "mpau_session_v2"


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Resolve opaque sessions and enforce CSRF on authenticated mutations."""

    def __init__(self, app, service: AuthService, target_resolver=None) -> None:
        super().__init__(app)
        self._service = service
        self._target_resolver = target_resolver

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.agent_device = None
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        agent_auth = None
        has_agent_bearer = (
            request.url.path.startswith("/api/agent/") and scheme.lower() == "bearer"
        )
        if has_agent_bearer:
            agent_auth = self._service.resolve_agent(token.strip())
            request.state.agent_device = agent_auth
        # Device credentials authorize only execution endpoints. Browser
        # management endpoints still require their own cookie session and CSRF.
        # Version the cookie name so an old HTTPS-only session cannot prevent
        # an HTTP direct connection from storing its replacement session.
        session = self._service.resolve(request.cookies.get(_SESSION_COOKIE))
        request.state.auth_session = session
        expected_user = request.headers.get("x-mpau-user-id")
        if session is not None and expected_user and expected_user != session.user.id:
            return JSONResponse(status_code=409, content={"detail": "登录身份已变化，请重新登录后再操作"},
                                headers={"X-MPAU-Session-Changed": "1"})

        if (
            request.method not in _SAFE_METHODS
            and request.url.path not in _CSRF_EXEMPT_PATHS
            and session is not None
            and not self._service.verify_csrf(
                session.session_id, request.headers.get("x-csrf-token")
            )
        ):
            return JSONResponse(status_code=403, content={"detail": "CSRF 校验失败"})
        target = None
        if session is not None and self._target_resolver is not None and request.headers.get("x-mpau-agent-proof"):
            try:
                target = self._target_resolver(request, session)
            except (AgentTargetError, PermissionError) as exc:
                return JSONResponse(status_code=409, content={"detail": str(exc)})
        selected, binding = target if isinstance(target, tuple) else (target, None)
        marker = verified_agent_id.set(selected)
        binding_marker = verified_agent_binding.set(binding)
        try:
            response = await call_next(request)
            if session is not None:
                response.headers["X-MPAU-User-ID"] = session.user.id
            return response
        finally:
            verified_agent_id.reset(marker)
            verified_agent_binding.reset(binding_marker)
