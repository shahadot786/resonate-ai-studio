// ============================================================
// app.js — Narrator Dashboard Logic (v3 Premium Edition)
// ============================================================

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ── DOM ELEMENTS MAP ──
const DOM = {
    // Header & Status
    statusDot:        $('#system-status .status-dot'),
    statusLabel:      $('#system-status .status-lbl'),

    // Workspace & Editor
    editor:           $('#script-textarea'),
    gutter:           $('#gutter'),
    chunkCounter:     $('#chunk-counter'),
    wordCounter:      $('#word-counter'),
    btnSaveScript:    $('#btn-save-script'),
    tagButtons:       $$('.tag-insert'),

    // Voice Preset
    selectVoice:      $('#select-voice'),
    sliderSpeed:      $('#slider-speed'),
    lblSpeed:         $('#lbl-speed'),

    // Reference Voice Profile
    selectRef:        $('#select-ref'),
    btnRefPlay:       $('#btn-ref-play'),
    txtRefTranscript: $('#txt-ref-transcript'),
    dropZone:         $('#drop-zone'),
    inputFileUpload:  $('#input-file-upload'),
    btnBrowseTrigger: $('#btn-browse-trigger'),

    // Emotion Custom Presets
    selectEmotion:    $('#select-emotion-preset'),
    txtEmotion:       $('#txt-emotion-instructions'),

    // Audio Engineering Pipeline Toggles
    numSilence:       $('#num-silence-padding'),
    checkNormalize:   $('#check-normalize'),
    checkExportMp3:   $('#check-export-mp3'),

    // Action Panel Buttons
    btnActionGenerate: $('#btn-action-generate'),
    btnActionStop:     $('#btn-action-stop'),
    btnActionClear:    $('#btn-action-clear'),
    btnDownloadWav:    $('#btn-download-wav'),
    btnDownloadMp3:    $('#btn-download-mp3'),

    // Generation Progress Status
    statusOverlay:    $('#status-overlay'),
    progressBarFill:  $('#progress-bar-fill'),
    statusMsg:        $('#status-msg'),
    statusStats:      $('#status-stats'),

    // Segment List Display
    chunkSuite:       $('#chunk-suite'),
    chunkRowsContainer: $('#chunk-rows-container'),
    chunkStatsSummary: $('#chunk-stats-summary'),

    // Integrated Playback Bar
    audioPlaybackPlayer: $('#audio-playback-player'),
    btnPlaybackToggle:   $('#btn-playback-toggle'),
    playbackTitle:       $('#playback-title'),
    playbackDuration:    $('#playback-duration'),
    playbackRangeInput:  $('#playback-range-input'),
    playbackTime:        $('#playback-time'),

    // Audio Output Nodes
    audioMainNode:    $('#audio-main-node'),
    audioRefNode:     $('#audio-ref-node'),
};

let activePlayingChunk = null;
let sseSource = null;

// Default reference transcripts map
const REF_TRANSCRIPTS = {
    "ref_voice_male.wav": "The day Paul Reston shook my hand and called me the most talented analyst he'd ever worked with, I believed him.",
    "ref_voice_female.wav": "I came to Hargrove & Associates three years out of Northwestern with a finance degree, a minor in statistics, and the kind of focus that made my college roommates call me \"the monk.\""
};

// ── INITIALIZATION ──
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    await loadVoices();
    await loadRefs();
    await loadScript();
    await loadChunks();
    setupGutterSync();
    setupEventListeners();
    connectSSE();
});

// ── API UTILITIES ──
async function apiFetch(url, options = {}) {
    try {
        const response = await fetch(url, options);
        return await response.json();
    } catch (err) {
        console.error('API Fetch Error:', err);
        return null;
    }
}

function apiPost(url, payload) {
    return apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}

function apiDelete(url) {
    return apiFetch(url, { method: 'DELETE' });
}

