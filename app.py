import os
import random
import sys
import concurrent.futures
from flask import Flask, render_template, jsonify
from PIL import Image, ImageOps, ExifTags

# --- Configuration ---
SOURCE_FOLDER = '/home/liam/Pictures/Backup/Panasonic G7/107_PANA'
# This is the PHYSICAL file system path
TARGET_FOLDER = 'photos/static/cropped_images'
# *** 1. ADD THIS: This is the WEB URL path ***
API_URL_BASE = 'static/cropped_images' 

RATIO_H = 7 / 5
RATIO_V = 5 / 7

# This setup is correct
app = Flask(
    __name__,
    static_folder='photos/static',
    template_folder='templates'
)

SHOULD_RUN_PROCESSING = "--reload" in sys.argv

# --- Helper Function (Unchanged) ---
def center_crop(img, crop_width, crop_height):
    img_width, img_height = img.size
    left = (img_width - crop_width) / 2
    top = (img_height - crop_height) / 2
    right = (img_width + crop_width) / 2
    bottom = (img_height + crop_height) / 2
    return img.crop((left, top, right, bottom))

# --- Worker Function for Image Processing (Unchanged) ---
def process_single_image(source_tuple):
    source_path, mtime = source_tuple
    filename = os.path.basename(source_path)
    target_path = os.path.join(TARGET_FOLDER, filename)
    if os.path.exists(target_path):
        return filename
    try:
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            if width > height: # Horizontal
                target_ratio = RATIO_H
                new_width = height * target_ratio
                new_height = height if new_width <= width else width / target_ratio
                new_width = width if new_width > width else new_width
            else: # Vertical
                target_ratio = RATIO_V
                new_height = width / target_ratio
                new_width = width if new_height <= height else height * target_ratio
                new_height = height if new_height > height else new_height
            cropped_img = center_crop(img, new_width, new_height)
            cropped_img.save(target_path)
            return filename
    except Exception as e:
        print(f"Error processing {filename}: {e}")
        return None

# --- Updated Image Processing Manager Function (Unchanged) ---
def process_images():
    if not os.path.exists(TARGET_FOLDER):
        os.makedirs(TARGET_FOLDER)
        print(f"Created directory: {TARGET_FOLDER}")
    source_files = []
    for filename in os.listdir(SOURCE_FOLDER):
        source_path = os.path.join(SOURCE_FOLDER, filename)
        if (os.path.isfile(source_path) and
            not filename.startswith('._') and
            filename.upper().endswith('.JPG')):
            mtime = os.path.getmtime(source_path)
            source_files.append((source_path, mtime))
    source_files.sort(key=lambda x: x[1])
    processed_files = []
    if SHOULD_RUN_PROCESSING:
        print(f"Found {len(source_files)} images. Processing in PARALLEL...")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = list(executor.map(process_single_image, source_files))
        processed_files = [f for f in results if f is not None]
        print(f"Finished processing. {len(processed_files)} images available.")
    else:
        print("Skipping processing. Using existing images.")
        for source_tuple in source_files:
            filename = os.path.basename(source_tuple[0])
            if os.path.exists(os.path.join(TARGET_FOLDER, filename)):
                processed_files.append(filename)
    return processed_files

# --- Worker Function for API Data ---
def get_photo_data_worker(task_tuple):
    i, filename = task_tuple
    target_path = os.path.join(TARGET_FOLDER, filename)
    source_path = os.path.join(SOURCE_FOLDER, filename)
    
    metadata = {
        "filename": filename,
        "model": "Unknown",
        "f_stop": "Unknown",
        "shutter_speed": "Unknown",
        "iso": "Unknown"
    }
    
    try:
        with Image.open(target_path) as img:
            width, height = img.size
            orientation = 'horizontal' if width > height else 'vertical'
            
        with Image.open(source_path) as img:
            exif_data = img.getexif()
            if exif_data:
                exif = {
                    ExifTags.TAGS[k]: v
                    for k, v in exif_data.items()
                    if k in ExifTags.TAGS
                }
                metadata["model"] = exif.get("Model", "Unknown")
                metadata["f_stop"] = f"f/{exif.get('FNumber', 'N/A')}"
                ss = exif.get('ExposureTime', 0)
                if ss > 0:
                    metadata["shutter_speed"] = f"1/{round(1/ss)}s" if ss < 1 else f"{ss}s"
                metadata["iso"] = exif.get("ISOSpeedRatings", "N/A")
    except Exception as e:
        print(f"Error reading metadata for {filename}: {e}")
        orientation = 'horizontal'
            
    return {
        "id": i + 1,
        "rating": random.randint(1, 10),
        "orientation": orientation,
        # *** 2. THIS IS THE FIX: Use API_URL_BASE ***
        "url": f"/{API_URL_BASE}/{filename}", 
        "metadata": metadata
    }

# --- Main Flask Routes (Unchanged) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/photos')
def get_photos():
    processed_files = process_images()
    tasks = list(enumerate(processed_files))
    photo_data = []
    if SHOULD_RUN_PROCESSING:
        print("Getting photo data in PARALLEL...")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            photo_data = list(executor.map(get_photo_data_worker, tasks))
    else:
        print("Getting photo data in SERIAL...")
        for task in tasks:
            photo_data.append(get_photo_data_worker(task))
    return jsonify(photo_data)

if __name__ == '__main__':
    app.run(debug=True)