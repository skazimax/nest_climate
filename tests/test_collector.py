from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from nest_climate.collector import (
    CONNECTIVITY_TRAIT,
    HUMIDITY_TRAIT,
    TEMPERATURE_TRAIT,
    THERMOSTAT_TYPE,
    TokenProvider,
    extract_measurements,
    five_minute_bucket,
)


def thermostat(room: str, suffix: str, temperature: float, humidity: int):
    return {
        "name": f"enterprises/project/devices/{suffix}",
        "type": THERMOSTAT_TYPE,
        "parentRelations": [{"displayName": room}],
        "traits": {
            TEMPERATURE_TRAIT: {"ambientTemperatureCelsius": temperature},
            HUMIDITY_TRAIT: {"ambientHumidityPercent": humidity},
            CONNECTIVITY_TRAIT: {"status": "ONLINE"},
        },
    }


class CollectorTest(unittest.TestCase):
    def test_rounds_to_five_minute_bucket(self):
        value = datetime(2026, 9, 4, 7, 42, 10, tzinfo=timezone.utc)
        self.assertEqual(
            five_minute_bucket(value),
            datetime(2026, 9, 4, 7, 40, tzinfo=timezone.utc),
        )

    def test_maps_both_floor_names(self):
        moment = datetime(2026, 9, 4, 7, 42, tzinfo=timezone.utc)
        result = extract_measurements(
            [
                thermostat("Второй этаж", "two", 24.7, 50),
                thermostat("Первый этаж", "one", 24.8, 52),
            ],
            moment,
        )
        self.assertEqual([item.location for item in result], ["floor_1", "floor_2"])
        self.assertEqual(result[0].humidity_percent, 52)
        self.assertEqual(result[1].temperature_c, 24.7)

    def test_rejects_missing_floor(self):
        with self.assertRaisesRegex(RuntimeError, "floor_2"):
            extract_measurements(
                [thermostat("Первый этаж", "one", 24.8, 52)],
                datetime.now(timezone.utc),
            )

    @patch.dict(
        os.environ,
        {
            "NEST_OAUTH_CLIENT_ID": "id",
            "NEST_OAUTH_CLIENT_SECRET": "secret",
            "NEST_OAUTH_REFRESH_TOKEN": "refresh",
        },
        clear=True,
    )
    def test_token_provider_caches_token(self):
        response = Mock()
        response.json.return_value = {"access_token": "token", "expires_in": 3600}
        session = Mock()
        session.post.return_value = response
        provider = TokenProvider(session=session, monotonic=lambda: 100.0)
        self.assertEqual(provider.get(), "token")
        self.assertEqual(provider.get(), "token")
        session.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
