// ============================================================
// app.js — Narrator Dashboard Client (v2)
// ============================================================

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const D = {
    // Header
    statusDot:   $('#status .dot'),
    statusLabel: $('#status .label'),
    // Editor
    editor:      $('#editor'),
    lines:       $('#lines'),
    stats:       $('#script-stats'),
    btnSave:     $('#btn-save'),
    // Voice
    selVoice:    $('#sel-voice'),
    rngSpeed:    $('#rng-speed'),
    speedVal:    $('#speed-val'),
    // Ref
    selRef:      $('#sel-ref'),
    btnPlayRef:  $('#btn-play-ref'),
    inpRefText:  $('#inp-ref-text'),
    uploadArea:  $('#upload-area'),
    inpUpload:   $('#inp-upload'),
    btnBrowse:   $('#btn-browse'),
    // Emotion
    selEmotion:  $('#sel-emotion'),
    inpEmotion:  $('#inp-emotion'),
    // Pipeline
    inpSilence:  $('#inp-silence'),
    chkNorm:     $('#chk-norm'),
    chkMp3:      $('#chk-mp3'),
    // Actions
    btnGen:      $('#btn-gen'),
    btnStop:     $('#btn-stop'),
    btnClear:    $('#btn-clear'),
    btnDlWav:    $('#btn-dl-wav'),
    btnDlMp3:    $('#btn-dl-mp3'),
    // Progress
    progBar:     $('#prog-bar'),
    progStatus:  $('#prog-status'),
    progDetail:  $('#prog-detail'),
    // Chunks
    chunkWrap:   $('#chunk-wrap'),
    chunkList:   $('#chunk-list'),
    chunkSum:    $('#chunk-summary'),
    // Player
    player:      $('#player'),
    btnPP:       $('#btn-pp'),
    plTitle:     $('#pl-title'),
    plDur:       $('#pl-dur'),
    plSeek:      $('#pl-seek'),
    plTime:      $('#pl-time'),
    // Audio
    audio:       $('#audio'),
    audioRef:    $('#audio-ref'),
};

let playingChunk = null;
let sse = null;

// ── Init ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    await loadVoices();
    await loadRefs();
    await loadScript();
    await loadChunks();
    setupEditor();
    setupEvents();
    connectSSE();
});

// ── API ─────────────────────────────────────────────────────

async function api(url, opts = {}) {
    try { const r = await fetch(url, opts); return await r.json(); }
    catch (e) { console.error('API:', e); return null; }
}
function post(url, data) {
    return api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
}
function del(url) {
    return api(url, { method: 'DELETE' });
}

// ── Config ──────────────────────────────────────────────────

async function loadConfig() {
    const c = await api('/api/config');
    if (!c) return;
    D.rngSpeed.value = c.speed;
    D.speedVal.textContent = c.speed + '×';
    D.inpEmotion.value = c.emotion || '';
    D.inpSilence.value = c.silence_padding;
    D.chkNorm.checked = c.normalize_audio;
    D.chkMp3.checked = c.export_mp3;
    D.inpRefText.value = c.ref_text || '';

    // Try to select matching emotion preset
    selectEmotionPreset(c.emotion);
}

function selectEmotionPreset(text) {
    if (!text) { D.selEmotion.value = ''; return; }
    const opts = D.selEmotion.options;
    for (let i = 0; i < opts.length; i++) {
        if (opts[i].value === text) { D.selEmotion.value = text; return; }
    }
    D.selEmotion.value = '';
}

async function loadVoices() {
    const data = await api('/api/voices');
    const cfg = await api('/api/config');
    if (!data) return;
    D.selVoice.innerHTML = '';
    data.voices.forEach(v => {
        const o = document.createElement('option');
        o.value = v;
        o.textContent = v.charAt(0).toUpperCase() + v.slice(1);
        if (cfg && v === cfg.voice) o.selected = true;
        D.selVoice.appendChild(o);
    });
}

async function loadRefs() {
    const data = await api('/api/refs');
    if (!data) return;
    D.selRef.innerHTML = '';
    data.refs.forEach(r => {
        const o = document.createElement('option');
        o.value = r.path;
        o.textContent = `${r.name}  (${r.duration})`;
        if (r.active) o.selected = true;
        D.selRef.appendChild(o);
    });
}

