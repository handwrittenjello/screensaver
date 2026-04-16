import os
import json
import random
import re
import sqlite3
import subprocess
import sys
import time
import requests
from math import radians, sin, cos, sqrt, atan2
from flask import Flask, jsonify, render_template, request

try:
    from PIL import Image as PilImage
    from io import BytesIO
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

app = Flask(__name__)

# Load configuration from /config/config.json
def load_config():
    config_path = os.path.join(os.getcwd(), "config", "config.json")
    with open(config_path) as f:
        return json.load(f)

config_data = load_config()

# Airport lookup — populated by download_airports.py
_airports_path = os.path.join(os.getcwd(), "data", "airports.json")
_airports = {}
if os.path.exists(_airports_path):
    with open(_airports_path, encoding="utf-8") as _f:
        _airports = json.load(_f)

_AIRCRAFT_TYPES_DIR  = os.path.join(os.getcwd(), "static", "aircraft_types")
_AIRCRAFT_PHOTOS_DIR = os.path.join(os.getcwd(), "static", "aircraft_photos")
os.makedirs(_AIRCRAFT_TYPES_DIR,  exist_ok=True)
os.makedirs(_AIRCRAFT_PHOTOS_DIR, exist_ok=True)

_DB_PATH = os.path.join(os.getcwd(), "data", "routes.db")

