import os
import random
import sys
import concurrent.futures
import json
import time
import threading

from flask import Flask, render_template, jsonify
from PIL import Image, ImageOps, ExifTags # ExifTags imported

# --- Configuration ---
SOURCE_FOLDER = 'cropped_images' # Source folder containing original images
TARGET_FOLDER = 'photos/static/cropped_images' # Main target folder (will contain 'original' and 'compressed' subfolders)
API_URL_BASE = 'static/cropped_images'
RATING_CACHE_FILE = 'photo_ratings.json'

# Sub-folder names
ORIGINAL_SUBFOLDER = 'original'
COMPRESSED_SUBFOLDER = 'compressed_avif' # Subfolder for AVIF files

# Set based on your system's capabilities for I/O bound tasks
MAX_WORKERS = 2 # Adjust if needed based on performance/RAM

# --- Flask Setup ---
app = Flask(
    __name__,
    static_folder='photos/static',
    template_folder='templates'
)
SHOULD_PROCESS_PHOTOS = "--reload" in sys.argv
SHOULD_FETCH_NEW_RATINGS = SHOULD_PROCESS_PHOTOS # Logic simplified, now only depends on --reload

# --- Global State ---
ALL_PHOTO_DATA = []

# --- Rate Tracking Variables ---
# These will be accessed by the main thread and the rate display thread
start_time = None
current_processed_count = 0
current_processed_lock = threading.Lock() # Protects access to the counter
rate_display_thread = None
stop_rate_display = threading.Event() # Signal to stop the rate display thread

def update_rate_display():
    """Function run by the rate display thread."""
    global current_processed_count, start_time
    last_count = 0
    last_time = time.time()
    while not stop_rate_display.is_set():
        time.sleep(0.5) # Update approximately every 0.5 seconds
        with current_processed_lock:
            current_count = current_processed_count
        now = time.time()

        # Calculate instantaneous rate based on the last interval
        # This provides a more responsive rate display
        count_delta = current_count - last_count
        time_delta = now - last_time

        if time_delta > 0:
            instant_rate = count_delta / time_delta
        else:
            instant_rate = 0.0

        # Calculate overall average rate since start
        if start_time:
            elapsed = now - start_time
            if elapsed > 0:
                overall_rate = current_count / elapsed
            else:
                overall_rate = 0.0
        else:
            overall_rate = 0.0

        # Print the rate information on the same line, overwriting previous output
        # Use \r to return cursor to the beginning of the line
        # Use end='' to prevent adding a newline
        # Use flush=True to ensure the output is displayed immediately
        sys.stdout.write(f"\r[Rate Monitor] Processed: {current_count}, Instant Rate: {instant_rate:.2f} img/s, Overall Rate: {overall_rate:.2f} img/s")
        sys.stdout.flush()

        last_count = current_count
        last_time = now

# --- Helper Functions ---
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
    # Define paths for the output files in their respective subfolders
    original_target_path = os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER, filename)
    compressed_target_path = os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER, f"{os.path.splitext(filename)[0]}.avif") # Change extension to .avif

    # Check if the compressed version already exists (primary check)
    if os.path.exists(compressed_target_path):
        print(f"\nCompressed file {os.path.basename(compressed_target_path)} already exists, skipping processing for {filename}.")
        return os.path.basename(compressed_target_path) # Return the name of the compressed file generated

    # Create subdirectories if they don't exist
    os.makedirs(os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER), exist_ok=True)
    os.makedirs(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER), exist_ok=True)

    try:
        # Open the original image
        with Image.open(source_path) as original_img:
            # --- Save Original Image ---
            # Ensure the original image is in a compatible format (e.g., RGB) for saving
            original_img_to_save = ImageOps.exif_transpose(original_img) # Apply EXIF orientation
            # If the original image was in a mode like RGBA, P, etc., you might need to convert it
            # original_img_to_save = original_img_to_save.convert("RGB") # Uncomment if needed
            original_img_to_save.save(original_target_path)

            # --- Process and Save Compressed Image (AVIF) ---
            width, height = original_img_to_save.size
            if width > height: # Horizontal
                RATIO_H = 7 / 5 # Example value, ensure this is defined
                new_width = int(height * RATIO_H)
                new_height = int(height if new_width <= width else width / RATIO_H)
                new_width = int(width if new_width > width else new_width)
            else: # Vertical
                RATIO_V = 5 / 7 # Example value, ensure this is defined
                new_height = int(width / RATIO_V)
                new_width = int(width if new_height <= height else height * RATIO_V)
                new_height = int(height if new_height > height else new_height)

            cropped_img = center_crop(original_img_to_save, new_width, new_height)

            # Save cropped image as AVIF using pillow-avif-plugin
            # AVIF compression settings can be adjusted (e.g., quality, speed)
            # Here, we use default settings from Pillow's AVIF plugin
            # You can add options like quality=80, speed=4 if supported by the plugin
            cropped_img.save(compressed_target_path, format="AVIF", quality=80) # Example quality setting

        # Update the global counter and lock it briefly
        with current_processed_lock:
            global current_processed_count
            current_processed_count += 1

        return os.path.basename(compressed_target_path) # Return the name of the *compressed* file generated
    except Exception as e:
        print(f"\nError processing {filename}: {e}")
        return None