function saveConfig() {
    post('/api/config', {
        voice: D.selVoice.value,
        speed: parseFloat(D.rngSpeed.value),
        emotion: D.inpEmotion.value,
        ref_audio: D.selRef.value,
        ref_text: D.inpRefText.value,
        silence_padding: parseFloat(D.inpSilence.value),
        normalize_audio: D.chkNorm.checked,
        export_mp3: D.chkMp3.checked,
    });
}

// ── Script ──────────────────────────────────────────────────

async function loadScript() {
    const d = await api('/api/script');
    if (d) { D.editor.value = d.text || ''; updateLines(); updateStats(); }
}

async function saveScript() {
    const d = await post('/api/script', { text: D.editor.value });
    if (d && d.ok) { toast('Saved', 'ok'); updateStats(); }
}

// ── Editor ──────────────────────────────────────────────────

function setupEditor() {
    updateLines();
    D.editor.addEventListener('input', () => { updateLines(); updateStats(); });
    D.editor.addEventListener('scroll', () => { D.lines.scrollTop = D.editor.scrollTop; });
}

function updateLines() {
    const ls = D.editor.value.split('\n');
    let h = '';
    for (let i = 0; i < ls.length; i++)
        h += `<div style="opacity:${ls[i].trim() ? 1 : .3}">${i + 1}</div>`;
    D.lines.innerHTML = h;
}

function updateStats() {
    const ls = D.editor.value.split('\n').filter(l => l.trim());
    const wc = ls.reduce((a, l) => a + l.trim().split(/\s+/).length, 0);
    const est = Math.ceil(wc / 150); // ~150 words/min narration
    D.stats.textContent = `${ls.length} chunks · ${wc} words · ~${est} min`;
}

// ── Refs ────────────────────────────────────────────────────

function setupUpload() {
    D.btnBrowse.addEventListener('click', e => { e.preventDefault(); D.inpUpload.click(); });
    D.uploadArea.addEventListener('click', e => { if (e.target !== D.btnBrowse) D.inpUpload.click(); });
    D.uploadArea.addEventListener('dragover', e => { e.preventDefault(); D.uploadArea.classList.add('drag'); });
    D.uploadArea.addEventListener('dragleave', () => D.uploadArea.classList.remove('drag'));
    D.uploadArea.addEventListener('drop', e => {
        e.preventDefault(); D.uploadArea.classList.remove('drag');
        if (e.dataTransfer.files[0]) uploadRef(e.dataTransfer.files[0]);
    });
    D.inpUpload.addEventListener('change', () => { if (D.inpUpload.files[0]) uploadRef(D.inpUpload.files[0]); });
    D.btnPlayRef.addEventListener('click', () => {
        if (D.selRef.value) {
            const name = D.selRef.selectedOptions[0]?.textContent.split('  ')[0];
            D.audioRef.src = `/api/audio/ref/${name}`;
            D.audioRef.play();
        }
    });
}

async function uploadRef(file) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('ref_text', D.inpRefText.value);
    toast('Uploading…', 'ok');
    try {
        const r = await fetch('/api/refs/upload', { method: 'POST', body: fd });
        const d = await r.json();
        if (d.ok) { toast(`Uploaded: ${d.name}`, 'ok'); await loadRefs(); }
        else toast('Upload failed', 'err');
    } catch { toast('Upload failed', 'err'); }
}

// ── SSE ─────────────────────────────────────────────────────

function connectSSE() {
    if (sse) sse.close();
    sse = new EventSource('/api/generate/progress');
    sse.addEventListener('progress', e => handleProgress(JSON.parse(e.data)));
    sse.onopen = () => { D.statusDot.className = 'dot ok'; D.statusLabel.textContent = 'Ready'; };
    sse.onerror = () => {
        D.statusDot.className = 'dot err'; D.statusLabel.textContent = 'Disconnected';
        setTimeout(connectSSE, 3000);
    };
}

