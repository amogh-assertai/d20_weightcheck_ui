/* ---------------------------------------------------
   history.js
   History page: Export to Excel confirmation modal. Clicking "Export to
   Excel" doesn't download immediately - it shows a modal explaining that
   only the currently filtered set will be exported (not the full history),
   with the exact record count, before the user confirms.
--------------------------------------------------- */

(function () {
    var exportBtn = document.getElementById('export-btn');
    var modal = document.getElementById('export-modal');
    var cancelBtn = document.getElementById('export-cancel');
    var confirmLink = document.getElementById('export-confirm');

    if (!exportBtn || !modal) return; // no matching activities - button isn't rendered

    exportBtn.addEventListener('click', function () {
        var baseUrl = exportBtn.getAttribute('data-export-url');
        var queryString = window.location.search; // exact filters currently applied
        confirmLink.setAttribute('href', baseUrl + queryString);
        modal.style.display = 'flex';
    });

    cancelBtn.addEventListener('click', function () {
        modal.style.display = 'none';
    });

    // Clicking the dark overlay (outside the box) also cancels.
    modal.addEventListener('click', function (e) {
        if (e.target === modal) modal.style.display = 'none';
    });

    // The confirm link itself triggers the download and can just close the
    // modal right away - no need to wait for anything.
    confirmLink.addEventListener('click', function () {
        modal.style.display = 'none';
    });
})();
