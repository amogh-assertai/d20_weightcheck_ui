/* ---------------------------------------------------
   activity_detail_review.js
   Marked for Discussion: a single button that flips between Yes/No on
   each click, instead of two separate Yes/No radio options. The actual
   submitted value still lives in the hidden #discuss-hidden-input (same
   YES/NO/untouched data model as before - only the input widget changed).

   Kept as its own file rather than merged into activity_detail.js, so
   this addition can't accidentally clash with whatever else that file
   already does (image zoom/pan, arrow-key navigation).
--------------------------------------------------- */

(function () {
    var toggleBtn = document.getElementById('discuss-toggle');
    var hiddenInput = document.getElementById('discuss-hidden-input');
    if (!toggleBtn || !hiddenInput) return;

    function render(value) {
        if (value === 'YES') {
            toggleBtn.textContent = 'Yes';
            toggleBtn.className = 'single-toggle single-toggle--yes';
        } else if (value === 'NO') {
            toggleBtn.textContent = 'No';
            toggleBtn.className = 'single-toggle single-toggle--no';
        } else {
            toggleBtn.textContent = 'Not set - click to mark';
            toggleBtn.className = 'single-toggle single-toggle--unset';
        }
    }

    toggleBtn.addEventListener('click', function () {
        // Unset or "No" -> clicking sets "Yes"; "Yes" -> clicking sets "No".
        var next = hiddenInput.value === 'YES' ? 'NO' : 'YES';
        hiddenInput.value = next;
        render(next);
    });

    render(hiddenInput.value);
})();
