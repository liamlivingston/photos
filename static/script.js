document.addEventListener('DOMContentLoaded', () => {
    
    const galleryContainer = document.getElementById('gallery');
    
    // This is our "row capacity". A horizontal (H) image costs 2,
    // a vertical (V) image costs 1.
    // A '4' unit row could be: V,V,V,V or H,V,V or H,H
    // You can change this value to make the tiles larger/smaller.
    const MAX_ROW_UNITS = 4;

    /**
     * This function builds a single row and adds it to the DOM.
     * @param {Array} rowPhotos - The list of photo objects for this row.
     */
    function buildRow(rowPhotos) {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'gallery-row';

        rowPhotos.forEach(photo => {
            const img = document.createElement('img');
            img.src = photo.url;
            img.alt = `Photo ${photo.id}`;

            const isHorizontal = (photo.orientation === 'horizontal');
            
            // 1. Set the aspect-ratio class
            img.className = isHorizontal ? 'img-horizontal' : 'img-vertical';
            
            // 2. Set the 'flex-grow' value based on its "cost"
            // This tells the H images to take up 2x the space of V images.
            img.style.flexGrow = isHorizontal ? '2' : '1';

            rowDiv.appendChild(img);
        });

        galleryContainer.appendChild(rowDiv);
    }

    /**
     * This is the "row packing" algorithm.
     * It loops through photos and groups them into rows.
     * @param {Array} photos - The full, chronological list of photos.
     */
    function createLayout(photos) {
        let photoQueue = [...photos]; // Create a copy
        
        while (photoQueue.length > 0) {
            
            let rowPhotos = [];
            let rowUnits = 0;
            
            // Keep adding photos until the row is "full"
            while (photoQueue.length > 0) {
                const nextPhoto = photoQueue[0]; // Peek at next photo
                const nextPhotoUnits = (nextPhoto.orientation === 'horizontal') ? 2 : 1;

                // If adding this photo would overflow, stop.
                if (rowUnits > 0 && (rowUnits + nextPhotoUnits > MAX_ROW_UNITS)) {
                    break;
                }
                
                // It fits! Consume the photo from the queue and add to row.
                rowUnits += nextPhotoUnits;
                rowPhotos.push(photoQueue.shift());
            }

            // Build the row (if it has any photos)
            if (rowPhotos.length > 0) {
                buildRow(rowPhotos);
            }
        }
    }


    // --- Main execution ---
    fetch('/api/photos')
        .then(response => response.json())
        .then(photos => {
            galleryContainer.innerHTML = ''; 
            createLayout(photos);
        })
        .catch(error => {
            console.error('Error fetching photos:', error);
            galleryContainer.innerHTML = '<p>Error loading photos.</p>';
        });
    
    // We don't need a resize handler, as this flexbox-based
    // layout is 100% fluid and will reflow perfectly.
});