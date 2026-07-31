/* ---------------------------------------------------
   activity_detail.js
   Activity Details page: evidence-image zoom/pan and arrow-key navigation
   between activities. Extracted from the template so the browser can cache
   it; contains no server-injected values.
--------------------------------------------------- */

(function () {
    // --- Image zoom (wheel) + pan (drag when zoomed) ---
    var container = document.getElementById('zoom-container');
    var img = document.getElementById('zoom-image');
    if (container && img) {
        var scale = 1, minScale = 1, maxScale = 4;
        var originX = 0, originY = 0;
        var isDragging = false, startX = 0, startY = 0;

        function applyTransform() {
            img.style.transform = 'translate(' + originX + 'px, ' + originY + 'px) scale(' + scale + ')';
            container.style.cursor = scale > minScale ? 'grab' : 'default';
        }

        container.addEventListener('wheel', function (e) {
            e.preventDefault();
            var delta = e.deltaY < 0 ? 0.15 : -0.15;
            scale = Math.min(maxScale, Math.max(minScale, scale + delta));
            if (scale === minScale) { originX = 0; originY = 0; }
            applyTransform();
        }, { passive: false });

        container.addEventListener('mousedown', function (e) {
            if (scale <= minScale) return;
            isDragging = true;
            startX = e.clientX - originX;
            startY = e.clientY - originY;
            container.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', function (e) {
            if (!isDragging) return;
            originX = e.clientX - startX;
            originY = e.clientY - startY;
            applyTransform();
        });

        window.addEventListener('mouseup', function () {
            isDragging = false;
            applyTransform();
        });
    }

    // --- Keyboard prev/next (skip if typing in the comment box) ---
    document.addEventListener('keydown', function (e) {
        var activeTag = (document.activeElement && document.activeElement.tagName) || '';
        if (activeTag === 'TEXTAREA' || activeTag === 'INPUT') return;

        if (e.key === 'ArrowLeft') {
            var prevLink = document.getElementById('prev-link');
            if (prevLink) window.location.href = prevLink.href;
        } else if (e.key === 'ArrowRight') {
            var nextLink = document.getElementById('next-link');
            if (nextLink) window.location.href = nextLink.href;
        }
    });
})();
