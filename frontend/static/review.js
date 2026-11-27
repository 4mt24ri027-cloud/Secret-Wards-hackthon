/* Read the uploaded tables in this browser. Original cells never enter the release ZIP. */
function parseTable(text, delimiter) {
    const rows = [];
    let row = [], cell = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (ch === '"') {
            if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
            else if (quoted || cell === '') quoted = !quoted;
            else cell += ch;
        } else if (!quoted && ch === delimiter) {
            row.push(cell); cell = '';
        } else if (!quoted && (ch === '\r' || ch === '\n')) {
            if (ch === '\r' && text[i + 1] === '\n') i++;
            row.push(cell); rows.push(row); row = []; cell = '';
        } else cell += ch;
    }
    if (row.length || cell.length || text.endsWith('"')) { row.push(cell); rows.push(row); }
    return rows;
}

function readOriginal(bytes) {
    if (bytes[0] === 255 && bytes[1] === 254) return new TextDecoder('utf-16le').decode(bytes);
    if (bytes[0] === 254 && bytes[1] === 255) return new TextDecoder('utf-16be').decode(bytes);
    try { return new TextDecoder('utf-8', {fatal:true}).decode(bytes); }
    catch { return new TextDecoder('windows-1252').decode(bytes); }
}

function visitDay(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((value || '').trim());
    if (!m) return null;
    const date = new Date(Date.UTC(+m[1], +m[2]-1, +m[3]));
    return date.toISOString().slice(0,10) === m[0] ? date.getTime()/86400000 : null;
}

const review = document.getElementById('review');
const rowSelect = document.getElementById('review-row');
const changesOnly = document.getElementById('only-changes');
const reveal = document.getElementById('reveal');
let reviewTables = new Map(), patientVisits = new Map(), generation = 0;

function resetReview() {
    generation++;
    reviewTables.clear(); patientVisits.clear();
    review.hidden = true; review.open = false; reveal.checked = false;
    document.getElementById('review-body').replaceChildren();
    rowSelect.replaceChildren();
}

async function prepareReview(zip, uploads) {
    resetReview();
    const current = generation;
    const entries = fflate.unzipSync(zip, {filter: e => e.name === 'records.jsonl' ||
        (e.name.startsWith('sanitized/') && /\.(csv|tsv)$/i.test(e.name))});
    const index = new Map();
    for (const line of new TextDecoder().decode(entries['records.jsonl']).split(/\r?\n/)) {
        if (!line.trim()) continue;
        const r = JSON.parse(line);
        index.set(r.file + '|' + r.loc, r.patient);
    }
    for (const [path, cleaned] of Object.entries(entries)) {
        const match = /^sanitized\/batch_(\d+)\/.*\.(csv|tsv)$/i.exec(path);
        if (!match) continue;
        const original = uploads[Number(match[1])-1];
        if (!original) continue;
        const delimiter = match[2].toLowerCase() === 'tsv' ? '\t' : ',';
        const before = parseTable(readOriginal(new Uint8Array(await original.arrayBuffer())), delimiter);
        if (current !== generation) return;
        const after = parseTable(new TextDecoder().decode(cleaned), delimiter);
        if (before.length !== after.length || after.length < 2) continue;
        const table = {before, after, path, visits:[]};
        reviewTables.set(path, table);
        const dateCol = before[0].findIndex(h => /^(visit|encounter)[ _-]?date$/i.test(h.trim()));
        for (let i = 1; i < after.length; i++) {
            const pid = index.get(path + '|row:' + (i-1));
            if (!pid || !after[i].includes(pid)) continue;
            const visit = {pid, original:visitDay(before[i][dateCol]), cleaned:visitDay(after[i][dateCol])};
            table.visits[i] = visit;
            if (!patientVisits.has(pid)) patientVisits.set(pid, []);
            patientVisits.get(pid).push(visit);
        }
    }
    selectReviewFile();
}

function selectReviewFile() {
    const table = reviewTables.get(previewFile.value);
    reveal.checked = false; review.open = false; review.hidden = !table;
    rowSelect.replaceChildren();
    if (!table) return;
    for (let i=1; i<table.after.length; i++) rowSelect.add(new Option('Row '+i, i));
    drawReview();
}

function drawReview() {
    const table = reviewTables.get(previewFile.value);
    if (!table) return;
    const i = Number(rowSelect.value);
    const body = document.getElementById('review-body');
    body.replaceChildren();
    for (let col=0; col<table.after[0].length; col++) {
        const oldValue = table.before[i][col], newValue = table.after[i][col];
        const changed = oldValue !== newValue || table.before[0][col] !== table.after[0][col];
        if (changesOnly.checked && !changed) continue;
        const tr = body.insertRow();
        if (changed) tr.className = 'changed';
        for (const value of [table.after[0][col], reveal.checked ? oldValue ?? '—' : 'Hidden', newValue ?? '—'])
            tr.insertCell().textContent = value;
    }
    if (!body.rows.length) body.insertRow().insertCell().textContent = 'No changed fields in this row.';
    const evidence = document.getElementById('visit-check');
    const visit = table.visits[i], group = visit && patientVisits.get(visit.pid);
    evidence.textContent = '';
    if (group && group.length > 1) {
        evidence.textContent = group.length+' records share patient code '+visit.pid+'.';
        const other = group.find(v => v !== visit && v.original !== null && v.cleaned !== null);
        if (other && visit.original !== null && visit.cleaned !== null) {
            const before = visit.original-other.original, after = visit.cleaned-other.cleaned;
            evidence.textContent += ' Compared with another linked visit: '+Math.abs(before)+' days before cleaning, '+
                Math.abs(after)+' days after. '+(before === after ? 'Interval preserved.' : 'Timeline changed.');
        } else {
            evidence.textContent += ' Exact visit gap unavailable: both visits need complete YYYY-MM-DD dates before and after cleaning.';
        }
    }
}
for (const control of [rowSelect,changesOnly,reveal]) control.addEventListener('change',drawReview);
review.addEventListener('toggle',()=>{if (!review.open && reveal.checked) {reveal.checked=false;drawReview();}});
