from __future__ import annotations

import os

import ydb

from .collector import Measurement


CREATE_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS `{table}` (
    location Utf8 NOT NULL,
    measured_at Timestamp NOT NULL,
    device_id Utf8 NOT NULL,
    temperature_c Double NOT NULL,
    humidity_percent Uint32 NOT NULL,
    online Bool NOT NULL,
    PRIMARY KEY (location, measured_at)
);
"""

UPSERT_QUERY = """
DECLARE $location AS Utf8;
DECLARE $measured_at AS Timestamp;
DECLARE $device_id AS Utf8;
DECLARE $temperature_c AS Double;
DECLARE $humidity_percent AS Uint32;
DECLARE $online AS Bool;

UPSERT INTO `{table}` (
    location,
    measured_at,
    device_id,
    temperature_c,
    humidity_percent,
    online
) VALUES (
    $location,
    $measured_at,
    $device_id,
    $temperature_c,
    $humidity_percent,
    $online
);
"""


def safe_table_name(value: str) -> str:
    if not value or not all(character.isalnum() or character == "_" for character in value):
        raise ValueError("YDB_TABLE must contain only letters, digits, and underscores")
    return value


class YdbStore:
    def __init__(self) -> None:
        self.table = safe_table_name(
            os.getenv("YDB_TABLE", "nest_environment_readings")
        )
        self.driver = ydb.Driver(
            ydb.DriverConfig(
                endpoint=os.environ["YDB_ENDPOINT"],
                database=os.environ["YDB_DATABASE"],
                credentials=ydb.iam.MetadataUrlCredentials(),
            )
        )
        self.driver.wait(timeout=10, fail_fast=True)
        self.pool = ydb.QuerySessionPool(self.driver, size=2)

    def close(self) -> None:
        self.driver.stop()

    def create_table(self) -> None:
        self.pool.execute_with_retries(
            CREATE_TABLE_QUERY.format(table=self.table),
            retry_settings=ydb.RetrySettings(idempotent=True),
        )

    def upsert(self, measurements: list[Measurement]) -> None:
        query = UPSERT_QUERY.format(table=self.table)
        for item in measurements:
            self.pool.execute_with_retries(
                query,
                {
                    "$location": ydb.TypedValue(
                        item.location, ydb.PrimitiveType.Utf8
                    ),
                    "$measured_at": ydb.TypedValue(
                        item.measured_at, ydb.PrimitiveType.Timestamp
                    ),
                    "$device_id": ydb.TypedValue(
                        item.device_id, ydb.PrimitiveType.Utf8
                    ),
                    "$temperature_c": ydb.TypedValue(
                        item.temperature_c, ydb.PrimitiveType.Double
                    ),
                    "$humidity_percent": ydb.TypedValue(
                        item.humidity_percent, ydb.PrimitiveType.Uint32
                    ),
                    "$online": ydb.TypedValue(item.online, ydb.PrimitiveType.Bool),
                },
                retry_settings=ydb.RetrySettings(idempotent=True),
            )