def _init_db():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS route_cache (
            callsign          TEXT PRIMARY KEY,
            last_updated      INTEGER,
            origin            TEXT,
            destination       TEXT,
            airline_iata      TEXT,
            airline_icao      TEXT,
            hex               TEXT,
            reg_number        TEXT,
            flight_iata       TEXT,
            flight_icao       TEXT,
            flight_number     TEXT,
            cs_airline_iata   TEXT,
            cs_flight_iata    TEXT,
            cs_flight_number  TEXT,
            dep_icao          TEXT,
            dep_terminal      TEXT,
            dep_gate          TEXT,
            dep_time          TEXT,
            dep_time_ts       INTEGER,
            dep_time_utc      TEXT,
            dep_estimated     TEXT,
            dep_estimated_ts  INTEGER,
            dep_estimated_utc TEXT,
            dep_delayed       INTEGER,
            arr_icao          TEXT,
            arr_terminal      TEXT,
            arr_gate          TEXT,
            arr_baggage       TEXT,
            arr_time          TEXT,
            arr_time_ts       INTEGER,
            arr_time_utc      TEXT,
            arr_estimated     TEXT,
            arr_estimated_ts  INTEGER,
            arr_estimated_utc TEXT,
            arr_delayed       INTEGER,
            duration          INTEGER,
            status            TEXT,
            updated           INTEGER,
            aircraft_icao     TEXT,
            flag              TEXT,
            lat               REAL,
            lng               REAL,
            alt               REAL,
            dir               REAL,
            speed             REAL,
            v_speed           REAL,
            squawk            TEXT,
            model             TEXT,
            manufacturer      TEXT,
            msn               TEXT,
            type              TEXT,
            engine            TEXT,
            engine_count      TEXT,
            built             INTEGER,
            age               INTEGER
        )
    """)
    con.commit()

    # Migrate: add columns introduced after initial schema
    for col_def in [
        "data_source TEXT",
        "dep_municipality TEXT",
        "arr_municipality TEXT",
        "dep_country TEXT",
        "arr_country TEXT",
        "is_cargo INTEGER",
    ]:
        try:
            con.execute(f"ALTER TABLE route_cache ADD COLUMN {col_def}")
        except Exception:
            pass  # column already exists

    # Second table: persistent aircraft photo cache keyed by model string
    con.execute("""
        CREATE TABLE IF NOT EXISTS aircraft_photo_cache (
            key          TEXT PRIMARY KEY,
            local_path   TEXT,
            source_url   TEXT,
            source       TEXT,
            last_updated INTEGER
        )
    """)

    con.commit()
    con.close()

_init_db()

def _airport_city(iata):
    """Return city name for an IATA code, or '' if unknown."""
    return _airports.get(iata, {}).get("city", "") if iata else ""

def _get_route_from_airlabs(callsign):
    """
    Fetch scheduled flight data from AirLabs.co, persist all fields to DB.
    Returns parsed route dict or {} on failure.
    """
    api_key = config_data.get("AIRLABS_API_KEY", "")
    if not api_key or not callsign:
        return {}
    cs = callsign.strip().upper()
    try:
        r = requests.get(
            "https://airlabs.co/api/v9/flight",
            params={"flight_icao": cs, "api_key": api_key},
            timeout=5,
        )
        if r.status_code != 200:
            return {}
        body = r.json()
        if "error" in body:
            return {}
        f = body.get("response", {})
        if not f:
            return {}

        now = int(time.time())
        con = sqlite3.connect(_DB_PATH)
        con.execute("""
            INSERT OR REPLACE INTO route_cache (
                callsign, last_updated,
                origin, destination, airline_iata, airline_icao,
                hex, reg_number, flight_iata, flight_icao, flight_number,
                cs_airline_iata, cs_flight_iata, cs_flight_number,
                dep_icao, dep_terminal, dep_gate,
                dep_time, dep_time_ts, dep_time_utc,
                dep_estimated, dep_estimated_ts, dep_estimated_utc, dep_delayed,
                arr_icao, arr_terminal, arr_gate, arr_baggage,
                arr_time, arr_time_ts, arr_time_utc,
                arr_estimated, arr_estimated_ts, arr_estimated_utc, arr_delayed,
                duration, status, updated,
                aircraft_icao, flag, lat, lng, alt, dir, speed, v_speed, squawk,
                model, manufacturer, msn, type, engine, engine_count, built, age
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
        """, (
            cs, now,
            f.get("dep_iata", ""), f.get("arr_iata", ""),
            f.get("airline_iata", ""), f.get("airline_icao", ""),
            f.get("hex", ""), f.get("reg_number", ""),
            f.get("flight_iata", ""), f.get("flight_icao", ""), f.get("flight_number", ""),
            f.get("cs_airline_iata", ""), f.get("cs_flight_iata", ""), f.get("cs_flight_number", ""),
            f.get("dep_icao", ""), f.get("dep_terminal", ""), f.get("dep_gate", ""),
            f.get("dep_time", ""), f.get("dep_time_ts"), f.get("dep_time_utc", ""),
            f.get("dep_estimated", ""), f.get("dep_estimated_ts"), f.get("dep_estimated_utc", ""),
            f.get("dep_delayed"),
            f.get("arr_icao", ""), f.get("arr_terminal", ""), f.get("arr_gate", ""),
            f.get("arr_baggage", ""),
            f.get("arr_time", ""), f.get("arr_time_ts"), f.get("arr_time_utc", ""),
            f.get("arr_estimated", ""), f.get("arr_estimated_ts"), f.get("arr_estimated_utc", ""),
            f.get("arr_delayed"),
            f.get("duration"), f.get("status", ""), f.get("updated"),
            f.get("aircraft_icao", ""), f.get("flag", ""),
            f.get("lat"), f.get("lng"), f.get("alt"), f.get("dir"),
            f.get("speed"), f.get("v_speed"), f.get("squawk", ""),
            f.get("model", ""), f.get("manufacturer", ""), f.get("msn", ""),
            f.get("type", ""), f.get("engine", ""), f.get("engine_count", ""),
            f.get("built"), f.get("age"),
        ))
        con.commit()
        con.close()

        return {
            "origin":       f.get("dep_iata", ""),
            "destination":  f.get("arr_iata", ""),
            "airline_iata": f.get("airline_iata", ""),
        }
    except Exception:
        return {}


def _get_route_from_aerodatabox(callsign):
    """
    Fetch scheduled flight data from AeroDataBox via RapidAPI (Tier 2 endpoint).
    Persists all available fields to route_cache DB.
    Returns {'origin', 'destination', 'airline_iata'} or {} on failure.
    """
    api_key = config_data.get("AERODATABOX_RAPIDAPI_KEY", "")
    if not api_key or not callsign:
        return {}
    cs = callsign.strip().upper()
    try:
        r = requests.get(
            f"https://aerodatabox.p.rapidapi.com/flights/callsign/{cs}",
            headers={
                "x-rapidapi-key":  api_key,
                "x-rapidapi-host": "aerodatabox.p.rapidapi.com",
            },
            timeout=5,
        )
        if r.status_code != 200:
            return {}
        # AeroDataBox sometimes appends a rate-limit JSON object after the valid array,
        # making the full body invalid JSON. raw_decode() stops at the first value.
        try:
            flights, _ = json.JSONDecoder().raw_decode(r.text.strip())
        except ValueError:
            return {}
        if not flights or not isinstance(flights, list):
            return {}
        f        = flights[0]
        dep      = f.get("departure", {})
        arr      = f.get("arrival",   {})
        dep_apt  = dep.get("airport", {})
        arr_apt  = arr.get("airport", {})
        airline  = f.get("airline",   {})
        aircraft = f.get("aircraft",  {})
        dep_sched = dep.get("scheduledTime", {})
        arr_sched = arr.get("scheduledTime", {})
        dep_rev   = dep.get("revisedTime",   {}) or {}
        arr_rev   = arr.get("revisedTime",   {}) or {}

        now = int(time.time())
        con = sqlite3.connect(_DB_PATH)
        con.execute("""
            INSERT OR REPLACE INTO route_cache (
                callsign, last_updated, data_source,
                origin, destination, airline_iata, airline_icao,
                dep_icao, arr_icao,
                dep_municipality, arr_municipality,
                dep_country, arr_country,
                dep_terminal, arr_terminal,
                dep_gate, arr_gate, arr_baggage,
                dep_time_utc, arr_time_utc,
                dep_time, arr_time,
                dep_estimated_utc, arr_estimated_utc,
                status, flight_number,
                reg_number, model, hex, is_cargo
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            cs, now, "aerodatabox",
            dep_apt.get("iata",             ""),
            arr_apt.get("iata",             ""),
            airline.get("iata",             ""),
            airline.get("icao",             ""),
            dep_apt.get("icao",             ""),
            arr_apt.get("icao",             ""),
            dep_apt.get("municipalityName", ""),
            arr_apt.get("municipalityName", ""),
            dep_apt.get("countryCode",      ""),
            arr_apt.get("countryCode",      ""),
            dep.get("terminal",    ""),
            arr.get("terminal",    ""),
            dep.get("gate",        ""),
            arr.get("gate",        ""),
            arr.get("baggageBelt", ""),
            dep_sched.get("utc",   ""),
            arr_sched.get("utc",   ""),
            dep_sched.get("local", ""),
            arr_sched.get("local", ""),
            dep_rev.get("utc",     ""),
            arr_rev.get("utc",     ""),
            f.get("status",        ""),
            f.get("number",        ""),
            aircraft.get("reg",    ""),
            aircraft.get("model",  ""),
            aircraft.get("modeS",  ""),
            1 if f.get("isCargo") else 0,
        ))
        con.commit()
        con.close()

        return {
            "origin":       dep_apt.get("iata", ""),
            "destination":  arr_apt.get("iata", ""),
            "airline_iata": airline.get("iata",  ""),
            "model":        aircraft.get("model", ""),
        }
    except Exception as e:
        print(f"[AeroDataBox] error for {callsign}: {e}", flush=True)
        return {}


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# OpenSky OAuth2 token cache (Basic Auth deprecated March 2026)
_opensky_token = {}
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)

