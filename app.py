import os
import random
import sys
import concurrent.futures
import json

import pyiqa
import torch
# import torch.nn.functional as F  <-- No longer needed

from flask import Flask, render_template, jsonify
from PIL import Image, ImageOps, ExifTags

# --- Configuration (Unchanged) ---
SOURCE_FOLDER = '/home/liam/Pictures/Backup/Panasonic G7/107_PANA'
TARGET_FOLDER = 'photos/static/cropped_images'
API_URL_BASE = 'static/cropped_images' 
RATIO_H = 7 / 5
RATIO_V = 5 / 7
RATING_CACHE_FILE = 'photo_ratings.json' 

# --- Flask Setup (Unchanged) ---
app = Flask(
    __name__,
    static_folder='photos/static',
    template_folder='templates'
)
SHOULD_RUN_PROCESSING = "--reload" in sys.argv

# --- Local Model Setup (Unchanged) ---
try:
    # This will now find 'cuda' if you ran the install step
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")
    
    # We use the paq2piq model
    aesthetic_model = pyiqa.create_metric('paq2piq', device=device)
    
    print("Local aesthetic model (pyiqa paq2piq) loaded successfully.")

except Exception as e:
    print(f"Error loading local model: {e}")
    print("Please run 'pip install pyiqa torch torchvision --index-url https://download.pytorch.org/whl/rocm6.1'")
    aesthetic_model = None

# --- All helper functions (center_crop, process_single_image, process_images) are unchanged ---

def center_crop(img, crop_width, crop_height):
    img_width, img_height = img.size
    left = (img_width - crop_width) / 2
    top = (img_height - crop_height) / 2
    right = (img_width + crop_width) / 2
    bottom = (img_height + crop_height) / 2
    return img.crop((left, top, right, bottom))

def process_single_image(source_tuple):
    source_path, mtime = source_tuple
    filename = os.path.basename(source_path)
    target_path = os.path.join(TARGET_FOLDER, filename)
    if os.path.exists(target_path):
        return filename
    try:
        with Image.open(source_path) as img:
            img = ImageOps.ex_transpose(img)
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
        # ThreadPoolExecutor is correct for this I/O-bound task
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

# --- Local Rating Function (Unchanged) ---
def get_local_rating(cropped_image_path):
    """
    Runs the local paq2piq model on an image and returns a 1-10 rating.
    """
    if not aesthetic_model:
        return random.randint(3, 7) # Fallback

    try:
        score_0_to_100 = aesthetic_model(cropped_image_path).item()
        rating = (score_0_to_100 / 100) * 9 + 1
        rating = round(rating, 1) 
        print(f"Local model rated {os.path.basename(cropped_image_path)}: {rating}/10")
        return rating
    except Exception as e:
        print(f"Error during local rating for {os.path.basename(cropped_image_path)}: {e}")
        return 5 # Fallback on error


# --- Worker Function (Unchanged) ---
def get_photo_data_worker(task_tuple):
    """
    Worker task that gets orientation, metadata, AND local rating.
    """
    i, filename, ratings_cache = task_tuple 
    
    target_path = os.path.join(TARGET_FOLDER, filename)
    source_path = os.path.join(SOURCE_FOLDER, filename)
    
    metadata = { "filename": filename, "model": "Unknown", "f_stop": "Unknown", "shutter_speed": "Unknown", "iso": "Unknown" }
    
    try:
        with Image.open(target_path) as img:
            width, height = img.size
            orientation = 'horizontal' if width > height else 'vertical'
            
        with Image.open(source_path) as img:
            exif_data = img.getexif()
            if exif_data:
                exif = { ExifTags.TAGS[k]: v for k, v in exif_data.items() if k in ExifTags.TAGS }
                metadata["model"] = exif.get("Model", "Unknown")
                metadata["f_stop"] = f"f/{exif.get('FNumber', 'N/A')}"
                ss = exif.get('ExposureTime', 0)
                if ss > 0:
                    metadata["shutter_speed"] = f"1/{round(1/ss)}s" if ss < 1 else f"{ss}s"
                metadata["iso"] = exif.get("ISOSpeedRatings", "N/A")

    except Exception as e:
        print(f"Error reading metadata for {filename}: {e}")
        orientation = 'horizontal'
    
    # --- RATING LOGIC (Unchanged) ---
    if filename in ratings_cache:
        rating = ratings_cache[filename]
        new_rating = False
    else:
        if SHOULD_RUN_PROCESSING:
            rating = get_local_rating(target_path)
            new_rating = True
        else:
            rating = 5
            new_rating = False
            
    return {
        "id": i + 1,
        "rating": rating,
        "new_rating_acquired": new_rating,
        "orientation": orientation,
        "url": f"/{API_URL_BASE}/{filename}",
        "metadata": metadata
    }

# --- Main Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

# --- MODIFIED: get_photos (Switched BACK to ThreadPoolExecutor) ---
@app.route('/api/photos')
def get_photos():
    """
    This API now loads and saves the photo_ratings.json cache
    using the 'pyiqa' local model.
    """
    processed_files = process_images() 
    
    ratings_cache = {}
    if os.path.exists(RATING_CACHE_FILE):
        try:
            with open(RATING_CACHE_FILE, 'r') as f:
                ratings_cache = json.load(f)
                print(f"Loaded {len(ratings_cache)} ratings from cache.")
        except Exception as e:
            print(f"Error loading rating cache: {e}")

    tasks = [(i, filename, ratings_cache) for i, filename in enumerate(processed_files)]
    photo_data = []

    # *** THIS IS THE FIX FOR GPU ***
    # ThreadPoolExecutor is correct for GPU (and I/O) tasks
    # because the GPU work releases the Python GIL,
    # allowing true parallel execution.
    executor_cls = concurrent.futures.ThreadPoolExecutor
    
    if SHOULD_RUN_PROCESSING:
        print(f"Getting photo data in PARALLEL using {executor_cls.__name__}...")
        with executor_cls() as executor:
            photo_data = list(executor.map(get_photo_data_worker, tasks))
    else:
        print("Getting photo data in SERIAL...")
        for task in tasks:
            photo_data.append(get_photo_data_worker(task))

    # --- SAVE CACHE (Unchanged) ---
    cache_updated = False
    for data in photo_data:
        if data.get("new_rating_acquired", False):
            filename = data["metadata"]["filename"]
            ratings_cache[filename] = data["rating"]
            cache_updated = True
        data.pop("new_rating_acquired", None) 
            
    if cache_updated:
        print("Saving new ratings to cache...")
        try:
            with open(RATING_CACHE_FILE, 'w') as f:
                json.dump(ratings_cache, f, indent=2)
        except Exception as e:
            print(f"Error saving rating cache: {e}")

    return jsonify(photo_data)


if __name__ == '__main__':
    app.run(debug=True)