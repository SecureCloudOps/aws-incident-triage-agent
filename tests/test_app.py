from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "buggy-service"))

from app import app  # noqa: E402


class BuggyServiceTest(unittest.TestCase):
    @staticmethod
    async def request(path: str):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(path)

    def test_health_endpoint(self):
        response = asyncio.run(self.request("/health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})

    def test_crash_endpoint_is_a_controlled_500(self):
        response = asyncio.run(self.request("/crash"))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "intentional crash"})


if __name__ == "__main__":
    unittest.main()