def _get_opensky_token():
    """Return a valid Bearer token, refreshing 60s before expiry."""
    now = time.time()
    if _opensky_token.get("access_token") and now < _opensky_token.get("expires_at", 0) - 60:
        return _opensky_token["access_token"]
    client_id     = config_data.get("OPENSKY_CLIENT_ID")
    client_secret = config_data.get("OPENSKY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    try:
        r = requests.post(
            OPENSKY_TOKEN_URL,
            data={
                "grant_type":    "client_credentials",
                "client_id":     client_id,
                "client_secret": client_secret,
            },
            timeout=5,
        )
        r.raise_for_status()
        payload = r.json()
        _opensky_token["access_token"] = payload["access_token"]
        _opensky_token["expires_at"]   = now + payload.get("expires_in", 1800)
        return _opensky_token["access_token"]
    except Exception:
        return None


ROUTE_CACHE_TTL = config_data.get("ROUTE_CACHE_TTL_HOURS", 12) * 3600

def _get_route(icao24, callsign):
    """
    Return route dict with origin/destination IATA codes and airline_iata.
    Checks SQLite DB first (4-hour TTL). Priority: AeroDataBox → AirLabs → adsbdb.
    N-number callsigns (US private aircraft) are tried via AeroDataBox only;
    AirLabs and adsbdb are skipped for them as those sources have no private plane data.
    """
    cache_key = callsign or icao24
    if not cache_key:
        return {}
    cs = cache_key.strip().upper()

    # Detect N-number registrations used as callsigns (e.g. N6843Q, N367QS).
    # AeroDataBox may have IFR flight plan data; AirLabs/adsbdb never do.
    is_n_number = len(cs) >= 2 and cs[0] == 'N' and cs[1].isdigit()

    now = int(time.time())

    # Check DB cache
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT origin, destination, airline_iata, data_source, model, last_updated FROM route_cache WHERE callsign = ?",
            (cs,)
        ).fetchone()
        con.close()
        if row and (now - row["last_updated"]) < ROUTE_CACHE_TTL:
            print(f"[route] {cs}: cache hit origin={row['origin']!r} dest={row['destination']!r} source={row['data_source']!r}", flush=True)
            return {
                "origin":       row["origin"] or "",
                "destination":  row["destination"] or "",
                "airline_iata": row["airline_iata"] or "",
                "model":        row["model"] or "",
            }
    except Exception:
        pass

    data = {}

    # Primary: AeroDataBox via RapidAPI — try for ALL callsigns including N-numbers
    adb_enabled = config_data.get("AERODATABOX_ENABLED", True)
    if adb_enabled and callsign and config_data.get("AERODATABOX_RAPIDAPI_KEY", ""):
        data = _get_route_from_aerodatabox(callsign)
        print(f"[route] {cs}: aerodatabox -> origin={data.get('origin')!r} dest={data.get('destination')!r}", flush=True)
    else:
        print(f"[route] {cs}: aerodatabox SKIPPED (enabled={adb_enabled} key={'set' if config_data.get('AERODATABOX_RAPIDAPI_KEY') else 'MISSING'})", flush=True)

    # Secondary + fallback: skip for N-numbers (AirLabs/adsbdb have no private plane data)
    if not data.get("origin") and not is_n_number:
        # AirLabs
        if callsign:
            data = _get_route_from_airlabs(callsign)
            print(f"[route] {cs}: airlabs -> origin={data.get('origin')!r} dest={data.get('destination')!r}", flush=True)

    # adsbdb fallback (also skipped for N-numbers)
    if not data.get("origin") and not is_n_number and callsign and callsign.strip():
        try:
            r = requests.get(f"https://api.adsbdb.com/v0/callsign/{cs}", timeout=3)
            if r.status_code == 200:
                fr = r.json().get("response", {}).get("flightroute", {})
                data = {
                    "origin":       fr.get("origin", {}).get("iata_code", ""),
                    "destination":  fr.get("destination", {}).get("iata_code", ""),
                    "airline_iata": fr.get("airline", {}).get("iata", ""),
                }
                # Persist adsbdb result so we don't re-fetch within TTL
                print(f"[route] {cs}: adsbdb -> origin={data.get('origin')!r} dest={data.get('destination')!r}", flush=True)
                if data.get("origin"):
                    try:
                        con = sqlite3.connect(_DB_PATH)
                        con.execute(
                            """INSERT OR REPLACE INTO route_cache
                               (callsign, last_updated, origin, destination, airline_iata)
                               VALUES (?, ?, ?, ?, ?)""",
                            (cs, now, data["origin"], data["destination"], data["airline_iata"]),
                        )
                        con.commit()
                        con.close()
                    except Exception:
                        pass
        except Exception:
            pass

    return data