// ── CONFIGURATION & SETTINGS ──
async function loadConfig() {
    const config = await apiFetch('/api/config');
    if (!config) return;

    DOM.sliderSpeed.value = config.speed;
    DOM.lblSpeed.textContent = config.speed + 'x';
    DOM.txtEmotion.value = config.emotion || '';
    DOM.numSilence.value = config.silence_padding;
    DOM.checkNormalize.checked = config.normalize_audio;
    DOM.checkExportMp3.checked = config.export_mp3;
    DOM.txtRefTranscript.value = config.ref_text || '';

    syncEmotionDropdown(config.emotion);
}

function syncEmotionDropdown(text) {
    if (!text) {
        DOM.selectEmotion.value = '';
        return;
    }
    const options = DOM.selectEmotion.options;
    for (let i = 0; i < options.length; i++) {
        if (options[i].value === text) {
            DOM.selectEmotion.value = text;
            return;
        }
    }
    DOM.selectEmotion.value = '';
}

async function loadVoices() {
    const voicesData = await apiFetch('/api/voices');
    const config = await apiFetch('/api/config');
    if (!voicesData) return;

    DOM.selectVoice.innerHTML = '';
    voicesData.voices.forEach(voice => {
        const opt = document.createElement('option');
        opt.value = voice;
        opt.textContent = voice.charAt(0).toUpperCase() + voice.slice(1);
        if (config && voice === config.voice) opt.selected = true;
        DOM.selectVoice.appendChild(opt);
    });
}

async function loadRefs() {
    const refsData = await apiFetch('/api/refs');
    if (!refsData) return;

    DOM.selectRef.innerHTML = '';
    refsData.refs.forEach(ref => {
        const opt = document.createElement('option');
        opt.value = ref.path;
        opt.textContent = `${ref.name} (${ref.duration})`;
        if (ref.active) opt.selected = true;
        DOM.selectRef.appendChild(opt);
    });

    // Autofill transcript field if it's empty
    const currentRef = refsData.refs.find(r => r.active);
    if (currentRef && !DOM.txtRefTranscript.value.trim()) {
        const defaultText = REF_TRANSCRIPTS[currentRef.name];
        if (defaultText) DOM.txtRefTranscript.value = defaultText;
    }
}

function triggerSaveConfig() {
    apiPost('/api/config', {
        voice: DOM.selectVoice.value,
        speed: parseFloat(DOM.sliderSpeed.value),
        emotion: DOM.txtEmotion.value,
        ref_audio: DOM.selectRef.value,
        ref_text: DOM.txtRefTranscript.value,
        silence_padding: parseFloat(DOM.numSilence.value),
        normalize_audio: DOM.checkNormalize.checked,
        export_mp3: DOM.checkExportMp3.checked,
    });
}

// ── SCRIPT EDITOR WIDGET ──
async function loadScript() {
    const data = await apiFetch('/api/script');
    if (data) {
        DOM.editor.value = data.text || '';
        updateGutter();
        updateMetadataStats();
    }
}

async function saveScriptData() {
    const data = await apiPost('/api/script', { text: DOM.editor.value });
    if (data && data.ok) {
        showToast('Script saved successfully', 'ok');
        updateMetadataStats();
    } else {
        showToast('Error saving script', 'err');
    }
}

function setupGutterSync() {
    updateGutter();
    DOM.editor.addEventListener('input', () => {
        updateGutter();
        updateMetadataStats();
    });
    DOM.editor.addEventListener('scroll', () => {
        DOM.gutter.scrollTop = DOM.editor.scrollTop;
    });
}

function updateGutter() {
    const lines = DOM.editor.value.split('\n');
    let gutterHtml = '';
    for (let i = 0; i < lines.length; i++) {
        const hasText = lines[i].trim().length > 0;
        gutterHtml += `<div style="opacity: ${hasText ? 1 : 0.25}">${i + 1}</div>`;
    }
    DOM.gutter.innerHTML = gutterHtml;
}

