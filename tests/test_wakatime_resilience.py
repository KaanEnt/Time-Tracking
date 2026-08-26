import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, call, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sources"))
os.environ.setdefault("INPUT_GH_TOKEN", "test-token")
os.environ.setdefault("INPUT_WAKATIME_API_KEY", "test-key")
os.environ.setdefault("INPUT_SYMBOL_VERSION", "1")

import manager_download  # noqa: E402
from manager_debug import init_debug_manager  # noqa: E402
from main import format_total_code_time_badge, format_yearly_code_time_badge  # noqa: E402

init_debug_manager()


class FakeResponse:
    def __init__(self, status_code, payload, url):
        self.status_code = status_code
        self._payload = payload
        self.url = url
        self.content = b""

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    async def get(self, url):
        self.urls.append(url)
        return next(self.responses)


class DownloadManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_processing_responses_until_data_is_ready(self):
        url = "https://wakatime.example/all-time"
        processing = FakeResponse(202, {"message": "Calculating stats"}, url)
        ready = FakeResponse(200, {"data": {"text": "785 hrs 3 mins"}}, url)
        client = FakeClient([processing, ready])

        original_client = manager_download.DownloadManager._client
        original_cache = manager_download.DownloadManager._REMOTE_RESOURCES_CACHE
        manager_download.DownloadManager._client = client
        manager_download.DownloadManager._REMOTE_RESOURCES_CACHE = {"waka_all": processing}

        try:
            with patch("manager_download.sleep", new=AsyncMock()) as mocked_sleep:
                result = await manager_download.DownloadManager.get_remote_json("waka_all")
        finally:
            manager_download.DownloadManager._client = original_client
            manager_download.DownloadManager._REMOTE_RESOURCES_CACHE = original_cache

        self.assertEqual(result, {"data": {"text": "785 hrs 3 mins"}})
        self.assertEqual(client.urls, [url, url])
        mocked_sleep.assert_has_awaits([call(2), call(4)])


class BadgeFormattingTests(unittest.TestCase):
    def test_formats_total_code_time_badge(self):
        badge = format_total_code_time_badge({"data": {"text": "785 hrs 3 mins"}})

        self.assertEqual(
            badge,
            "![Code Time](http://img.shields.io/badge/Code%20Time-785%20hrs%203%20mins-darkred)\n\n",
        )

    def test_rejects_missing_wakatime_data(self):
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            format_total_code_time_badge(None)

    def test_formats_yearly_badge(self):
        badge = format_yearly_code_time_badge({"data": {"human_readable_total": "307 hrs 40 mins"}})

        self.assertEqual(
            badge,
            "![Last 12 Months](http://img.shields.io/badge/Last%2012%20Months-307%20hrs%2040%20mins-darkred)\n\n",
        )

    def test_rejects_missing_yearly_data(self):
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            format_yearly_code_time_badge(None)

    def test_rejects_uncalculated_yearly_stats(self):
        with self.assertRaisesRegex(RuntimeError, "not calculated yet"):
            format_yearly_code_time_badge({"data": {"human_readable_total": None}})


if __name__ == "__main__":
    unittest.main()
