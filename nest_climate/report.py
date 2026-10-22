"""Build and optionally deliver the weekly home climate report."""
from __future__ import annotations

import argparse
import html
import io
import json
import math
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import ydb
from PIL import Image, ImageDraw, ImageFont


TIMEZONE = ZoneInfo(os.getenv("REPORT_TIMEZONE", "Europe/Moscow"))
LOCATIONS = ("floor_1", "floor_2")
LABELS = {"floor_1": "1 этаж", "floor_2": "2 этаж"}
COLORS = {"floor_1": "#2563eb", "floor_2": "#f97316"}
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


@dataclass(frozen=True)
class Reading:
    location: str
    measured_at: datetime
    temperature_c: float
    humidity_percent: int
    online: bool = True


@dataclass(frozen=True)
class FloorStats:
    readings: tuple[Reading, ...]
    temperature_min: float
    temperature_mean: float
    temperature_max: float
    humidity_min: int
    humidity_mean: float
    humidity_max: int
    coverage_percent: float


def safe_table_name(value: str) -> str:
    if not value or not all(character.isalnum() or character == "_" for character in value):
        raise ValueError("YDB_TABLE must contain only letters, digits, and underscores")
    return value


def utc_literal(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def report_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    end = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    return end - timedelta(days=7), end


def fetch_readings(start: datetime, end: datetime) -> list[Reading]:
    table = safe_table_name(os.getenv("YDB_TABLE", "nest_environment_readings"))
    query = f'''SELECT location, measured_at, temperature_c, humidity_percent, online
        FROM `{table}`
        WHERE measured_at >= Timestamp("{utc_literal(start)}")
          AND measured_at < Timestamp("{utc_literal(end)}")
          AND location IN ("floor_1", "floor_2")
        ORDER BY measured_at;'''
    credential_directory = os.getenv("CREDENTIALS_DIRECTORY")
    if not os.getenv("YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS") and credential_directory:
        os.environ["YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS"] = str(
            Path(credential_directory) / "ydb-key.json"
        )
    driver = ydb.Driver(ydb.DriverConfig(
        endpoint=os.environ["YDB_ENDPOINT"],
        database=os.environ["YDB_DATABASE"],
        credentials=ydb.credentials_from_env_variables(),
    ))
    try:
        driver.wait(timeout=15, fail_fast=True)
        result = ydb.QuerySessionPool(driver, size=1).execute_with_retries(query)
        return [Reading(
            location=row.location,
            measured_at=(row.measured_at.replace(tzinfo=timezone.utc)
                         if row.measured_at.tzinfo is None else row.measured_at.astimezone(timezone.utc)),
            temperature_c=float(row.temperature_c),
            humidity_percent=int(row.humidity_percent),
            online=bool(row.online),
        ) for row in result[0].rows]
    finally:
        driver.stop()


def summarize(readings: list[Reading], start: datetime, end: datetime) -> dict[str, FloorStats | None]:
    expected = max(1, round((end - start).total_seconds() / 300))
    result: dict[str, FloorStats | None] = {}
    for location in LOCATIONS:
        items = sorted((item for item in readings
                        if item.location == location and item.online
                        and -40 <= item.temperature_c <= 80
                        and 0 <= item.humidity_percent <= 100),
                       key=lambda item: item.measured_at.timestamp())
        if not items:
            result[location] = None
            continue
        temperatures = [item.temperature_c for item in items]
        humidity = [item.humidity_percent for item in items]
        samples = len({item.measured_at for item in items})
        result[location] = FloorStats(
            tuple(items), min(temperatures), statistics.mean(temperatures), max(temperatures),
            min(humidity), statistics.mean(humidity), max(humidity),
            min(100.0, samples / expected * 100),
        )
    if all(value is None for value in result.values()):
        raise RuntimeError("No valid climate measurements for the weekly report")
    return result


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def line_segments(items: tuple[Reading, ...], maximum_gap_minutes: int = 60):
    segments: list[list[Reading]] = []
    for item in items:
        if not segments or item.measured_at - segments[-1][-1].measured_at > timedelta(minutes=maximum_gap_minutes):
            segments.append([])
        segments[-1].append(item)
    return segments


def chart_bounds(stats: dict[str, FloorStats | None], field: str,
                 default_low: float, default_high: float, padding: float) -> tuple[float, float]:
    values = [float(getattr(item, field)) for value in stats.values() if value
              for item in value.readings]
    if not values:
        return default_low, default_high
    return min(default_low, math.floor(min(values) - padding)), max(default_high, math.ceil(max(values) + padding))


def render_report(stats: dict[str, FloorStats | None], start: datetime, end: datetime) -> bytes:
    width = height = 1280
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((55, 38), "Климат дома", font=font(34, True), fill="#172554")
    draw.text((55, 83), f"{start:%d.%m %H:%M} — {end:%d.%m %H:%M} МСК",
              font=font(17), fill="#64748b")

    for index, location in enumerate(LOCATIONS):
        left = 55 + index * 610
        draw.rounded_rectangle((left, 125, left + 570, 330), radius=18,
                               fill="#ffffff", outline="#dbeafe", width=2)
        draw.text((left + 28, 150), LABELS[location], font=font(20, True), fill=COLORS[location])
        value = stats[location]
        if value is None:
            draw.text((left + 28, 225), "Нет данных", font=font(34, True), fill="#94a3b8")
            continue
        draw.text((left + 28, 193), "Среднее за период", font=font(14), fill="#64748b")
        draw.text((left + 28, 220), f"{value.temperature_mean:.1f} °C", font=font(38, True), fill="#0f172a")
        draw.text((left + 245, 220), f"{value.humidity_mean:.0f}%", font=font(38, True), fill="#0f172a")
        draw.text((left + 28, 280), f"мин/макс {value.temperature_min:.1f}/{value.temperature_max:.1f}",
                  font=font(14), fill="#64748b")
        draw.text((left + 245, 280), f"мин/макс {value.humidity_min}/{value.humidity_max}",
                  font=font(14), fill="#64748b")
        draw.text((left + 435, 280), f"данные {value.coverage_percent:.0f}%", font=font(14), fill="#64748b")

    plot_left, plot_width = 90, 1130
    temperature_bounds = chart_bounds(stats, "temperature_c", 22, 26, 0.5)
    humidity_bounds = chart_bounds(stats, "humidity_percent", 48, 60, 2)
    panels = [(415, 250, "Температура", "temperature_c", *temperature_bounds),
              (795, 250, "Влажность", "humidity_percent", *humidity_bounds)]
    total_seconds = (end - start).total_seconds()
    for top, plot_height, title, field, low, high in panels:
        ticks = (low, (low + high) / 2, high)
        draw.text((55, top - 43), title, font=font(19, True), fill="#334155")
        for index in range(8):
            x = plot_left + round(plot_width * index / 7)
            moment = start + (end - start) * index / 7
            draw.line((x, top, x, top + plot_height), fill="#dbe4ef", width=1)
            label = moment.strftime("%d.%m")
            box = draw.textbbox((0, 0), label, font=font(15))
            draw.text((x - (box[2] - box[0]) / 2, top + plot_height + 18), label,
                      font=font(15), fill="#64748b")
        for value in ticks:
            y = top + round((high - value) / (high - low) * plot_height)
            draw.line((plot_left, y, plot_left + plot_width, y), fill="#dbe4ef", width=1)
            draw.text((57, y - 9), f"{value:g}", font=font(15), fill="#64748b")
        for location in LOCATIONS:
            value = stats[location]
            if value is None:
                continue
            for segment in line_segments(value.readings):
                points = []
                for item in segment:
                    x = plot_left + (item.measured_at.astimezone(TIMEZONE) - start).total_seconds() / total_seconds * plot_width
                    sample = float(getattr(item, field))
                    y = top + (high - sample) / (high - low) * plot_height
                    points.append((round(x), round(y)))
                if len(points) >= 2:
                    draw.line(points, fill=COLORS[location], width=4, joint="curve")
                elif points:
                    x, y = points[0]
                    draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=COLORS[location])

    draw.text((640, 1125), "Синий — 1 этаж · оранжевый — 2 этаж · разрыв линии — нет данных больше часа",
              font=font(15), fill="#64748b", anchor="mm")
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    return output.getvalue()


