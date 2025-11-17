import os
import random
import sys
import concurrent.futures
import json
import time
import threading
import subprocess # NEW: For checking if exiftool is installed
import exiftool # NEW: Import pyexiftool
from collections import deque # NEW: For 5-second rate average

from flask import Flask, render_template, jsonify
from PIL import Image, ImageOps, ExifTags # ExifTags imported

# --- Configuration ---
SOURCE_FOLDER = 'photos/lumix-export' # Source folder containing original images
TARGET_FOLDER = 'photos/static/cropped_images' # Main target folder (will contain 'original' and 'compressed' subfolders)
API_URL_BASE = 'static/cropped_images'
RATING_CACHE_FILE = 'photo_ratings.json'

# Sub-folder names
ORIGINAL_SUBFOLDER = 'original'
COMPRESSED_SUBFOLDER = 'compressed_avif' # Subfolder for AVIF files

# Set based on your system's capabilities for I/O bound tasks
MAX_WORKERS = 16 # Adjust if needed based on performance/RAM

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
EXIFTOOL_IS_INSTALLED = False

# --- Rate Tracking Variables ---
start_time = None
current_processed_count = 0
current_processed_lock = threading.Lock() # Protects access to the counter
rate_display_thread = None
stop_rate_display = threading.Event() # Signal to stop the rate display thread
# NEW: For 5-second average
rate_history = deque()

def check_exiftool():
    """Checks if the ExifTool command-line utility is installed."""
    global EXIFTOOL_IS_INSTALLED
    try:
        subprocess.run(["exiftool", "-ver"], check=True, capture_output=True)
        print("ExifTool is installed. Metadata will be preserved.")
        EXIFTOOL_IS_INSTALLED = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("--- WARNING ---")
        print("ExifTool not found. brew install exiftool (macOS) or apt-get install libimage-exiftool-perl (Linux)")
        print("Metadata will NOT be transferred to processed images.")
        print("---------------")
        EXIFTOOL_IS_INSTALLED = False

def _update_progress_display(total_items, task_name="Processing"):
    """Function run by the rate display thread."""
    global current_processed_count, start_time, rate_history # --- MODIFIED: Added global declarations ---
    
    rate_history.clear()
    
    while not stop_rate_display.is_set():
        time.sleep(0.5) # Update approximately every 0.5 seconds
        now = time.time()
        
        with current_processed_lock:
            current_count = current_processed_count

        # Add the current state to the events list
        rate_history.append((now, current_count))
        
        # Remove events older than 5 seconds
        cutoff_time = now - 5.0
        while rate_history and rate_history[0][0] < cutoff_time:
            rate_history.popleft()

        # Calculate the 5-second average rate
        if len(rate_history) >= 2:
            first_time, first_count = rate_history[0]
            last_time, last_count = rate_history[-1]
            
            time_span = last_time - first_time
            count_span = last_count - first_count
            
            if time_span > 0:
                current_rate = count_span / time_span
            else:
                current_rate = 0.0
        else:
            current_rate = 0.0

        # Calculate overall average rate since start
        if start_time:
            elapsed = now - start_time
            if elapsed > 0:
                overall_rate = current_count / elapsed
            else:
                overall_rate = 0.0
        else:
            overall_rate = 0.0
            
        # Calculate percentage
        percent_done = 0
        if total_items > 0:
            percent_done = (current_count / total_items) * 100

        # Print the rate information on the same line
        sys.stdout.write(
            f"\r{task_name}: {current_count}/{total_items} ({percent_done:.1f}%) | "
            f"Avg: {overall_rate:.2f} img/s | "
            f"Current: {current_rate:.2f} img/s"
        )
        sys.stdout.flush()

# --- Helper Functions ---

def _find_source_file(base_filename_no_ext, folder):
    """Checks for .JPG, .jpg, .JPEG, and .jpeg."""
    for ext in [".JPG", ".jpg", ".JPEG", ".jpeg"]:
        path = os.path.join(folder, f"{base_filename_no_ext}{ext}")
        if os.path.exists(path):
            return path
    return None # Not found