def process_images():
    global start_time, rate_display_thread, stop_rate_display, current_processed_count

    # Create main target directory and subdirectories
    os.makedirs(os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER), exist_ok=True)
    os.makedirs(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER), exist_ok=True)
    print(f"Ensured directories exist: {os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER)} and {os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER)}")

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

        # Reset counters and start time before processing
        current_processed_count = 0
        start_time = time.time()
        stop_rate_display.clear() # Ensure the stop event is clear

        # Start the rate display thread
        rate_display_thread = threading.Thread(target=update_rate_display, daemon=True)
        rate_display_thread.start()

        try:
            # Note: This uses ThreadPoolExecutor, which is suitable for I/O bound tasks
            # like image loading and saving.
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                results = list(executor.map(process_single_image, source_files))

            # Wait for the main processing to complete
            processed_files = [f for f in results if f is not None]

        finally:
            # Stop the rate display thread after processing is done
            stop_rate_display.set()
            if rate_display_thread and rate_display_thread.is_alive():
                 rate_display_thread.join(timeout=2) # Wait for up to 2 seconds for the thread to finish
            print("\n") # Add a newline after the rate display stops
            print(f"Finished processing. {len(processed_files)} compressed images available in '{COMPRESSED_SUBFOLDER}' subfolder.")

    else:
        print("Skipping photo processing. Scanning existing compressed AVIF images...")
        try:
            # Scan the COMPRESSED_SUBFOLDER for .avif files
            for filename in os.listdir(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER)):
                if (not filename.startswith('._') and
                    filename.lower().endswith('.avif')): # Check for .avif extension
                    processed_files.append(filename) # Append the name of the AVIF file
            processed_files.sort()
            print(f"Found {len(processed_files)} existing compressed AVIF images.")
        except FileNotFoundError:
            print(f"Warning: Compressed sub-folder not found at {os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER)}")
            return []

    return processed_files

# --- Updated get_photo_data_worker ---
def get_photo_data_worker(task_tuple):
    i, filename, ratings_cache = task_tuple
    # The filename now refers to the compressed AVIF file
    compressed_filename = filename
    # The original filename is the AVIF name without extension, plus .JPG
    original_filename = f"{os.path.splitext(filename)[0]}.JPG"

    # Paths for the compressed (AVIF) and original (JPG) files
    compressed_target_path = os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER, compressed_filename)
    original_source_path = os.path.join(SOURCE_FOLDER, original_filename) # Path to original in source folder

    metadata = { "filename": compressed_filename, "model": "Unknown", "f_stop": "Unknown", "shutter_speed": "Unknown", "iso": "Unknown" }

    try:
        # Load metadata from the original source image (JPG)
        if os.path.exists(original_source_path):
            with Image.open(original_source_path) as img:
                width, height = img.size
                orientation = 'horizontal' if width > height else 'vertical'

                exif_data = img.getexif()
                if exif_data:
                    exif = { ExifTags.TAGS[k]: v for k, v in exif_data.items() if k in ExifTags.TAGS }
                    metadata["model"] = exif.get("Model", "Unknown")
                    metadata["f_stop"] = f"f/{exif.get('FNumber', 'N/A')}"
                    ss = exif.get('ExposureTime', 0)
                    if ss > 0:
                        metadata["shutter_speed"] = f"1/{round(1/ss)}s" if ss < 1 else f"{ss}s"
                    metadata["iso"] = exif.get("ISOSpeedRatings", "N/A")
        else:
            print(f"Warning: Original source file {original_source_path} not found for metadata extraction.")
            # Fallback to get dimensions from the compressed AVIF if source is missing
            with Image.open(compressed_target_path) as img:
                 width, height = img.size
                 orientation = 'horizontal' if width > height else 'vertical'
    except Exception as e:
        print(f"Error reading metadata for {compressed_filename} (from source {original_source_path}): {e}")
        # Set a default orientation if dimensions couldn't be read
        orientation = 'horizontal'

    # Determine rating logic (same as before, but filename refers to AVIF now)
    if compressed_filename.replace("avif", "JPG") in ratings_cache and not SHOULD_FETCH_NEW_RATINGS:
        rating = ratings_cache[compressed_filename.replace("avif", "JPG")]
        new_rating = False
    elif compressed_filename.replace("avif", "JPG") in ratings_cache and SHOULD_FETCH_NEW_RATINGS:
        rating = ratings_cache[compressed_filename.replace("avif", "JPG")]
        new_rating = False
    else:
        if SHOULD_FETCH_NEW_RATINGS:
            rating = -1 # Placeholder for new rating logic
            new_rating = True
            print(f"Fetching new rating for {compressed_filename}...")
        else:
            rating = -1 # Default rating when not fetching new ratings
            new_rating = False
            print(f"Assigning default rating for {compressed_filename}...")

    return {
        "id": i + 1,
        "rating": rating,
        "new_rating_acquired": new_rating,
        "orientation": orientation,
        # The URL now points to the compressed AVIF file
        "url": f"/{API_URL_BASE}/{COMPRESSED_SUBFOLDER}/{compressed_filename}",
        "metadata": metadata
    }