# Aircraft type lookup cache — hexdb.io, free, no key required
_type_cache = {}
TYPE_CACHE_TTL = 86400  # 24 hours

def _get_aircraft_type(icao24):
    """Return {'icao_type': 'B738', 'type_name': 'Boeing 737-800'} or {} on failure."""
    if not icao24:
        return {}
    hex_key = icao24.strip().lower()
    now = time.time()
    cached = _type_cache.get(hex_key)
    if cached and (now - cached["ts"]) < TYPE_CACHE_TTL:
        return cached["data"]
    try:
        r = requests.get(f"https://hexdb.io/api/v1/aircraft/{hex_key}", timeout=3)
        if r.status_code == 200:
            body = r.json()
            data = {
                "icao_type": body.get("ICAOTypeCode", ""),
                "type_name":  body.get("Type", ""),
            }
        else:
            data = {}
    except Exception:
        data = {}
    _type_cache[hex_key] = {"data": data, "ts": now}
    return data


# Aircraft photo cache — disk-backed, survives restarts
_photo_cache = {}
PHOTO_CACHE_TTL = 86400       # 24 hours in-memory TTL
PHOTO_DB_TTL    = 90 * 86400  # 90 days for DB-persisted photos

def _download_image(url, dest_path):
    """Download image bytes to dest_path. Returns True on success."""
    try:
        r = requests.get(url, timeout=5, stream=True)
        if r.status_code == 200 and "image" in r.headers.get("Content-Type", ""):
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return True
    except Exception:
        pass
    return False

