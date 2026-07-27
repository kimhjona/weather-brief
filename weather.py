#!/usr/bin/env python3
"""weather-brief: a one-glance morning weather brief, in Celsius.

Answers two questions and nothing else: what should I wear, and do I need
an umbrella. Standard library only, no API keys.

  weather.py set-location 94110    save where you are
  weather.py set-topic             pick an ntfy topic for phone pushes
  weather.py                       print today's brief
  weather.py send                  print it and push it to your phone
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://api.zippopotam.us"
NTFY_URL = "https://ntfy.sh"

# The hours we actually care about dressing for.
DAY_START, DAY_END = 7, 21

# Two ways a day earns an umbrella: enough rain in total to soak you eventually,
# or one hour heavy enough to soak you at once. Below both, the brief stays quiet.
# 5mm is about 0.2 inches. 1.5mm in an hour is the top of "light rain" and well
# clear of drizzle, which runs nearer 0.2mm/hr.
DEFAULT_UMBRELLA_MM = 5.0
DEFAULT_UMBRELLA_PEAK_MM = 1.5

# An hour counts as "raining" when naming the wet stretches. Set above drizzle so
# a long damp tail does not widen the window.
WET_HOUR_MM = 0.3

# Feels-like ceiling, the word for it, and what to put on. Ordered high to low.
WARDROBE = (
    (26, "Hot", "🩳👕"),
    (18, "Warm", "👕"),
    (14, "Cool", "👕🧥"),
    (10, "Chilly", "🧥"),
    (5, "Cold", "🧥🧣"),
    (0, "Very cold", "🧥🧣🧤"),
)
FREEZING = ("Freezing", "🧥🧣🧤🥾")

WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "heavy rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


# ---------------------------------------------------------------- config

def config_path() -> Path:
    override = os.environ.get("WEATHER_BRIEF_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".config" / "weather-brief" / "config.json"


def load_config() -> dict:
    path = config_path()
    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            die(f"{path} is not valid JSON ({exc}). Fix or delete it.")

    # Environment wins, so CI can run without a config file on disk.
    for key, env in (("lat", "WEATHER_LAT"), ("lon", "WEATHER_LON")):
        if os.environ.get(env):
            cfg[key] = float(os.environ[env])
    if os.environ.get("WEATHER_LABEL"):
        cfg["label"] = os.environ["WEATHER_LABEL"]
    if os.environ.get("NTFY_TOPIC"):
        cfg["ntfy_topic"] = os.environ["NTFY_TOPIC"]
    return cfg


def save_config(cfg: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    return path


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


# ------------------------------------------------------------------ http

def fetch_json(url: str, payload: dict | None = None, timeout: int = 20) -> dict:
    """GET, or POST if payload is given. Retries transient failures."""
    data = None
    headers = {"User-Agent": "weather-brief/1.0"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            # 4xx will not fix itself; stop immediately.
            if exc.code < 500:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
        time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


# -------------------------------------------------------------- location

def geocode_zip(zip_code: str, country: str = "us") -> dict:
    url = f"{GEOCODE_URL}/{country.lower()}/{zip_code.strip().replace(' ', '%20')}"
    try:
        data = fetch_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            die(f"no such postal code: {zip_code} ({country.upper()})")
        raise
    places = data.get("places") or []
    if not places:
        die(f"no such postal code: {zip_code} ({country.upper()})")
    place = places[0]
    city = place.get("place name", "").strip()
    code = str(data.get("post code", zip_code)).strip()
    label = f"{city} {code}".strip() if city else code
    return {"lat": float(place["latitude"]), "lon": float(place["longitude"]), "label": label}


# -------------------------------------------------------------- forecast

def get_forecast(lat: float, lon: float) -> dict:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "timezone": "auto",
        "forecast_days": "1",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "apparent_temperature_max", "apparent_temperature_min",
            "precipitation_sum", "snowfall_sum", "precipitation_probability_max",
            "wind_speed_10m_max", "uv_index_max",
        ]),
        "hourly": ",".join([
            "temperature_2m", "apparent_temperature",
            "precipitation_probability", "precipitation",
        ]),
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return fetch_json(f"{FORECAST_URL}?{query}")


def local_now(forecast: dict) -> datetime:
    """Wall-clock time at the forecast location, without needing tzdata."""
    offset = timedelta(seconds=forecast.get("utc_offset_seconds", 0))
    return datetime.now(timezone.utc).astimezone(timezone(offset))


# ---------------------------------------------------------------- advice

def dress_advice(feels_max: float) -> tuple[str, str]:
    """Returns (word, icons) for the day's feels-like high."""
    for threshold, word, icons in WARDROBE:
        if feels_max >= threshold:
            return word, icons
    return FREEZING


