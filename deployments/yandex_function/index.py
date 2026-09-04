from __future__ import annotations

import json

from nest_climate.collector import TokenProvider, collect
from nest_climate.ydb_store import YdbStore


TOKEN_PROVIDER = TokenProvider()


def handler(event, context):
    store = YdbStore()
    try:
        if isinstance(event, dict) and event.get("action") == "create-schema":
            store.create_table()
            return {"statusCode": 200, "body": json.dumps({"status": "schema-ready"})}
        measurements = collect(TOKEN_PROVIDER)
        store.upsert(measurements)
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "status": "ok",
                    "measurements": len(measurements),
                    "locations": [item.location for item in measurements],
                }
            ),
        }
    finally:
        store.close()