def center_crop(img, crop_width, crop_height):
    img_width, img_height = img.size
    left = (img_width - crop_width) / 2
    top = (img_height - crop_height) / 2
    right = (img_width + crop_width) / 2
    bottom = (img_height + crop_height) / 2
    return img.crop((left, top, right, bottom))

def _update_metadata_single_image(paths_tuple):
    """
    A dedicated function to run exiftool.
    This is run in parallel during Pass 3.
    """
    # --- MODIFIED: Moved global declaration to top of function ---
    global current_processed_count
    
    source_path, compressed_target_path = paths_tuple
    
    try:
        with exiftool.ExifToolHelper() as et:
            et.execute(
                f"-TagsFromFile {source_path}",
                "-all:all", # Copy all tag groups
                "-overwrite_original", # Modify the AVIF file in-place
                f"{compressed_target_path}"
            )
        
        with current_processed_lock:
            current_processed_count += 1
            
    except Exception as e:
        filename = os.path.basename(source_path)
        print(f"\nExifTool failed for {filename}: {e}")

def process_single_image(source_tuple):
    """
    Smarter processing function - PASS 1: File Creation.
    1. Does FAST os.path.exists() checks first.
    2. If files exist, returns immediately.
    3. If files are missing, *then* opens source JPG to create them.
    """
    # --- MODIFIED: Moved global declaration to top of function ---
    global current_processed_count
    
    source_path, mtime = source_tuple
    filename = os.path.basename(source_path)
    
    # --- MODIFICATION: Standardize all output filenames ---
    base_name = os.path.splitext(filename)[0]
    standardized_jpg_filename = f"{base_name}.JPG" # Always use .JPG
    standardized_avif_filename = f"{base_name}.avif"

    original_target_path = os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER, standardized_jpg_filename)
    compressed_target_path = os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER, standardized_avif_filename)
    # --- END MODIFICATION ---

    # Ensure target directories exist (this is cheap, can run every time)
    os.makedirs(os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER), exist_ok=True)
    os.makedirs(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER), exist_ok=True)

    # --- NEW: Fast "ls" check first ---
    need_to_create_jpg = not os.path.exists(original_target_path)
    need_to_create_avif = not os.path.exists(compressed_target_path)

    # If both files exist, we are done. This is the fast path.
    if not need_to_create_jpg and not need_to_create_avif:
        with current_processed_lock:
            current_processed_count += 2 # Count both files as "checked"
        return (standardized_avif_filename, mtime) # Return standardized avif name
    
    # --- SLOW PATH: Only run if files are missing ---
    try:
        # We only open the source image *if we have to*
        with Image.open(source_path) as original_img:
            source_exif_data = original_img.info.get('exif')
            original_img_to_save = ImageOps.exif_transpose(original_img)
            
        if need_to_create_jpg:
             original_img_to_save.save(original_target_path, exif=source_exif_data)

        if need_to_create_avif:
            # --- Perform Cropping and Saving (no metadata) ---
            width, height = original_img_to_save.size
            if width > height: # Horizontal
                RATIO_H = 7 / 5 
                new_width = int(height * RATIO_H)
                new_height = int(height if new_width <= width else width / RATIO_H)
                new_width = int(width if new_width > width else new_width)
            else: # Vertical
                RATIO_V = 5 / 7
                new_height = int(width / RATIO_V)
                new_width = int(width if new_height <= height else height * RATIO_V)
                new_height = int(height if new_height > height else new_height)

            cropped_img = center_crop(original_img_to_save, new_width, new_height)
            
            # --- MODIFIED: Save *without* exif data. We'll add it after. ---
            cropped_img.save(compressed_target_path, format="AVIF", quality=80)
        
        # --- MODIFIED: Always increment the counter ---
        with current_processed_lock:
            # We increment by 2, for the 2 files we just checked/processed
            current_processed_count += 2

        # --- 4. Return ---
        return (standardized_avif_filename, mtime) # Return standardized avif name

    except Exception as e:
        print(f"\nError processing {filename}: {e}")
        # --- MODIFIED: Also increment counter on error so progress bar doesn't stall ---
        with current_processed_lock:
            # We increment by 2, for the 2 files we just checked/processed
            current_processed_count += 2 # Count it as "processed" even if it failed
        return None