def fmt_range(lo: float, hi: float) -> str:
    """A hyphen reads as a minus sign once either end goes below zero."""
    if lo < 0 or hi < 0:
        return f"{lo:.0f} to {hi:.0f}"
    return f"{lo:.0f}-{hi:.0f}"


def fmt_hour(hour: int) -> str:
    suffix = "am" if hour < 12 else "pm"
    display = hour % 12 or 12
    return f"{display}{suffix}"


def fmt_run(run: list[dict]) -> str:
    start, end = run[0]["hour"], run[-1]["hour"] + 1
    if end - start <= 1:
        return f"around {fmt_hour(start)}"
    return f"{fmt_hour(start)} to {fmt_hour(end)}"


def rain_report(hours: list[dict], from_hour: int, threshold_mm: float,
                peak_mm: float = DEFAULT_UMBRELLA_PEAK_MM) -> str | None:
    """The umbrella line, or None when there is not enough rain to mention.

    Only counts rain still to come. Rain that already fell overnight should not
    talk you into carrying an umbrella.
    """
    upcoming = [h for h in hours if h["hour"] >= from_hour]
    total = sum(h["mm"] for h in upcoming)
    peak = max((h["mm"] for h in upcoming), default=0.0)
    if total < threshold_mm and peak < peak_mm:
        return None

    runs, current = [], []
    for h in upcoming:
        if h["mm"] >= WET_HOUR_MM:
            if current and h["hour"] != current[-1]["hour"] + 1:
                runs.append(current)
                current = []
            current.append(h)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    amount = f"{total:.0f}mm" if total >= 1 else f"{total:.1f}mm"
    if not runs:
        return f"☂️ Umbrella. {amount} of rain today."
    # Rank by how much rain each stretch actually delivers, not how long it is.
    runs.sort(key=lambda r: sum(h["mm"] for h in r), reverse=True)
    if len(runs) > 2:
        spread = sorted(runs, key=lambda r: r[0]["hour"])
        window = (f"on and off from {fmt_hour(spread[0][0]['hour'])} "
                  f"to {fmt_hour(spread[-1][-1]['hour'] + 1)}")
    else:
        window = " and ".join(fmt_run(r) for r in
                              sorted(runs[:2], key=lambda r: r[0]["hour"]))
    return f"☂️ Umbrella. Rain {window} ({amount})."


# ----------------------------------------------------------------- brief