def _get_photo(icao24):
    """
    Return a photo URL for an aircraft, or ''.
    Phase 1   — specific aircraft: planespotters.net by ICAO24 hex (CDN URL, no local storage).
    Phase 1.5 — specific aircraft: AeroDataBox by registration; downloads image and caches in
                aircraft_photo_cache DB keyed by model string (e.g. "Embraer Phenom 300") so all
                aircraft of the same model share one cached photo. CC-licensed, attribution required.
    Phase 2   — type fallback: hexdb.io type lookup + planespotters.net type search,
                downloaded to disk; also written to aircraft_photo_cache by model key.
    """
    if not icao24:
        return ""
    hex_key = icao24.strip().lower()
    now = time.time()
    cached = _photo_cache.get(hex_key)
    if cached and (now - cached["ts"]) < PHOTO_CACHE_TTL:
        return cached["url"]

    def _cache(url):
        if url:  # only cache hits; misses fall through every time so new DB entries are picked up
            _photo_cache[hex_key] = {"url": url, "ts": now}
        return url

    def _db_cache_photo(model_key, local_path, source_url, source):
        try:
            con = sqlite3.connect(_DB_PATH)
            con.execute(
                "INSERT OR REPLACE INTO aircraft_photo_cache VALUES (?,?,?,?,?)",
                (model_key, local_path, source_url, source, int(now))
            )
            con.commit()
            con.close()
        except Exception:
            pass

    # Phase 1: specific aircraft photo — Planespotters by ICAO24 hex
    try:
        r = requests.get(
            f"https://api.planespotters.net/pub/photos/hex/{hex_key}", timeout=3
        )
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            if photos:
                print(f"[photo] {hex_key}: planespotters hex hit", flush=True)
                return _cache(photos[0]["thumbnail_large"]["src"])
    except Exception:
        pass

    # Phase 1.5: check our local aircraft_photo_cache DB, then try AeroDataBox API.
    # Step A: look up reg + model from route_cache (modeS stored uppercase, compare case-insensitively)
    reg   = ""
    model = ""
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT reg_number, model FROM route_cache WHERE UPPER(hex) = UPPER(?) AND reg_number != '' LIMIT 1",
            (hex_key,)
        ).fetchone()
        con.close()
        reg   = row["reg_number"] if row else ""
        model = row["model"]      if row else ""
    except Exception:
        pass

    # Step B: check aircraft_photo_cache by model key — always, regardless of API key.
    # This covers images populated by fetch_aircraft_photos.py (Wikipedia/DuckDuckGo)
    # as well as previously downloaded AeroDataBox images.
    adb_already_checked = False
    if model:
        try:
            con2 = sqlite3.connect(_DB_PATH)
            con2.row_factory = sqlite3.Row
            db_row = con2.execute(
                "SELECT local_path FROM aircraft_photo_cache WHERE key = ? AND last_updated > ?",
                (model, int(now) - PHOTO_DB_TTL)
            ).fetchone()
            con2.close()
            if db_row is not None:
                local = db_row["local_path"] or ""
                if local and os.path.exists(os.path.join(os.getcwd(), local.lstrip("/"))):
                    print(f"[photo] {hex_key}: photo cache hit ({model})", flush=True)
                    return _cache(local)
                # Row exists with empty path — AeroDataBox was already tried, skip API call
                adb_already_checked = True
        except Exception:
            pass

    # Step C: call AeroDataBox image API only if we haven't already recorded a miss
    api_key     = config_data.get("AERODATABOX_RAPIDAPI_KEY", "")
    adb_enabled = config_data.get("AERODATABOX_ENABLED", True)
    if adb_enabled and api_key and reg and model and not adb_already_checked:
        try:
            r = requests.get(
                f"https://aerodatabox.p.rapidapi.com/aircrafts/reg/{reg}/image/beta",
                headers={
                    "x-rapidapi-key":  api_key,
                    "x-rapidapi-host": "aerodatabox.p.rapidapi.com",
                },
                timeout=3,
            )
            src_url = ""
            if r.status_code == 200:
                src_url = r.json().get("url", "")
            if src_url:
                safe = model.replace("/", "_").replace(" ", "_")
                dest = os.path.join(_AIRCRAFT_PHOTOS_DIR, f"{safe}.jpg")
                if _download_image(src_url, dest):
                    local_path = f"/static/aircraft_photos/{safe}.jpg"
                    _db_cache_photo(model, local_path, src_url, "aerodatabox")
                    print(f"[photo] {hex_key}: aerodatabox image downloaded ({model})", flush=True)
                    return _cache(local_path)
            # No image found (204, no URL, or download failed) — record the attempt
            print(f"[photo] {hex_key}: aerodatabox no image for {reg!r} model={model!r} status={r.status_code}", flush=True)
            _db_cache_photo(model, "", src_url, "aerodatabox")
        except Exception as e:
            print(f"[photo] {hex_key}: aerodatabox phase error: {e}", flush=True)

    # Phase 2: generic type photo via hexdb.io + Planespotters
    ac_type   = _get_aircraft_type(hex_key)
    icao_type = ac_type.get("icao_type", "")
    if not icao_type:
        return _cache("")

    local_type = os.path.join(_AIRCRAFT_TYPES_DIR, f"type_{icao_type}.jpg")
    if os.path.exists(local_type):
        print(f"[photo] {hex_key}: type image cache hit ({icao_type})", flush=True)
        return _cache(f"/static/aircraft_types/type_{icao_type}.jpg")

    type_name = ac_type.get("type_name", "")
    try:
        r = requests.get(
            f"https://api.planespotters.net/pub/photos/type/{icao_type}", timeout=3
        )
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            if photos:
                src = photos[0]["thumbnail_large"]["src"]
                if _download_image(src, local_type):
                    local_path = f"/static/aircraft_types/type_{icao_type}.jpg"
                    if type_name:
                        _db_cache_photo(type_name, local_path, src, "planespotters")
                    print(f"[photo] {hex_key}: planespotters type downloaded ({icao_type} / {type_name})", flush=True)
                    return _cache(local_path)
    except Exception:
        pass

    # All phases exhausted — record that we checked this model so we don't retry until TTL expires
    if type_name:
        _db_cache_photo(type_name, "", "", "none")

    return _cache("")