function updateMetadataStats() {
    const chunksList = DOM.editor.value.split('\n').filter(line => line.trim().length > 0);
    let totalWords = 0;
    chunksList.forEach(line => {
        const words = line.trim().split(/\s+/).filter(w => w.length > 0);
        totalWords += words.length;
    });

    // Estimation: average narration speed is roughly 145-150 words per minute.
    const estDurationMins = Math.ceil(totalWords / 145);
    const timeStr = estDurationMins === 1 ? '1 minute' : `${estDurationMins} mins`;
    
    DOM.chunkCounter.textContent = `${chunksList.length} Chunks`;
    DOM.wordCounter.textContent = `${totalWords} words · Est. ${timeStr}`;
}

// ── REFERENCE CLONING UPLOADS ──
function setupReferenceVoiceActions() {
    DOM.btnBrowseTrigger.addEventListener('click', (e) => {
        e.preventDefault();
        DOM.inputFileUpload.click();
    });

    DOM.dropZone.addEventListener('click', (e) => {
        if (e.target !== DOM.btnBrowseTrigger) {
            DOM.inputFileUpload.click();
        }
    });

    DOM.dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        DOM.dropZone.classList.add('dragover');
    });

    DOM.dropZone.addEventListener('dragleave', () => {
        DOM.dropZone.classList.remove('dragover');
    });

    DOM.dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        DOM.dropZone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFileUpload(e.dataTransfer.files[0]);
        }
    });

    DOM.inputFileUpload.addEventListener('change', () => {
        if (DOM.inputFileUpload.files && DOM.inputFileUpload.files[0]) {
            handleFileUpload(DOM.inputFileUpload.files[0]);
        }
    });

    DOM.btnRefPlay.addEventListener('click', () => {
        if (DOM.selectRef.value) {
            const fullTextOption = DOM.selectRef.selectedOptions[0]?.textContent || '';
            const filename = fullTextOption.split(' (')[0].trim();
            DOM.audioRefNode.src = `/api/audio/ref/${filename}`;
            DOM.audioRefNode.play();
        } else {
            showToast('No reference voice active', 'err');
        }
    });
}

async function handleFileUpload(file) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('ref_text', DOM.txtRefTranscript.value);
    showToast('Uploading clone audio...', 'ok');

    try {
        const response = await fetch('/api/refs/upload', {
            method: 'POST',
            body: fd,
        });
        const data = await response.json();
        if (data.ok) {
            showToast(`Voice uploaded: ${data.name}`, 'ok');
            await loadRefs();
            triggerSaveConfig();
        } else {
            showToast('Upload failed: ' + (data.error || 'unknown'), 'err');
        }
    } catch (err) {
        showToast('Upload failed due to connection error', 'err');
    }
}

// ── SSE ENGINE PROGRESS LISTENER ──
function connectSSE() {
    if (sseSource) sseSource.close();

    sseSource = new EventSource('/api/generate/progress');

    sseSource.addEventListener('progress', (e) => {
        const progress = JSON.parse(e.data);
        updateProgressUI(progress);
    });

    sseSource.onopen = () => {
        DOM.statusDot.className = 'status-dot ok';
        DOM.statusLabel.textContent = 'Ready';
    };

    sseSource.onerror = () => {
        DOM.statusDot.className = 'status-dot err';
        DOM.statusLabel.textContent = 'Disconnected';
        setTimeout(connectSSE, 4000);
    };
}