def build_brief(forecast: dict, label: str, from_hour: int = 0,
                threshold_mm: float = DEFAULT_UMBRELLA_MM,
                peak_mm: float = DEFAULT_UMBRELLA_PEAK_MM) -> dict:
    daily = forecast["daily"]
    hourly = forecast["hourly"]
    today = daily["time"][0]

    def d(key, default=0.0):
        value = daily.get(key, [None])[0]
        return default if value is None else value

    hours = []
    for i, stamp in enumerate(hourly["time"]):
        if not stamp.startswith(today):
            continue
        hours.append({
            "hour": int(stamp[11:13]),
            "feels": hourly["apparent_temperature"][i],
            "temp": hourly["temperature_2m"][i],
            "prob": hourly["precipitation_probability"][i] or 0,
            "mm": hourly["precipitation"][i] or 0.0,
        })

    daytime = [h for h in hours if DAY_START <= h["hour"] <= DAY_END
               and h["feels"] is not None and h["temp"] is not None]
    if daytime:
        feels_max = max(h["feels"] for h in daytime)
        feels_min = min(h["feels"] for h in daytime)
        temp_max = max(h["temp"] for h in daytime)
        temp_min = min(h["temp"] for h in daytime)
    else:
        # Running late in the day, or a sparse response. Fall back to the daily rollup.
        feels_max = d("apparent_temperature_max")
        feels_min = d("apparent_temperature_min")
        temp_max = d("temperature_2m_max")
        temp_min = d("temperature_2m_min")

    prob = d("precipitation_probability_max")
    snow = d("snowfall_sum")
    wind = d("wind_speed_10m_max")
    uv = d("uv_index_max")
    code = int(d("weather_code"))

    word, icons = dress_advice(feels_max)
    headline = f"{icons} {word}, {fmt_range(temp_min, temp_max)}°C"

    # Silence is the answer for a dry day. Only speak up when it matters.
    if snow >= 0.5:
        rain, tag = f"🌨 Snow, {snow:.0f}cm. Boots.", "snowflake"
    else:
        rain = rain_report(hours, from_hour, threshold_mm, peak_mm)
        tag = "umbrella" if rain else ("sunny" if code in (0, 1) else "cloud")

    notes = []
    if feels_max >= 38:
        notes.append(f"Feels like {feels_max:.0f}°C. Stay in the shade and drink more than you want to.")
    elif feels_min <= -10:
        notes.append(f"Feels like {feels_min:.0f}°C. Cover every bit of skin.")
    if feels_max - feels_min >= 9:
        notes.append(f"Big swing, {feels_min:.0f}° to {feels_max:.0f}°. Wear layers.")
    if wind >= 35:
        notes.append(f"Windy, gusting to {wind:.0f} km/h. Something windproof.")
    if uv >= 7 and prob < 50:
        notes.append(f"UV index {uv:.0f}. Sunscreen.")

    when_dt = datetime.strptime(today, "%Y-%m-%d")
    footer = (f"{label} · {when_dt.strftime('%a %-d %b')} · "
              f"{WMO.get(code, 'mixed')} · feels {fmt_range(feels_min, feels_max)}°C")

    lines = ([rain] if rain else []) + notes + [footer]
    return {
        "title": headline,
        "body": "\n".join(lines),
        "tag": tag,
        "hours": hours,
    }


def render_detail(hours: list[dict]) -> str:
    rows = []
    for h in hours:
        if not (6 <= h["hour"] <= 22) or h["hour"] % 2:
            continue
        bar = "|" * int(round((h["prob"] or 0) / 10))
        rows.append(f"  {fmt_hour(h['hour']):>5}  {h['temp']:>5.1f}°C  "
                    f"feels {h['feels']:>5.1f}°C  {h['prob']:>3.0f}% {bar}")
    return "\n".join(rows)


# ------------------------------------------------------------------ ntfy

def push(topic: str, brief: dict) -> None:
    fetch_json(NTFY_URL, payload={
        "topic": topic,
        "title": brief["title"],
        "message": brief["body"],
        "tags": [brief["tag"]],
        "priority": 3,
    })


# ------------------------------------------------------------------- cli

def require_location(cfg: dict) -> tuple[float, float, str]:
    if "lat" not in cfg or "lon" not in cfg:
        die("no location saved. Run: weather.py set-location 94110")
    return cfg["lat"], cfg["lon"], cfg.get("label", "Home")


def cmd_set_location(args) -> int:
    cfg = load_config()
    if args.coords:
        try:
            lat, lon = (float(p) for p in args.coords.split(","))
        except ValueError:
            die("--coords wants two numbers, like: --coords 37.75,-122.42")
        found = {"lat": lat, "lon": lon, "label": args.name or f"{lat:.2f},{lon:.2f}"}
    else:
        if not args.zip_code:
            die("give a postal code, or --coords LAT,LON")
        found = geocode_zip(args.zip_code, args.country)
        if args.name:
            found["label"] = args.name
    cfg.update(found)
    path = save_config(cfg)
    print(f"Saved {found['label']} ({found['lat']:.4f}, {found['lon']:.4f}) to {path}")
    return 0


