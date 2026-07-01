// ============================================================
// app.js — Narrator Dashboard Client
// ============================================================

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── DOM refs ────────────────────────────────────────────────

const DOM = {
    // Header
    modelStatus:    $('#model-status'),
    statusDot:      $('#model-status .status-dot'),
    statusText:     $('#model-status .status-text'),

    // Editor
    editor:         $('#script-editor'),
    lineNumbers:    $('#line-numbers'),
    chunkCount:     $('#chunk-count'),
    btnSave:        $('#btn-save-script'),

    // Voice
    voiceSelect:    $('#voice-select'),
    speedSlider:    $('#speed-slider'),
    speedValue:     $('#speed-value'),
    emotionInput:   $('#emotion-input'),

    // Pipeline
    silenceInput:   $('#silence-input'),
    toggleNorm:     $('#toggle-normalize'),
    toggleMp3:      $('#toggle-mp3'),

    // Ref
    refCurrent:     $('#ref-current .ref-name'),
    refTextInput:   $('#ref-text-input'),
    btnPlayRef:     $('#btn-play-ref'),
    uploadZone:     $('#upload-zone'),
    refUpload:      $('#ref-upload'),
    btnBrowse:      $('#btn-browse'),

    // Generate
    btnGenerate:    $('#btn-generate'),
    btnStop:        $('#btn-stop'),
    btnClear:       $('#btn-clear'),

    // Progress
    progressBar:    $('#progress-bar'),
    progressStatus: $('#progress-status'),
    progressDetail: $('#progress-detail'),

    // Chunks
    chunksSection:  $('#chunks-section'),
    chunksList:     $('#chunks-list'),
    chunksTotal:    $('#chunks-total'),

    // Player
    playerSection:  $('#player-section'),
    playerTitle:    $('#player-title'),
    playerDuration: $('#player-duration'),
    btnPlayPause:   $('#btn-play-pause'),
    playerTimeline: $('#player-timeline'),
    playerTime:     $('#player-time'),
    btnDownloadWav: $('#btn-download-wav'),
    btnDownloadMp3: $('#btn-download-mp3'),

    // Audio elements
    audioPlayer:    $('#audio-player'),
    audioRef:       $('#audio-ref'),
};


// ── State ───────────────────────────────────────────────────

let currentlyPlayingChunk = null;
let sseSource = null;


// ── Init ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    await loadVoices();
    await loadScript();
    await loadRefs();
    await loadChunks();
    connectSSE();
    setupEditorLineNumbers();
    setupEventListeners();
});


// ── API helpers ─────────────────────────────────────────────

async function api(url, opts = {}) {
    try {
        const res = await fetch(url, opts);
        return await res.json();
    } catch (e) {
        console.error('API error:', e);
        return null;
    }
}

async function apiPost(url, data) {
    return api(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
}


// ── Load config ─────────────────────────────────────────────

async function loadConfig() {
    const cfg = await api('/api/config');
    if (!cfg) return;

    DOM.speedSlider.value = cfg.speed;
    DOM.speedValue.textContent = cfg.speed;
    DOM.emotionInput.value = cfg.emotion || '';
    DOM.silenceInput.value = cfg.silence_padding;
    DOM.toggleNorm.checked = cfg.normalize_audio;
    DOM.toggleMp3.checked = cfg.export_mp3;
    DOM.refTextInput.value = cfg.ref_text || '';
}

async function loadVoices() {
    const data = await api('/api/voices');
    if (!data) return;

    const cfg = await api('/api/config');
    DOM.voiceSelect.innerHTML = '';

    data.voices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v.charAt(0).toUpperCase() + v.slice(1);
        if (cfg && v === cfg.voice) opt.selected = true;
        DOM.voiceSelect.appendChild(opt);
    });
}


// ── Load script ─────────────────────────────────────────────

async function loadScript() {
    const data = await api('/api/script');
    if (data) {
        DOM.editor.value = data.text || '';
        updateLineNumbers();
        updateChunkCount();
    }
}

async function saveScript() {
    const text = DOM.editor.value;
    const data = await apiPost('/api/script', { text });
    if (data && data.ok) {
        toast('Script saved', 'success');
        updateChunkCount();
    }
}


