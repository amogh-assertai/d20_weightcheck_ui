/* ---------------------------------------------------
   live_monitoring.js
   Live Monitoring board: real-time WebSocket updates, the configurable
   blink/solid signal, and audio playback with autoplay unlocking.

   Extracted from the template so the browser can cache it. Anything the
   server needs to supply (signal settings, audio mapping) arrives via the
   #live-monitoring-config JSON block rather than being templated in here.
--------------------------------------------------- */

(function () {
    // Server-injected config, read from the JSON block in the template.
    // Kept out of this file so the file itself stays static and cacheable.
    var configEl = document.getElementById('live-monitoring-config');
    var CONFIG = configEl ? JSON.parse(configEl.textContent) : {};

    var SIGNAL_PATTERN = CONFIG.signal_pattern || 'blink';
    var SIGNAL_DURATION_MS = CONFIG.signal_duration_ms || 5000;
    var SIGNAL_RETAIN_COLOR = CONFIG.signal_retain_color === true;
    var AUDIO_CONFIG = CONFIG.audio_config || {};

    // --- Audio on/off corner indicator + full-page unlock modal ---
    // Browsers block autoplay audio until the user has interacted with the
    // page at least once (a policy, not a bug). Any click/tap/keypress
    // ANYWHERE on this page counts as that interaction and unlocks audio -
    // the modal below is just a clear, unmissable nudge until that happens.
    var SILENT_AUDIO_SRC = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';
    var audioEnabled = false;
    var audioStatusEl = document.getElementById('audio-status');
    var audioModalEl = document.getElementById('audio-unlock-modal');

    function updateAudioStatusUI() {
        if (!audioStatusEl) return;
        if (audioEnabled) {
            audioStatusEl.innerHTML = '&#128266; Audio On';
            audioStatusEl.classList.add('audio-status--on');
            audioStatusEl.classList.remove('audio-status--off');
        } else {
            audioStatusEl.innerHTML = '&#128264; Click to enable audio';
            audioStatusEl.classList.add('audio-status--off');
            audioStatusEl.classList.remove('audio-status--on');
        }
    }

    function showAudioModal() {
        if (audioModalEl) audioModalEl.style.display = 'flex';
    }

    function hideAudioModal() {
        if (audioModalEl) audioModalEl.style.display = 'none';
    }

    function removeUnlockListeners() {
        document.removeEventListener('click', handleUnlockAttempt);
        document.removeEventListener('keydown', handleUnlockAttempt);
        document.removeEventListener('touchstart', handleUnlockAttempt);
    }

    function tryEnableAudio() {
        var testAudio = new Audio(SILENT_AUDIO_SRC);
        testAudio.play().then(function () {
            audioEnabled = true;
            updateAudioStatusUI();
            hideAudioModal();
            removeUnlockListeners();
        }).catch(function () {
            audioEnabled = false;
            updateAudioStatusUI();
            showAudioModal();
        });
    }

    function handleUnlockAttempt() {
        if (!audioEnabled) tryEnableAudio();
    }

    tryEnableAudio(); // succeeds immediately if the browser already granted permission from an earlier visit
    document.addEventListener('click', handleUnlockAttempt);
    document.addEventListener('keydown', handleUnlockAttempt);
    document.addEventListener('touchstart', handleUnlockAttempt);
    updateAudioStatusUI();

    // Preload every configured audio file up front, so playback is instant
    // when a real event arrives later - no network fetch at play-time.
    // Files that don't exist yet (404) are handled gracefully - logged
    // quietly, never thrown as an error, never breaks the page.
    var audioCache = {};
    var audioFileMissing = {};
    (function preloadAudio() {
        var seen = {};
        Object.keys(AUDIO_CONFIG).forEach(function (tableId) {
            Object.keys(AUDIO_CONFIG[tableId]).forEach(function (result) {
                var entry = AUDIO_CONFIG[tableId][result];
                if (entry && entry.file && !seen[entry.file]) {
                    seen[entry.file] = true;
                    var audio = new Audio('/audio/' + entry.file);
                    audio.preload = 'auto';
                    audio.addEventListener('error', function () {
                        audioFileMissing[entry.file] = true;
                        console.info('Audio file not available yet (ignored): ' + entry.file);
                    });
                    audioCache[entry.file] = audio;
                }
            });
        });
    })();

    // Plays the configured sound for this table+result, the configured
    // number of times, back to back. Only ever called from a live socket
    // update (see updateCard below) - never on initial page load/refresh.
    function playAudioForSignal(tableId, result) {
        var tableConfig = AUDIO_CONFIG[tableId];
        if (!tableConfig) return;
        var entry = tableConfig[result];
        if (!entry || !entry.file) return;
        if (audioFileMissing[entry.file]) return; // known-missing file - skip quietly

        var baseAudio = audioCache[entry.file];
        if (!baseAudio) return;

        var timesRemaining = entry.times || 1;
        function playNext() {
            if (timesRemaining <= 0) return;
            timesRemaining--;
            // Clone so rapid/overlapping triggers don't fight over one <audio> element's state.
            var clip = baseAudio.cloneNode();
            clip.addEventListener('ended', playNext);
            clip.addEventListener('error', function () {
                // Missing/broken file - stop this repeat chain quietly, no console error, no crash.
                audioFileMissing[entry.file] = true;
            });
            clip.play().catch(function () {
                // Covers both a missing file and the browser's autoplay-block
                // policy (blocked until the user interacts with the page once) -
                // neither is a real error, so handled silently here.
            });
        }
        playNext();
    }

    function badgeClassFor(result) {
        if (result === 'PASS') return 'pass';
        if (result === 'FAIL') return 'fail';
        if (result === 'MISSING_DATA' || result === 'INVALID_WEIGHT_DATA') return 'warn';
        return 'muted';
    }

    function signalColorClassFor(result) {
        return 'signal--' + badgeClassFor(result);
    }

    function clearSignal(card) {
        if (card._signalTimer) {
            clearTimeout(card._signalTimer);
            card._signalTimer = null;
        }
        card.classList.remove('signal-blink', 'signal--pass', 'signal--fail', 'signal--warn', 'signal--muted');
    }

    // Configurable per Settings: blink (repeating flash) or solid (steady
    // color) for SIGNAL_DURATION_MS, then either revert to neutral or keep
    // the color showing - SIGNAL_RETAIN_COLOR now applies to BOTH patterns.
    function applySignal(card, result) {
        clearSignal(card);
        var colorClass = signalColorClassFor(result);

        if (SIGNAL_PATTERN === 'solid') {
            card.classList.add(colorClass);
            card._signalTimer = setTimeout(function () {
                if (!SIGNAL_RETAIN_COLOR) {
                    card.classList.remove(colorClass);
                }
            }, SIGNAL_DURATION_MS);
        } else {
            card.classList.add('signal-blink', colorClass);
            card._signalTimer = setTimeout(function () {
                card.classList.remove('signal-blink');
                if (!SIGNAL_RETAIN_COLOR) {
                    card.classList.remove(colorClass);
                }
            }, SIGNAL_DURATION_MS);
        }
    }

    function updateCard(tableId, data) {
        var card = document.querySelector('.table-card[data-table-id="' + tableId + '"]');
        if (!card) return;

        var body = card.querySelector('.table-card__body');
        if (body) {
            body.innerHTML =
                '<span class="table-card__field"><span class="table-card__field-label">Activity Number:</span> ' + data.activity_number + '</span>' +
                '<span class="table-card__field table-card__field--result"><span class="table-card__field-label">RESULT:</span> <span class="badge badge--' + badgeClassFor(data.result) + '">' + data.result + '</span></span>' +
                '<span class="table-card__field"><span class="table-card__field-label">Order #:</span> ' + data.order_number + '</span>' +
                '<span class="table-card__field"><span class="table-card__field-label">Datetime:</span> ' + data.activity_datetime_display + '</span>';
        }

        // Rebuild the View Details link's target URL with the new activity/order
        // number, and make sure it's visible now that this card has real data.
        var viewBtn = card.querySelector('.table-card__view-btn');
        if (viewBtn) {
            var baseUrl = viewBtn.getAttribute('data-details-base-url');
            var params = new URLSearchParams({
                table_id: tableId,
                activity_number: data.activity_number,
                order_number: data.order_number
            });
            viewBtn.setAttribute('href', baseUrl + '?' + params.toString());
            viewBtn.style.visibility = 'visible';
        }

        applySignal(card, data.result);
        playAudioForSignal(tableId, data.result);
    }

    // Real-time push: the server only ever broadcasts genuinely new data
    // (duplicates filtered out server-side), so every event received here
    // is acted on immediately - no polling, no delay beyond the network.
    var socket = io();
    socket.on('table_update', function (data) {
        updateCard(data.table_id, data);
    });
})();