@app.route('/')
def index():
    poll_ms = int(config_data.get("FLIGHT_POLL_INTERVAL", 90)) * 1000
    return render_template("index.html", flight_poll_ms=poll_ms)

@app.route('/weather')
def weather():
    # Construct the API URL for OpenWeatherMap One Call 3 API
    api_key = config_data.get("OPENWEATHER_API_KEY")
    lat = config_data.get("LAT")
    lon = config_data.get("LON")
    units = config_data.get("UNITS", "imperial")  # default to imperial
    url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={api_key}&units={units}"

    # Make the API request
    response = requests.get(url)
    if response.status_code != 200:
        return jsonify({"error": "Unable to fetch weather data"}), response.status_code

    data = response.json()

    # Process and simplify the response for the front end.
    simplified = {}

    # Current conditions
    current = data.get("current", {})
    simplified["current"] = {
        "temp": current.get("temp"),
        "feels_like": current.get("feels_like"),
        "humidity": current.get("humidity"),
        "clouds": current.get("clouds"),
        "visibility": current.get("visibility"),
        "dew_point": current.get("dew_point"),
        "wind_speed": current.get("wind_speed"),
        "wind_deg": current.get("wind_deg"),
        "weather": current.get("weather", [{}])[0],  # first weather object
        "units": units
    }

    # Today's forecast (using daily[0])
    daily = data.get("daily", [])
    if daily:
        today = daily[0]
        simplified["today"] = {
            "temp_min": today.get("temp", {}).get("min"),
            "temp_max": today.get("temp", {}).get("max"),
            "pop": today.get("pop"),  # probability of precipitation
            "rain": today.get("rain"),  # mm, absent if no rain
            "snow": today.get("snow"),  # mm, absent if no snow
            "clouds": today.get("clouds"),
            "summary": today.get("summary") or today.get("weather", [{}])[0].get("description", ""),
            "moon_phase": today.get("moon_phase"),
            "moonrise": today.get("moonrise"),
            "moonset": today.get("moonset")
        }

    # 7-Day forecast (daily[1] through daily[7])
    forecast = []
    for day in daily[1:8]:
        forecast.append({
            "dt": day.get("dt"),
            "temp": day.get("temp", {}),
            "pop": day.get("pop"),
            "rain": day.get("rain"),
            "snow": day.get("snow"),
            "clouds": day.get("clouds"),
            "weather": day.get("weather", [{}])[0]
        })
    simplified["forecast"] = forecast

    # Weather alerts (empty list if none)
    alerts = data.get("alerts", [])
    simplified["alerts"] = [
        {
            "event": a.get("event"),
            "description": a.get("description"),
            "start": a.get("start"),
            "end": a.get("end")
        }
        for a in alerts
    ]

    return jsonify(simplified)

@app.route('/battery')
def battery():
    try:
        response = requests.get("http://sdr:5000/api/latest", timeout=3)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception:
        return jsonify({"error": "offline"}), 503


@app.route('/flights')
def flights():
    lat = config_data.get("LAT", 32.8674)
    lon = config_data.get("LON", -79.8049)
    try:
        radius_mi = min(float(request.args.get("radius", 7.0)), 250.0)
    except (TypeError, ValueError):
        radius_mi = 7.0
    lat_delta = radius_mi / 69.0
    lon_delta = radius_mi / (69.0 * cos(radians(lat)))

    url = (
        f"https://opensky-network.org/api/states/all"
        f"?lamin={lat - lat_delta}&lamax={lat + lat_delta}"
        f"&lomin={lon - lon_delta}&lomax={lon + lon_delta}"
    )
    token = _get_opensky_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        states = response.json().get("states") or []
    except Exception:
        return jsonify({"error": "offline"}), 503

    results = []
    for state in states:
        if len(state) < 11:
            continue
        ac_lon, ac_lat = state[5], state[6]
        if ac_lon is None or ac_lat is None or state[8]:  # skip no-position + on-ground
            continue
        dist = haversine_miles(lat, lon, ac_lat, ac_lon)
        if dist > radius_mi:
            continue

        icao24   = (state[0] or "").strip().lower()
        callsign = (state[1] or "").strip()
        baro_m = state[7]
        vel_ms = state[9]
        hdg    = state[10]

        route     = _get_route(icao24, callsign)
        ac_type   = _get_aircraft_type(icao24)
        photo_url = _get_photo(icao24)
        origin      = route.get("origin", "")
        destination = route.get("destination", "")
        results.append({
            "callsign":         callsign or icao24,
            "origin":           origin,
            "origin_city":      _airport_city(origin),
            "destination":      destination,
            "destination_city": _airport_city(destination),
            "airline_iata":     route.get("airline_iata", ""),
            "aircraft_type":    ac_type.get("type_name", "") or route.get("model", ""),
            "photo_url":        photo_url,
            "altitude_ft": round(baro_m * 3.28084) if baro_m is not None else None,
            "speed_mph":   round(vel_ms * 2.23694) if vel_ms is not None else None,
            "distance_mi": round(dist, 1),
            "heading_deg": round(hdg)  if hdg    is not None else None,
        })

    results.sort(key=lambda x: x["distance_mi"])
    return jsonify({"flights": results[:8]})

