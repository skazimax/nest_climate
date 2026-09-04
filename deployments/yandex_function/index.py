from __future__ import annotations

import json

from nest_climate.collector import TokenProvider, collect
from nest_climate.ydb_store import YdbStore


TOKEN_PROVIDER = TokenProvider()
SCHEMA_READY = False


def handler(event, context):
    global SCHEMA_READY
    store = YdbStore()
    try:
        if not SCHEMA_READY:
            store.create_table()
            SCHEMA_READY = True
        if isinstance(event, dict) and event.get("action") == "create-schema":
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
