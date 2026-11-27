let previewZip;
const previewFile = document.getElementById('preview-file');
const previewText = document.getElementById('preview-text');
const picker = document.getElementById('picker');

const languageNote = document.createElement('p');
languageNote.className = 'caption';
languageNote.textContent = 'Cleaned files keep the original language, including notes that mix Hindi and English.';
previewText.after(languageNote);

function clearPreview() {
    resetReview();
    previewZip = null;
    previewFile.replaceChildren();
    previewText.textContent = '';
    picker.hidden = true;
}

function showSelectedFile() {
    selectReviewFile();
    const name = previewFile.value;
    try {
        const entries = fflate.unzipSync(previewZip, {filter: entry => entry.name === name});
        const bytes = entries[name];
        const limit = 128 * 1024;
        previewText.textContent = new TextDecoder().decode(bytes.subarray(0, limit))
            + (bytes.length > limit ? '\n\nPreview ends here. Download the ZIP for the complete file.' : '');
        if (!bytes.length) previewText.textContent = 'This cleaned file is empty.';
    } catch {
        previewText.textContent = 'Preview unavailable. Download the ZIP to see the complete output.';
    }
}

async function previewRelease(blob) {
    clearPreview();
    try {
        previewZip = new Uint8Array(await blob.arrayBuffer());
        fflate.unzipSync(previewZip, {filter: entry => {
            if (entry.name.startsWith('sanitized/') && !entry.name.endsWith('/')) {
                previewFile.add(new Option(entry.name.slice(10), entry.name));
            }
            return false;
        }});
        picker.hidden = !previewFile.length;
        if (previewFile.length) {
            showSelectedFile();
            await prepareReview(previewZip, document.getElementById("files").files);
        }
        else previewText.textContent = 'No cleaned files to display. The ZIP includes the processing report.';
    } catch {
        previewText.textContent = 'Preview unavailable. You can still download the ZIP.';
    }
}
previewFile.addEventListener('change', showSelectedFile);