@app.route('/images')
def images():
    """
    Return a JSON list of image objects from the static/images folder.
    Each object contains the filename.
    """
    image_folder = os.path.join(os.getcwd(), "static", "images")
    allowed_extensions = (".png", ".jpg", ".jpeg", ".gif")
    images_list = []
    for filename in os.listdir(image_folder):
        if filename.lower().endswith(allowed_extensions):
            images_list.append({"filename": filename})
    random.shuffle(images_list)
    return jsonify(images_list)

@app.route('/upload', methods=['POST'])
def upload_image():
    """
    Handle image upload and save the file to the static/images folder.
    """
    if 'file' not in request.files:
        return "No file part in the request", 400
    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400
    if file and file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        image_folder = os.path.join(os.getcwd(), "static", "images")
        file.save(os.path.join(image_folder, filename))
        return "File uploaded successfully", 200
    else:
        return "File type not allowed", 400

def _query_routes(where_clause, params):
    """Run a SELECT against route_cache and return list of dicts."""
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT * FROM route_cache WHERE {where_clause} ORDER BY last_updated DESC",
            params,
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


@app.route('/api/routes/callsign/<path:callsign>')
def api_routes_callsign(callsign):
    rows = _query_routes("callsign = ?", (callsign.strip().upper(),))
    return jsonify(rows)


@app.route('/api/routes/origin/<origin>')
def api_routes_origin(origin):
    rows = _query_routes("origin = ?", (origin.strip().upper(),))
    return jsonify(rows)


@app.route('/api/routes/destination/<destination>')
def api_routes_destination(destination):
    rows = _query_routes("destination = ?", (destination.strip().upper(),))
    return jsonify(rows)


@app.route('/api/routes/airline/<airline_iata>')
def api_routes_airline(airline_iata):
    rows = _query_routes("airline_iata = ?", (airline_iata.strip().upper(),))
    return jsonify(rows)


@app.route('/api/routes/model/<path:model>')
def api_routes_model(model):
    rows = _query_routes("model LIKE ?", (f"%{model.strip()}%",))
    return jsonify(rows)


@app.route('/api/stats')
def api_stats():
    """Return AeroDataBox and other API call counts by source, this month and all-time."""
    from datetime import datetime, timezone
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    dt = datetime.now(timezone.utc)
    month_start = int(datetime(dt.year, dt.month, 1, tzinfo=timezone.utc).timestamp())
    month_rows = con.execute(
        "SELECT data_source, COUNT(*) as cnt FROM route_cache"
        " WHERE last_updated >= ? GROUP BY data_source ORDER BY cnt DESC",
        (month_start,)
    ).fetchall()
    all_rows = con.execute(
        "SELECT data_source, COUNT(*) as cnt FROM route_cache"
        " GROUP BY data_source ORDER BY cnt DESC"
    ).fetchall()
    con.close()
    return jsonify({
        "this_month":      {r["data_source"]: r["cnt"] for r in month_rows},
        "all_time":        {r["data_source"]: r["cnt"] for r in all_rows},
        "month_start_ts":  month_start,
        "settings": {
            "aerodatabox_enabled":   config_data.get("AERODATABOX_ENABLED", True),
            "flight_poll_interval":  config_data.get("FLIGHT_POLL_INTERVAL", 90),
            "route_cache_ttl_hours": config_data.get("ROUTE_CACHE_TTL_HOURS", 12),
        },
    })


@app.route('/api/photos/missing')
def api_photos_missing():
    """Return aircraft models that have been checked but have no image."""
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT key, source, last_updated FROM aircraft_photo_cache"
            " WHERE local_path = '' ORDER BY last_updated DESC"
        ).fetchall()
        con.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/photos')
