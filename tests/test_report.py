from __future__ import annotations

import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("YDB_ENDPOINT", "grpcs://unused.invalid:2135")
os.environ.setdefault("YDB_DATABASE", "/unused")

from PIL import Image
from nest_climate import report


MOSCOW = ZoneInfo("Europe/Moscow")


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.end = datetime(2026, 9, 7, 8, tzinfo=MOSCOW)
        self.start = self.end - timedelta(days=7)

    def reading(self, location="floor_1", hours=1, temperature=24.0, humidity=52, online=True):
        return report.Reading(location, self.start + timedelta(hours=hours), temperature, humidity, online)

    def test_window_is_monday_eight(self):
        start, end = report.report_window(datetime(2026, 9, 9, 15, tzinfo=MOSCOW))
        self.assertEqual(end, self.end)
        self.assertEqual(start, datetime(2026, 8, 31, 8, tzinfo=MOSCOW))

    def test_before_monday_run_uses_previous_week(self):
        _, end = report.report_window(datetime(2026, 9, 7, 7, 59, tzinfo=MOSCOW))
        self.assertEqual(end, datetime(2026, 8, 31, 8, tzinfo=MOSCOW))

    def test_summary_is_mean_and_coverage(self):
        values = report.summarize([
            self.reading(temperature=23, humidity=50),
            self.reading(hours=2, temperature=25, humidity=56),
        ], self.start, self.end)["floor_1"]
        self.assertEqual(values.temperature_mean, 24)
        self.assertEqual(values.humidity_mean, 53)
        self.assertAlmostEqual(values.coverage_percent, 2 / 2016 * 100)

    def test_offline_and_invalid_values_are_excluded(self):
        values = report.summarize([
            self.reading(temperature=24, humidity=52),
            self.reading(hours=2, temperature=100, humidity=52),
            self.reading(hours=3, temperature=23, humidity=101),
            self.reading(hours=4, temperature=22, humidity=50, online=False),
        ], self.start, self.end)["floor_1"]
        self.assertEqual(len(values.readings), 1)

    def test_no_data_on_both_floors_is_error(self):
        with self.assertRaisesRegex(RuntimeError, "No valid climate"):
            report.summarize([], self.start, self.end)

    def test_one_floor_can_render(self):
        values = report.summarize([self.reading()], self.start, self.end)
        image = Image.open(io.BytesIO(report.render_report(values, self.start, self.end)))
        self.assertEqual(image.size, (1280, 1280))
        self.assertEqual(image.format, "PNG")

    def test_line_breaks_after_missing_samples(self):
        items = (self.reading(hours=1), self.reading(hours=1.1), self.reading(hours=2))
        self.assertEqual([len(part) for part in report.line_segments(items)], [2, 1])

    def test_chart_bounds_expand_for_extreme_readings(self):
        values = report.summarize([self.reading(temperature=30, humidity=70)], self.start, self.end)
        self.assertEqual(report.chart_bounds(values, "temperature_c", 22, 26, .5), (22, 31))
        self.assertEqual(report.chart_bounds(values, "humidity_percent", 48, 60, 2), (48, 72))

    def test_caption_calls_values_average(self):
        values = report.summarize([self.reading(), self.reading(hours=2, temperature=26)], self.start, self.end)
        value = report.caption(values, self.start, self.end)
        self.assertIn("среднее 25.0 °C", value)
        self.assertIn("2 этаж: нет данных", value)

    def test_explicit_report_recipients_have_priority(self):
        with patch.dict(os.environ, {"TELEGRAM_REPORT_CHAT_IDS": "2,3", "TELEGRAM_ADMIN_USER_IDS": "1"}):
            self.assertEqual(report.recipients(), [2, 3])

    def test_admin_is_default_recipient(self):
        with patch.dict(os.environ, {"TELEGRAM_ADMIN_USER_IDS": "1"}, clear=True):
            self.assertEqual(report.recipients(), [1])

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_ADMIN_USER_IDS": "1"})
    def test_send_uses_photo_and_does_not_expose_token(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"message_id": 10}}
        with patch.object(report.requests, "post", return_value=response) as post:
            self.assertEqual(report.send_report(b"png", "caption"), [1])
        self.assertTrue(post.call_args.args[0].endswith("/sendPhoto"))
        self.assertEqual(post.call_args.kwargs["data"]["chat_id"], 1)

    def test_table_name_is_validated(self):
        self.assertEqual(report.safe_table_name("nest_environment_readings"), "nest_environment_readings")
        with self.assertRaises(ValueError):
            report.safe_table_name("table`; DROP")

    def test_systemd_credential_directory_is_used(self):
        driver = Mock()
        driver.wait.return_value = None
        pool = Mock()
        pool.execute_with_retries.return_value = [Mock(rows=[])]
        seen = []
        def credentials_from_environment():
            seen.append(os.environ["YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS"])
            return Mock()
        with patch.dict(os.environ, {
            "CREDENTIALS_DIRECTORY": "/run/credentials/report",
            "YDB_ENDPOINT": "endpoint", "YDB_DATABASE": "database",
        }, clear=True), patch.object(report.ydb, "Driver", return_value=driver), \
                patch.object(report.ydb, "QuerySessionPool", return_value=pool), \
                patch.object(report.ydb, "credentials_from_env_variables", side_effect=credentials_from_environment):
            report.fetch_readings(self.start, self.end)
        self.assertEqual(seen, ["/run/credentials/report/ydb-key.json"])


if __name__ == "__main__":
    unittest.main()