function updateProgressUI(data) {
    const { running, status, message, current_chunk, total_chunks, chunks_done } = data;

    // Set high-end descriptive messages
    let descriptiveMsg = message;
    if (status === 'loading') descriptiveMsg = "⚡ Booting Qwen3-TTS Engine & loading model weights...";
    else if (status === 'stitching') descriptiveMsg = "🎛️ Merging acoustic segment outputs...";
    else if (status === 'done') {
        descriptiveMsg = "✅ Narration compilation completed — starting B-Roll video…";
        // Auto-kick the video pipeline right after audio finishes
        setTimeout(autoStartVideoAfterAudio, 800);
    }
    else if (status === 'error') descriptiveMsg = "⚠️ Generation pipeline halted due to an error.";
    else if (status === 'cancelled') descriptiveMsg = "🛑 Generation pipeline aborted by request.";
    
    DOM.statusMsg.textContent = descriptiveMsg || statusLabelText(status);

    // Header Status Updates
    if (running) {
        DOM.statusDot.className = 'status-dot';
        DOM.statusLabel.textContent = 'Processing Pipeline...';
    } else if (status === 'error') {
        DOM.statusDot.className = 'status-dot err';
        DOM.statusLabel.textContent = 'Pipeline Failure';
    } else {
        DOM.statusDot.className = 'status-dot ok';
        DOM.statusLabel.textContent = 'Connected';
    }

    // Modern Progress Visualizer Bar
    if (total_chunks > 0) {
        const percentage = Math.round((current_chunk / total_chunks) * 100);
        DOM.progressBarFill.style.width = `${percentage}%`;
        DOM.statusStats.textContent = `Completed Chunks: ${current_chunk} / ${total_chunks} (${percentage}%)`;
        DOM.progressBarFill.classList.toggle('active', running);
    } else {
        DOM.progressBarFill.style.width = '0%';
        DOM.progressBarFill.classList.remove('active');
        DOM.statusStats.textContent = '';
    }

    // Toggle Action Buttons
    DOM.btnActionGenerate.classList.toggle('hidden', running);
    DOM.btnActionStop.classList.toggle('hidden', !running);

    // List out completed segments in a detailed list view
    if (chunks_done && chunks_done.length > 0) {
        renderSegmentRows(chunks_done, total_chunks);
    }
}

function statusLabelText(status) {
    const statuses = {
        idle: 'System Standby',
        loading: 'Model Initialization...',
        generating: 'Generating acoustic segments...',
        stitching: 'Processing post-engineering normalization...',
        done: 'Generation Completed',
        error: 'Pipeline Failure',
        cancelled: 'Aborted',
    };
    return statuses[status] || status;
}

// ── COMPILATION LIST DISPLAY & PLAYBACK ──
async function loadChunks() {
    const data = await apiFetch('/api/chunks');
    if (!data) return;

    if (data.chunks.length > 0) {
        DOM.chunkSuite.classList.remove('hidden');
        DOM.chunkStatsSummary.textContent = `Total: ${data.chunks.length} segments ready`;
        renderStaticSegmentRows(data.chunks);
    } else {
        DOM.chunkSuite.classList.add('hidden');
    }

    if (data.final.exists) {
        displayAudioPlayer(data.final.duration, data.final.mp3_exists);
    } else {
        DOM.btnDownloadWav.classList.add('hidden');
        DOM.btnDownloadMp3.classList.add('hidden');
        DOM.audioPlaybackPlayer.classList.add('hidden');
    }
}

function renderSegmentRows(chunks, total) {
    DOM.chunkSuite.classList.remove('hidden');
    DOM.chunkStatsSummary.textContent = `${chunks.length} of ${total} finished`;
    DOM.chunkRowsContainer.innerHTML = '';

    chunks.forEach((chunk, index) => {
        const row = document.createElement('div');
        row.className = `chunk-row-item ${chunk.error ? 'failure' : ''}`;
        
        const hasFinished = !chunk.error;
        const iconSymbol = chunk.error ? '✗' : (chunk.skipped ? '⏭' : '▶');
        const durationDisplay = chunk.duration || '—';
        const elapsedText = chunk.time ? ` (+${chunk.time})` : '';

        row.innerHTML = `
            <span class="chunk-row-idx">${String(index + 1).padStart(2, '0')}</span>
            <span class="chunk-row-icon">${iconSymbol}</span>
            <span class="chunk-row-text">${chunk.file.replace('.wav', '')}</span>
            <span class="chunk-row-dur">${durationDisplay}</span>
            <span class="chunk-row-elapsed">${elapsedText}</span>
            <button class="chunk-row-del-btn" title="Remove Segment">✕</button>
        `;

        if (hasFinished) {
            row.querySelector('.chunk-row-icon').addEventListener('click', () => {
                triggerSegmentPlayback(chunk.file, row);
            });
        }

        row.querySelector('.chunk-row-del-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            removeSegmentFile(chunk.file);
        });

        DOM.chunkRowsContainer.appendChild(row);
    });
}

