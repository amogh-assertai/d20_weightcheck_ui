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

/* ---------------------------------------------------
   Save for Active Learning: an instant-effect toggle, not tied to the
   review form's Save button - clicking it IS the save. Calls the server
   immediately via fetch() and recolors itself from the actual response,
   rather than assuming success and flipping color optimistically.
--------------------------------------------------- */
(function () {
    var btn = document.getElementById('active-learning-toggle');
    if (!btn) return;

    function render(isOn) {
        btn.textContent = isOn ? 'Saved for Active Learning' : 'Save for Active Learning';
        btn.classList.toggle('active-learning-toggle--on', isOn);
    }

    btn.addEventListener('click', function () {
        var url = btn.getAttribute('data-toggle-url');
        btn.disabled = true;
        fetch(url, { method: 'POST' })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                render(!!data.saved_for_active_learning);
            })
            .catch(function () {
                console.warn('Could not update the active learning flag - please try again.');
            })
            .finally(function () {
                btn.disabled = false;
            });
    });
})();