// ── Load refs ───────────────────────────────────────────────

async function loadRefs() {
    const data = await api('/api/refs');
    if (data) {
        const active = data.refs.find(r => r.active);
        DOM.refCurrent.textContent = active ? active.name : data.current;
    }
}


// ── Load chunks ─────────────────────────────────────────────

async function loadChunks() {
    const data = await api('/api/chunks');
    if (!data) return;

    if (data.chunks.length > 0) {
        DOM.chunksSection.classList.remove('hidden');
        DOM.chunksTotal.textContent = `${data.chunks.length} chunks`;
        renderChunkPills(data.chunks);
    }

    if (data.final.exists) {
        showPlayer(data.final.duration, data.final.mp3_exists);
    }
}

function renderChunkPills(chunks) {
    DOM.chunksList.innerHTML = '';
    chunks.forEach((c, i) => {
        const pill = document.createElement('button');
        pill.className = 'chunk-pill done';
        pill.innerHTML = `<span class="pill-icon">▶</span> ${c.name.replace('.wav', '')} <span style="opacity:0.5">${c.duration}</span>`;
        pill.onclick = () => playChunk(c.name, pill);
        DOM.chunksList.appendChild(pill);
    });
}

function playChunk(filename, pillEl) {
    // Remove playing state from all pills
    $$('.chunk-pill.playing').forEach(p => p.classList.remove('playing'));

    const audio = DOM.audioPlayer;
    audio.src = `/api/audio/chunk/${filename}`;
    audio.play();

    if (pillEl) pillEl.classList.add('playing');
    currentlyPlayingChunk = filename;

    audio.onended = () => {
        if (pillEl) pillEl.classList.remove('playing');
        currentlyPlayingChunk = null;
    };
}


// ── Editor ──────────────────────────────────────────────────

function setupEditorLineNumbers() {
    updateLineNumbers();
    DOM.editor.addEventListener('input', () => {
        updateLineNumbers();
        updateChunkCount();
    });
    DOM.editor.addEventListener('scroll', () => {
        DOM.lineNumbers.scrollTop = DOM.editor.scrollTop;
    });
}

function updateLineNumbers() {
    const lines = DOM.editor.value.split('\n');
    let html = '';
    for (let i = 0; i < lines.length; i++) {
        const isBlank = !lines[i].trim();
        html += `<div style="opacity:${isBlank ? 0.3 : 1}">${i + 1}</div>`;
    }
    DOM.lineNumbers.innerHTML = html;
}

function updateChunkCount() {
    const lines = DOM.editor.value.split('\n').filter(l => l.trim());
    DOM.chunkCount.textContent = `${lines.length} chunk${lines.length !== 1 ? 's' : ''}`;
}


// ── Save config on change ───────────────────────────────────

function saveConfig() {
    apiPost('/api/config', {
        voice: DOM.voiceSelect.value,
        speed: parseFloat(DOM.speedSlider.value),
        emotion: DOM.emotionInput.value,
        silence_padding: parseFloat(DOM.silenceInput.value),
        normalize_audio: DOM.toggleNorm.checked,
        export_mp3: DOM.toggleMp3.checked,
        ref_text: DOM.refTextInput.value,
    });
}


// ── SSE (real-time progress) ────────────────────────────────

function connectSSE() {
    if (sseSource) sseSource.close();

    sseSource = new EventSource('/api/generate/progress');

    sseSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        handleProgress(data);
    });

    sseSource.onerror = () => {
        DOM.statusDot.className = 'status-dot error';
        DOM.statusText.textContent = 'Disconnected';
        setTimeout(connectSSE, 3000);
    };

    sseSource.onopen = () => {
        DOM.statusDot.className = 'status-dot ready';
        DOM.statusText.textContent = 'Connected';
    };
}

