"""
One-time script to download airport data from OpenFlights and save it as
data/airports.json for use by the flights widget.

Usage:
    python download_airports.py

Source: https://github.com/jpatokal/openflights (public domain)
CSV columns: id, name, city, country, iata, icao, lat, lon, alt, tz, dst, tz_name, type, source
"""

import csv
import io
import json
import os
import urllib.request

URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"

def main():
    print("Downloading airports data from OpenFlights...")
    with urllib.request.urlopen(URL) as response:
        content = response.read().decode("utf-8", errors="replace")

    airports = {}
    reader = csv.reader(io.StringIO(content))
    for row in reader:
        if len(row) < 5:
            continue
        iata = row[4].strip().strip('"')
        if not iata or iata == r"\N" or len(iata) != 3:
            continue
        city    = row[2].strip().strip('"')
        name    = row[1].strip().strip('"')
        country = row[3].strip().strip('"')
        airports[iata] = {"city": city, "name": name, "country": country}

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", "airports.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(airports, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(airports)} airports to {out_path}")

if __name__ == "__main__":
    main()