function renderStaticSegmentRows(chunks) {
    DOM.chunkRowsContainer.innerHTML = '';
    chunks.forEach((chunk, index) => {
        const row = document.createElement('div');
        row.className = 'chunk-row-item';
        
        row.innerHTML = `
            <span class="chunk-row-idx">${String(index + 1).padStart(2, '0')}</span>
            <span class="chunk-row-icon">▶</span>
            <span class="chunk-row-text">${chunk.name.replace('.wav', '')}</span>
            <span class="chunk-row-dur">${chunk.duration}</span>
            <span class="chunk-row-elapsed"></span>
            <button class="chunk-row-del-btn" title="Remove Segment">✕</button>
        `;

        row.querySelector('.chunk-row-icon').addEventListener('click', () => {
            triggerSegmentPlayback(chunk.name, row);
        });

        row.querySelector('.chunk-row-del-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            removeSegmentFile(chunk.name);
        });

        DOM.chunkRowsContainer.appendChild(row);
    });
}

function triggerSegmentPlayback(filename, rowElement) {
    $$('.chunk-row-item.playing').forEach(item => item.classList.remove('playing'));
    
    DOM.audioMainNode.src = `/api/audio/chunk/${filename}`;
    DOM.audioMainNode.play();
    
    if (rowElement) rowElement.classList.add('playing');
    activePlayingChunk = filename;
    
    DOM.audioPlaybackPlayer.classList.remove('hidden');
    DOM.playbackTitle.textContent = `Playing: ${filename.replace('.wav', '')}`;
    DOM.btnPlaybackToggle.textContent = '⏸';

    DOM.audioMainNode.onended = () => {
        if (rowElement) rowElement.classList.remove('playing');
        activePlayingChunk = null;
        DOM.btnPlaybackToggle.textContent = '▶';
        DOM.playbackTitle.textContent = "Full Output";
    };
}

async function removeSegmentFile(filename) {
    const data = await apiDelete(`/api/chunks/${filename}`);
    if (data && data.ok) {
        showToast('Segment removed', 'ok');
        await loadChunks();
    } else {
        showToast('Error removing segment file', 'err');
    }
}

// ── INTEGRATED PLAYBACK SUITE ──
function displayAudioPlayer(totalDuration, mp3Exists) {
    DOM.audioPlaybackPlayer.classList.remove('hidden');
    DOM.playbackDuration.textContent = totalDuration || '';
    DOM.playbackTitle.textContent = 'Full Output Narration';
    
    DOM.btnDownloadWav.classList.remove('hidden');
    DOM.btnDownloadMp3.classList.toggle('hidden', !mp3Exists);
}

function setupAudioPlaybackControls() {
    DOM.btnPlaybackToggle.addEventListener('click', () => {
        if (!DOM.audioMainNode.src || !activePlayingChunk) {
            DOM.audioMainNode.src = '/api/audio/final';
            DOM.playbackTitle.textContent = 'Full Output Narration';
        }
        
        if (DOM.audioMainNode.paused) {
            DOM.audioMainNode.play();
            DOM.btnPlaybackToggle.textContent = '⏸';
        } else {
            DOM.audioMainNode.pause();
            DOM.btnPlaybackToggle.textContent = '▶';
        }
    });

    DOM.audioMainNode.addEventListener('timeupdate', () => {
        if (!DOM.audioMainNode.duration) return;
        const progressPct = (DOM.audioMainNode.currentTime / DOM.audioMainNode.duration) * 100;
        DOM.playbackRangeInput.value = progressPct;
        DOM.playbackTime.textContent = `${formatTimelineLabel(DOM.audioMainNode.currentTime)} / ${formatTimelineLabel(DOM.audioMainNode.duration)}`;
    });

    DOM.audioMainNode.addEventListener('ended', () => {
        DOM.btnPlaybackToggle.textContent = '▶';
        activePlayingChunk = null;
        $$('.chunk-row-item.playing').forEach(item => item.classList.remove('playing'));
    });

    DOM.audioMainNode.addEventListener('play', () => {
        DOM.btnPlaybackToggle.textContent = '⏸';
        DOM.audioPlaybackPlayer.classList.remove('hidden');
    });

    DOM.playbackRangeInput.addEventListener('input', () => {
        if (DOM.audioMainNode.duration) {
            DOM.audioMainNode.currentTime = (DOM.playbackRangeInput.value / 100) * DOM.audioMainNode.duration;
        }
    });
}