def caption(stats: dict[str, FloorStats | None], start: datetime, end: datetime) -> str:
    lines = ["🏠 <b>Климат дома · неделя</b>", f"🗓 {start:%d.%m %H:%M} — {end:%d.%m %H:%M} МСК"]
    for location in LOCATIONS:
        value = stats[location]
        if value is None:
            lines.append(f"⚠️ {LABELS[location]}: нет данных")
        else:
            lines.append(f"🌡 {LABELS[location]}: среднее {value.temperature_mean:.1f} °C · влажность {value.humidity_mean:.0f}% · данные {value.coverage_percent:.0f}%")
    return "\n".join(lines)


def recipients() -> list[int]:
    value = os.getenv("TELEGRAM_REPORT_CHAT_IDS") or os.environ["TELEGRAM_ADMIN_USER_IDS"]
    try:
        result = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise RuntimeError("Telegram report recipients must be numeric IDs") from exc
    if not result:
        raise RuntimeError("No Telegram report recipients configured")
    return result


def send_report(image: bytes, message: str) -> list[int]:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    proxy = os.getenv("TELEGRAM_PROXY_URL")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    sent = []
    for chat_id in recipients():
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": message, "parse_mode": "HTML"},
                files={"photo": ("climate_weekly.png", image, "image/png")},
                proxies=proxies, timeout=(10, 40),
            )
            payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Telegram connection failed: {type(exc).__name__}") from None
        except ValueError:
            raise RuntimeError(f"Telegram returned HTTP {response.status_code} with invalid JSON") from None
        if response.status_code >= 400 or not payload.get("ok"):
            raise RuntimeError(f"Telegram rejected report with HTTP {response.status_code}")
        sent.append(chat_id)
    return sent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--end", type=datetime.fromisoformat)
    args = parser.parse_args()
    now = args.end.replace(tzinfo=TIMEZONE) if args.end and args.end.tzinfo is None else args.end
    start, end = report_window(now)
    values = summarize(fetch_readings(start, end), start, end)
    picture = render_report(values, start, end)
    if args.output:
        args.output.write_bytes(picture)
        args.output.chmod(0o600)
    delivered = send_report(picture, caption(values, start, end)) if args.send else []
    print(json.dumps({"period_start": start.isoformat(), "period_end": end.isoformat(),
                      "sent_count": len(delivered), "dry_run": not args.send}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
