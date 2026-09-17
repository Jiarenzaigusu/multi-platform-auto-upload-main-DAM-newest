from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from webapp.api.dam import DamApiError, DamOpenApiClient, DamSettings, stream_download


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


if __name__ == "__main__":
    unittest.main()