function formatTimelineLabel(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// ── GENERATION TRIGGERS ──
async function triggerAudioGeneration() {
    await saveScriptData();
    triggerSaveConfig();
    const data = await apiPost('/api/generate', { mode: 'batch' });
    if (data && !data.ok) {
        showToast(data.error || 'Failed to initialize pipeline', 'err');
    }
}

async function abortGeneration() {
    await apiPost('/api/generate/stop', {});
    showToast('Aborting pipeline...', 'err');
}

async function purgeProjectOutputs() {
    if (!confirm('Are you sure you want to delete ALL generated audio clips and video? This cannot be undone.')) {
        return;
    }
    const data = await apiPost('/api/clear', {});
    if (data && data.ok) {
        // ── Reset audio UI ──────────────────────────────────
        DOM.chunkSuite.classList.add('hidden');
        DOM.chunkRowsContainer.innerHTML = '';
        DOM.audioPlaybackPlayer.classList.add('hidden');
        DOM.btnDownloadWav.classList.add('hidden');
        DOM.btnDownloadMp3.classList.add('hidden');
        DOM.progressBarFill.style.width = '0%';
        DOM.statusStats.textContent = '';
        DOM.statusMsg.textContent = 'System Standby';

        // ── Reset video UI ──────────────────────────────────
        const videoSection = document.getElementById('video-section');
        if (videoSection) videoSection.classList.add('hidden');

        const chipRow = document.getElementById('video-chip-row');
        if (chipRow) chipRow.innerHTML = '';

        const videoPlayer = document.getElementById('video-output-player');
        if (videoPlayer) videoPlayer.classList.add('hidden');

        const videoBar = document.getElementById('video-progress-bar');
        if (videoBar) videoBar.style.width = '0%';

        const videoMsg = document.getElementById('video-status-msg');
        if (videoMsg) videoMsg.textContent = '';

        const videoBadge = document.getElementById('video-seg-badge');
        if (videoBadge) videoBadge.textContent = '0 / 0';

        _videoRunning = false;

        showToast('All outputs cleared', 'ok');
    }
}

// ── TOAST NOTIFICATIONS ──
function showToast(message, type = '') {
    const box = document.createElement('div');
    box.className = `toast-msg-box ${type}`;
    box.textContent = message;
    document.body.appendChild(box);
    setTimeout(() => box.remove(), 3200);
}

// ── EVENT ROUTERS & EVENT LISTENER MAPS ──
function setupEventListeners() {
    // Save hotkey trigger
    DOM.btnSaveScript.addEventListener('click', saveScriptData);
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 's') {
            e.preventDefault();
            saveScriptData();
        }
    });

    // Auto config save routers
    DOM.selectVoice.addEventListener('change', triggerSaveConfig);
    DOM.sliderSpeed.addEventListener('input', () => {
        DOM.lblSpeed.textContent = DOM.sliderSpeed.value + 'x';
        triggerSaveConfig();
    });
    DOM.numSilence.addEventListener('change', triggerSaveConfig);
    DOM.checkNormalize.addEventListener('change', triggerSaveConfig);
    DOM.checkExportMp3.addEventListener('change', triggerSaveConfig);
    DOM.txtRefTranscript.addEventListener('change', triggerSaveConfig);

    // Reference Profile change
    DOM.selectRef.addEventListener('change', () => {
        const fullTextOption = DOM.selectRef.selectedOptions[0]?.textContent || '';
        const filename = fullTextOption.split(' (')[0].trim();
        const path = DOM.selectRef.value;
        
        // Sync transcript input
        const defaultTranscript = REF_TRANSCRIPTS[filename];
        if (defaultTranscript) {
            DOM.txtRefTranscript.value = defaultTranscript;
        }

        apiPost('/api/refs/activate', {
            path: path,
            ref_text: DOM.txtRefTranscript.value
        });
    });

    // Emotion Preset mapping
    DOM.selectEmotion.addEventListener('change', () => {
        const val = DOM.selectEmotion.value;
        if (val) DOM.txtEmotion.value = val;
        triggerSaveConfig();
    });
    DOM.txtEmotion.addEventListener('change', triggerSaveConfig);

    // Hot insert tags helpers
    DOM.tagButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tag = btn.getAttribute('data-tag');
            const pos = DOM.editor.selectionStart;
            const text = DOM.editor.value;
            DOM.editor.value = text.slice(0, pos) + tag + ' ' + text.slice(pos);
            DOM.editor.focus();
            DOM.editor.setSelectionRange(pos + tag.length + 1, pos + tag.length + 1);
            updateGutter();
            updateMetadataStats();
        });
    });

    // Main action routers
    DOM.btnActionGenerate.addEventListener('click', triggerAudioGeneration);
    DOM.btnActionStop.addEventListener('click', abortGeneration);
    DOM.btnActionClear.addEventListener('click', purgeProjectOutputs);

    // Download handlers
    DOM.btnDownloadWav.addEventListener('click', () => {
        window.open('/api/download/wav', '_blank');
    });
    DOM.btnDownloadMp3.addEventListener('click', () => {
        window.open('/api/download/mp3', '_blank');
    });

    // Audio Playbacks setup
    setupAudioPlaybackControls();
    
    // File upload zones setup
    setupReferenceVoiceActions();

    // ── ASPECT RATIO SELECTOR ────────────────────────────────
    setupAspectRatio();

    // ── VIDEO AUTO-PIPELINE SETUP ────────────────────────────
    setupVideoPipeline();
}