# --- Updated Eager Processing Function ---
def run_eager_processing():
    """
    This is the main function that runs at startup.
    It prepares all photo data and populates the global ALL_PHOTO_DATA.
    """
    global ALL_PHOTO_DATA

    processed_files = process_images()

    ratings_cache = {}
    # SHOULD_RELOAD_RATINGS removed: Always load cache if it exists when not processing fresh
    if os.path.exists(RATING_CACHE_FILE):
        try:
            with open(RATING_CACHE_FILE, 'r') as f:
                ratings_cache = json.load(f)
                print(f"Loaded {len(ratings_cache)} ratings from cache.")
        except Exception as e:
            print(f"Error loading rating cache: {e}")
    # else: print("No rating cache file found, will start fresh or assign defaults.")

    tasks = [(i, filename, ratings_cache) for i, filename in enumerate(processed_files)]
    photo_data_map = {}

    if SHOULD_FETCH_NEW_RATINGS:
        # Use ThreadPoolExecutor (correct for Mac + I/O bound tasks like metadata reading)
        executor_cls = concurrent.futures.ThreadPoolExecutor

        print(f"Getting photo data in PARALLEL using {executor_cls.__name__} (max_workers: {MAX_WORKERS})...")
        start_time_meta = time.time()

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

                except Exception as e:
                    print(f"\n[Parallel Error] Failed to process {filename}. Adding to retry queue. Error: {e}\n")
                    failed_tasks.append(task)

        end_time_meta = time.time()
        print(f"\nFinished Pass 1 (metadata/rating) in {end_time_meta - start_time_meta:.2f} seconds.")

        # --- Pass 2: Serial Retry ---
        if failed_tasks:
            print(f"\nRetrying {len(failed_tasks)} failed images in SERIAL (this will be stable)...")
            start_time_serial = time.time()

            for i, task in enumerate(failed_tasks):
                filename = task[1]
                try:
                    result = get_photo_data_worker(task)
                    photo_data_map[result['id']] = result
                except Exception as e:
                    print(f"\n[Serial Error] FAILED to process {filename} even in serial mode: {e}")

            end_time_serial = time.time()
            print(f"\nFinished Pass 2 in {end_time_serial - start_time_serial:.2f} seconds.")

    else:
        # --- FAST LAUNCH path ---
        print("Getting photo data in SERIAL (using cache or assigning defaults)...")
        for task in tasks:
            photo_data_map[task[0]] = get_photo_data_worker(task)

    # --- Final Processing ---
    ALL_PHOTO_DATA = [ photo_data_map[key] for key in sorted(photo_data_map.keys()) ]

    cache_updated = False
    for data in ALL_PHOTO_DATA:
        if data.get("new_rating_acquired", False):
            # The key in the cache is the name of the compressed AVIF file
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


# --- Main Flask Routes ---
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