import os
import json
import random
import sqlite3
import time
import requests
from math import radians, sin, cos, sqrt, atan2
from flask import Flask, jsonify, render_template, request

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

_AIRCRAFT_TYPES_DIR = os.path.join(os.getcwd(), "static", "aircraft_types")
os.makedirs(_AIRCRAFT_TYPES_DIR, exist_ok=True)

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


ROUTE_CACHE_TTL = 7 * 86400  # 7 days

def _get_route(icao24, callsign):
    """
    Return route dict with origin/destination IATA codes and airline_iata.
    Checks SQLite DB first (7-day TTL). Primary live source: AirLabs.co.
    Fallback: adsbdb.com (static historical).
    """
    cache_key = callsign or icao24
    if not cache_key:
        return {}
    cs = cache_key.strip().upper()
    now = int(time.time())

    # Check DB cache
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT origin, destination, airline_iata, last_updated FROM route_cache WHERE callsign = ?",
            (cs,)
        ).fetchone()
        con.close()
        if row and (now - row["last_updated"]) < ROUTE_CACHE_TTL:
            return {
                "origin":       row["origin"] or "",
                "destination":  row["destination"] or "",
                "airline_iata": row["airline_iata"] or "",
            }
    except Exception:
        pass

    data = {}

    # Primary: AirLabs scheduled data (writes to DB on success)
    if callsign:
        data = _get_route_from_airlabs(callsign)

    # Fallback: adsbdb static database
    if not data.get("origin") and callsign and callsign.strip():
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
PHOTO_CACHE_TTL = 86400  # 24 hours

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
    Phase 1 — specific aircraft: planespotters.net CDN URL (not stored locally).
    Phase 2 — type fallback: hexdb.io type lookup + planespotters.net type search,
               downloaded to disk and shared across all aircraft of that type.
    """
    if not icao24:
        return ""
    hex_key = icao24.strip().lower()
    now = time.time()
    cached = _photo_cache.get(hex_key)
    if cached and (now - cached["ts"]) < PHOTO_CACHE_TTL:
        return cached["url"]

    def _cache(url):
        _photo_cache[hex_key] = {"url": url, "ts": now}
        return url

    # Phase 1: specific aircraft photo — return CDN URL directly, no local storage
    try:
        r = requests.get(
            f"https://api.planespotters.net/pub/photos/hex/{hex_key}", timeout=3
        )
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            if photos:
                return _cache(photos[0]["thumbnail_large"]["src"])
    except Exception:
        pass

    # Phase 2: generic type photo
    ac_type = _get_aircraft_type(hex_key)
    icao_type = ac_type.get("icao_type", "")
    if not icao_type:
        return _cache("")

    local_type = os.path.join(_AIRCRAFT_TYPES_DIR, f"type_{icao_type}.jpg")
    if os.path.exists(local_type):
        return _cache(f"/static/aircraft_types/type_{icao_type}.jpg")

    try:
        r = requests.get(
            f"https://api.planespotters.net/pub/photos/type/{icao_type}", timeout=3
        )
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            if photos:
                src = photos[0]["thumbnail_large"]["src"]
                if _download_image(src, local_type):
                    return _cache(f"/static/aircraft_types/type_{icao_type}.jpg")
    except Exception:
        pass

    return _cache("")


@app.route('/')
def index():
    return render_template("index.html")  # Serves your front end

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
            "aircraft_type":    ac_type.get("type_name", ""),
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