function handleProgress(d) {
    const { running, status, message, current_chunk, total_chunks, chunks_done } = d;

    // Status text
    D.progStatus.textContent = message || statusText(status);

    // Dot
    if (running) { D.statusDot.className = 'dot'; D.statusLabel.textContent = statusText(status); }
    else if (status === 'error') { D.statusDot.className = 'dot err'; D.statusLabel.textContent = 'Error'; }
    else { D.statusDot.className = 'dot ok'; D.statusLabel.textContent = 'Ready'; }

    // Progress bar
    if (total_chunks > 0) {
        const pct = Math.round((current_chunk / total_chunks) * 100);
        D.progBar.style.width = pct + '%';
        D.progDetail.textContent = `${current_chunk}/${total_chunks} chunks · ${pct}%`;
        D.progBar.classList.toggle('active', running);
    } else {
        D.progBar.style.width = '0%';
        D.progBar.classList.remove('active');
        D.progDetail.textContent = '';
    }

    // Buttons
    D.btnGen.classList.toggle('hidden', running);
    D.btnStop.classList.toggle('hidden', !running);

    // Chunk list
    if (chunks_done && chunks_done.length > 0) {
        renderChunks(chunks_done, total_chunks);
    }

    // Done
    if (status === 'done' && !running) { loadChunks(); }
}

function statusText(s) {
    return { idle: 'Ready', loading: 'Loading model…', generating: 'Generating…',
             stitching: 'Stitching audio…', done: 'Complete', error: 'Error',
             cancelled: 'Cancelled' }[s] || s;
}

// ── Chunks ──────────────────────────────────────────────────

async function loadChunks() {
    const d = await api('/api/chunks');
    if (!d) return;
    if (d.chunks.length > 0) {
        D.chunkWrap.classList.remove('hidden');
        D.chunkSum.textContent = `${d.chunks.length} chunks`;
        renderChunkFiles(d.chunks);
    }
    if (d.final.exists) {
        showPlayer(d.final.duration, d.final.mp3_exists);
    } else {
        D.btnDlWav.classList.add('hidden');
        D.btnDlMp3.classList.add('hidden');
    }
}

function renderChunks(chunks, total) {
    D.chunkWrap.classList.remove('hidden');
    D.chunkSum.textContent = `${chunks.length}/${total}`;
    D.chunkList.innerHTML = '';
    chunks.forEach((c, i) => {
        const row = document.createElement('div');
        row.className = `chunk-row ${c.error ? 'err' : ''}`;
        const icon = c.error ? '✗' : (c.skipped ? '⏭' : '✓');
        const dur = c.duration || '';
        const tm = c.time ? c.time : '';
        row.innerHTML = `
            <span class="chunk-idx">${i + 1}</span>
            <span class="chunk-icon" title="Play">${c.error ? '✗' : '▶'}</span>
            <span class="chunk-text">${c.file.replace('.wav', '')}</span>
            <span class="chunk-dur">${dur}</span>
            <span class="chunk-time">${tm}</span>
            <button class="chunk-del" title="Delete">✕</button>
        `;
        if (!c.error) {
            row.querySelector('.chunk-icon').onclick = () => playChunk(c.file, row);
        }
        row.querySelector('.chunk-del').onclick = (e) => { e.stopPropagation(); deleteChunk(c.file); };
        D.chunkList.appendChild(row);
    });
}

function renderChunkFiles(chunks) {
    D.chunkList.innerHTML = '';
    chunks.forEach((c, i) => {
        const row = document.createElement('div');
        row.className = 'chunk-row';
        row.innerHTML = `
            <span class="chunk-idx">${i + 1}</span>
            <span class="chunk-icon" title="Play">▶</span>
            <span class="chunk-text">${c.name.replace('.wav', '')}</span>
            <span class="chunk-dur">${c.duration}</span>
            <span class="chunk-time"></span>
            <button class="chunk-del" title="Delete">✕</button>
        `;
        row.querySelector('.chunk-icon').onclick = () => playChunk(c.name, row);
        row.querySelector('.chunk-del').onclick = (e) => { e.stopPropagation(); deleteChunk(c.name); };
        D.chunkList.appendChild(row);
    });
}

function playChunk(file, row) {
    $$('.chunk-row.playing').forEach(r => r.classList.remove('playing'));
    D.audio.src = `/api/audio/chunk/${file}`;
    D.audio.play();
    if (row) row.classList.add('playing');
    playingChunk = file;
    D.player.classList.remove('hidden');
    D.plTitle.textContent = file.replace('.wav', '');
    D.btnPP.textContent = '⏸';
    D.audio.onended = () => {
        if (row) row.classList.remove('playing');
        playingChunk = null;
        D.btnPP.textContent = '▶';
    };
}

async function deleteChunk(file) {
    const d = await del(`/api/chunks/${file}`);
    if (d && d.ok) {
        toast('Deleted ' + file, 'ok');
        await loadChunks();
    } else {
        toast('Delete failed', 'err');
    }
}

