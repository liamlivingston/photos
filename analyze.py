#!/usr/bin/env python3

import os
import sys
import argparse  # New import
from PIL import Image
import concurrent.futures

# --- Worker Function (Efficient) ---
def get_fast_orientation(filepath):
    """
    Efficiently gets the orientation by reading only the image headers.
    """
    try:
        with Image.open(filepath) as img:
            width, height = img.size
            orientation_tag = None
            exif = img.getexif()
            if exif:
                orientation_tag = exif.get(0x0112) # 0x0112 = Orientation tag

            # Tags 5, 6, 7, 8 mean the camera was held vertically
            if orientation_tag in [5, 6, 7, 8]:
                return 'V'
            else:
                # Tags 1-4 or None, use pixel dimensions
                if width > height:
                    return 'H'
                else:
                    return 'V'
                    
    except Exception as e:
        print(f"Skipping {os.path.basename(filepath)}: {e}", file=sys.stderr)
        return None

# --- This function now returns stats instead of printing ---
def get_directory_stats(directory_path, num_threads):
    """
    Analyzes a single directory and returns a dictionary of its stats.
    Uses a thread pool for parallel file processing.
    """
    
    # --- 1. Find, filter, and sort all images (Serial) ---
    all_files = []
    try:
        for filename in os.listdir(directory_path):
            filepath = os.path.join(directory_path, filename)
            
            if (os.path.isfile(filepath) and
                not filename.startswith('._') and
                filename.upper().endswith('.JPG')):
                
                mtime = os.path.getmtime(filepath)
                all_files.append((filepath, mtime))
                
    except FileNotFoundError:
        print(f"Error: Directory not found at '{directory_path}'", file=sys.stderr)
        return None
    except Exception as e:
        print(f"An error occurred listing files: {e}", file=sys.stderr)
        return None

    all_files.sort(key=lambda x: x[1])

    if not all_files:
        # This is not an error, just an empty directory
        return None

    # --- 2. Determine orientation for each image (Parallel) ---
    
    filepaths_in_order = [f[0] for f in all_files]
    orientations = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        results_with_none = list(executor.map(get_fast_orientation, filepaths_in_order))

    orientations = [o for o in results_with_none if o is not None]
    total_images = len(orientations)

    if total_images < 2:
        return None # Not enough images to calculate randomness

    # --- 3. Calculate stats ---
    h_count = orientations.count('H')
    v_count = orientations.count('V')
    
    h_v_ratio = h_count / v_count if v_count > 0 else float('inf')

    switches = 0
    for i in range(1, total_images):
        if orientations[i] != orientations[i-1]:
            switches += 1
            
    total_possible_switches = total_images - 1
    switch_percentage = (switches / total_possible_switches) * 100

    # Return all stats in a dictionary
    return {
        "path": directory_path,
        "randomness": switch_percentage,
        "total_images": total_images,
        "h_count": h_count,
        "v_count": v_count,
        "h_v_ratio": h_v_ratio
    }

# --- Main Execution Block ---
if __name__ == "__main__":
    
    # 1. Setup Argument Parser
    parser = argparse.ArgumentParser(
        description="Analyze image orientation randomness in directories."
    )
    parser.add_argument(
        "directory",
        help="The root directory to analyze."
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Analyze all subdirectories recursively."
    )
    parser.add_argument(
        "-t", "--threads",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of threads to use for file processing."
    )
    
    args = parser.parse_args()
    
    # 2. Build the list of directories to analyze
    directories_to_analyze = []
    if args.recursive:
        print(f"Recursively scanning for directories in {args.directory}...")
        for root, dirs, files in os.walk(args.directory):
            directories_to_analyze.append(root)
    else:
        directories_to_analyze.append(args.directory)

    # 3. Run the analysis for each directory
    print(f"Found {len(directories_to_analyze)} director{'y' if len(directories_to_analyze) == 1 else 'ies'}. Analyzing with {args.threads} threads...")
    all_stats = []
    
    for i, path in enumerate(directories_to_analyze):
        # Print progress
        print(f"Analyzing [{i+1}/{len(directories_to_analyze)}] {path}", end='\r')
        
        stats = get_directory_stats(path, args.threads)
        if stats:
            all_stats.append(stats)
            
    print("\nAnalysis complete." + " "*20) # Clear progress line

    # 4. Sort and print the final "Top 3" report
    if not all_stats:
        print("No directories with valid images were found.")
        sys.exit(0)

    # Sort by "randomness" percentage, descending
    all_stats.sort(key=lambda x: x["randomness"], reverse=True)

    print("\n--- Top 3 Most Random Directories ---")
    
    for i, stats in enumerate(all_stats[:3]):
        print(f"\n#{i+1}: {stats['path']}")
        print(f"  **Randomness: {stats['randomness']:.2f}%**")
        print(f"  Total Images: {stats['total_images']} (H:{stats['h_count']}, V:{stats['v_count']})")
        if stats['v_count'] > 0:
            print(f"  H/V Ratio:    {stats['h_v_ratio']:.2f}")
        else:
            print("  H/V Ratio:    Undefined")