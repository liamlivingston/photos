document.addEventListener('DOMContentLoaded', () => {
    
    const galleryContainer = document.getElementById('gallery');
    
    // --- Get references to all our new UI elements ---
    const lightbox = document.getElementById('lightbox-overlay');
    const lightboxImg = document.getElementById('lightbox-img');
    const sidebar = document.getElementById('metadata-sidebar');
    const metadataContent = document.getElementById('metadata-content');
    const closeButton = document.getElementById('close-button');
    const detailsButton = document.getElementById('details-button');
    const prevButton = document.getElementById('prev-button');
    const nextButton = document.getElementById('next-button');
    
    // --- Get sort UI references ---
    const sortKeySelect = document.getElementById('sort-key');
    const sortDirSelect = document.getElementById('sort-dir');
    
    const MAX_ROW_UNITS = 4;
    
    // Store all photo data here. This list will be sorted in place.
    let allPhotosData = [];
    let currentPhoto = null; // Store the currently open photo
    let currentPhotoIndex = -1; // Store the current index

    /**
     * Builds a single row.
     */
    function buildRow(rowPhotos) {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'gallery-row';

        rowPhotos.forEach(photo => {
            const img = document.createElement('img');
            img.src = photo.url; // Use the compressed AVIF URL for the grid
            img.alt = `Photo ${photo.id}`;
            
            const isHorizontal = (photo.orientation === 'horizontal');
            img.className = isHorizontal ? 'img-horizontal' : 'img-vertical';
            img.style.flexGrow = isHorizontal ? '2' : '1';
            
            img.dataset.photoId = photo.id; // Store ID for lookup
            img.addEventListener('click', openLightbox);
            
            rowDiv.appendChild(img);
        });
        galleryContainer.appendChild(rowDiv);
    }

    /**
     * The row packing algorithm.
     */
    function createLayout(photos) {
        let photoQueue = [...photos];
        while (photoQueue.length > 0) {
            let rowPhotos = [];
            let rowUnits = 0;
            while (photoQueue.length > 0) {
                const nextPhoto = photoQueue[0];
                const nextPhotoUnits = (nextPhoto.orientation === 'horizontal') ? 2 : 1;
                if (rowUnits > 0 && (rowUnits + nextPhotoUnits > MAX_ROW_UNITS)) {
                    break;
                }
                rowUnits += nextPhotoUnits;
                rowPhotos.push(photoQueue.shift());
            }
            if (rowPhotos.length > 0) {
                buildRow(rowPhotos);
            }
        }
    }

    // --- Main function to sort the data and re-render the gallery ---
    function applySortAndRender() {
        const key = sortKeySelect.value;
        const dir = sortDirSelect.value;
        
        // Sort the allPhotosData array in place
        allPhotosData.sort((a, b) => {
            let valA, valB;
            
            // Get the values to compare
            if (key === 'rating') {
                valA = a.rating;
                valB = b.rating;
            } else if (key === 'date') { // --- MODIFIED: Use new date field ---
                valA = a.date_for_sort;
                valB = b.date_for_sort;
            } else { // 'filename'
                valA = a.metadata.filename.toLowerCase();
                valB = b.metadata.filename.toLowerCase();
            }
            
            // Perform comparison
            let comparison = 0;
            if (valA > valB) {
                comparison = 1;
            } else if (valA < valB) {
                comparison = -1;
            }
            
            // Apply direction (Ascending or Descending)
            return (dir === 'asc') ? comparison : -comparison;
        });
        
        // Clear the old gallery
        galleryContainer.innerHTML = '';
        
        // Re-build the layout with the sorted data
        createLayout(allPhotosData);
    }

    // --- Helper function to show a photo by its index ---
    function showPhotoByIndex(index) {
        if (index < 0 || index >= allPhotosData.length) {
            console.error('Index out of bounds');
            return;
        }
        
        currentPhotoIndex = index;
        currentPhoto = allPhotosData[currentPhotoIndex];
        
        // --- THIS IS THE ORIGINAL IMAGE LOGIC ---
        // It correctly replaces the .avif URL with the .JPG URL
        lightboxImg.src = currentPhoto.url.replace(/\/compressed_avif\//, '/original/').replace(/\.avif$/i, '.JPG');
        
        // If metadata sidebar is open, update it
        if (sidebar.classList.contains('show')) {
            populateMetadata(currentPhoto);
        }
    }

    // --- Navigation functions ---
    function showNextPhoto(event) {
        if(event) event.stopPropagation(); 
        let nextIndex = (currentPhotoIndex + 1) % allPhotosData.length;
        showPhotoByIndex(nextIndex);
    }
    
    function showPrevPhoto(event) {
        if(event) event.stopPropagation(); 
        let prevIndex = (currentPhotoIndex - 1 + allPhotosData.length) % allPhotosData.length;
        showPhotoByIndex(prevIndex);
    }

    // --- UPDATED: openLightbox function ---
    function openLightbox(event) {
        const photoId = parseInt(event.target.dataset.photoId);
        
        // Find the index of the clicked photo *in the currently sorted list*
        const photoIndex = allPhotosData.findIndex(p => p.id === photoId);
        if (photoIndex === -1) {
            console.error('Photo not found');
            return;
        }

        // Show the photo
        showPhotoByIndex(photoIndex);
        
        lightbox.classList.add('show');
        document.body.style.overflow = 'hidden';
        document.addEventListener('keydown', handleKeydown);
    }

    // --- UPDATED: closeLightbox function ---
    function closeLightbox() {
        lightbox.classList.remove('show');
        sidebar.classList.remove('show');
        lightbox.classList.remove('show-metadata');
        currentPhoto = null;
        currentPhotoIndex = -1;
        
        document.body.style.overflow = 'auto'; 
        document.removeEventListener('keydown', handleKeydown);
    }
    
    function toggleDetails(event) {
        if(event) event.stopPropagation();
        if (!currentPhoto) return;
        
        const isShowing = sidebar.classList.toggle('show');
        lightbox.classList.toggle('show-metadata', isShowing);
        
        if (isShowing) {
            populateMetadata(currentPhoto);
        }
    }
    
    // --- MODIFIED: Updated populateMetadata ---
    function populateMetadata(photo) {
        const meta = photo.metadata;
        
        // Format the date string
        let dateStr = "Unknown";
        if (meta.date_taken) {
            // EXIF dates are 'YYYY:MM:DD HH:MM:SS'. Need to replace colons in date part for JS.
            const parts = meta.date_taken.split(' ');
            const datePart = parts[0].replace(/:/g, '/');
            dateStr = new Date(datePart + ' ' + parts[1]).toLocaleString();
        } else {
            // Fall back to file modification time
            dateStr = new Date(photo.mtime * 1000).toLocaleString();
        }

        // Build simple HTML for the metadata
        // meta.filename is now the original JPG filename (from app.py)
        metadataContent.innerHTML = `
            <p><strong>Filename</strong> ${meta.filename}</p>
            <p><strong>Date Taken</strong> ${dateStr}</p>
            <p><strong>Rating</strong> ${photo.rating < 0 ? 'Not Rated' : Number.parseFloat(photo.rating).toFixed(2) + ' / 10'}</p>
            <p><strong>Model</strong> ${meta.model}</p>
            <p><strong>F-Stop</strong> ${meta.f_stop}</p>
            <p><strong>Shutter Speed</strong> ${meta.shutter_speed}</p>
            <p><strong>ISO</strong> ${meta.iso}</p>
        `;
    }
    
    // --- Keydown handler ---
    function handleKeydown(event) {
        if (event.key === 'ArrowRight') {
            showNextPhoto();
        } else if (event.key === 'ArrowLeft') {
            showPrevPhoto();
        } else if (event.key === 'Escape') {
            closeLightbox();
        }
    }

    // --- Add listeners to buttons ---
    closeButton.addEventListener('click', closeLightbox);
    detailsButton.addEventListener('click', toggleDetails);
    prevButton.addEventListener('click', showPrevPhoto);
    nextButton.addEventListener('click', showNextPhoto);
    
    // --- Add sort UI listeners ---
    sortKeySelect.addEventListener('change', applySortAndRender);
    sortDirSelect.addEventListener('change', applySortAndRender);
    
    // Close lightbox if user clicks on the dark backdrop
    lightbox.addEventListener('click', (event) => {
        if (event.target === lightbox) {
            closeLightbox();
        }
    });

    // --- Main execution ---
    fetch('/api/photos')
        .then(response => response.json())
        .then(photos => {
            allPhotosData = photos; // Store photos
            
            // --- MODIFIED: Update sort key value to 'date' ---
            // Set the UI to "Date" and "Descending" and apply it.
            sortKeySelect.value = 'date';
            sortDirSelect.value = 'desc';
            applySortAndRender(); 
        })
        .catch(error => {
            console.error('Error fetching photos:', error);
            galleryContainer.innerHTML = '<p>Error loading photos.</p>';
        });
    
});