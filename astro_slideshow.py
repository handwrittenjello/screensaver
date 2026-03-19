import os
import json
import random
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

def _airport_city(iata):
    """Return city name for an IATA code, or '' if unknown."""
    return _airports.get(iata, {}).get("city", "") if iata else ""


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


# Route lookup cache — adsbdb.com, free, no key required
_route_cache = {}
ROUTE_CACHE_TTL = 3600  # 1 hour

def _get_route(callsign):
    """Fetch origin/destination IATA codes from adsbdb.com. Returns {} on failure."""
    if not callsign or not callsign.strip():
        return {}
    cs = callsign.strip().upper()
    now = time.time()
    cached = _route_cache.get(cs)
    if cached and (now - cached["ts"]) < ROUTE_CACHE_TTL:
        return cached["data"]
    try:
        r = requests.get(f"https://api.adsbdb.com/v0/callsign/{cs}", timeout=3)
        if r.status_code == 200:
            fr = r.json().get("response", {}).get("flightroute", {})
            data = {
                "origin":      fr.get("origin", {}).get("iata_code", ""),
                "destination": fr.get("destination", {}).get("iata_code", ""),
            }
        else:
            data = {}
    except Exception:
        data = {}
    _route_cache[cs] = {"data": data, "ts": now}
    return data


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

        callsign = (state[1] or "").strip()
        baro_m = state[7]
        vel_ms = state[9]
        hdg    = state[10]

        route = _get_route(callsign)
        origin      = route.get("origin", "")
        destination = route.get("destination", "")
        results.append({
            "callsign":         callsign or state[0],
            "origin":           origin,
            "origin_city":      _airport_city(origin),
            "destination":      destination,
            "destination_city": _airport_city(destination),
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
