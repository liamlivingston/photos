document.addEventListener('DOMContentLoaded', () => {
    
    const galleryContainer = document.getElementById('gallery');
    
    // --- NEW: Get references to all our new UI elements ---
    const lightbox = document.getElementById('lightbox-overlay');
    const lightboxImg = document.getElementById('lightbox-img');
    const sidebar = document.getElementById('metadata-sidebar');
    const metadataContent = document.getElementById('metadata-content');
    const closeButton = document.getElementById('close-button');
    const detailsButton = document.getElementById('details-button');
    
    const MAX_ROW_UNITS = 4;
    
    // Store all photo data here for easy lookup
    let allPhotosData = [];
    let currentPhoto = null; // Store the currently open photo

    /**
     * Builds a single row.
     */
    function buildRow(rowPhotos) {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'gallery-row';

        rowPhotos.forEach(photo => {
            const img = document.createElement('img');
            img.src = photo.url;
            img.alt = `Photo ${photo.id}`;
            
            const isHorizontal = (photo.orientation === 'horizontal');
            img.className = isHorizontal ? 'img-horizontal' : 'img-vertical';
            img.style.flexGrow = isHorizontal ? '2' : '1';

            // --- NEW: Add click listener to the image ---
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

    // --- NEW: Functions to control the lightbox ---

    function openLightbox(event) {
        const photoId = parseInt(event.target.dataset.photoId);
        currentPhoto = allPhotosData.find(p => p.id === photoId);
        
        if (!currentPhoto) return;

        lightboxImg.src = currentPhoto.url; // Set the image
        lightbox.classList.add('show');      // Show the overlay
        
        // Prevent body from scrolling underneath
        document.body.style.overflow = 'hidden'; 
    }

    function closeLightbox() {
        lightbox.classList.remove('show');          // Hide overlay
        sidebar.classList.remove('show');         // Hide sidebar
        lightbox.classList.remove('show-metadata'); // Remove 'push'
        currentPhoto = null;
        
        // Allow body scrolling again
        document.body.style.overflow = 'auto'; 
    }
    
    function toggleDetails() {
        if (!currentPhoto) return;
        
        const isShowing = sidebar.classList.toggle('show');
        lightbox.classList.toggle('show-metadata', isShowing); // 'show-metadata' only if sidebar is showing
        
        if (isShowing) {
            populateMetadata(currentPhoto);
        }
    }
    
    function populateMetadata(photo) {
        const meta = photo.metadata;
        // Build simple HTML for the metadata
        metadataContent.innerHTML = `
            <p><strong>Filename</strong> ${meta.filename}</p>
            <p><strong>Rating</strong> ${photo.rating} / 10</p>
            <p><strong>Model</strong> ${meta.model}</p>
            <p><strong>F-Stop</strong> ${meta.f_stop}</p>
            <p><strong>Shutter Speed</strong> ${meta.shutter_speed}</p>
            <p><strong>ISO</strong> ${meta.iso}</p>
        `;
    }
    
    // --- NEW: Add listeners to buttons ---
    closeButton.addEventListener('click', closeLightbox);
    detailsButton.addEventListener('click', toggleDetails);
    
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
            galleryContainer.innerHTML = ''; 
            allPhotosData = photos; // Store photos
            createLayout(photos);
        })
        .catch(error => {
            console.error('Error fetching photos:', error);
            galleryContainer.innerHTML = '<p>Error loading photos.</p>';
        });
    
    // We don't need the resize handler anymore
});