// ============================================================
// ASPECT RATIO SELECTOR
// ============================================================

function setupAspectRatio() {
    const grid = document.getElementById('aspect-ratio-grid');
    if (!grid) return;

    // Load current resolution from server and highlight active button
    fetch('/api/video/config')
        .then(r => r.json())
        .then(cfg => {
            if (cfg.resolution) setActiveAR(cfg.resolution);
        })
        .catch(() => {});

    // Click handler — update active state and save to server
    grid.querySelectorAll('.ar-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const res = btn.dataset.res;
            setActiveAR(res);
            // Persist to server
            fetch('/api/video/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ resolution: res }),
            }).catch(() => {});
        });
    });
}

function setActiveAR(resolution) {
    document.querySelectorAll('.ar-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.res === resolution);
    });
}


// ============================================================
// B-ROLL VIDEO — Fully Automated Pipeline
// Auto-starts when audio generation finishes.
// Shows inline progress chips + final video player below audio.
// ============================================================

let _videoSSE       = null;
let _videoRunning   = false;

function setupVideoPipeline() {
    connectVideoSSE();
    // Restore state if server already has a done/running video
    refreshVideoState();
}

// ── SSE connection ────────────────────────────────────────────

function connectVideoSSE() {
    if (_videoSSE) _videoSSE.close();
    _videoSSE = new EventSource('/api/video/events');
    _videoSSE.addEventListener('progress', e => {
        handleVideoProgress(JSON.parse(e.data));
    });
    _videoSSE.onerror = () => setTimeout(connectVideoSSE, 3000);
}

