#!/usr/bin/env python3
"""
fetch_aircraft_photos.py

Searches for images of aircraft models missing photos in aircraft_photo_cache.
Sources tried in order:
  1. Wikipedia (free, no key, high quality)
  2. DuckDuckGo image search (free, no key, broad coverage)

Usage:
    python3 fetch_aircraft_photos.py           # fetch and save
    python3 fetch_aircraft_photos.py --dry-run # preview only, no changes
"""

import argparse
import os
import re
import sqlite3
import time

import requests

try:
    from PIL import Image
    from io import BytesIO
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("WARNING: Pillow not installed — images will be saved without resizing.")
    print("         Install with: pip install Pillow\n")

try:
    try:
        from ddgs import DDGS  # new package name (formerly duckduckgo_search)
    except ImportError:
        from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    print("INFO: ddgs not installed — DuckDuckGo fallback disabled.")
    print("      Install with: pip install ddgs\n")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
DB_PATH          = os.path.join(SCRIPT_DIR, "data", "routes.db")
OUTPUT_DIR       = os.path.join(SCRIPT_DIR, "static", "aircraft_types")
THUMB_MAX_WIDTH  = 800
THUMB_MAX_HEIGHT = 600

os.makedirs(OUTPUT_DIR, exist_ok=True)

WIKIPEDIA_HEADERS = {
    "User-Agent": "screensaver-aircraft-photo-fetcher/1.0 (educational project)"
}


# ---------------------------------------------------------------------------
# Wikipedia helpers
# ---------------------------------------------------------------------------

def wikipedia_search_title(query):
    """Return the best-matching Wikipedia article title for a search query."""
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action":    "opensearch",
                "search":    query,
                "limit":     3,
                "format":    "json",
                "namespace": 0,
            },
            headers=WIKIPEDIA_HEADERS,
            timeout=5,
        )
        if r.status_code == 200:
            results = r.json()
            titles = results[1] if len(results) > 1 else []
            if titles:
                return titles[0]
    except Exception:
        pass
    return None


def wikipedia_page_image_url(title):
    """Return a thumbnail image URL for a Wikipedia article title, or None."""
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action":      "query",
                "titles":      title,
                "prop":        "pageimages",
                "format":      "json",
                "pithumbsize": THUMB_MAX_WIDTH,
                "redirects":   1,
            },
            headers=WIKIPEDIA_HEADERS,
            timeout=5,
        )
        if r.status_code == 200:
            pages = r.json().get("query", {}).get("pages", {})
            for page in pages.values():
                thumb = page.get("thumbnail", {})
                if thumb.get("source"):
                    return thumb["source"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# DuckDuckGo fallback
# ---------------------------------------------------------------------------

def duckduckgo_image_url(model):
    """Return a photo URL from DuckDuckGo image search, or None."""
    if not DDGS_AVAILABLE:
        return None
    try:
        results = DDGS().images(
            f"{model} aircraft",
            max_results=5,
            safesearch="moderate",
            type_image="photo",
        )
        if results:
            return results[0]["image"]
    except Exception as e:
        print(f"    DuckDuckGo error: {e}")
    return None


# ---------------------------------------------------------------------------
# Image download + save
# ---------------------------------------------------------------------------

def safe_filename(model):
    """Convert a model name to a safe filename stem."""
    return re.sub(r'[^\w\-]', '_', model).strip('_')


def download_and_save(image_url, dest_path):
    """
    Download image_url, optionally resize with Pillow, save to dest_path.
    Returns True on success.
    """
    try:
        r = requests.get(image_url, timeout=8, stream=True,
                         headers=WIKIPEDIA_HEADERS)
        if r.status_code != 200:
            return False
        content_type = r.headers.get("Content-Type", "")
        if "image" not in content_type:
            return False

        raw = b"".join(r.iter_content(8192))

        if PILLOW_AVAILABLE:
            img = Image.open(BytesIO(raw))
            img.thumbnail((THUMB_MAX_WIDTH, THUMB_MAX_HEIGHT), Image.LANCZOS)
            img.convert("RGB").save(dest_path, "JPEG", quality=85)
        else:
            with open(dest_path, "wb") as f:
                f.write(raw)

        return True
    except Exception as e:
        print(f"    download error: {e}")
        return False


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_missing_models():
    """Return list of model keys from aircraft_photo_cache where local_path=''."""
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT key FROM aircraft_photo_cache WHERE local_path = '' ORDER BY key"
    ).fetchall()
    con.close()
    return [row[0] for row in rows]


def update_db(model, local_path, source_url, source):
    """Update the aircraft_photo_cache row for model with the found image."""
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """UPDATE aircraft_photo_cache
           SET local_path=?, source_url=?, source=?, last_updated=?
           WHERE key=?""",
        (local_path, source_url, source, int(time.time()), model)
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch images for aircraft models missing photos (Wikipedia then DuckDuckGo)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be fetched without downloading or updating the DB."
    )
    args = parser.parse_args()

    models = get_missing_models()
    if not models:
        print("No missing aircraft photos found in the database.")
        return

    print(f"Found {len(models)} model(s) missing images.\n")

    found = 0
    not_found = 0

    for model in models:
        if args.dry_run:
            print(f"  [dry-run] {model}")
            continue

        # Step 1a: Wikipedia
        image_url = None
        source    = None
        title = wikipedia_search_title(model)
        if title:
            image_url = wikipedia_page_image_url(title)
            if image_url:
                source = "wikipedia"

        # Step 1b: DuckDuckGo fallback
        if not image_url:
            image_url = duckduckgo_image_url(model)
            if image_url:
                source = "duckduckgo"

        if not image_url:
            print(f"  x {model}  (no image found via Wikipedia or DuckDuckGo)")
            not_found += 1
            time.sleep(0.5)
            continue

        # Step 2: download + save
        filename   = f"{safe_filename(model)}.jpg"
        dest_path  = os.path.join(OUTPUT_DIR, filename)
        local_path = f"/static/aircraft_types/{filename}"

        if download_and_save(image_url, dest_path):
            update_db(model, local_path, image_url, source)
            label = f"via Wikipedia '{title}'" if source == "wikipedia" else "via DuckDuckGo"
            print(f"  + {model}  ->  {filename}  ({label})")
            found += 1
        else:
            print(f"  x {model}  (download failed)")
            not_found += 1

        time.sleep(0.5)

    if not args.dry_run:
        print(f"\nDone. {found} downloaded, {not_found} not found.")


if __name__ == "__main__":
    main()
