document.addEventListener('DOMContentLoaded', () => {

    // --- DOM References ---
    const imgA = document.getElementById('image-a');
    const imgB = document.getElementById('image-b');
    const wrapperA = document.getElementById('image-a-wrapper');
    const wrapperB = document.getElementById('image-b-wrapper');
    const undoButton = document.getElementById('undo-button');
    const totalVotesSpan = document.getElementById('total-votes');

    // --- State ---
    let currentPair = null;
    let voteHistory = []; // Frontend history stack to restore images on undo
    let totalVotes = parseInt(totalVotesSpan.textContent, 10) || 0;
    let isVoting = false; // Lock to prevent double-voting

    /**
     * Fetches the next pair of images from the backend.
     */
    async function fetchNextPair() {
        // if (isVoting) return; // <-- THIS IS THE BUGGY LINE. IT IS NOW REMOVED.
        isVoting = true; // This lock now correctly applies *only* to the fetch operation.

        // Show placeholders while loading
        imgA.src = "https://placehold.co/800x600/333/555?text=Loading...";
        imgB.src = "https://placehold.co/800x600/333/555?text=Loading...";
        
        try {
            // Added a cache-busting timestamp query parameter
            const url = `/api/rater/next-pair?t=${new Date().getTime()}`;
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error('Failed to fetch next pair.');
            }
            const data = await response.json();
            
            // Preload images before showing them
            await Promise.all([
                preloadImage(data.image_a.url),
                preloadImage(data.image_b.url)
            ]);
            
            currentPair = data;
            imgA.src = data.image_a.url;
            imgB.src = data.image_b.url;

        } catch (error) {
            console.error(error);
            imgA.src = "https://placehold.co/800x600/c0392b/ffffff?text=Error+Loading";
            imgB.src = "https://placehold.co/800x600/c0392b/ffffff?text=Error+Loading";
        } finally {
            isVoting = false; // Release the lock *after* fetching is done.
        }
    }
    
    /**
     * Helper to preload an image
     */
    function preloadImage(src) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = () => reject(new Error(`Failed to load ${src}`));
            img.src = src;
        });
    }

    /**
     * Sends the user's vote to the backend.
     */
    async function sendVote(winnerName, loserName) {
        // This check is good. It prevents the user from double-clicking.
        if (isVoting || !currentPair) return; 
        isVoting = true; // Set the lock to prevent new votes.
        
        // Push the *current* state to history before voting
        voteHistory.push(currentPair);

        try {
            const response = await fetch('/api/rater/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ winner: winnerName, loser: loserName })
            });
            const data = await response.json();

            if (data.success) {
                totalVotes++;
                totalVotesSpan.textContent = totalVotes;
                undoButton.disabled = false; // Enable undo after the first vote
                await fetchNextPair(); // This will now run correctly.
            } else {
                throw new Error(data.message || 'Vote failed to record.');
            }
        } catch (error) {
            console.error(error);
            // Roll back history if vote failed
            voteHistory.pop();
            isVoting = false; // Manually release lock on error
        }
        // On success, the lock is released by the `finally` block in fetchNextPair()
    }

    /**
     * Handles the "Undo" button click.
     */
    async function handleUndo() {
        if (voteHistory.length === 0) return;

        // Disable button to prevent double-undo
        undoButton.disabled = true; 

        try {
            const response = await fetch('/api/rater/undo', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                // Restore the previous pair from our frontend history
                const lastPair = voteHistory.pop();
                currentPair = lastPair;
                imgA.src = lastPair.image_a.url;
                imgB.src = lastPair.image_b.url;
                
                totalVotes--;
                totalVotesSpan.textContent = totalVotes;
            } else {
                throw new Error(data.message || 'Undo failed.');
            }
        } catch (error) {
            console.error(error);
        } finally {
            // Re-enable the button *if* there's still history
            if (voteHistory.length > 0) {
                undoButton.disabled = false;
            }
        }
    }

    // --- Event Listeners ---

    // Click listeners
    wrapperA.addEventListener('click', () => {
        if (currentPair && !isVoting) { // Check that a pair is loaded and not voting
            sendVote(currentPair.image_a.name, currentPair.image_b.name);
        }
    });

    wrapperB.addEventListener('click', () => {
        if (currentPair && !isVoting) { // Check that a pair is loaded and not voting
            sendVote(currentPair.image_b.name, currentPair.image_a.name);
        }
    });

    // Undo button
    undoButton.addEventListener('click', handleUndo);

    // Keyboard listeners
    document.addEventListener('keydown', (e) => {
        // This check prevents key actions while loading or if pair isn't loaded
        if (isVoting || !currentPair) return; 

        if (e.key === 'ArrowLeft') {
            sendVote(currentPair.image_a.name, currentPair.image_b.name);
        } else if (e.key === 'ArrowRight') {
            sendVote(currentPair.image_b.name, currentPair.image_a.name);
        } else if (e.key === 'Backspace' && !undoButton.disabled) {
            handleUndo();
        }
    });

    // --- Initial Load ---
    fetchNextPair();
});