// ── Player ──────────────────────────────────────────────────

function showPlayer(dur, hasMp3) {
    D.player.classList.remove('hidden');
    D.plDur.textContent = dur || '';
    D.plTitle.textContent = 'Final Output';
    D.btnDlWav.classList.remove('hidden');
    D.btnDlMp3.classList.toggle('hidden', !hasMp3);
}

function setupPlayer() {
    D.btnPP.addEventListener('click', () => {
        if (!D.audio.src || !playingChunk) {
            D.audio.src = '/api/audio/final';
            D.plTitle.textContent = 'Final Output';
        }
        if (D.audio.paused) { D.audio.play(); D.btnPP.textContent = '⏸'; }
        else { D.audio.pause(); D.btnPP.textContent = '▶'; }
    });
    D.audio.addEventListener('timeupdate', () => {
        if (!D.audio.duration) return;
        D.plSeek.value = (D.audio.currentTime / D.audio.duration) * 100;
        D.plTime.textContent = `${fmt(D.audio.currentTime)} / ${fmt(D.audio.duration)}`;
    });
    D.audio.addEventListener('ended', () => {
        D.btnPP.textContent = '▶'; playingChunk = null;
        $$('.chunk-row.playing').forEach(r => r.classList.remove('playing'));
    });
    D.audio.addEventListener('play', () => { D.btnPP.textContent = '⏸'; D.player.classList.remove('hidden'); });
    D.plSeek.addEventListener('input', () => {
        if (D.audio.duration) D.audio.currentTime = (D.plSeek.value / 100) * D.audio.duration;
    });
}

function fmt(s) { return Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0'); }

// ── Generate ────────────────────────────────────────────────

async function startGen() {
    await saveScript();
    saveConfig();
    const d = await post('/api/generate', { mode: 'batch' });
    if (d && !d.ok) toast(d.error || 'Failed', 'err');
}

async function stopGen() {
    await post('/api/generate/stop', {});
    toast('Cancelling…', 'err');
}

async function clearAll() {
    if (!confirm('Delete ALL generated chunks and outputs?')) return;
    const d = await post('/api/clear', {});
    if (d && d.ok) {
        D.chunkWrap.classList.add('hidden');
        D.chunkList.innerHTML = '';
        D.player.classList.add('hidden');
        D.btnDlWav.classList.add('hidden');
        D.btnDlMp3.classList.add('hidden');
        D.progBar.style.width = '0%';
        D.progDetail.textContent = '';
        D.progStatus.textContent = 'Ready';
        toast('All cleared', 'ok');
    }
}

// ── Toast ───────────────────────────────────────────────────

function toast(msg, type = '') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// ── Events ──────────────────────────────────────────────────

function setupEvents() {
    // Save
    D.btnSave.addEventListener('click', saveScript);
    document.addEventListener('keydown', e => {
        if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); saveScript(); }
    });

    // Config auto-save
    D.selVoice.addEventListener('change', saveConfig);
    D.rngSpeed.addEventListener('input', () => { D.speedVal.textContent = D.rngSpeed.value + '×'; saveConfig(); });
    D.inpSilence.addEventListener('change', saveConfig);
    D.chkNorm.addEventListener('change', saveConfig);
    D.chkMp3.addEventListener('change', saveConfig);
    D.inpRefText.addEventListener('change', saveConfig);

    // Ref voice select → activate
    D.selRef.addEventListener('change', () => {
        post('/api/refs/activate', { path: D.selRef.value, ref_text: D.inpRefText.value });
    });

    // Emotion preset → fill textarea
    D.selEmotion.addEventListener('change', () => {
        const v = D.selEmotion.value;
        if (v) D.inpEmotion.value = v;
        saveConfig();
    });
    D.inpEmotion.addEventListener('change', saveConfig);

    // Generate
    D.btnGen.addEventListener('click', startGen);
    D.btnStop.addEventListener('click', stopGen);
    D.btnClear.addEventListener('click', clearAll);

    // Downloads
    D.btnDlWav.addEventListener('click', () => window.open('/api/download/wav', '_blank'));
    D.btnDlMp3.addEventListener('click', () => window.open('/api/download/mp3', '_blank'));

    // Player
    setupPlayer();

    // Upload
    setupUpload();
}
