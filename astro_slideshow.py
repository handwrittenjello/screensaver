import os
import random
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# Folder where astrophotography images are stored
IMAGE_FOLDER = "static/images"

# Default settings with Ken Burns enabled by default.
settings = {
    "display_time": 5,        # Seconds per image (used by frontend as a default)
    "transition_speed": 1,      # Transition speed in seconds
    "ken_burns": True           # Ken Burns effect enabled by default
}

def get_images():
    """Retrieve image filenames from the static images folder.
       Returns a list of dicts with a 'filename' key.
       The list is randomly shuffled.
    """
    image_files = [
        {"filename": f}
        for f in os.listdir(IMAGE_FOLDER)
        if f.lower().endswith(('png', 'jpg', 'jpeg', 'gif'))
    ]
    random.shuffle(image_files)
    return image_files

@app.route('/')
def index():
    return render_template("index.html", settings=settings)

@app.route('/images')
def images():
    """Return the list of images as JSON."""
    return jsonify(get_images())

@app.route('/settings', methods=['POST'])
def update_settings():
    """Update the slideshow settings."""
    global settings
    data = request.json
    settings.update(data)
    return jsonify(settings)

@app.route('/upload', methods=['POST'])
def upload_image():
    """Handle image upload and save the file to the static/images folder."""
    if 'file' not in request.files:
        return "No file part in the request", 400
    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400
    if file and file.filename.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):
        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        file_path = os.path.join(IMAGE_FOLDER, filename)
        file.save(file_path)
        return "File uploaded successfully", 200
    else:
        return "File type not allowed", 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