function handleProgress(data) {
    const { running, status, message, current_chunk, total_chunks, chunks_done } = data;

    // Status text
    DOM.progressStatus.textContent = message || statusLabel(status);

    // Status dot
    if (status === 'loading') {
        DOM.statusDot.className = 'status-dot';
        DOM.statusText.textContent = 'Loading model...';
    } else if (running) {
        DOM.statusDot.className = 'status-dot';
        DOM.statusText.textContent = 'Generating...';
    } else if (status === 'done') {
        DOM.statusDot.className = 'status-dot ready';
        DOM.statusText.textContent = 'Ready';
    } else if (status === 'error') {
        DOM.statusDot.className = 'status-dot error';
        DOM.statusText.textContent = 'Error';
    } else {
        DOM.statusDot.className = 'status-dot ready';
        DOM.statusText.textContent = 'Ready';
    }

    // Progress bar
    if (total_chunks > 0) {
        const pct = Math.round((current_chunk / total_chunks) * 100);
        DOM.progressBar.style.width = `${pct}%`;
        DOM.progressDetail.textContent = `${current_chunk} / ${total_chunks}`;

        if (running) {
            DOM.progressBar.classList.add('active');
        } else {
            DOM.progressBar.classList.remove('active');
        }
    } else {
        DOM.progressBar.style.width = '0%';
        DOM.progressBar.classList.remove('active');
        DOM.progressDetail.textContent = '';
    }

    // Buttons
    if (running) {
        DOM.btnGenerate.classList.add('hidden');
        DOM.btnStop.classList.remove('hidden');
    } else {
        DOM.btnGenerate.classList.remove('hidden');
        DOM.btnStop.classList.add('hidden');
    }

    // Chunks done
    if (chunks_done && chunks_done.length > 0) {
        DOM.chunksSection.classList.remove('hidden');
        DOM.chunksTotal.textContent = `${chunks_done.length} / ${total_chunks}`;

        DOM.chunksList.innerHTML = '';
        chunks_done.forEach(c => {
            const pill = document.createElement('button');
            pill.className = `chunk-pill ${c.error ? 'error' : 'done'}`;
            const icon = c.error ? '✗' : (c.skipped ? '⏭' : '✓');
            const dur = c.duration || '';
            const timeStr = c.time ? ` · ${c.time}` : '';
            pill.innerHTML = `<span class="pill-icon">${icon}</span> ${c.file.replace('.wav', '')} <span style="opacity:0.5">${dur}${timeStr}</span>`;
            if (!c.error) {
                pill.onclick = () => playChunk(c.file, pill);
            }
            DOM.chunksList.appendChild(pill);
        });
    }

    // Done — show player
    if (status === 'done' && !running) {
        loadChunks();
    }
}

function statusLabel(status) {
    const labels = {
        idle: 'Ready',
        loading: 'Loading model...',
        generating: 'Generating...',
        stitching: 'Stitching audio...',
        done: 'Complete!',
        error: 'Error',
        cancelled: 'Cancelled',
    };
    return labels[status] || status;
}


// ── Generate ────────────────────────────────────────────────

async function startGeneration() {
    // Auto-save script first
    await saveScript();

    // Save current settings
    saveConfig();

    const data = await apiPost('/api/generate', { mode: 'batch' });
    if (data && !data.ok) {
        toast(data.error || 'Failed to start', 'error');
    }
}

async function stopGeneration() {
    await apiPost('/api/generate/stop', {});
    toast('Cancelling...', 'error');
}

async function clearOutputs() {
    if (!confirm('Delete all generated chunks and outputs?')) return;
    const data = await apiPost('/api/clear', {});
    if (data && data.ok) {
        DOM.chunksSection.classList.add('hidden');
        DOM.playerSection.classList.add('hidden');
        DOM.progressBar.style.width = '0%';
        DOM.progressDetail.textContent = '';
        DOM.progressStatus.textContent = 'Ready';
        toast('Outputs cleared', 'success');
    }
}


// ── Audio Player ────────────────────────────────────────────

function showPlayer(duration, hasMp3) {
    DOM.playerSection.classList.remove('hidden');
    DOM.playerDuration.textContent = duration || '';
    DOM.playerTitle.textContent = 'Final Output';

    if (!hasMp3) {
        DOM.btnDownloadMp3.classList.add('hidden');
    } else {
        DOM.btnDownloadMp3.classList.remove('hidden');
    }
}

