import os
import random
import sys
import concurrent.futures
import json
import time
import threading

# --- 1. NEW IMPORTS (Corrected) ---
import open_clip
import aesthetic_predictor  # <-- This is the fix
import torch

from flask import Flask, render_template, jsonify
from PIL import Image, ImageOps, ExifTags

# --- Configuration ---
# !!! IMPORTANT: Make sure this path is correct for your Mac !!!
SOURCE_FOLDER = '/home/liam/Pictures/Backup/Panasonic G7/107_PANA'
TARGET_FOLDER = 'photos/static/cropped_images'
API_URL_BASE = 'static/cropped_images' 
RATIO_H = 7 / 5
RATIO_V = 5 / 7
RATING_CACHE_FILE = 'photo_ratings.json' 

# Set to 2 to prevent OOM crash on 8GB RAM
MAX_WORKERS = 2 

# --- Flask Setup ---
app = Flask(
    __name__,
    static_folder='photos/static',
    template_folder='templates'
)
SHOULD_PROCESS_PHOTOS = "--reload" in sys.argv
SHOULD_RELOAD_RATINGS = "--reload-ratings" in sys.argv
SHOULD_FETCH_NEW_RATINGS = SHOULD_PROCESS_PHOTOS or SHOULD_RELOAD_RATINGS

# --- Global State ---
device = None
aesthetic_model = None # This will be our new scorer
clip_model = None      # This is the CLIP model
clip_preprocess = None # This prepares images for CLIP
ALL_PHOTO_DATA = []

# --- 2. Mac-Only Device Detection ---
def get_auto_device():
    """
    Finds the Mac GPU (MPS) or falls back to CPU.
    """
    if torch.backends.mps.is_available():
        print("Found Apple Metal (MPS) GPU.")
        return torch.device('mps')
    else:
        print("No GPU found. Using CPU.")
        return torch.device('cpu')

# --- Helper Functions (Unchanged) ---
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

