# Astro Slideshow

A Raspberry Pi-based fullscreen slideshow that displays astrophotography images alongside live local weather and real-time overhead flight tracking. Built with Python/Flask on the backend and plain HTML/JS on the frontend.

---

## Features

- **Astrophotography slideshow** — rotates through images in `static/images/`, with upload support
- **Live weather** — current conditions via OpenWeatherMap
- **Overhead flight tracking** — polls OpenSky Network for aircraft within a configurable radius, enriched with route data, airline logos, aircraft type, and photos
- **Private plane support** — N-number callsigns are looked up via AeroDataBox, which has IFR flight plan data that AirLabs/adsbdb lack
- **Aircraft photo pipeline** — specific photos via Planespotters, then a local image cache, then AeroDataBox by registration, then generic type photos
- **Persistent route + photo cache** — SQLite-backed so API calls are minimized across restarts

---

## Requirements

- Python 3.9+
- `pip install flask requests pillow ddgs`
- API keys (see Configuration)

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd screensaver
pip install flask requests pillow ddgs
```

### 2. Configure

Copy the example and fill in your keys:

```bash
cp config/config.json.example config/config.json
```

Edit `config/config.json`:

```json
{
    "LAT": 34.0522,
    "LON": -118.2437,
    "UNITS": "imperial",
    "OPENWEATHER_API_KEY": "your_key_here",
    "OPENSKY_CLIENT_ID": "your_client_id",
    "OPENSKY_CLIENT_SECRET": "your_client_secret",
    "AIRLABS_API_KEY": "your_key_here",
    "AERODATABOX_RAPIDAPI_KEY": "your_rapidapi_key_here"
}
```

| Key | Source | Notes |
|-----|--------|-------|
| `LAT` / `LON` | Your location | Decimal degrees |
| `UNITS` | — | `"imperial"` or `"metric"` |
| `OPENWEATHER_API_KEY` | [openweathermap.org](https://openweathermap.org/api) | Free tier sufficient |
| `OPENSKY_CLIENT_ID/SECRET` | [opensky-network.org](https://opensky-network.org) | Free; higher rate limits than anonymous |
| `AIRLABS_API_KEY` | [airlabs.co](https://airlabs.co) | Free tier (1,000 calls/month); commercial route fallback |
| `AERODATABOX_RAPIDAPI_KEY` | [rapidapi.com/aedbx/api/aerodatabox](https://rapidapi.com/aedbx/api/aerodatabox) | $5/month Pro (~6,000 calls); primary route + image source |

### 3. Add images

Drop `.jpg`, `.png`, or `.gif` astrophotography images into `static/images/`. They can also be uploaded via the UI or the `/upload` endpoint.

### 4. Run

```bash
python astro_slideshow.py
```

The app starts on port **5050**. Open `http://<your-pi-ip>:5050` in a browser.

#### Running with PM2 (recommended for Raspberry Pi)

```bash
pm2 start astro_slideshow.py --name screensaver --interpreter python3
pm2 save
pm2 startup
```

View logs:
```bash
pm2 logs screensaver --lines 100
```

---

## Project Structure