# --- NEW: Helper function for Pass 2 (Audit) ---
def _audit_metadata_single_image(source_tuple):
    """
    A dedicated function to audit metadata.
    This is run in parallel during Pass 2.
    Returns paths if update is needed, else None.
    
    --- MODIFIED: This now uses exiftool for a reliable check. ---
    """
    # --- MODIFIED: Moved global declaration to top of function ---
    global current_processed_count
    
    source_path, mtime = source_tuple
    filename = os.path.basename(source_path)
    base_name = os.path.splitext(filename)[0]
    compressed_target_path = os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER, f"{base_name}.avif")

    needs_update = False
    
    try:
        # Use a single exiftool context to get tags from both files
        with exiftool.ExifToolHelper() as et:
            # We only need one or two tags to do this check.
            # 'EXIF:DateTimeOriginal' is a good proxy for "has metadata".
            tags_to_get = ["EXIF:DateTimeOriginal", "EXIF:DateTimeDigitized"]
            source_meta = et.get_tags(source_path, tags_to_get)
            target_meta = et.get_tags(compressed_target_path, tags_to_get)

        # Get the first available tag from the source
        source_date_tag = next((tag for tag in tags_to_get if tag in source_meta), None)
        
        if source_date_tag:
            # Source has a date. Target must also have it.
            if not any(tag in target_meta for tag in tags_to_get):
                needs_update = True
        elif target_meta:
            # Source has NO date, but target does (e.g., stale metadata).
            needs_update = True
        
    except Exception as e:
        # This can happen if the AVIF file is corrupt or empty
        print(f"\nError auditing {filename}, adding to update queue: {e}")
        needs_update = True # Update just in case
    
    finally:
        # Increment progress counter *after* check
        with current_processed_lock:
            current_processed_count += 1
    
    if needs_update:
        return (source_path, compressed_target_path)
    
    return None # Metadata matches


