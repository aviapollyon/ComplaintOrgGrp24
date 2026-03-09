/**
 * Validates all <input type="file"> elements on the page.
 * Shows an inline warning if:
 *   - More than MAX_FILES files are selected
 *   - Any single file exceeds MAX_MB megabytes
 *
 * Blocks form submission if validation fails.
 */
const MAX_FILES = 5;
const MAX_BYTES = 5 * 1024 * 1024; // 5 MB

function validateFileInput(input) {
    const warningId = 'fileWarn_' + input.id;
    let warning = document.getElementById(warningId);

    // Create warning element if it doesn't exist yet
    if (!warning) {
        warning = document.createElement('div');
        warning.id = warningId;
        warning.className = 'alert alert-warning py-1 px-2 mt-1 small d-none';
        input.closest('div,label')?.insertAdjacentElement('afterend', warning) ||
            input.insertAdjacentElement('afterend', warning);
    }

    const files = Array.from(input.files);
    const oversized = files.filter(f => f.size > MAX_BYTES);
    const messages = [];

    if (files.length > MAX_FILES) {
        messages.push(`⚠️ Max ${MAX_FILES} files allowed (${files.length} selected).`);
    }
    if (oversized.length > 0) {
        messages.push(`⚠️ These files exceed 5 MB: ${oversized.map(f => f.name).join(', ')}`);
    }

    if (messages.length) {
        warning.innerHTML = messages.join('<br>');
        warning.classList.remove('d-none');
        input.setCustomValidity('invalid');
    } else {
        warning.classList.add('d-none');
        warning.innerHTML = '';
        input.setCustomValidity('');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[type="file"]').forEach(input => {
        // Give each file input a stable id if it doesn't have one
        if (!input.id) input.id = 'fileInput_' + Math.random().toString(36).slice(2);

        input.addEventListener('change', () => {
            validateFileInput(input);

            // Update the filename label if present
            const labelId = input.id.replace('fileInput_', 'fileLabel_');
            const label   = document.getElementById(labelId);
            if (label) {
                label.textContent = input.files.length
                    ? Array.from(input.files).map(f => f.name).join(', ')
                    : 'No file chosen';
            }
        });
    });

    // Block submission if any file input is invalid
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', e => {
            let blocked = false;
            form.querySelectorAll('input[type="file"]').forEach(input => {
                validateFileInput(input);
                if (input.validity.customError) blocked = true;
            });
            if (blocked) e.preventDefault();
        });
    });
});

// ── Character counter for fields with data-minlen attribute ──────────────────
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-minlen]').forEach(function (el) {
            const minLen = parseInt(el.dataset.minlen, 10) || 0;
            const maxLen = parseInt(el.dataset.maxlen, 10) || 0;
            const counter = document.createElement('div');
            counter.className = 'form-text char-counter';
            el.insertAdjacentElement('afterend', counter);
            function update() {
                const len = el.value.length;
                const ok  = len >= minLen;
                counter.textContent = len + '\u202f/\u202fmin\u00a0' + minLen
                    + (maxLen ? '\u202f(max\u00a0' + maxLen + ')' : '')
                    + '\u00a0characters';
                counter.className = 'form-text char-counter ' + (ok ? 'text-success' : 'text-danger');
            }
            el.addEventListener('input', update);
            update();
        });
    });
}());