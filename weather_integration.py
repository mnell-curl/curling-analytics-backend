"""
Weather integration — pulls historical weather for an event's host city
and date range, using Open-Meteo (free, no API key required).

Unlike everything else in this project, this is NOT a CurlingZone scraper —
it's a separate, well-documented public API. Two Open-Meteo endpoints:

1. Geocoding API — turns a city name into lat/lon coordinates.
2. Archive (historical weather) API — daily weather for a lat/lon + date range.

Usage:
    py weather_integration.py <event_id>

Reads `location` and `dates` off the `events` table (populated by
roster_scraper.py's `game-meta` mode — run that first if an event's
location/dates are still empty), geocodes the city, fetches daily
weather for the full event date range, and saves it.

Example:
    py weather_integration.py 9205
"""

import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

import requests

DB_PATH = "curling.db"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# WMO weather codes -> plain-English description, for readability.
# https://open-meteo.com/en/docs (see "WMO Weather interpretation codes")
WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def create_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_weather (
            event_id INTEGER,
            date TEXT,
            temp_max_c REAL,
            temp_min_c REAL,
            precipitation_mm REAL,
            weather_code INTEGER,
            weather_description TEXT,
            humidity_min_pct REAL,
            humidity_max_pct REAL,
            humidity_mean_pct REAL,
            pressure_mean_hpa REAL,
            dew_point_mean_c REAL,
            PRIMARY KEY (event_id, date)
        )
        """
    )
    conn.commit()


def parse_date_range(dates_str: str):
    """
    Parses the `events.dates` text field into (start_date, end_date) as
    ISO strings. Handles both same-month ("Aug 14 - 17, 2025") and
    cross-month ("Aug 30 - Sep 2, 2025") formats — confirmed both occur
    in practice, since events can span a month boundary.
    """
    m = re.match(r"(\w+)\s+(\d+)\s*-\s*(\d+),\s*(\d{4})", dates_str)
    if m:
        month, start_day, end_day, year = m.groups()
        start = datetime.strptime(f"{month} {start_day} {year}", "%b %d %Y")
        end = datetime.strptime(f"{month} {end_day} {year}", "%b %d %Y")
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    m = re.match(r"(\w+)\s+(\d+)\s*-\s*(\w+)\s+(\d+),\s*(\d{4})", dates_str)
    if m:
        start_month, start_day, end_month, end_day, year = m.groups()
        start = datetime.strptime(f"{start_month} {start_day} {year}", "%b %d %Y")
        end = datetime.strptime(f"{end_month} {end_day} {year}", "%b %d %Y")
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    return None, None


def geocode_city(location: str):
    """
    `location` is stored as "City, Country" (e.g. "Baden-Daettwil,
    Switzerland"). The geocoding API works best on just the city name,
    so split off the country and use it only to help disambiguate if
    multiple cities share a name.
    """
    parts = [p.strip() for p in location.split(",")]
    city = parts[0]
    country_hint = parts[1] if len(parts) > 1 else None

    resp = requests.get(GEOCODE_URL, params={"name": city, "count": 5}, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    if not results:
        return None

    if country_hint:
        for r in results:
            if country_hint.lower() in r.get("country", "").lower():
                return r

    return results[0]  # best guess if no country match


def fetch_historical_weather(lat: float, lon: float, start_date: str, end_date: str):
    resp = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            # Humidity/pressure/dew point aren't requested as daily aggregates
            # here — we weren't fully confident those daily-aggregate names
            # are supported, so we pull them hourly (a documented, safe bet)
            # and compute daily min/max/mean ourselves below.
            "hourly": "relative_humidity_2m,surface_pressure,dew_point_2m",
            "timezone": "auto",
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    daily = payload["daily"]
    hourly = payload["hourly"]

    # Group hourly readings by date to compute per-day humidity/pressure/dew point stats.
    by_date = defaultdict(lambda: {"humidity": [], "pressure": [], "dew_point": []})
    for i, ts in enumerate(hourly["time"]):
        date = ts.split("T")[0]
        by_date[date]["humidity"].append(hourly["relative_humidity_2m"][i])
        by_date[date]["pressure"].append(hourly["surface_pressure"][i])
        by_date[date]["dew_point"].append(hourly["dew_point_2m"][i])

    days = []
    for i, date in enumerate(daily["time"]):
        h = by_date[date]["humidity"]
        p = by_date[date]["pressure"]
        d = by_date[date]["dew_point"]

        days.append({
            "date": date,
            "temp_max_c": daily["temperature_2m_max"][i],
            "temp_min_c": daily["temperature_2m_min"][i],
            "precipitation_mm": daily["precipitation_sum"][i],
            "weather_code": daily["weathercode"][i],
            "humidity_min_pct": min(h) if h else None,
            "humidity_max_pct": max(h) if h else None,
            "humidity_mean_pct": round(sum(h) / len(h), 1) if h else None,
            "pressure_mean_hpa": round(sum(p) / len(p), 1) if p else None,
            "dew_point_mean_c": round(sum(d) / len(d), 1) if d else None,
        })
    return days


def save_weather(event_id: int, days: list):
    conn = sqlite3.connect(DB_PATH)
    create_table(conn)
    cur = conn.cursor()
    for d in days:
        cur.execute(
            """
            INSERT INTO event_weather (
                event_id, date, temp_max_c, temp_min_c, precipitation_mm,
                weather_code, weather_description,
                humidity_min_pct, humidity_max_pct, humidity_mean_pct,
                pressure_mean_hpa, dew_point_mean_c
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, date) DO UPDATE SET
                temp_max_c = excluded.temp_max_c,
                temp_min_c = excluded.temp_min_c,
                precipitation_mm = excluded.precipitation_mm,
                weather_code = excluded.weather_code,
                weather_description = excluded.weather_description,
                humidity_min_pct = excluded.humidity_min_pct,
                humidity_max_pct = excluded.humidity_max_pct,
                humidity_mean_pct = excluded.humidity_mean_pct,
                pressure_mean_hpa = excluded.pressure_mean_hpa,
                dew_point_mean_c = excluded.dew_point_mean_c
            """,
            (
                event_id, d["date"], d["temp_max_c"], d["temp_min_c"],
                d["precipitation_mm"], d["weather_code"],
                WEATHER_CODES.get(d["weather_code"], "Unknown"),
                d["humidity_min_pct"], d["humidity_max_pct"], d["humidity_mean_pct"],
                d["pressure_mean_hpa"], d["dew_point_mean_c"],
            ),
        )
    conn.commit()
    conn.close()


def run(event_id: int):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT event_name, location, dates FROM events WHERE event_id = ?", (event_id,)
    ).fetchone()
    conn.close()

    if row is None:
        raise ValueError(f"No event with event_id={event_id} in the database")

    event_name, location, dates = row
    if not location or not dates:
        raise ValueError(
            f"Event {event_id} is missing location/dates — run "
            f"'py roster_scraper.py game-meta <cz_game_id>' for this event first."
        )

    print(f"{event_name} — {location}, {dates}")

    start_date, end_date = parse_date_range(dates)
    if not start_date:
        raise ValueError(f"Could not parse date range from: {dates!r}")
    print(f"Date range: {start_date} to {end_date}")

    place = geocode_city(location)
    if place is None:
        raise ValueError(f"Could not geocode location: {location!r}")
    print(f"Geocoded to: {place['name']}, {place.get('country')} ({place['latitude']}, {place['longitude']})")

    days = fetch_historical_weather(place["latitude"], place["longitude"], start_date, end_date)
    print(f"\nWeather during event ({len(days)} days):")
    for d in days:
        desc = WEATHER_CODES.get(d["weather_code"], "Unknown")
        print(
            f"  {d['date']}: {d['temp_min_c']}\u2013{d['temp_max_c']}\u00b0C, {d['precipitation_mm']}mm, {desc} | "
            f"humidity {d['humidity_min_pct']}\u2013{d['humidity_max_pct']}% (avg {d['humidity_mean_pct']}%), "
            f"pressure {d['pressure_mean_hpa']} hPa, dew point {d['dew_point_mean_c']}\u00b0C"
        )

    save_weather(event_id, days)
    print(f"\nSaved {len(days)} days of weather for event_id={event_id}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py weather_integration.py <event_id>")
        sys.exit(1)

    run(int(sys.argv[1]))
