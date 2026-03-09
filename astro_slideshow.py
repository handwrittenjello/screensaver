import os
import json
import random
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Load configuration from /config/config.json
def load_config():
    config_path = os.path.join(os.getcwd(), "config", "config.json")
    with open(config_path) as f:
        return json.load(f)

config_data = load_config()


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
