import os
import random
import sys
import json
import time
import threading
from flask import Flask, render_template, jsonify, request

# --- Configuration ---
# Use the same static asset folders as your main app.py
IMAGE_DIR = os.path.join('photos', 'static', 'cropped_images', 'original')
IMAGE_URL_PREFIX = '/static/cropped_images/original' # URL path to access these images
DATASET_FILE = 'ratings_dataset.jsonl' # We use .jsonl (JSON Lines) for easy appending

# --- Flask Setup ---
# We set up the static/template folders to match your existing project
app = Flask(
    __name__,
    static_folder='photos/static',
    template_folder='templates'
)

# --- Global State ---
image_pool = []
rating_history = [] # A stack to hold recent votes for the "undo" feature
data_lock = threading.Lock() # Ensures file/history writes are safe

def load_image_pool():
    """Scans the image directory and populates the in-memory list."""
    global image_pool
    if not os.path.exists(IMAGE_DIR):
        print(f"Error: Image directory not found at {IMAGE_DIR}", file=sys.stderr)
        print("Please run 'app.py --reload' first to generate images.", file=sys.stderr)
        return

    for filename in os.listdir(IMAGE_DIR):
        if filename.lower().endswith(('.jpg', '.jpeg')):
            image_pool.append(filename)
    
    print(f"--- Rater Loaded: Found {len(image_pool)} images in {IMAGE_DIR} ---")

def get_total_votes():
    """Counts the number of lines in the dataset file."""
    if not os.path.exists(DATASET_FILE):
        return 0
    try:
        with open(DATASET_FILE, 'r') as f:
            return len(f.readlines())
    except Exception as e:
        print(f"Error reading vote count: {e}", file=sys.stderr)
        return 0

# --- Web Routes ---

@app.route('/rater')
def rater_page():
    """Serves the main HTML page for the rater."""
    total_votes = get_total_votes()
    return render_template('rater.html', total_votes=total_votes)

# --- API Routes ---

@app.route('/api/rater/next-pair')
def get_next_pair():
    """Gets two random, unique images from the pool."""
    if len(image_pool) < 2:
        return jsonify({"error": "Not enough images in the pool."}), 500
    
    try:
        img_a_name, img_b_name = random.sample(image_pool, 2)
        
        img_a = {"name": img_a_name, "url": f"{IMAGE_URL_PREFIX}/{img_a_name}"}
        img_b = {"name": img_b_name, "url": f"{IMAGE_URL_PREFIX}/{img_b_name}"}
        
        return jsonify({"image_a": img_a, "image_b": img_b})
    except Exception as e:
        print(f"Error sampling images: {e}", file=sys.stderr)
        return jsonify({"error": str(e)}), 500

@app.route('/api/rater/vote', methods=['POST'])
def record_vote():
    """Records a vote to the dataset file and history."""
    data = request.json
    winner = data.get('winner')
    loser = data.get('loser')
    
    if not winner or not loser:
        return jsonify({"success": False, "message": "Invalid vote data."}), 400
    
    vote_entry = {
        "winner": winner,
        "loser": loser,
        "timestamp": time.time()
    }
    
    with data_lock:
        try:
            # Append to the JSON Lines file
            with open(DATASET_FILE, 'a') as f:
                f.write(json.dumps(vote_entry) + '\n')
            
            # Add to the in-memory history for "undo"
            rating_history.append(vote_entry)
            
            return jsonify({"success": True, "message": "Vote recorded."})
        except Exception as e:
            print(f"Error saving vote: {e}", file=sys.stderr)
            return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/rater/undo', methods=['POST'])
def undo_last_vote():
    """Removes the last vote from the dataset file and history."""
    with data_lock:
        if not rating_history:
            return jsonify({"success": False, "message": "No history to undo."}), 404
        
        try:
            # Remove from in-memory history
            last_vote = rating_history.pop()
            
            # Remove from the file (this is inefficient, but simple and safe)
            if os.path.exists(DATASET_FILE):
                with open(DATASET_FILE, 'r') as f:
                    lines = f.readlines()
                
                # Write all lines *except* the last one
                with open(DATASET_FILE, 'w') as f:
                    f.writelines(lines[:-1])
            
            return jsonify({"success": True, "undone_vote": last_vote})
        except Exception as e:
            print(f"Error undoing vote: {e}", file=sys.stderr)
            return jsonify({"success": False, "message": str(e)}), 500

# --- Main Execution ---

if __name__ == '__main__':
    load_image_pool()
    if not image_pool:
        print("--- Rater exiting: No images found to rate. ---", file=sys.stderr)
        sys.exit(1)
        
    # Run on a different port (e.g., 5001) so it doesn't conflict with app.py
    app.run(debug=True, port=5001)