def cmd_set_topic(args) -> int:
    cfg = load_config()
    topic = args.topic or f"weather-{secrets.token_hex(8)}"
    cfg["ntfy_topic"] = topic
    path = save_config(cfg)
    print(f"Saved topic to {path}\n")
    print("Now, on your phone:")
    print("  1. Install ntfy from the App Store")
    print("  2. Tap + and subscribe to this exact topic:\n")
    print(f"       {topic}\n")
    print("Test it with: weather.py send")
    print("\nAnyone who knows the topic name can read it, which is why it is random.")
    return 0


def cmd_where(args) -> int:
    cfg = load_config()
    lat, lon, label = require_location(cfg)
    print(f"{label}  ({lat:.4f}, {lon:.4f})")
    print(f"topic: {cfg.get('ntfy_topic', '(none set)')}")
    print(f"config: {config_path()}")
    return 0


def cmd_today(args) -> int:
    cfg = load_config()
    lat, lon, label = require_location(cfg)
    forecast = get_forecast(lat, lon)
    now = local_now(forecast)

    if args.at_hour is not None and now.hour != args.at_hour:
        print(f"local time is {now:%H:%M}, not {args.at_hour:02d}:00. Nothing sent.")
        return 0

    brief = build_brief(forecast, label, from_hour=0 if args.full_day else now.hour,
                        threshold_mm=cfg.get("umbrella_mm", DEFAULT_UMBRELLA_MM),
                        peak_mm=cfg.get("umbrella_peak_mm", DEFAULT_UMBRELLA_PEAK_MM))

    print(brief["title"])
    print(brief["body"])
    if args.detail:
        print()
        print(render_detail(brief["hours"]))

    if args.send:
        topic = cfg.get("ntfy_topic")
        if not topic:
            die("no ntfy topic saved. Run: weather.py set-topic")
        if args.dry_run:
            print(f"\n[dry run] would push to {NTFY_URL}/{topic}")
        else:
            push(topic, brief)
            print(f"\nPushed to {NTFY_URL}/{topic}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="weather.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("set-location", help="save a postal code or coordinates")
    p.add_argument("zip_code", nargs="?", help="postal code, e.g. 94110")
    p.add_argument("--country", default="us", help="two-letter country code (default: us)")
    p.add_argument("--coords", help="LAT,LON instead of a postal code")
    p.add_argument("--name", help="override the display name")
    p.set_defaults(func=cmd_set_location)

    p = sub.add_parser("set-topic", help="set the ntfy topic for phone pushes")
    p.add_argument("topic", nargs="?", help="topic name (default: generate a random one)")
    p.set_defaults(func=cmd_set_topic)

    p = sub.add_parser("where", help="show the saved location and topic")
    p.set_defaults(func=cmd_where)

    for name, help_text in (("today", "print today's brief"),
                            ("send", "print today's brief and push it to your phone")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--detail", action="store_true", help="also show an hourly table")
        p.add_argument("--at-hour", type=int, metavar="H",
                       help="do nothing unless the local hour is H (for UTC cron)")
        p.add_argument("--dry-run", action="store_true", help="do not actually push")
        p.add_argument("--full-day", action="store_true",
                       help="count rain from midnight, not from now")
        p.set_defaults(func=cmd_today, send=(name == "send"))

    # argparse reads "--coords -54.8,-68.3" as a flag. Southern latitudes are real.
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, token in enumerate(argv[:-1]):
        if token == "--coords" and argv[i + 1].startswith("-"):
            argv[i:i + 2] = [f"--coords={argv[i + 1]}"]
            break

    args = parser.parse_args(argv)
    if args.command is None:
        # Bare `weather.py` is the common case: just print today.
        args = parser.parse_args(["today"])
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except urllib.error.HTTPError as exc:
        die(f"{exc.url} returned HTTP {exc.code}")
    except urllib.error.URLError as exc:
        die(f"network unreachable: {exc.reason}")