function setupPlayerControls() {
    const audio = DOM.audioPlayer;

    DOM.btnPlayPause.addEventListener('click', () => {
        // Load final output if not already playing a chunk
        if (!audio.src || !currentlyPlayingChunk) {
            audio.src = '/api/audio/final';
            DOM.playerTitle.textContent = 'Final Output';
        }

        if (audio.paused) {
            audio.play();
            DOM.btnPlayPause.textContent = '⏸';
        } else {
            audio.pause();
            DOM.btnPlayPause.textContent = '▶';
        }
    });

    audio.addEventListener('timeupdate', () => {
        if (!audio.duration) return;
        const pct = (audio.currentTime / audio.duration) * 100;
        DOM.playerTimeline.value = pct;
        DOM.playerTime.textContent = `${fmtTime(audio.currentTime)} / ${fmtTime(audio.duration)}`;
    });

    audio.addEventListener('ended', () => {
        DOM.btnPlayPause.textContent = '▶';
        currentlyPlayingChunk = null;
        $$('.chunk-pill.playing').forEach(p => p.classList.remove('playing'));
    });

    audio.addEventListener('play', () => {
        DOM.btnPlayPause.textContent = '⏸';
        DOM.playerSection.classList.remove('hidden');
    });

    DOM.playerTimeline.addEventListener('input', () => {
        if (audio.duration) {
            audio.currentTime = (DOM.playerTimeline.value / 100) * audio.duration;
        }
    });
}

function fmtTime(secs) {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}


// ── Upload reference voice ──────────────────────────────────

function setupUpload() {
    DOM.btnBrowse.addEventListener('click', (e) => {
        e.preventDefault();
        DOM.refUpload.click();
    });

    DOM.uploadZone.addEventListener('click', (e) => {
        if (e.target !== DOM.btnBrowse) {
            DOM.refUpload.click();
        }
    });

    DOM.uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        DOM.uploadZone.classList.add('dragover');
    });

    DOM.uploadZone.addEventListener('dragleave', () => {
        DOM.uploadZone.classList.remove('dragover');
    });

    DOM.uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        DOM.uploadZone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) uploadRefFile(file);
    });

    DOM.refUpload.addEventListener('change', () => {
        const file = DOM.refUpload.files[0];
        if (file) uploadRefFile(file);
    });

    DOM.btnPlayRef.addEventListener('click', () => {
        const refName = DOM.refCurrent.textContent;
        if (refName && refName !== '—') {
            DOM.audioRef.src = `/api/audio/ref/${refName}`;
            DOM.audioRef.play();
        }
    });
}

async function uploadRefFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('ref_text', DOM.refTextInput.value);

    toast('Uploading reference voice...', 'success');

    try {
        const res = await fetch('/api/refs/upload', {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (data.ok) {
            DOM.refCurrent.textContent = data.name;
            toast(`Reference voice uploaded: ${data.name}`, 'success');
        } else {
            toast('Upload failed', 'error');
        }
    } catch (e) {
        toast('Upload failed', 'error');
    }
}


// ── Toast notifications ─────────────────────────────────────

function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
}


// ── Event listeners ─────────────────────────────────────────

function setupEventListeners() {
    // Save script
    DOM.btnSave.addEventListener('click', saveScript);

    // Ctrl+S to save
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 's') {
            e.preventDefault();
            saveScript();
        }
    });

    // Config changes
    DOM.voiceSelect.addEventListener('change', saveConfig);
    DOM.speedSlider.addEventListener('input', () => {
        DOM.speedValue.textContent = DOM.speedSlider.value;
        saveConfig();
    });
    DOM.emotionInput.addEventListener('change', saveConfig);
    DOM.silenceInput.addEventListener('change', saveConfig);
    DOM.toggleNorm.addEventListener('change', saveConfig);
    DOM.toggleMp3.addEventListener('change', saveConfig);
    DOM.refTextInput.addEventListener('change', saveConfig);

    // Generate
    DOM.btnGenerate.addEventListener('click', startGeneration);
    DOM.btnStop.addEventListener('click', stopGeneration);
    DOM.btnClear.addEventListener('click', clearOutputs);

    // Downloads
    DOM.btnDownloadWav.addEventListener('click', () => {
        window.open('/api/download/wav', '_blank');
    });
    DOM.btnDownloadMp3.addEventListener('click', () => {
        window.open('/api/download/mp3', '_blank');
    });

    // Player
    setupPlayerControls();

    // Upload
    setupUpload();
}