def process_images():
    # --- MODIFIED: Added global declarations for all assigned global vars ---
    global start_time, rate_display_thread, stop_rate_display, current_processed_count, rate_history

    # Create main target directory and subdirectories
    os.makedirs(os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER), exist_ok=True)
    os.makedirs(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER), exist_ok=True)
    print(f"Ensured directories exist: {os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER)} and {os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER)}")

    processed_files = [] # This will hold (avif_filename, mtime)

    if SHOULD_PROCESS_PHOTOS:
        print("Running --reload: Checking photo library for updates...")
        if not os.path.exists(SOURCE_FOLDER):
            print(f"ERROR: --reload failed. SOURCE_FOLDER not found at {SOURCE_FOLDER}")
            return []

        source_files = []
        for filename in os.listdir(SOURCE_FOLDER):
            source_path = os.path.join(SOURCE_FOLDER, filename)
            if (os.path.isfile(source_path) and
                not filename.startswith('._') and
                filename.lower().endswith(('.jpg', '.jpeg'))): # <-- MODIFIED: Check all extensions
                mtime = os.path.getmtime(source_path)
                source_files.append((source_path, mtime))

        source_files.sort(key=lambda x: x[1])
        print(f"Found {len(source_files)} source images.")

        # --- PASS 1: File Generation ---
        print(f"\nPass 1: Checking for {len(source_files) * 2} (JPG + AVIF) files...")
        # Reset counters and start time before processing
        current_processed_count = 0
        start_time = time.time()
        stop_rate_display.clear() # Ensure the stop event is clear
        rate_history.clear()

        # Start the rate display thread
        rate_display_thread = threading.Thread(
            target=_update_progress_display, 
            args=(len(source_files) * 2, "Pass 1: Checking/Creating files"), # Total items is 2 * num_sources
            daemon=True
        )
        rate_display_thread.start()

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                results = list(executor.map(process_single_image, source_files))
            processed_files = [f for f in results if f is not None]

        finally:
            stop_rate_display.set()
            if rate_display_thread and rate_display_thread.is_alive():
                 rate_display_thread.join(timeout=2)
            print("\nPass 1 complete.")

        # --- PASS 2: Metadata Audit (NOW PARALLEL) ---
        if EXIFTOOL_IS_INSTALLED:
            print("\nPass 2: Auditing metadata...")
            files_to_update_metadata = []
            
            # Reset counters
            current_processed_count = 0
            start_time = time.time()
            stop_rate_display.clear()
            rate_history.clear()
            
            rate_display_thread = threading.Thread(
                target=_update_progress_display,
                args=(len(source_files), "Pass 2: Auditing metadata"), # Total items is num_sources
                daemon=True
            )
            rate_display_thread.start()
            
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    # This runs the audit in parallel
                    audit_results = list(executor.map(_audit_metadata_single_image, source_files))
                
                # Filter out the 'None' results
                files_to_update_metadata = [res for res in audit_results if res is not None]
            
            finally:
                stop_rate_display.set()
                if rate_display_thread and rate_display_thread.is_alive():
                     rate_display_thread.join(timeout=2)
                print("\nPass 2 (Audit) complete.")

            # --- PASS 3: Metadata Update (NOW BATCHED) ---
            if files_to_update_metadata:
                print(f"\nPass 3: Found {len(files_to_update_metadata)} images needing metadata update.")
                print("Updating all in a single batch (this may take a moment)...")
                
                # --- MODIFIED: Removed parallel processing for a single, stable batch command ---
                start_batch_time = time.time()
                try:
                    with exiftool.ExifToolHelper() as et:
                        for source_path, compressed_target_path in files_to_update_metadata:
                            # Build and execute commands one by one, but in a single helper context
                            et.execute(
                                f"-TagsFromFile {source_path}",
                                "-all:all", # Copy all tags
                                "-overwrite_original", # Modify the AVIF file in-place
                                f"{compressed_target_path}"
                            )
                    end_batch_time = time.time()
                    print(f"\nPass 3 (Update) complete in {end_batch_time - start_batch_time:.2f} seconds.")
                except Exception as e:
                    print(f"\nPass 3 FAILED: {e}")
                    print("You may need to run with --reload again.")
                # --- END MODIFICATION ---

            else:
                print("Metadata is up-to-date.")

        else: # Exiftool not installed
            print("Skipping metadata update (ExifTool not found).")
            
    # --- NON-RELOAD PATH (Fast Startup) ---
    else:
        # ... (This part is unchanged and fine) ...
        print("Skipping photo processing. Scanning existing compressed AVIF images...")
        try:
            for filename in os.listdir(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER)):
                if (not filename.startswith('._') and
                    filename.lower().endswith('.avif')): # Check for .avif extension
                    
                    # --- MODIFIED: Use helper to find original file (JPG or jpg) ---
                    base_name = os.path.splitext(filename)[0]
                    original_file_path = _find_source_file(base_name, os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER))
                    
                    mtime = 0 # Default mtime if original is missing
                    if original_file_path: # Check if it was found
                        mtime = os.path.getmtime(original_file_path)
                    elif os.path.exists(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER, filename)):
                        mtime = os.path.getmtime(os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER, filename))
                    
                    processed_files.append((filename, mtime)) # Append tuple (filename, mtime)
            
            processed_files.sort(key=lambda x: x[1]) 
            print(f"Found {len(processed_files)} existing compressed AVIF images.")
        except FileNotFoundError:
            print(f"Warning: Compressed sub-folder not found at {os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER)}")
            return []

    return processed_files