def api_photos_all():
    """Return all aircraft photo cache entries."""
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT key, local_path, source_url, source, last_updated"
            " FROM aircraft_photo_cache ORDER BY last_updated DESC"
        ).fetchall()
        con.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin/photos')
def admin_photos():
    return render_template('admin_photos.html')


@app.route('/admin/run-fetch', methods=['POST'])
def admin_run_fetch():
    """Run fetch_aircraft_photos.py as a subprocess and return captured output."""
    script = os.path.join(os.getcwd(), 'fetch_aircraft_photos.py')
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=120
        )
        return jsonify({
            'stdout':     result.stdout,
            'stderr':     result.stderr,
            'returncode': result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({'stdout': '', 'stderr': 'Script timed out after 120s.', 'returncode': -1})
    except Exception as e:
        return jsonify({'stdout': '', 'stderr': str(e), 'returncode': -1})


@app.route('/admin/photos/upload', methods=['POST'])
def admin_photos_upload():
    """Upload a photo for a specific aircraft model and update aircraft_photo_cache."""
    model = request.form.get('model', '').strip()
    file  = request.files.get('file')

    if not model:
        return jsonify({'ok': False, 'error': 'Model name is required.'}), 400
    if not file or file.filename == '':
        return jsonify({'ok': False, 'error': 'No file provided.'}), 400
    if not file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
        return jsonify({'ok': False, 'error': 'File must be an image (jpg, png, gif, webp).'}), 400

    safe       = re.sub(r'[^\w\-]', '_', model).strip('_')
    dest       = os.path.join(_AIRCRAFT_TYPES_DIR, f'{safe}.jpg')
    local_path = f'/static/aircraft_types/{safe}.jpg'

    try:
        raw = file.read()
        if PILLOW_AVAILABLE:
            img = PilImage.open(BytesIO(raw))
            img.thumbnail((800, 600), PilImage.LANCZOS)
            img.convert('RGB').save(dest, 'JPEG', quality=85)
        else:
            with open(dest, 'wb') as f:
                f.write(raw)

        now_ts = int(time.time())
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        # Upsert the row for the exact typed model key
        con.execute(
            "INSERT OR REPLACE INTO aircraft_photo_cache VALUES (?,?,?,?,?)",
            (model, local_path, '', 'upload', now_ts)
        )
        # Also fix any other missing rows whose safe filename resolves to the same file.
        # This handles the case where the DB key differs slightly from what the user typed
        # (e.g. "MU-2B-60 Marquise" vs "MU-2B -60  Marquise") but both map to the same .jpg.
        missing_keys = [r["key"] for r in con.execute(
            "SELECT key FROM aircraft_photo_cache WHERE local_path = '' AND key != ?", (model,)
        ).fetchall()]
        def _norm(s):
            return re.sub(r'_+', '_', re.sub(r'[^\w\-]', '_', s)).strip('_')
        for mk in missing_keys:
            if _norm(mk) == _norm(model):
                con.execute(
                    "UPDATE aircraft_photo_cache SET local_path=?, source=?, last_updated=? WHERE key=?",
                    (local_path, 'upload', now_ts, mk)
                )
                print(f"[upload] also updated mismatched key {mk!r} -> {local_path}", flush=True)
        con.commit()
        con.close()

        return jsonify({'ok': True, 'local_path': local_path})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/admin/photos/delete', methods=['POST'])
def admin_photos_delete():
    """Clear a photo entry: delete the local file and reset the DB row to local_path=''."""
    data  = request.get_json(silent=True) or {}
    key   = data.get('key', '').strip()
    if not key:
        return jsonify({'ok': False, 'error': 'key is required'}), 400
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT local_path FROM aircraft_photo_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            con.close()
            return jsonify({'ok': False, 'error': 'Key not found'}), 404
        local_path = row['local_path'] or ''
        # Delete file from disk if it lives in one of our managed dirs
        if local_path:
            abs_path = os.path.join(os.getcwd(), local_path.lstrip('/'))
            managed  = (
                abs_path.startswith(_AIRCRAFT_TYPES_DIR) or
                abs_path.startswith(_AIRCRAFT_PHOTOS_DIR)
            )
            if managed and os.path.exists(abs_path):
                os.remove(abs_path)
                print(f"[delete] removed file {abs_path}", flush=True)
        # Reset the DB row so it shows as missing again (available for re-fetch/upload)
        con.execute(
            "UPDATE aircraft_photo_cache SET local_path='', source='none', source_url='', last_updated=? WHERE key=?",
            (int(time.time()), key)
        )
        con.commit()
        con.close()
        # Evict in-memory photo cache entries that referenced this file
        global _photo_cache
        _photo_cache = {k: v for k, v in _photo_cache.items() if v.get('url') != local_path}
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
