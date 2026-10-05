import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, call, patch
from urllib.parse import parse_qs, urlsplit


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

    async def test_fetches_every_yearly_summary_chunk_in_order(self):
        today = date(2026, 10, 5)
        urls = list(manager_download.yearly_summary_urls(today).values())
        client = FakeClient([FakeResponse(200, {"cumulative_total": {"seconds": index}}, url) for index, url in enumerate(urls)])

        original_client = manager_download.DownloadManager._client
        original_cache = manager_download.DownloadManager._REMOTE_RESOURCES_CACHE
        manager_download.DownloadManager._client = client
        manager_download.DownloadManager._REMOTE_RESOURCES_CACHE = dict()

        try:
            summaries = await manager_download.DownloadManager.get_yearly_summaries(today)
        finally:
            manager_download.DownloadManager._client = original_client
            manager_download.DownloadManager._REMOTE_RESOURCES_CACHE = original_cache

        self.assertEqual(client.urls, urls)
        self.assertEqual([summary["cumulative_total"]["seconds"] for summary in summaries], list(range(len(urls))))


class YearlySummaryWindowTests(unittest.TestCase):
    def test_chunks_cover_365_days_ending_today_without_gaps_or_overlap(self):
        today = date(2026, 10, 5)
        covered = []

        for url in manager_download.yearly_summary_urls(today).values():
            query = parse_qs(urlsplit(url).query)
            start, end = date.fromisoformat(query["start"][0]), date.fromisoformat(query["end"][0])
            self.assertLessEqual((end - start).days + 1, manager_download.YEARLY_SUMMARY_CHUNK_DAYS)
            covered += [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

        self.assertEqual(covered, [date(2025, 10, 6) + timedelta(days=offset) for offset in range(365)])
        self.assertEqual(covered[-1], today)


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

    def test_sums_yearly_badge_across_summary_chunks(self):
        badge = format_yearly_code_time_badge([{"cumulative_total": {"seconds": 1000000.9}}, {"cumulative_total": {"seconds": 447006.0}}])

        self.assertEqual(
            badge,
            "![Last 12 Months](http://img.shields.io/badge/Last%2012%20Months-401%20hrs%2056%20mins-darkred)\n\n",
        )

    def test_formats_singular_units_and_thousands(self):
        self.assertIn("1%20hr%201%20min-", format_yearly_code_time_badge([{"cumulative_total": {"seconds": 3660}}]))
        self.assertIn("1%2C000%20hrs%200%20mins-", format_yearly_code_time_badge([{"cumulative_total": {"seconds": 3600000}}]))

    def test_rejects_missing_yearly_summary_chunk(self):
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            format_yearly_code_time_badge([{"cumulative_total": {"seconds": 60}}, None])

    def test_rejects_yearly_summary_without_total(self):
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            format_yearly_code_time_badge([{"data": []}])


if __name__ == "__main__":
    unittest.main()
