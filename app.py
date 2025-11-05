import os
import random
import concurrent.futures  # Import the parallelization library
from flask import Flask, render_template, jsonify
from PIL import Image, ImageOps

# --- Configuration ---
SOURCE_FOLDER = '/photos/lumix-export'
TARGET_FOLDER = 'static/cropped_images'
RATIO_H = 7 / 5  # approx 1.4
RATIO_V = 5 / 7  # approx 0.71

app = Flask(__name__)

# --- Helper Function (Unchanged) ---
def center_crop(img, crop_width, crop_height):
    """Helper function to crop an image from the center."""
    img_width, img_height = img.size
    left = (img_width - crop_width) / 2
    top = (img_height - crop_height) / 2
    right = (img_width + crop_width) / 2
    bottom = (img_height + crop_height) / 2
    
    return img.crop((left, top, right, bottom))

# --- Worker Function for Image Processing ---
def process_single_image(source_tuple):
    """
    Worker task that processes one image.
    Takes a (source_path, mtime) tuple.
    Returns filename on success/exists, None on failure.
    """
    source_path, mtime = source_tuple
    filename = os.path.basename(source_path)
    target_path = os.path.join(TARGET_FOLDER, filename)

    if os.path.exists(target_path):
        return filename  # Skip processing, return success
    
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
        return None  # Return None on failure

# --- Updated Image Processing Manager Function ---
def process_images():
    """
    Crops images from the source folder and saves them to the target folder.
    Runs in parallel if app.debug is True.
    """
    if not os.path.exists(TARGET_FOLDER):
        os.makedirs(TARGET_FOLDER)
        print(f"Created directory: {TARGET_FOLDER}")

    # 1. Find and filter files (Fast, serial)
    source_files = []
    for filename in os.listdir(SOURCE_FOLDER):
        source_path = os.path.join(SOURCE_FOLDER, filename)
        if (os.path.isfile(source_path) and
            not filename.startswith('._') and
            filename.upper().endswith('.JPG')):
            mtime = os.path.getmtime(source_path)
            source_files.append((source_path, mtime))

    # 2. Sort by modification time (Fast, serial)
    source_files.sort(key=lambda x: x[1])
    
    print(f"Found {len(source_files)} images to process...")
    processed_files = []

    # 3. Process images (Parallel in debug, serial in prod)
    if app.debug:
        print("Processing images in PARALLEL (debug mode)...")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # map preserves the order, which is critical
            results = list(executor.map(process_single_image, source_files))
        processed_files = [f for f in results if f is not None]
    
    else:
        print("Processing images in SERIAL (production mode)...")
        for source_tuple in source_files:
            result = process_single_image(source_tuple)
            if result:
                processed_files.append(result)
    
    print(f"Finished processing. {len(processed_files)} images available.")
    return processed_files

# --- Worker Function for API Data ---
def get_photo_data_worker(task_tuple):
    """
    Worker task that gets orientation for one processed image.
    Takes an (index, filename) tuple.
    Returns the final API dictionary.
    """
    i, filename = task_tuple
    target_path = os.path.join(TARGET_FOLDER, filename)
    
    try:
        with Image.open(target_path) as img:
            width, height = img.size
            orientation = 'horizontal' if width > height else 'vertical'
    except Exception:
        orientation = 'horizontal' # Fallback
        
    return {
        "id": i + 1,
        "rating": random.randint(1, 10),
        "orientation": orientation,
        "url": f"/{TARGET_FOLDER}/{filename}"
    }

# --- Main Flask Routes ---
@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')


@app.route('/api/photos')
def get_photos():
    """
    This API now reads our PROCESSED images, which are already sorted
    by the process_images function.
    This step also runs in parallel during debug mode.
    """
    processed_files = process_images() # This list is now chronological
    
    tasks = list(enumerate(processed_files))
    photo_data = []

    if app.debug:
        print("Getting photo data in PARALLEL (debug mode)...")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # map preserves the order
            photo_data = list(executor.map(get_photo_data_worker, tasks))
    else:
        print("Getting photo data in SERIAL (production mode)...")
        for task in tasks:
            photo_data.append(get_photo_data_worker(task))

    return jsonify(photo_data)


if __name__ == '__main__':
    # Setting debug=True here will enable the parallel processing
    app.run(debug=True)