# --- Updated get_photo_data_worker ---
def get_photo_data_worker(task_tuple):
    """
    MODIFIED: This function now uses exiftool to read metadata.
    This is slower than Pillow but correctly reads all tags.
    """
    i, filename, mtime, ratings_cache = task_tuple
    compressed_filename = filename # e.g., P1070001.avif
    
    # --- MODIFIED: Use helper to find original file paths ---
    base_name = os.path.splitext(filename)[0] # e.g., P1070001
    
    original_source_path = _find_source_file(base_name, SOURCE_FOLDER)
    original_copy_path = _find_source_file(base_name, os.path.join(TARGET_FOLDER, ORIGINAL_SUBFOLDER))

    # Get the *actual* filename (with correct case) from the found path
    original_filename = os.path.basename(original_source_path) if original_source_path else f"{base_name}.JPG" # Fallback
    # --- END MODIFICATION ---

    compressed_target_path = os.path.join(TARGET_FOLDER, COMPRESSED_SUBFOLDER, compressed_filename)
    
    metadata = { 
        "filename": original_filename, 
        "model": "Unknown", 
        "f_stop": "Unknown", 
        "shutter_speed": "Unknown", 
        "iso": "Unknown",
        "date_taken": None 
    }
    orientation = 'horizontal' # Default

    try:
        # --- MODIFIED: Use pyexiftool to read metadata ---
        path_to_read = original_copy_path if original_copy_path else original_source_path
        
        if path_to_read and os.path.exists(path_to_read) and EXIFTOOL_IS_INSTALLED:
            with exiftool.ExifToolHelper() as et:
                # --- THIS IS THE BUG FIX ---
                # Changed from get_metadata_batch() to get_metadata()
                meta_list = et.get_metadata([path_to_read])
                # --- END BUG FIX ---
                
                if meta_list:
                    meta = meta_list[0] # Get the first (and only) item
                    
                    # --- Map EXIFTool tags to our simpler keys ---
                    metadata["model"] = meta.get("EXIF:Model", "Unknown")
                    
                    # F-Stop
                    f_number = meta.get("EXIF:FNumber", 0)
                    if f_number > 0:
                        metadata["f_stop"] = f"f/{f_number}"
                    else:
                        metadata["f_stop"] = "N/A"
                        
                    # Shutter Speed
                    ss_raw = meta.get("EXIF:ExposureTime", 0)
                    if isinstance(ss_raw, str) and '/' in ss_raw:
                        metadata["shutter_speed"] = f"{ss_raw}s"
                    elif ss_raw > 0:
                        if ss_raw < 1:
                            metadata["shutter_speed"] = f"1/{round(1/ss_raw)}s"
                        else:
                            metadata["shutter_speed"] = f"{ss_raw}s"
                    else:
                         metadata["shutter_speed"] = "N/A"
                         
                    metadata["iso"] = meta.get("EXIF:ISO", "N/A")
                    
                    # --- THIS IS THE DATE FIX ---
                    # Prioritize "DateTimeDigitized" (Created On)
                    # Fall back to "DateTimeOriginal" (what Pillow was getting)
                    metadata["date_taken"] = meta.get("EXIF:DateTimeDigitized", meta.get("EXIF:DateTimeOriginal", None))
                    
                    # --- Get Orientation ---
                    orientation_tag = meta.get("EXIF:Orientation", 1)
                    if orientation_tag in [5, 6, 7, 8]:
                        orientation = 'vertical'
                    else:
                        # Use pixel dimensions (which are pre-rotation)
                        width = meta.get("EXIF:ImageWidth", 1)
                        height = meta.get("EXIF:ImageHeight", 1)
                        orientation = 'horizontal' if width > height else 'vertical'
        
        # --- Fallback to Pillow if exiftool fails or is missing ---
        elif path_to_read and os.path.exists(path_to_read):
            print(f"Warning: Using Pillow fallback for {filename}")
            with Image.open(path_to_read) as img:
                width, height = img.size
                orientation_tag = None
                exif_data = img.getexif()
                if exif_data:
                    orientation_tag = exif_data.get(0x0112)
                    exif = { ExifTags.TAGS[k]: v for k, v in exif_data.items() if k in ExifTags.TAGS }
                    metadata["model"] = exif.get("Model", "Unknown")
                    metadata["f_stop"] = f"f/{exif.get('FNumber', 'N/A')}"
                    ss = exif.get('ExposureTime', 0)
                    if ss > 0:
                        metadata["shutter_speed"] = f"1/{round(1/ss)}s" if ss < 1 else f"{ss}s"
                    metadata["iso"] = exif.get("ISOSpeedRatings", "N/A")
                    # This is the "wrong" date, but it's the best Pillow can do
                    metadata["date_taken"] = exif.get("DateTimeOriginal", None) 
                
                if orientation_tag in [5, 6, 7, 8]:
                    orientation = 'vertical'
                else:
                    orientation = 'horizontal' if width > height else 'vertical'
        else:
             print(f"Warning: No source file found for {base_name}. Reading AVIF dimensions.")
             with Image.open(compressed_target_path) as img:
                 width, height = img.size
                 orientation = 'horizontal' if width > height else 'vertical'

    except Exception as e:
        print(f"Error reading metadata for {compressed_filename}: {e}")
        orientation = 'horizontal' # Keep default on error

    # Determine rating logic
    cache_key = original_filename # Cache key is the original JPG name
    if cache_key in ratings_cache and not SHOULD_FETCH_NEW_RATINGS:
        rating = float(ratings_cache[cache_key]) 
        new_rating = False
    elif cache_key in ratings_cache and SHOULD_FETCH_NEW_RATINGS:
        rating = float(ratings_cache[cache_key])
        new_rating = False
    else:
        if SHOULD_FETCH_NEW_RATINGS:
            rating = -1.0 
            new_rating = True
        else:
            rating = -1.0 
            new_rating = False

    return {
        "id": i + 1,
        "rating": rating,
        "date_for_sort": metadata["date_taken"] or mtime, # Use this for sorting
        "mtime": mtime, # Keep mtime for reference
        "new_rating_acquired": new_rating,
        "orientation": orientation,
        "url": f"/{API_URL_BASE}/{COMPRESSED_SUBFOLDER}/{compressed_filename}", # URL is for the AVIF
        "metadata": metadata # Metadata contains original filename, date, etc.
    }