```
screensaver/
├── astro_slideshow.py        # Flask app — all backend logic
├── fetch_aircraft_photos.py  # Utility: populate aircraft image cache from Wikipedia/DuckDuckGo
├── download_airports.py      # Utility: fetch airport data from OpenFlights
├── config/
│   └── config.json           # API keys and location settings
├── data/
│   ├── airports.json         # Airport IATA → city/name lookup
│   └── routes.db             # SQLite: route_cache + aircraft_photo_cache
├── static/
│   ├── images/               # Slideshow images (user-provided)
│   ├── aircraft_types/       # Downloaded generic type photos (auto-populated)
│   └── aircraft_photos/      # Downloaded specific aircraft photos (auto-populated)
├── templates/
│   └── index.html            # Frontend (HTML/JS/CSS, no framework)
└── bruno/                    # Bruno API test collection
    ├── screensaver-api/      # App endpoints
    ├── db-queries/           # DB inspection endpoints
    ├── aerodatabox/          # AeroDataBox API tests
    └── external-apis/        # OpenSky, Planespotters, AirLabs, etc.
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the frontend |
| `GET` | `/weather` | Current weather from OpenWeatherMap |
| `GET` | `/flights?radius=<mi>` | Overhead aircraft within radius (default 7 mi) |
| `GET` | `/images` | List of slideshow images |
| `POST` | `/upload` | Upload a new slideshow image |
| `GET` | `/battery` | Raspberry Pi battery status |
| `GET` | `/api/routes/callsign/<cs>` | Route cache lookup by callsign |
| `GET` | `/api/routes/origin/<iata>` | Routes by origin airport |
| `GET` | `/api/routes/destination/<iata>` | Routes by destination airport |
| `GET` | `/api/routes/airline/<iata>` | Routes by airline IATA code |
| `GET` | `/api/routes/model/<model>` | Routes by aircraft model |
| `GET` | `/api/photos/missing` | Aircraft models with no photo in cache |
| `GET` | `/api/photos` | All entries in the aircraft photo cache |

---

## Flight Data Pipeline

For each aircraft detected by OpenSky within range, the app resolves route and photo data in priority order:

### Route lookup (`_get_route`)

1. **SQLite cache** — 4-hour TTL; avoids redundant API calls for recently seen flights
2. **AeroDataBox** (primary) — handles all callsigns including N-number private planes; has IFR flight plan data
3. **AirLabs** (secondary) — commercial flights only; skipped for N-numbers
4. **adsbdb** (fallback) — historical route database; skipped for N-numbers

### Aircraft photo lookup (`_get_photo`)

1. **Planespotters by hex** — specific photo of the individual aircraft (CDN URL)
2. **Local `aircraft_photo_cache` DB** — images downloaded by this app or `fetch_aircraft_photos.py`
3. **AeroDataBox by registration** — CC-licensed aircraft photo; downloaded and cached locally
4. **Planespotters by ICAO type** — generic type photo (e.g. all B738s share one image); downloaded and cached locally

---

## Aircraft Photo Utility

`fetch_aircraft_photos.py` populates the local image cache for aircraft models that have been seen overhead but have no photo. It queries `aircraft_photo_cache` for rows where `local_path` is empty, then searches for images:

1. **Wikipedia** — article thumbnail via the public MediaWiki API (no key required)
2. **DuckDuckGo** — image search fallback via the `ddgs` library (no key required)

```bash
# Preview what would be fetched
python3 fetch_aircraft_photos.py --dry-run

# Download and populate
python3 fetch_aircraft_photos.py
```

Images are saved to `static/aircraft_types/` and the DB row is updated with the local path and source.

---

## Database

`data/routes.db` contains two tables:

### `route_cache`

Stores flight route data keyed by callsign. Populated by AeroDataBox, AirLabs, and adsbdb. TTL: 4 hours (flights change throughout the day).

Key columns: `callsign`, `origin`, `destination`, `airline_iata`, `data_source`, `model`, `reg_number`, `hex`, `dep_municipality`, `arr_municipality`, `status`

### `aircraft_photo_cache`

Stores aircraft model photos keyed by model string (e.g. `"Cirrus SR-22"`). One cached image serves all aircraft of the same model. TTL: 90 days.

Key columns: `key` (model name), `local_path`, `source_url`, `source`, `last_updated`

A row with an empty `local_path` means the image was looked up but not found — the app will not retry until the TTL expires. Query missing models at `/api/photos/missing`.

---

## Bruno API Tests

The `bruno/` folder contains a [Bruno](https://www.usebruno.com/) collection organized into four folders. To use it, open Bruno, import the collection, and select the `local` environment.

Set your API keys in `bruno/environments/local.bru` (copy from `local.bru.example`).
