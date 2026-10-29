from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from webapp.api.dam import DEFAULT_DAM_SETTINGS, DamApiError, DamOpenApiClient, DamSettings, stream_download
from webapp.api.main import WebSettings, create_app


class DamHttpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = DamSettings(
            host="https://ross-api-uat.baozun.com/ddc-dam-backend",
            key="dam-test-key",
            secret="dam-test-secret",
            tenant="baozun",
            catalog="rsc_design_crossteam",
        )

    def test_api_requests_ignore_environment_socks_proxy(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"code": "OPEN_KEY_INVALID", "message": "OpenAPI Key 无效"},
            )

        transport = httpx.MockTransport(handler)
        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            self.assertIs(kwargs.get("trust_env"), False)
            kwargs["transport"] = transport
            return original_client(*args, **kwargs)

        with patch.dict(
            os.environ,
            {"ALL_PROXY": "socks5://127.0.0.1:1"},
        ), patch("webapp.api.dam.httpx.AsyncClient", side_effect=client_factory):
            with self.assertRaisesRegex(DamApiError, "OpenAPI Key 无效"):
                asyncio.run(DamOpenApiClient(self.settings).bindings())

    def test_asset_download_ignores_environment_socks_proxy(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"asset")

        transport = httpx.MockTransport(handler)
        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            self.assertIs(kwargs.get("trust_env"), False)
            kwargs["transport"] = transport
            return original_client(*args, **kwargs)

        async def download() -> bytes:
            _, chunks = await stream_download(
                "https://assets.example/image.jpg",
                max_bytes=1024,
            )
            return b"".join([chunk async for chunk in chunks])

        with patch.dict(
            os.environ,
            {"ALL_PROXY": "socks5://127.0.0.1:1"},
        ), patch("webapp.api.dam.httpx.AsyncClient", side_effect=client_factory):
            self.assertEqual(asyncio.run(download()), b"asset")


class DamDefaultConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.app = create_app(WebSettings(root / "data", root / "frontend"))
        self.client = self.enterContext(TestClient(self.app))
        self.app.state.auth_service.bootstrap_admin(
            username="damadmin", display_name="DAM Admin", password="test-password-123",
        )
        response = self.client.post("/api/auth/login", json={
            "username": "damadmin", "password": "test-password-123",
        })
        self.assertEqual(response.status_code, 200)
        self.binding = {
            "tenantCode": "baozun", "catalogCode": "rsc_design_crossteam",
            "scopeMode": "FOLDER_ROOTS", "rootCollectionIds": [42],
        }

    def test_picker_uses_default_credentials_without_dam_login(self):
        requests = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertEqual(request.headers["X-DAM-Open-Key"], DEFAULT_DAM_SETTINGS.key)
            self.assertEqual(request.headers["X-DAM-Open-Secret"], DEFAULT_DAM_SETTINGS.secret)
            if request.url.path.endswith("/bindings"):
                data = [self.binding]
            else:
                self.assertEqual(request.headers["X-DAM-Open-Tenant"], "baozun")
                self.assertEqual(request.headers["X-DAM-Open-Catalog"], "rsc_design_crossteam")
                data = [{"id": 43, "name": "素材目录"}]
            return httpx.Response(200, json={"code": "0", "data": data})

        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original_client(*args, **kwargs)

        with patch("webapp.api.dam.httpx.AsyncClient", side_effect=client_factory):
            status = self.client.get("/api/dam/status")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["binding"], self.binding)
            self.assertTrue(status.json()["configured"])
            self.assertNotIn(DEFAULT_DAM_SETTINGS.key, status.text)
            self.assertNotIn(DEFAULT_DAM_SETTINGS.secret, status.text)
            folders = self.client.get("/api/dam/folders?parent_id=42")
            self.assertEqual(folders.status_code, 200)
            self.assertEqual(folders.json()["folders"][0]["id"], 43)
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(str(request.url).startswith(
            DEFAULT_DAM_SETTINGS.host + "/api/open/v1/",
        ) for request in requests))

    def test_default_connection_rejects_unrelated_catalog(self):
        with patch.object(DamOpenApiClient, "bindings", return_value=[{
            **self.binding, "catalogCode": "other-catalog",
        }]):
            response = self.client.get("/api/dam/status")
        self.assertEqual(response.status_code, 403)

    def test_connection_failure_returns_error(self):
        with patch.object(DamOpenApiClient, "bindings", side_effect=DamApiError(
            "DAM_NETWORK_ERROR", "无法连接 DAM 素材库",
        )):
            response = self.client.get("/api/dam/status")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "无法连接 DAM 素材库")

    def test_default_connection_requires_application_login(self):
        self.client.cookies.clear()
        with patch.object(DamOpenApiClient, "bindings") as bindings:
            response = self.client.get("/api/dam/status")
        self.assertEqual(response.status_code, 401)
        bindings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
