from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests


TOKEN_URL = "https://oauth2.googleapis.com/token"
DEVICES_URL = "https://smartdevicemanagement.googleapis.com/v1/enterprises/{project_id}/devices"
THERMOSTAT_TYPE = "sdm.devices.types.THERMOSTAT"
INFO_TRAIT = "sdm.devices.traits.Info"
TEMPERATURE_TRAIT = "sdm.devices.traits.Temperature"
HUMIDITY_TRAIT = "sdm.devices.traits.Humidity"
CONNECTIVITY_TRAIT = "sdm.devices.traits.Connectivity"

DEFAULT_ROOM_MAP = {
    "Первый этаж": "floor_1",
    "Второй этаж": "floor_2",
}


@dataclass(frozen=True)
class Measurement:
    location: str
    measured_at: datetime
    device_id: str
    temperature_c: float
    humidity_percent: int
    online: bool


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def five_minute_bucket(moment: datetime) -> datetime:
    moment = moment.astimezone(timezone.utc)
    return moment.replace(
        minute=moment.minute - moment.minute % 5,
        second=0,
        microsecond=0,
    )


class TokenProvider:
    def __init__(self, session: Any = requests, monotonic: Callable[[], float] = time.monotonic):
        self.session = session
        self.monotonic = monotonic
        self._token: str | None = None
        self._expires_at = 0.0

    def get(self) -> str:
        now = self.monotonic()
        if self._token and now < self._expires_at:
            return self._token
        response = self.session.post(
            TOKEN_URL,
            data={
                "client_id": required_env("NEST_OAUTH_CLIENT_ID"),
                "client_secret": required_env("NEST_OAUTH_CLIENT_SECRET"),
                "refresh_token": required_env("NEST_OAUTH_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("OAuth response has no access_token")
        lifetime = max(60, int(body.get("expires_in", 3600)))
        self._token = token
        self._expires_at = now + lifetime - 60
        return token


def room_name(device: dict[str, Any]) -> str:
    for relation in device.get("parentRelations", []):
        display_name = relation.get("displayName")
        if isinstance(display_name, str) and display_name:
            return display_name
    return ""


def extract_measurements(
    devices: list[dict[str, Any]],
    measured_at: datetime,
    room_map: dict[str, str] | None = None,
) -> list[Measurement]:
    mapping = room_map or DEFAULT_ROOM_MAP
    bucket = five_minute_bucket(measured_at)
    found: dict[str, Measurement] = {}
    for device in devices:
        if device.get("type") != THERMOSTAT_TYPE:
            continue
        location = mapping.get(room_name(device))
        if not location:
            continue
        traits = device.get("traits", {})
        temperature = traits.get(TEMPERATURE_TRAIT, {}).get(
            "ambientTemperatureCelsius"
        )
        humidity = traits.get(HUMIDITY_TRAIT, {}).get("ambientHumidityPercent")
        if (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or not isinstance(humidity, (int, float))
            or isinstance(humidity, bool)
        ):
            raise RuntimeError(f"Incomplete climate traits for {location}")
        name = str(device.get("name", ""))
        if not name:
            raise RuntimeError(f"Missing device name for {location}")
        online = (
            traits.get(CONNECTIVITY_TRAIT, {}).get("status") == "ONLINE"
        )
        found[location] = Measurement(
            location=location,
            measured_at=bucket,
            device_id=name.rsplit("/", maxsplit=1)[-1],
            temperature_c=float(temperature),
            humidity_percent=int(round(float(humidity))),
            online=online,
        )
    missing = sorted(set(mapping.values()) - set(found))
    if missing:
        raise RuntimeError("Missing thermostats: " + ", ".join(missing))
    return [found[location] for location in sorted(found)]


def collect(
    token_provider: TokenProvider,
    session: Any = requests,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> list[Measurement]:
    project_id = required_env("NEST_DEVICE_ACCESS_PROJECT_ID")
    response = session.get(
        DEVICES_URL.format(project_id=project_id),
        headers={"Authorization": f"Bearer {token_provider.get()}"},
        timeout=20,
    )
    response.raise_for_status()
    devices = response.json().get("devices", [])
    if not isinstance(devices, list):
        raise RuntimeError("SDM response has no devices list")
    return extract_measurements(devices, now())