async function refreshVideoState() {
    try {
        const st = await fetch('/api/video/status').then(r => r.json());
        handleVideoProgress(st);
        if (st.status === 'done' && st.output_file) revealVideoPlayer();
    } catch(_) {}
}

// ── Called externally when audio generation finishes ─────────
// Hooked into the existing audio-done SSE handler below.

function autoStartVideoAfterAudio() {
    if (_videoRunning) return;
    startVideoGeneration();
}

// ── Start video generation ────────────────────────────────────

async function startVideoGeneration() {
    if (_videoRunning) return;

    // Reset UI
    const section = document.getElementById('video-section');
    section.classList.remove('hidden');
    document.getElementById('video-chip-row').innerHTML = '';
    document.getElementById('video-output-player').classList.add('hidden');
    document.getElementById('video-progress-bar').style.width = '0%';
    document.getElementById('video-status-msg').textContent = 'Starting…';
    document.getElementById('video-seg-badge').textContent = '0 / 0';

    try {
        const res  = await fetch('/api/video/create', { method: 'POST' });
        const data = await res.json();
        if (!data.ok) {
            document.getElementById('video-status-msg').textContent =
                '❌ ' + (data.error || 'Could not start video');
        }
    } catch(e) {
        document.getElementById('video-status-msg').textContent = '❌ Request failed';
    }
}

// ── Progress handler ──────────────────────────────────────────

function handleVideoProgress(data) {
    const { running, status, message, current_chunk, total_chunks, segments_done } = data;
    _videoRunning = !!running;

    // Show the section whenever there's activity
    if (status && status !== 'idle') {
        document.getElementById('video-section').classList.remove('hidden');
    }

    // Progress bar (purple)
    const pct = total_chunks > 0 ? Math.round((current_chunk / total_chunks) * 100) : 0;
    document.getElementById('video-progress-bar').style.width = pct + '%';

    // Badge
    if (total_chunks > 0) {
        document.getElementById('video-seg-badge').textContent =
            `${current_chunk} / ${total_chunks}`;
    }

    // Status label
    const icons = { idle:'⚙', searching:'🔍', merging:'🎞', done:'✅', error:'❌', cancelled:'⛔' };
    document.getElementById('video-status-msg').textContent =
        (icons[status] || '⚙') + ' ' + (message || '');

    // Render chips
    if (segments_done && segments_done.length) {
        segments_done.forEach(seg => renderChip(seg));
    }

    // Done — show video player
    if (status === 'done') {
        document.getElementById('video-progress-bar').style.width = '100%';
        revealVideoPlayer();
    }
}

// ── Segment chip ──────────────────────────────────────────────

function renderChip(seg) {
    const row = document.getElementById('video-chip-row');
    const id  = `vchip-${seg.index}`;
    let chip  = document.getElementById(id);

    if (!chip) {
        chip    = document.createElement('span');
        chip.id = id;
        row.appendChild(chip);
    }

    const typeEmoji = seg.type === 'video'  ? '🎬' :
                      seg.type === 'image'  ? '🖼'  :
                      seg.type === 'color'  ? '⬛'  :
                      seg.type === 'cached' ? '♻'   : '⏳';

    const cls = seg.ok === true  ? (seg.type === 'image' ? 'chip-image' : 'chip-done') :
                seg.ok === false ? 'chip-error' : 'chip-working';

    chip.className = `vchip ${cls}`;
    chip.innerHTML = `<span class="vchip-dot"></span>${typeEmoji} #${seg.index + 1} ${escapeHtml(seg.keyword || '')}`;
    chip.title     = `Source: ${seg.source || '?'} | ${seg.time || ''}`;
}

function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Reveal video player ───────────────────────────────────────

function revealVideoPlayer() {
    const player = document.getElementById('video-output-player');
    const video  = document.getElementById('video-player-node');
    player.classList.remove('hidden');
    video.src = '/api/video/download?t=' + Date.now();
    video.load();
    // Scroll to it
    player.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
