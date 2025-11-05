import os
import sys
import pyiqa
import torch
from PIL import Image, ImageOps

# --- 1. Configuration ---
# TODO: CHANGE THIS to a real image path on your system
TEST_IMAGE_PATH = "/home/liam/Pictures/Backup/Panasonic G7/107_PANA/P1070001.JPG"
TARGET_FILE_PATH = "test_cropped_image.jpg" # It will save this in the same folder

RATIO_H = 7 / 5  # approx 1.4
RATIO_V = 5 / 7  # approx 0.71

# --- Global model variable
aesthetic_model = None 

# --- 2. Helper Functions ---

def get_cpu_device():
    """Forcing CPU for stability."""
    print("Forcing device: cpu")
    return torch.device('cpu')

def load_model(device):
    """Loads the AI model into memory."""
    global aesthetic_model
    print(f"Using device: {device}")
    try:
        # We will use the paq2piq model
        aesthetic_model = pyiqa.create_metric('paq2piq', device=device)
        print("Local aesthetic model (pyiqa paq2piq) loaded successfully.")
    except Exception as e:
        print(f"Error loading local model: {e}")
        sys.exit(1)

def center_crop(img, crop_width, crop_height):
    """Crops an image from the center."""
    img_width, img_height = img.size
    left = (img_width - crop_width) / 2
    top = (img_height - crop_height) / 2
    right = (img_width + crop_width) / 2
    bottom = (img_height + crop_height) / 2
    return img.crop((left, top, right, bottom))

def crop_image(source_path, target_path):
    """Crops a single image to the 1:sqrt(2) ratio."""
    print(f"Processing crop for: {source_path}")
    try:
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img) # Respect camera rotation
            
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
            print(f"Successfully saved cropped image to: {target_path}")
            return True
    except Exception as e:
        print(f"Error during image cropping: {e}")
        return False

def get_local_rating(cropped_image_path):
    """Runs the AI model on the cropped image."""
    if not aesthetic_model:
        print("Model is not loaded. Cannot get rating.")
        return -1
    
    print(f"Running AI model on: {cropped_image_path}")
    try:
        # Run the model (on the CPU)
        score_0_to_100 = aesthetic_model(cropped_image_path).item()
        
        # Scale the score to be 1-10
        rating = (score_0_to_100 / 100) * 9 + 1
        rating = round(rating, 1) 
        
        print(f"\n--- AI RATING: {rating}/10 ---")
        return rating
    except Exception as e:
        print(f"\n!!!!!!!!!!!!!!!!! ERROR !!!!!!!!!!!!!!!!!")
        print(f"Failed to get rating for image: {cropped_image_path}")
        print(f"Error: {e}")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        return -1

# --- 3. Main Test Execution ---
if __name__ == '__main__':
    
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"Error: Test image not found at {TEST_IMAGE_PATH}")
        print("Please update the TEST_IMAGE_PATH variable in this script.")
        sys.exit(1)
        
    print("--- STARTING STABILITY TEST (CPU ONLY) ---")

    # 1. Load the AI Model
    device = get_cpu_device()
    load_model(device)
    
    # 2. Process the Image Crop
    success = crop_image(TEST_IMAGE_PATH, TARGET_FILE_PATH)
    
    # 3. Rate the Cropped Image
    if success:
        get_local_rating(TARGET_FILE_PATH)
    
    print("\n--- TEST COMPLETE ---")