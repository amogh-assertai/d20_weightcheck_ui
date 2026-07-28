// Theme toggle: switches data-theme on <html> and remembers the choice.
// Default is "dark" (set in base.html) if the user hasn't chosen yet.
(function () {
    var root = document.documentElement;
    var toggleBtn = document.getElementById('theme-toggle');
    var iconEl = document.getElementById('theme-toggle-icon');
    var labelEl = document.getElementById('theme-toggle-label');

    function applyLabel(theme) {
        if (!iconEl || !labelEl) return;
        if (theme === 'light') {
            iconEl.textContent = '\u2600'; // sun
            labelEl.textContent = 'Light';
        } else {
            iconEl.textContent = '\u263D'; // moon
            labelEl.textContent = 'Dark';
        }
    }

    // Sync the button label with whichever theme is already active
    // (pre-paint script in base.html may have already applied a saved theme).
    applyLabel(root.getAttribute('data-theme') || 'dark');

    if (toggleBtn) {
        toggleBtn.addEventListener('click', function () {
            var current = root.getAttribute('data-theme') || 'dark';
            var next = current === 'dark' ? 'light' : 'dark';
            root.setAttribute('data-theme', next);
            applyLabel(next);
            try {
                localStorage.setItem('theme', next);
            } catch (e) {
                // Can't persist (e.g. private browsing) - theme still applies for this session
            }
        });
    }
})();

// Auto-dismiss flash messages (e.g. "Review saved.") after a few seconds.
(function () {
    document.querySelectorAll('.flash-message').forEach(function (el) {
        setTimeout(function () {
            el.style.transition = 'opacity 0.3s ease';
            el.style.opacity = '0';
            setTimeout(function () { el.remove(); }, 300);
        }, 3000);
    });
})();

// Toggle-buttons (Yes/No style radio groups): give instant visual feedback
// when an option is picked. Radios already enforce "only one selected"
// natively via shared 'name'; this just keeps the highlighted-label class
// in sync. Global so any page using .toggle-buttons gets this for free
// (Activity Details review form, Settings page pattern picker, etc.)
(function () {
    document.querySelectorAll('.toggle-buttons').forEach(function (group) {
        group.querySelectorAll('input[type="radio"]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                group.querySelectorAll('.toggle-buttons__option').forEach(function (label) {
                    label.classList.remove('is-selected');
                });
                if (radio.checked) {
                    var label = radio.closest('.toggle-buttons__option');
                    if (label) label.classList.add('is-selected');
                }
            });
        });
    });
})();