# --- Updated Eager Processing Function ---
def run_eager_processing():
    """
    This is the main function that runs at startup.
    It prepares all photo data and populates the global ALL_PHOTO_DATA.
    """
    # --- MODIFIED: Added global declaration ---
    global ALL_PHOTO_DATA

    processed_files = process_images() # This is now a list of (filename, mtime) tuples

    ratings_cache = {}
    if os.path.exists(RATING_CACHE_FILE):
        try:
            with open(RATING_CACHE_FILE, 'r') as f:
                ratings_cache = json.load(f)
                print(f"Loaded {len(ratings_cache)} ratings from cache.")
        except Exception as e:
            print(f"Error loading rating cache: {e}")

    tasks = [(i, file_tuple[0], file_tuple[1], ratings_cache) for i, file_tuple in enumerate(processed_files)]
    photo_data_map = {}

    # --- MODIFIED: We always run data-gathering in parallel now ---
    executor_cls = concurrent.futures.ThreadPoolExecutor
    print(f"\nGathering metadata in PARALLEL using {executor_cls.__name__} (max_workers: {MAX_WORKERS})...")
    start_time_meta = time.time()
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
    print(f"\nFinished gathering metadata in {end_time_meta - start_time_meta:.2f} seconds.")

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

    # --- Final Processing ---
    ALL_PHOTO_DATA = [ photo_data_map[key] for key in sorted(photo_data_map.keys()) ]

    cache_updated = False
    for data in ALL_PHOTO_DATA:
        if data.get("new_rating_acquired", False):
            # --- MODIFIED: Use the original filename from metadata for the cache key ---
            filename_jpg = data['metadata']['filename']
            ratings_cache[filename_jpg] = data["rating"]
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
    # --- NEW: Check for ExifTool at startup ---
    check_exiftool() 
    run_eager_processing()
    app.run(debug=True)