def process_images():
    if not os.path.exists(TARGET_FOLDER):
        os.makedirs(TARGET_FOLDER)
        print(f"Created directory: {TARGET_FOLDER}")
    
    processed_files = []

    if SHOULD_PROCESS_PHOTOS:
        print("Running --reload: Processing photos from SOURCE_FOLDER...")
        if not os.path.exists(SOURCE_FOLDER):
            print(f"ERROR: --reload failed. SOURCE_FOLDER not found at {SOURCE_FOLDER}")
            return []
            
        source_files = []
        for filename in os.listdir(SOURCE_FOLDER):
            source_path = os.path.join(SOURCE_FOLDER, filename)
            if (os.path.isfile(source_path) and
                not filename.startswith('._') and
                filename.upper().endswith('.JPG')):
                mtime = os.path.getmtime(source_path)
                source_files.append((source_path, mtime))
        
        source_files.sort(key=lambda x: x[1])
        print(f"Found {len(source_files)} images. Processing in PARALLEL...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(process_single_image, source_files))
        
        processed_files = [f for f in results if f is not None]
        print(f"Finished processing. {len(processed_files)} images available.")
    
    else:
        print("Skipping photo processing. Scanning existing cropped images...")
        try:
            for filename in os.listdir(TARGET_FOLDER):
                if (not filename.startswith('._') and
                    filename.upper().endswith('.JPG')):
                    processed_files.append(filename)
            processed_files.sort() 
            print(f"Found {len(processed_files)} existing images.")
        except FileNotFoundError:
            print(f"Warning: TARGET_FOLDER not found at {TARGET_FOLDER}")
            return []

    return processed_files

# --- 3. MODIFIED: get_local_rating (using CLIP) ---
def get_local_rating(cropped_image_path):
    """
    Runs the CLIP + Scorer model on an image.
    This reads the global models loaded in the main thread.
    """
    if not aesthetic_model or not clip_model or not clip_preprocess:
        print("FATAL: Models are not loaded. Returning random rating.")
        return random.randint(3, 7)
    try:
        # 1. Open the image
        image = Image.open(cropped_image_path)
        
        # 2. Prepare the image for CLIP
        image_tensor = clip_preprocess(image).unsqueeze(0).to(device)
        
        # 3. Get CLIP's "understanding" of the image
        with torch.no_grad():
            image_features = clip_model.encode_image(image_tensor)
            
            # 4. Normalize the features
            image_features /= image_features.norm(dim=-1, keepdim=True)
        
        # 5. Get the 1-10 aesthetic score
        # The .item() pulls the number out of the tensor
        rating = aesthetic_model(image_features).item()
        
        return round(rating, 1) 
    except Exception as e:
        raise e

# --- get_photo_data_worker (Unchanged) ---
def get_photo_data_worker(task_tuple):
    i, filename, ratings_cache = task_tuple 
    target_path = os.path.join(TARGET_FOLDER, filename)
    source_path = os.path.join(SOURCE_FOLDER, filename)
    metadata = { "filename": filename, "model": "Unknown", "f_stop": "Unknown", "shutter_speed": "Unknown", "iso": "Unknown" }
    
    try:
        with Image.open(target_path) as img:
            width, height = img.size
            orientation = 'horizontal' if width > height else 'vertical'
        
        if os.path.exists(source_path):
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
        if 'orientation' not in locals():
            orientation = 'horizontal'
    
    if filename in ratings_cache and not SHOULD_RELOAD_RATINGS:
        rating = ratings_cache[filename]
        new_rating = False
    else:
        if SHOULD_FETCH_NEW_RATINGS:
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

# --- 4. MODIFIED: Eager Processing Function (Loads CLIP) ---
def run_eager_processing():
    """
    This is the main function that runs at startup.
    It prepares all photo data and populates the global ALL_PHOTO_DATA.
    """
    global ALL_PHOTO_DATA, device, aesthetic_model, clip_model, clip_preprocess
    
    processed_files = process_images() 
    
    ratings_cache = {}
    if not SHOULD_RELOAD_RATINGS:
        if os.path.exists(RATING_CACHE_FILE):
            try:
                with open(RATING_CACHE_FILE, 'r') as f:
                    ratings_cache = json.load(f)
                    print(f"Loaded {len(ratings_cache)} ratings from cache.")
            except Exception as e:
                print(f"Error loading rating cache: {e}")
    else:
        print("Reloading ratings: Starting with an empty cache.")

    tasks = [(i, filename, ratings_cache) for i, filename in enumerate(processed_files)]
    photo_data_map = {}
    
    if SHOULD_FETCH_NEW_RATINGS:
        
        # 1. Load the device and models ONCE in the main thread
        device = get_auto_device()
        try:
            print(f"[Main Thread]: Loading aesthetic scorer model onto {device}...")
            # --- THIS IS THE FIX ---
            aesthetic_model = aesthetic_predictor.AestheticsPredictorV2(
                "sac_public_2022_06_29_vit_l_14_linear.pth"
            ).to(device)
            # ---------------------
            print("[Main Thread]: Scorer loaded.")
            
            print(f"[Main Thread]: Loading CLIP model onto {device}...")
            clip_model, _, clip_preprocess = open_clip.create_model_and_transforms(
                "ViT-L-14", pretrained="datacomp_xl_s13b_b90k"
            )
            clip_model = clip_model.to(device)
            print("[Main Thread]: CLIP model loaded successfully.")
            
        except Exception as e:
            print(f"[Main Thread]: FATAL ERROR loading models: {e}")
            # --- THIS IS THE FIX ---
            print("Please run 'pip install aesthetic-predictor open-clip-torch'")
            # ---------------------
            sys.exit(1)
        
        # 2. Use ThreadPoolExecutor (correct for Mac + MPS)
        executor_cls = concurrent.futures.ThreadPoolExecutor

        print(f"Getting photo data in PARALLEL using {executor_cls.__name__} (device: {device}, max_workers: {MAX_WORKERS})...")
        start_time = time.time()
        
        # --- 2-Pass system ---
        failed_tasks = []

        with executor_cls(max_workers=MAX_WORKERS) as executor:
            
            future_to_task = {
                executor.submit(get_photo_data_worker, task): task 
                for task in tasks
            }
            
            count = 0
            for future in concurrent.futures.as_completed(future_to_task):
                task = future_to_task[future]
                filename = task[1]
                count += 1
                
                try:
                    result = future.result()
                    photo_data_map[result['id']] = result
                    
                    percent = (count / len(tasks)) * 100
                    sys.stdout.write(f"\r  ... Pass 1: Rated {count} / {len(tasks)} ({percent:.1f}%) - {filename} -> {result['rating']}\n")
                    sys.stdout.flush()

                except Exception as e:
                    print(f"\n[Parallel Error] Failed to process {filename}. Adding to retry queue. Error: {e}\n")
                    failed_tasks.append(task)
            
        end_time = time.time()
        print(f"\nFinished Pass 1 in {end_time - start_time:.2f} seconds.")

        # --- Pass 2: Serial Retry ---
        if failed_tasks:
            print(f"\nRetrying {len(failed_tasks)} failed images in SERIAL (this will be stable)...")
            # Models are already loaded in the main thread
            start_time_serial = time.time()
            
            for i, task in enumerate(failed_tasks):
                filename = task[1]
                try:
                    result = get_photo_data_worker(task)
                    photo_data_map[result['id']] = result
                    sys.stdout.write(f"\r  ... Pass 2: Rerated {i + 1} / {len(failed_tasks)} ({filename}) -> {result['rating']}\n")
                    sys.stdout.flush()
                except Exception as e:
                    print(f"\n[Serial Error] FAILED to process {filename} even in serial mode: {e}")
            
            end_time_serial = time.time()
            print(f"\nFinished Pass 2 in {end_time_serial - start_time_serial:.2f} seconds.")

    else:
        # --- FAST LAUNCH path ---
        print("Getting photo data in SERIAL (using cache)...")
        for task in tasks:
            photo_data_map[task[0]] = get_photo_data_worker(task)
    
    # --- Final Processing (Unchanged) ---
    ALL_PHOTO_DATA = [ photo_data_map[key] for key in sorted(photo_data_map.keys()) ]
    
    cache_updated = False
    for data in ALL_PHOTO_DATA:
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

    print(f"\n--- {len(ALL_PHOTO_DATA)} photos loaded. Starting web server. ---")


# --- Main Flask Routes (Unchanged) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/photos')
def get_photos():
    global ALL_PHOTO_DATA
    return jsonify(ALL_PHOTO_DATA)


if __name__ == '__main__':
    # Removed all Linux 'spawn' logic
    run_eager_processing()
    app.run(debug=True)