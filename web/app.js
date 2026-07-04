// ============================================================
// app.js — Narrator Dashboard Logic (v3 Premium Edition)
// ============================================================

const $ = (s) => document.querySelector(s) || document.createElement('div');
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
    btnVoicePreview:  $('#btn-voice-preview'),
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
let _previewSegIndex = -1;

// ── PIPELINE MODE STATE ──
// 'audio' | 'both' | 'video'
let _pipelineMode = 'both';

const MODE_CONFIG = {
    audio: {
        label:      '🎙 Audio Only',
        hint:       'Generates narration audio only. No video will be created.',
        badgeColor: '#7c9dff',
    },
    both: {
        label:      '✨ Audio + Video',
        hint:       'Generates audio then automatically creates B-Roll video.',
        badgeColor: 'var(--accent)',
    },
    video: {
        label:      '🎬 Video Only',
        hint:       'Creates B-Roll video using the existing audio. Generate audio first.',
        badgeColor: '#ff7c7c',
    },
};

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
    setupModeSelector();
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

const KOKORO_VOICE_LABELS = {
    // American Female
    "af_sarah": "Sarah (US Female — Soft)",
    "af_bella": "Bella (US Female — Expressive)",
    "af_heart": "Heart (US Female — Warm)",
    "af_nicole": "Nicole (US Female — Clear)",
    "af_sky": "Sky (US Female — Bright)",
    "af_alloy": "Alloy (US Female — Balanced)",
    "af_aoede": "Aoede (US Female — Narrator)",
    "af_jessica": "Jessica (US Female — Crisp)",
    "af_kore": "Kore (US Female — Sweet)",
    "af_nova": "Nova (US Female — Energetic)",
    "af_river": "River (US Female — Calm)",
    
    // American Male
    "am_adam": "Adam (US Male — Deep)",
    "am_michael": "Michael (US Male — Natural)",
    "am_fenrir": "Fenrir (US Male — Rich)",
    "am_puck": "Puck (US Male — Lively)",
    "am_echo": "Echo (US Male — Corporate)",
    "am_eric": "Eric (US Male — Conversational)",
    "am_liam": "Liam (US Male — Friendly)",
    "am_onyx": "Onyx (US Male — Authority)",
    "am_santa": "Santa (US Male — Festive)",
    
    // British Female
    "bf_alice": "Alice (UK Female — Gentle)",
    "bf_emma": "Emma (UK Female — Elegant)",
    "bf_isabella": "Isabella (UK Female — Narrative)",
    "bf_lily": "Lily (UK Female — Bright)",
    
    // British Male
    "bm_daniel": "Daniel (UK Male — Warm)",
    "bm_fable": "Fable (UK Male — Dramatic)",
    "bm_george": "George (UK Male — Classic)",
    "bm_lewis": "Lewis (UK Male — Conversational)"
};

async function loadVoices() {
    const voicesData = await apiFetch('/api/voices');
    const config = await apiFetch('/api/config');
    if (!voicesData) return;

    DOM.selectVoice.innerHTML = '';
    voicesData.voices.forEach(voice => {
        const opt = document.createElement('option');
        opt.value = voice;
        opt.textContent = KOKORO_VOICE_LABELS[voice] || (voice.charAt(0).toUpperCase() + voice.slice(1));
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

async function saveScriptData(silent = false) {
    DOM.btnSaveScript.textContent = 'Saving...';
    const data = await apiPost('/api/script', { text: DOM.editor.value });
    if (data && data.ok) {
        DOM.btnSaveScript.textContent = 'Saved ✓';
        updateMetadataStats();
    } else {
        DOM.btnSaveScript.textContent = 'Save Failed ⚠️';
        if (!silent) showToast('Error saving script', 'err');
    }
    setTimeout(() => {
        DOM.btnSaveScript.textContent = '💾 Save Changes';
    }, 1200);
}

async function analyzeScriptData() {
    DOM.btnAnalyzeScript.disabled = true;
    DOM.btnAnalyzeScript.textContent = '🔍 Analyzing...';
    
    try {
        const data = await apiPost('/api/script/analyze', { text: DOM.editor.value });
        if (data && data.ok) {
            DOM.editor.value = data.text;
            updateGutter();
            updateMetadataStats();
            const modeLabel = data.mode === 'ai' ? 'AI Director Mode' : 'Local Rules';
            showToast(`Script auto-directed successfully (${modeLabel})`, 'ok');
            saveScriptData(true);
        } else {
            showToast('Error analyzing script', 'err');
        }
    } catch (e) {
        showToast('Error connecting to script analyzer', 'err');
    } finally {
        DOM.btnAnalyzeScript.disabled = false;
        DOM.btnAnalyzeScript.textContent = '🎨 Auto-Direct Script';
    }
}

async function polishScriptData() {
    DOM.btnPolishScript.disabled = true;
    DOM.btnPolishScript.textContent = '✨ Polishing...';
    
    try {
        const data = await apiPost('/api/script/polish', { text: DOM.editor.value });
        if (data && data.ok) {
            DOM.editor.value = data.text;
            updateGutter();
            updateMetadataStats();
            const modeLabel = data.mode === 'ai' ? 'AI Polish Mode' : 'Local Rules';
            showToast(`Script polished successfully (${modeLabel})`, 'ok');
            saveScriptData(true);
        } else {
            showToast('Error polishing script', 'err');
        }
    } catch (e) {
        showToast('Error connecting to script polish engine', 'err');
    } finally {
        DOM.btnPolishScript.disabled = false;
        DOM.btnPolishScript.textContent = '✨ Polish Text';
    }
}

let autoSaveTimeout = null;
function setupGutterSync() {
    updateGutter();
    DOM.editor.addEventListener('input', () => {
        updateGutter();
        updateMetadataStats();
        
        clearTimeout(autoSaveTimeout);
        autoSaveTimeout = setTimeout(() => {
            saveScriptData(true);
        }, 1500);
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
    if (status === 'loading') descriptiveMsg = "⚡ Loading Kokoro ONNX Engine & model weights...";
    else if (status === 'stitching') descriptiveMsg = "🎛️ Merging acoustic segment outputs...";
    else if (status === 'done') {
        descriptiveMsg = _pipelineMode === 'audio'
            ? "✅ Audio generation complete."
            : "✅ Narration complete — starting B-Roll video…";
        // Reload segment rows and reveal master player
        loadChunks();
        // Auto-kick the video pipeline right after audio finishes
        setTimeout(autoStartVideoAfterAudio, 800);
        // Refresh history to show the new archived entry
        setTimeout(loadHistory, 1500);
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

    // Reset master player source to force cache bust on next play
    DOM.audioMainNode.removeAttribute('src');
    DOM.btnPlaybackToggle.textContent = '▶';
}

function setupAudioPlaybackControls() {
    DOM.btnPlaybackToggle.addEventListener('click', () => {
        if (!DOM.audioMainNode.src || activePlayingChunk) {
            DOM.audioMainNode.src = `/api/audio/final?t=${Date.now()}`;
            DOM.playbackTitle.textContent = 'Full Output Narration';
            activePlayingChunk = null;
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
        showToast(data.error || 'Failed to initialize audio pipeline', 'err');
    }
}

async function triggerVideoGeneration() {
    await startVideoGeneration();
}

async function triggerGeneration() {
    if (_pipelineMode === 'audio') {
        await triggerAudioGeneration();
    } else if (_pipelineMode === 'video') {
        await triggerVideoGeneration();
    } else {
        await triggerAudioGeneration();
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
        DOM.statusMsg.textContent = 'System Idle'; // updated from 'System Standby'

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
    } else {
        showToast((data && data.error) ? data.error : 'Failed to clear outputs', 'err');
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
    DOM.btnSaveScript.addEventListener('click', () => saveScriptData(false));
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 's') {
            e.preventDefault();
            saveScriptData();
        }
    });

    // Auto config save routers
    DOM.selectVoice.addEventListener('change', () => {
        DOM.audioRefNode.pause();
        DOM.btnVoicePreview.textContent = '▶';
        triggerSaveConfig();
    });

    DOM.btnVoicePreview.addEventListener('click', () => {
        const voice = DOM.selectVoice.value;
        if (!voice) return;
        
        if (!DOM.audioRefNode.paused && DOM.audioRefNode.src.includes(`/api/voices/preview/${voice}`)) {
            DOM.audioRefNode.pause();
            DOM.btnVoicePreview.textContent = '▶';
        } else {
            DOM.audioRefNode.src = `/api/voices/preview/${voice}`;
            DOM.audioRefNode.play();
            DOM.btnVoicePreview.textContent = '⏸';
            
            DOM.audioRefNode.onended = () => {
                DOM.btnVoicePreview.textContent = '▶';
            };
        }
    });
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
    DOM.btnActionGenerate.addEventListener('click', triggerGeneration);
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

    // ── VIDEO PREVIEW MODAL ──────────────────────────────────
    setupVideoPreviewModal();

    // ── B-ROLL REVIEW DRAWER ──────────────────────────────────
    setupReviewDrawer();
}

// ============================================================
// ASPECT RATIO SELECTOR
// ============================================================

function setupAspectRatio() {
    const grid = document.getElementById('aspect-ratio-grid');
    if (!grid) return;

    // Load current video config from server
    fetch('/api/video/config')
        .then(r => r.json())
        .then(cfg => {
            if (cfg.resolution) setActiveAR(cfg.resolution);
            if (cfg.clip_interval !== undefined) {
                const inp = document.getElementById('num-clip-interval');
                if (inp) inp.value = cfg.clip_interval;
            }
            if (cfg.review_before_merge !== undefined) {
                const chk = document.getElementById('check-review-before-merge');
                if (chk) chk.checked = !!cfg.review_before_merge;
            }
            if (cfg.groq_api_keys !== undefined) {
                const groq = document.getElementById('inp-groq-api-keys');
                if (groq) groq.value = cfg.groq_api_keys || '';
            }
        })
        .catch(() => {});

    // Aspect ratio click
    grid.querySelectorAll('.ar-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const res = btn.dataset.res;
            setActiveAR(res);
            fetch('/api/video/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ resolution: res }),
            }).catch(() => {});
        });
    });

    // Clip interval change
    const clipInput = document.getElementById('num-clip-interval');
    if (clipInput) {
        clipInput.addEventListener('change', () => {
            const val = Math.max(0, parseInt(clipInput.value) || 0);
            clipInput.value = val;
            fetch('/api/video/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ clip_interval: val }),
            }).catch(() => {});
        });
    }

    // Review before merge toggle
    const reviewChk = document.getElementById('check-review-before-merge');
    if (reviewChk) {
        reviewChk.addEventListener('change', () => {
            fetch('/api/video/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ review_before_merge: reviewChk.checked }),
            }).catch(() => {});
        });
    }



    // Groq rotating API keys — save on change
    const groqKeyInp = document.getElementById('inp-groq-api-keys');
    if (groqKeyInp) {
        let groqSaveTimer = null;
        groqKeyInp.addEventListener('input', () => {
            clearTimeout(groqSaveTimer);
            groqSaveTimer = setTimeout(() => {
                fetch('/api/video/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ groq_api_keys: groqKeyInp.value.trim() }),
                }).catch(() => {});
            }, 800);  // debounce 800ms
        });
    }
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
// Only auto-starts video when mode is 'both'.

function autoStartVideoAfterAudio() {
    if (_pipelineMode !== 'both') return;
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
            // 409 = already running — not an error to show the user
            if (res.status === 409) return;
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
    const icons = { idle:'⚙', searching:'🔍', merging:'🎞', done:'✅', error:'❌',
                    cancelled:'⛔', review_ready:'🎬', loading:'⚡' };
    document.getElementById('video-status-msg').textContent =
        (icons[status] || '⚙') + ' ' + (message || '');

    // Render chips
    if (segments_done && segments_done.length) {
        segments_done.forEach(seg => renderChip(seg));
    }

    // Review Ready — open the Review Drawer (70% wide), show trigger buttons
    if (status === 'review_ready') {
        document.getElementById('video-progress-bar').style.width = '100%';
        buildReviewPanel(segments_done || []);
        
        // Show the review trigger button so the user can re-open it
        const triggerRow = document.getElementById('review-trigger-row');
        if (triggerRow) triggerRow.classList.remove('hidden');
        const toolbarBtn = document.getElementById('btn-open-review-drawer-toolbar');
        if (toolbarBtn) toolbarBtn.classList.remove('hidden');

        // Automatically open the drawer on initial transition
        const drawer = document.getElementById('review-drawer');
        const backdrop = document.getElementById('review-backdrop');
        if (drawer && backdrop && drawer.classList.contains('hidden')) {
            drawer.classList.remove('hidden');
            backdrop.classList.remove('hidden');
        }

        // Hide final player until merge is done
        document.getElementById('video-output-player').classList.add('hidden');
    } else {
        const triggerRow = document.getElementById('review-trigger-row');
        if (triggerRow) triggerRow.classList.add('hidden');
        const toolbarBtn = document.getElementById('btn-open-review-drawer-toolbar');
        if (toolbarBtn) toolbarBtn.classList.add('hidden');
        
        const drawer = document.getElementById('review-drawer');
        const backdrop = document.getElementById('review-backdrop');
        if (drawer && status !== 'review_ready') drawer.classList.add('hidden');
        if (backdrop && status !== 'review_ready') backdrop.classList.add('hidden');
    }

    // Done — show video player, hide review
    if (status === 'done') {
        document.getElementById('video-progress-bar').style.width = '100%';
        const drawer = document.getElementById('review-drawer');
        const backdrop = document.getElementById('review-backdrop');
        if (drawer) drawer.classList.add('hidden');
        if (backdrop) backdrop.classList.add('hidden');
        const toolbarBtn = document.getElementById('btn-open-review-drawer-toolbar');
        if (toolbarBtn) toolbarBtn.classList.add('hidden');
        revealVideoPlayer();
    }
}

// ── Segment chip — clickable for preview ─────────────────────

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
    chip.title     = `Source: ${seg.source || '?'} | ${seg.time || ''} — Click to preview`;

    // Make chips clickable — open preview modal
    chip.onclick = () => {
        if (seg.ok) showVideoPreviewModal(seg);
    };
}

function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Reveal video player ───────────────────────────────────────

// ── Video Preview Modal (with audio synchronization) ─────────

function showVideoPreviewModal(seg) {
    const modal  = document.getElementById('video-preview-modal');
    const player = document.getElementById('vpreview-player');
    const audio  = document.getElementById('vpreview-audio');
    const title  = document.getElementById('vpreview-title');
    const meta   = document.getElementById('vpreview-meta');
    if (!modal || !player || !audio) return;

    _previewSegIndex = seg.index;

    title.textContent = `Segment #${seg.index + 1} — ${seg.keyword || 'clip'}`;
    meta.textContent  = `Source: ${seg.source || '?'} · Type: ${seg.type || '?'}${seg.time ? ' · ' + seg.time : ''}`;
    
    // Load Video
    player.src = `/api/video/segments/${seg.index}?t=${Date.now()}`;
    player.load();
    player.muted = true; // Mute video so only synced narration audio plays

    // Load Audio chunk
    const padIndex = String(seg.index).padStart(4, '0');
    audio.src = `/api/audio/chunk/chunk_${padIndex}.wav?t=${Date.now()}`;
    audio.load();

    // Populate Change section
    const kwInput = document.getElementById('vpreview-change-kw');
    if (kwInput) kwInput.value = seg.keyword || '';
    const statusLabel = document.getElementById('vpreview-change-status');
    if (statusLabel) { statusLabel.style.display = 'none'; statusLabel.textContent = ''; }

    // Reset controls UI
    const playBtn = document.getElementById('vpreview-play-btn');
    if (playBtn) playBtn.textContent = '▶';
    const seekInput = document.getElementById('vpreview-seek');
    if (seekInput) seekInput.value = 0;
    const curTime = document.getElementById('vpreview-time-cur');
    if (curTime) curTime.textContent = '0:00';
    const durTime = document.getElementById('vpreview-time-dur');
    if (durTime) durTime.textContent = '0:00';

    modal.classList.remove('hidden');
}

function setupVideoPreviewModal() {
    const closeBtn = document.getElementById('video-preview-close');
    const modal    = document.getElementById('video-preview-modal');
    const player   = document.getElementById('vpreview-player');
    const audio    = document.getElementById('vpreview-audio');
    const playBtn  = document.getElementById('vpreview-play-btn');
    const seek     = document.getElementById('vpreview-seek');
    const curTime  = document.getElementById('vpreview-time-cur');
    const durTime  = document.getElementById('vpreview-time-dur');
    const vol      = document.getElementById('vpreview-vol');

    if (!modal || !player || !audio) return;

    function pauseAll() {
        player.pause();
        audio.pause();
        if (playBtn) playBtn.textContent = '▶';
    }

    function cleanup() {
        pauseAll();
        player.src = '';
        audio.src = '';
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.classList.add('hidden');
            cleanup();
        });
    }

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
            cleanup();
        }
    });

    if (playBtn) {
        playBtn.addEventListener('click', () => {
            if (player.paused) {
                // Synchronize audio and video start times
                audio.currentTime = player.currentTime;
                player.play();
                audio.play().catch(() => {});
                playBtn.textContent = '⏸';
            } else {
                pauseAll();
            }
        });
    }

    // Update seek bar and timer
    player.addEventListener('timeupdate', () => {
        if (player.duration) {
            const pct = (player.currentTime / player.duration) * 100;
            if (seek) seek.value = pct;
            if (curTime) curTime.textContent = formatTimelineLabel(player.currentTime);
            
            // Sync logic: Keep audio aligned with video
            if (!audio.paused) {
                const diff = Math.abs(player.currentTime - audio.currentTime);
                if (diff > 0.15) {
                    audio.currentTime = player.currentTime;
                }
            }
        }
    });

    player.addEventListener('loadedmetadata', () => {
        if (durTime && player.duration) {
            durTime.textContent = formatTimelineLabel(player.duration);
        }
    });

    // If audio is playing but video ended (or vice versa)
    player.addEventListener('ended', () => {
        pauseAll();
        if (seek) seek.value = 100;
    });

    if (seek) {
        seek.addEventListener('input', () => {
            if (player.duration) {
                const targetTime = (seek.value / 100) * player.duration;
                player.currentTime = targetTime;
                audio.currentTime = targetTime;
            }
        });
    }

    if (vol) {
        vol.addEventListener('input', () => {
            audio.volume = vol.value;
        });
    }

    // ── Change Clip actions inside Preview Modal ──
    const researchBtn = document.getElementById('btn-vpreview-research');
    const kwInput = document.getElementById('vpreview-change-kw');
    const uploadInput = document.getElementById('vpreview-change-upload');
    const statusLabel = document.getElementById('vpreview-change-status');

    async function handleModalResearch() {
        if (_previewSegIndex === -1) return;
        const keyword = kwInput ? kwInput.value.trim() : '';
        if (!keyword) { showToast('Enter a search keyword first', 'err'); return; }

        pauseAll();
        if (researchBtn) researchBtn.disabled = true;
        if (statusLabel) { statusLabel.textContent = '🔄 Rebuilding segment...'; statusLabel.style.display = 'inline'; }

        try {
            const res = await fetch(`/api/video/segments/${_previewSegIndex}/replace`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ keyword })
            });
            const data = await res.json();
            if (data.ok) {
                showToast(`Segment ${_previewSegIndex + 1} rebuilt ✓`, 'ok');
                
                // Reload preview video player
                player.src = `/api/video/segments/${_previewSegIndex}?t=${Date.now()}`;
                player.load();

                // Sync the corresponding card in the review grid if loaded
                const card = document.getElementById(`rcc-${_previewSegIndex}`);
                if (card) {
                    card.classList.remove('replacing');
                    card.classList.add('replaced');
                    const thumbVid = card.querySelector('.rcc-thumb video');
                    if (thumbVid) {
                        thumbVid.src = `/api/video/segments/${_previewSegIndex}?t=${Date.now()}`;
                        thumbVid.load();
                    }
                    const kwEl = card.querySelector('.rcc-keyword');
                    if (kwEl) kwEl.textContent = keyword;
                    const srcEl = card.querySelector('.rcc-source');
                    if (srcEl) srcEl.textContent = data.source || '';
                }
            } else {
                showToast('Rebuild failed: ' + (data.error || 'unknown'), 'err');
            }
        } catch (e) {
            showToast('Network error during rebuild', 'err');
        } finally {
            if (researchBtn) researchBtn.disabled = false;
            if (statusLabel) { statusLabel.style.display = 'none'; statusLabel.textContent = ''; }
        }
    }

    async function handleModalUpload() {
        if (_previewSegIndex === -1) return;
        const file = uploadInput.files && uploadInput.files[0];
        if (!file) return;

        pauseAll();
        if (statusLabel) { statusLabel.textContent = '📤 Uploading clip...'; statusLabel.style.display = 'inline'; }

        try {
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch(`/api/video/segments/${_previewSegIndex}/upload`, {
                method: 'POST',
                body: fd
            });
            const data = await res.json();
            if (data.ok) {
                showToast(`Segment ${_previewSegIndex + 1} replaced with uploaded file ✓`, 'ok');
                
                // Reload preview video player
                player.src = `/api/video/segments/${_previewSegIndex}?t=${Date.now()}`;
                player.load();

                // Sync the corresponding card in the review grid if loaded
                const card = document.getElementById(`rcc-${_previewSegIndex}`);
                if (card) {
                    card.classList.remove('replacing');
                    card.classList.add('replaced');
                    const thumbVid = card.querySelector('.rcc-thumb video');
                    if (thumbVid) {
                        thumbVid.src = `/api/video/segments/${_previewSegIndex}?t=${Date.now()}`;
                        thumbVid.load();
                    }
                    const kwEl = card.querySelector('.rcc-keyword');
                    if (kwEl) kwEl.textContent = 'custom upload';
                    const srcEl = card.querySelector('.rcc-source');
                    if (srcEl) srcEl.textContent = 'upload';
                }
            } else {
                showToast('Upload failed: ' + (data.error || 'unknown'), 'err');
            }
        } catch (e) {
            showToast('Network error during upload', 'err');
        } finally {
            if (statusLabel) { statusLabel.style.display = 'none'; statusLabel.textContent = ''; }
            uploadInput.value = '';
        }
    }

    if (researchBtn) researchBtn.addEventListener('click', handleModalResearch);
    if (uploadInput) uploadInput.addEventListener('change', handleModalUpload);
}

// ── Review Panel ──────────────────────────────────────────────

function buildReviewPanel(segments) {
    const grid = document.getElementById('review-clips-grid');
    if (!grid) return;
    // Only rebuild if not already populated (avoid flickering on re-broadcasts)
    if (grid.children.length === segments.length) return;
    grid.innerHTML = '';
    segments.forEach(seg => grid.appendChild(renderReviewCard(seg)));

    // Wire up Merge Now button
    const mergeBtn = document.getElementById('btn-merge-now');
    if (mergeBtn) {
        mergeBtn.onclick = () => triggerMerge(mergeBtn);
    }
}

function renderReviewCard(seg) {
    const card = document.createElement('div');
    card.className = 'review-clip-card';
    card.id = `rcc-${seg.index}`;

    const typeLabel = seg.type || 'clip';
    const srcLabel  = seg.source || '?';
    const kwLabel   = seg.keyword || '';
    const formId    = `rcc-form-${seg.index}`;
    const uploadId  = `rcc-upload-${seg.index}`;

    card.innerHTML = `
        <div class="rcc-spinner" id="rcc-spin-${seg.index}">🔄 Searching…</div>
        <div class="rcc-thumb" id="rcc-thumb-${seg.index}">
            <video muted preload="metadata" src="/api/video/segments/${seg.index}?t=${Date.now()}"
                   style="width:100%;height:100%;object-fit:cover;"></video>
            <div class="rcc-thumb-overlay">▶</div>
        </div>
        <div class="rcc-info">
            <div class="rcc-idx">Segment ${seg.index + 1}</div>
            <div class="rcc-keyword" title="${escapeHtml(kwLabel)}">${escapeHtml(kwLabel)}</div>
            <div class="rcc-source">${escapeHtml(srcLabel)}</div>
            <span class="rcc-type-badge ${typeLabel}">${typeLabel}</span>
        </div>
        <div class="rcc-actions">
            <div class="rcc-btn-row" style="margin-bottom: 6px;">
                <button class="btn-rcc btn-preview-rcc primary" style="border-color: #7c9dff; color: #7c9dff; background: rgba(124,157,255,0.06);">👁 Preview</button>
                <button class="btn-rcc" onclick="toggleReplaceForm(${seg.index})">🔄 Change</button>
            </div>
            <div class="rcc-replace-form" id="${formId}">
                <input class="rcc-kw-input" id="rcc-kw-${seg.index}" placeholder="New keyword…" value="${escapeHtml(kwLabel)}">
                <div class="rcc-btn-row">
                    <button class="btn-rcc primary" onclick="replaceClip(${seg.index})">🔍 Re-search</button>
                    <button class="btn-rcc danger" onclick="toggleReplaceForm(${seg.index})">Cancel</button>
                </div>
                <label class="rcc-upload-label" for="${uploadId}">📁 Upload Own Clip</label>
                <input class="rcc-upload-input" id="${uploadId}" type="file" accept="video/*"
                       onchange="uploadClip(${seg.index}, this)">
            </div>
        </div>
    `;

    // Click on thumb or preview button opens full preview modal
    const thumb = card.querySelector('.rcc-thumb');
    thumb.addEventListener('click', () => showVideoPreviewModal(seg));
    card.querySelector('.btn-preview-rcc').addEventListener('click', () => showVideoPreviewModal(seg));

    return card;
}

function toggleReplaceForm(index) {
    const form = document.getElementById(`rcc-form-${index}`);
    if (form) form.classList.toggle('open');
}

async function replaceClip(index) {
    const kwInput = document.getElementById(`rcc-kw-${index}`);
    const keyword = kwInput ? kwInput.value.trim() : '';
    if (!keyword) { showToast('Enter a keyword first', 'err'); return; }

    const card    = document.getElementById(`rcc-${index}`);
    const spinner = document.getElementById(`rcc-spin-${index}`);
    if (spinner) spinner.classList.add('active');
    if (card)   card.classList.add('replacing');

    try {
        const res  = await fetch(`/api/video/segments/${index}/replace`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword }),
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`Segment ${index + 1} replaced ✓`, 'ok');
            if (card) card.classList.remove('replacing');
            if (card) card.classList.add('replaced');
            // Reload thumb video
            const thumbVid = document.querySelector(`#rcc-thumb-${index} video`);
            if (thumbVid) {
                thumbVid.src = `/api/video/segments/${index}?t=${Date.now()}`;
                thumbVid.load();
            }
            // Update keyword label
            const kwEl = card ? card.querySelector('.rcc-keyword') : null;
            if (kwEl) kwEl.textContent = keyword;
            const srcEl = card ? card.querySelector('.rcc-source') : null;
            if (srcEl) srcEl.textContent = data.source || '';
            // Close form
            toggleReplaceForm(index);
        } else {
            showToast('Replace failed: ' + (data.error || 'unknown'), 'err');
            if (card) card.classList.remove('replacing');
        }
    } catch (e) {
        showToast('Network error during replace', 'err');
        if (card) card.classList.remove('replacing');
    } finally {
        if (spinner) spinner.classList.remove('active');
    }
}

async function uploadClip(index, inputEl) {
    const file = inputEl.files && inputEl.files[0];
    if (!file) return;

    const card    = document.getElementById(`rcc-${index}`);
    const spinner = document.getElementById(`rcc-spin-${index}`);
    if (spinner) { spinner.textContent = '📤 Uploading…'; spinner.classList.add('active'); }
    if (card)   card.classList.add('replacing');

    try {
        const fd = new FormData();
        fd.append('file', file);
        const res  = await fetch(`/api/video/segments/${index}/upload`, {
            method: 'POST',
            body: fd,
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`Segment ${index + 1} replaced with uploaded file ✓`, 'ok');
            if (card) card.classList.remove('replacing');
            if (card) card.classList.add('replaced');
            // Reload thumb
            const thumbVid = document.querySelector(`#rcc-thumb-${index} video`);
            if (thumbVid) { thumbVid.src = `/api/video/segments/${index}?t=${Date.now()}`; thumbVid.load(); }
            const kwEl = card ? card.querySelector('.rcc-keyword') : null;
            if (kwEl) kwEl.textContent = 'custom upload';
            const srcEl = card ? card.querySelector('.rcc-source') : null;
            if (srcEl) srcEl.textContent = 'upload';
        } else {
            showToast('Upload failed: ' + (data.error || 'unknown'), 'err');
            if (card) card.classList.remove('replacing');
        }
    } catch (e) {
        showToast('Network error during upload', 'err');
        if (card) card.classList.remove('replacing');
    } finally {
        if (spinner) { spinner.classList.remove('active'); spinner.textContent = '🔄 Searching…'; }
        inputEl.value = '';
    }
}

async function triggerMerge(btn) {
    if (btn) { btn.disabled = true; btn.textContent = '⚙ Merging…'; }
    try {
        const res  = await fetch('/api/video/merge', { method: 'POST' });
        const data = await res.json();
        if (!data.ok) {
            showToast('Merge failed: ' + (data.error || 'unknown'), 'err');
            if (btn) { btn.disabled = false; btn.textContent = '⚡ Merge Now'; }
        } else {
            showToast('Merging… final video coming soon!', 'ok');
            const drawer = document.getElementById('review-drawer');
            const backdrop = document.getElementById('review-backdrop');
            if (drawer) drawer.classList.add('hidden');
            if (backdrop) backdrop.classList.add('hidden');
        }
    } catch (e) {
        showToast('Network error triggering merge', 'err');
        if (btn) { btn.disabled = false; btn.textContent = '⚡ Merge Now'; }
    }
}

function revealVideoPlayer() {
    const player = document.getElementById('video-output-player');
    const video  = document.getElementById('video-player-node');
    player.classList.remove('hidden');
    video.src = '/api/video/download?t=' + Date.now();
    video.load();
    // Scroll to it
    player.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ============================================================
// PIPELINE MODE SELECTOR
// Controls which pipeline stages run when Generate is clicked.
// ============================================================

function setupModeSelector() {
    const buttons = document.querySelectorAll('.mode-btn');
    if (!buttons.length) return;

    // Restore from sessionStorage if available
    const saved = sessionStorage.getItem('narratorMode');
    if (saved && MODE_CONFIG[saved]) applyMode(saved, false);
    else applyMode('both', false);

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            const mode = btn.dataset.mode;
            applyMode(mode, true);
        });
    });
}

function applyMode(mode, save = true) {
    if (!MODE_CONFIG[mode]) return;
    _pipelineMode = mode;
    if (save) sessionStorage.setItem('narratorMode', mode);

    const cfg = MODE_CONFIG[mode];

    // Update pill buttons
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Update hint text
    const hint = document.getElementById('mode-hint');
    if (hint) hint.textContent = cfg.hint;

    // Update the bottom-console mode badge
    const badge = document.getElementById('current-mode-badge');
    if (badge) {
        badge.textContent = cfg.label;
        badge.style.borderColor   = cfg.badgeColor;
        badge.style.color         = cfg.badgeColor;
        badge.style.background    = cfg.badgeColor.startsWith('#')
            ? cfg.badgeColor + '1a'
            : 'rgba(0,255,136,0.1)';
    }

    // Show / hide sidebar cards based on mode
    const cardVoice   = document.getElementById('card-voice-settings');
    const cardCloning = document.getElementById('card-voice-cloning');
    const cardEmotion = document.getElementById('card-emotion');
    const cardAudio   = document.getElementById('card-audio-pipeline');
    const cardVideo   = document.getElementById('card-video-output');

    if (mode === 'video') {
        // Video only — audio cards not needed
        if (cardVoice)   cardVoice.style.display   = 'none';
        if (cardCloning) cardCloning.style.display = 'none';
        if (cardEmotion) cardEmotion.style.display = 'none';
        if (cardAudio)   cardAudio.style.display   = 'none';
        if (cardVideo)   cardVideo.style.display   = '';
    } else if (mode === 'audio') {
        // Audio only — video output card hidden
        if (cardVoice)   cardVoice.style.display   = '';
        if (cardCloning) cardCloning.style.display = '';
        if (cardEmotion) cardEmotion.style.display = '';
        if (cardAudio)   cardAudio.style.display   = '';
        if (cardVideo)   cardVideo.style.display   = 'none';
    } else {
        // Both — show everything
        if (cardVoice)   cardVoice.style.display   = '';
        if (cardCloning) cardCloning.style.display = '';
        if (cardEmotion) cardEmotion.style.display = '';
        if (cardAudio)   cardAudio.style.display   = '';
        if (cardVideo)   cardVideo.style.display   = '';
    }

    // Update generate button label
    const btnGen = document.getElementById('btn-action-generate');
    if (btnGen) {
        if (mode === 'audio')       btnGen.textContent = '⚡ Generate Audio';
        else if (mode === 'video')  btnGen.textContent = '🎬 Generate Video';
        else                        btnGen.textContent = '⚡ Run Generation';
    }
}


// ============================================================
// VOICE PICKER MODAL
// Browses all voices with search + category filter + preview
// ============================================================

const VOICE_PICKER_DATA = [
    // US Female
    { id: 'af_sarah',    name: 'Sarah',    desc: 'Soft, intimate tone. Best for confessional narratives.',     tag: 'US Female', cat: 'us-f', avatar: '👩' },
    { id: 'af_bella',    name: 'Bella',    desc: 'Expressive with emotional range. Great for drama.',          tag: 'US Female', cat: 'us-f', avatar: '👩‍🦰' },
    { id: 'af_heart',    name: 'Heart',    desc: 'Warm and nurturing. Ideal for personal stories.',            tag: 'US Female', cat: 'us-f', avatar: '👩‍🦱' },
    { id: 'af_nicole',   name: 'Nicole',   desc: 'Clear and articulate. Works for corporate or clear narr.', tag: 'US Female', cat: 'us-f', avatar: '👩' },
    { id: 'af_sky',      name: 'Sky',      desc: 'Bright and energetic. Upbeat storytelling.',                 tag: 'US Female', cat: 'us-f', avatar: '👩‍🦳' },
    { id: 'af_alloy',    name: 'Alloy',    desc: 'Balanced and versatile. All-purpose narrator.',              tag: 'US Female', cat: 'us-f', avatar: '👩' },
    { id: 'af_aoede',    name: 'Aoede',    desc: 'Strong narrator voice. Ideal for long-form content.',       tag: 'US Female', cat: 'us-f', avatar: '🧕' },
    { id: 'af_jessica',  name: 'Jessica',  desc: 'Crisp and professional. News-style delivery.',               tag: 'US Female', cat: 'us-f', avatar: '👩‍💼' },
    { id: 'af_kore',     name: 'Kore',     desc: 'Sweet and approachable. Gentle pacing.',                     tag: 'US Female', cat: 'us-f', avatar: '👧' },
    { id: 'af_nova',     name: 'Nova',     desc: 'Energetic and punchy. Fast-paced narratives.',               tag: 'US Female', cat: 'us-f', avatar: '👩‍🚀' },
    { id: 'af_river',    name: 'River',    desc: 'Calm and measured. Meditative storytelling.',                tag: 'US Female', cat: 'us-f', avatar: '🧘‍♀️' },
    // US Male
    { id: 'am_adam',     name: 'Adam',     desc: 'Deep, authoritative. Cinematic presence.',                   tag: 'US Male',   cat: 'us-m', avatar: '👨' },
    { id: 'am_michael',  name: 'Michael',  desc: 'Natural and warm. Conversational and trustworthy.',          tag: 'US Male',   cat: 'us-m', avatar: '👨‍🦱' },
    { id: 'am_fenrir',   name: 'Fenrir',   desc: 'Rich and resonant. Epic narration.',                         tag: 'US Male',   cat: 'us-m', avatar: '🧔' },
    { id: 'am_puck',     name: 'Puck',     desc: 'Lively and playful. Energetic delivery.',                    tag: 'US Male',   cat: 'us-m', avatar: '🤵' },
    { id: 'am_echo',     name: 'Echo',     desc: 'Corporate and clean. Professional tone.',                     tag: 'US Male',   cat: 'us-m', avatar: '👨‍💼' },
    { id: 'am_eric',     name: 'Eric',     desc: 'Conversational and relaxed. Everyday storytelling.',         tag: 'US Male',   cat: 'us-m', avatar: '🧑' },
    { id: 'am_liam',     name: 'Liam',     desc: 'Friendly and approachable. Modern narrator.',                tag: 'US Male',   cat: 'us-m', avatar: '👦' },
    { id: 'am_onyx',     name: 'Onyx',     desc: 'Commanding authority. Deep and powerful.',                   tag: 'US Male',   cat: 'us-m', avatar: '🦸‍♂️' },
    { id: 'am_santa',    name: 'Santa',    desc: 'Warm and jolly. Festive or grandfatherly.',                  tag: 'US Male',   cat: 'us-m', avatar: '🎅' },
    // UK Female
    { id: 'bf_alice',    name: 'Alice',    desc: 'Gentle British accent. Soft and refined.',                   tag: 'UK Female', cat: 'uk-f', avatar: '👩‍🎓' },
    { id: 'bf_emma',     name: 'Emma',     desc: 'Elegant and polished. Classic British narrator.',            tag: 'UK Female', cat: 'uk-f', avatar: '👸' },
    { id: 'bf_isabella', name: 'Isabella', desc: 'Narrative-first. Ideal for long stories.',                  tag: 'UK Female', cat: 'uk-f', avatar: '👩‍🏫' },
    { id: 'bf_lily',     name: 'Lily',     desc: 'Bright and cheerful. Uplifting tone.',                       tag: 'UK Female', cat: 'uk-f', avatar: '🌸' },
    // UK Male
    { id: 'bm_daniel',   name: 'Daniel',   desc: 'Warm British male. Trusted and engaging.',                   tag: 'UK Male',   cat: 'uk-m', avatar: '👨‍🏫' },
    { id: 'bm_fable',    name: 'Fable',    desc: 'Dramatic and theatrical. Storytelling flair.',               tag: 'UK Male',   cat: 'uk-m', avatar: '🎭' },
    { id: 'bm_george',   name: 'George',   desc: 'Classic British gravitas. Authoritative.',                   tag: 'UK Male',   cat: 'uk-m', avatar: '👴' },
    { id: 'bm_lewis',    name: 'Lewis',    desc: 'Conversational British. Natural and modern.',                tag: 'UK Male',   cat: 'uk-m', avatar: '🧑‍💻' },
];

function initVoicePickerModal() {
    const modal    = document.getElementById('voice-picker-modal');
    const closeBtn = document.getElementById('voice-picker-close');
    const openBtn  = document.getElementById('btn-open-voice-picker');
    const grid     = document.getElementById('voice-picker-grid');
    const search   = document.getElementById('voice-picker-search');
    const pills    = document.querySelectorAll('.vpill');

    if (!modal || !openBtn) return;

    let activeFilter = 'all';

    // Build grid of cards
    function buildGrid() {
        grid.innerHTML = '';
        const currentVoice = DOM.selectVoice.value;
        VOICE_PICKER_DATA.forEach(v => {
            const card = document.createElement('div');
            card.className = `vpc-card${v.id === currentVoice ? ' active' : ''}`;
            card.dataset.voiceId  = v.id;
            card.dataset.voiceCat = v.cat;
            const isUK   = v.cat.startsWith('uk');
            const isMale = v.cat.endsWith('m');
            const tagClass = [isUK ? 'uk' : '', isMale ? 'male' : ''].filter(Boolean).join(' ');
            card.innerHTML = `
                <div class="vpc-avatar">${v.avatar}</div>
                <button class="vpc-preview-btn" data-vid="${v.id}" title="Preview ${v.name}">▶</button>
                <div class="vpc-name">${v.name}</div>
                <div class="vpc-desc">${v.desc}</div>
                <span class="vpc-tag ${tagClass}">${v.tag}</span>
            `;
            // Select voice on card click
            card.addEventListener('click', (e) => {
                if (e.target.classList.contains('vpc-preview-btn')) return;
                DOM.selectVoice.value = v.id;
                triggerSaveConfig();
                // Highlight active
                document.querySelectorAll('.vpc-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                // Also update the DOM select value
                DOM.selectVoice.dispatchEvent(new Event('change'));
                showToast(`Voice set to ${v.name}`, 'ok');
            });
            // Preview button
            card.querySelector('.vpc-preview-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                const prevBtn = e.currentTarget;
                // Stop any playing ref
                DOM.audioRefNode.pause();
                DOM.audioRefNode.src = `/api/voices/preview/${v.id}`;
                DOM.audioRefNode.play();
                prevBtn.textContent = '⏸';
                DOM.audioRefNode.onended = () => { prevBtn.textContent = '▶'; };
            });
            grid.appendChild(card);
        });
    }

    // Filter visibility
    function applyFilter() {
        const q = (search.value || '').toLowerCase();
        document.querySelectorAll('.vpc-card').forEach(card => {
            const cat    = card.dataset.voiceCat;
            const vid    = card.dataset.voiceId;
            const vdata  = VOICE_PICKER_DATA.find(v => v.id === vid);
            const matchQ = !q || vdata.name.toLowerCase().includes(q) || vdata.desc.toLowerCase().includes(q) || vdata.tag.toLowerCase().includes(q);
            const matchF = activeFilter === 'all' || cat === activeFilter;
            card.classList.toggle('hidden', !(matchQ && matchF));
        });
    }

    openBtn.addEventListener('click', () => {
        buildGrid();
        applyFilter();
        modal.classList.remove('hidden');
    });

    closeBtn.addEventListener('click', () => modal.classList.add('hidden'));
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.classList.add('hidden'); });

    search.addEventListener('input', applyFilter);

    pills.forEach(pill => {
        pill.addEventListener('click', () => {
            activeFilter = pill.dataset.filter;
            pills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            applyFilter();
        });
    });
}


// ============================================================
// VOICE SUGGESTION MODAL — AI Advisor
// Analyzes a short script summary and recommends voice, emotion,
// speed, and tone prompt settings for the sidebar.
// Uses smart local keyword analysis (no extra server call needed).
// ============================================================

// Internal suggestion engine — pure JS logic
function analyzeScriptSummaryForVoice(summaryText) {
    const t = summaryText.toLowerCase();

    // ── Voice recommendation ──────────────────────────────────
    let voice = 'af_heart'; // safe default: warm female
    let voiceReason = 'Warm, intimate tone ideal for personal first-person storytelling.';

    // Female detection keywords
    const isFemaleChar = /\b(she|her|woman|female|girl|lady|maya|lisa|sarah|anna|emma|jessica)\b/.test(t);
    const isMaleChar   = /\b(he|him|man|male|guy|narrator|paul|adam|john|mike|david|james)\b/.test(t);
    const isEpic       = /\b(epic|powerful|commanding|authoritative|deep|strong|bold)\b/.test(t);
    const isSoft       = /\b(gentle|soft|quiet|intimate|warm|confess|personal|vulnerable|whisper)\b/.test(t);
    const isCinematic  = /\b(cinematic|dramatic|film|movie|thriller|suspense|tension|buildup)\b/.test(t);
    const isUK         = /\b(british|uk|england|london|accent)\b/.test(t);
    const isConf       = /\b(confession|confessional|betrayal|trust|hurt|wound|pain|cry)\b/.test(t);

    if (isUK && isFemaleChar) {
        voice = 'bf_emma'; voiceReason = 'British English elegance fits formal or classic storytelling tone.';
    } else if (isUK) {
        voice = 'bm_fable'; voiceReason = 'UK dramatic male voice adds theatrical gravitas.';
    } else if (isEpic && !isFemaleChar) {
        voice = 'am_onyx'; voiceReason = 'Deep commanding authority — perfect for powerful, bold narration.';
    } else if (isCinematic && isFemaleChar) {
        voice = 'af_aoede'; voiceReason = 'Strong female narrator voice built for cinematic long-form content.';
    } else if (isCinematic) {
        voice = 'am_adam'; voiceReason = 'Rich cinematic depth — the signature "documentary narrator" sound.';
    } else if ((isConf || isSoft) && isFemaleChar) {
        voice = 'af_heart'; voiceReason = 'Warm and intimate — best for personal confessional delivery.';
    } else if (isConf && !isFemaleChar) {
        voice = 'am_michael'; voiceReason = 'Natural, trusted voice — relatable and emotionally grounded.';
    } else if (isSoft && !isFemaleChar) {
        voice = 'am_eric'; voiceReason = 'Conversational and relaxed — feels like a real conversation.';
    } else if (isFemaleChar) {
        voice = 'af_bella'; voiceReason = 'Expressive with good emotional range for dramatic narration.';
    } else if (isMaleChar) {
        voice = 'am_michael'; voiceReason = 'Natural and warm — versatile for most narrative styles.';
    }

    // ── Emotion preset recommendation ─────────────────────────
    let emotion = '';
    let emotionLabel = 'Custom';
    let emotionReason = '';

    if (/\b(cinematic|film|documentary|story|narrative)\b/.test(t)) {
        emotion = "Deep, serious, and emotionally controlled. Speak slowly with gravitas and natural pauses. Begin calm and reflective, gradually build tension, express genuine hurt without melodrama, become intense during betrayal scenes, then finish with quiet confidence and emotional resolution.";
        emotionLabel = '🎭 Cinematic Narrator';
        emotionReason = 'Classic cinematic narrator delivery — controlled, gravitas-filled, and emotionally precise.';
    } else if (/\b(confess|confession|personal|friend|intimate|late night)\b/.test(t)) {
        emotion = "Warm, intimate, and conversational. Speak as if confiding in a close friend late at night. Natural pace with soft emphasis on emotional words. Gentle but honest.";
        emotionLabel = '💬 Intimate Confessional';
        emotionReason = 'Confessional tone feels real and vulnerable — pulls listeners in closely.';
    } else if (/\b(cold|detach|clinical|fact|precision|flat|emotionless)\b/.test(t)) {
        emotion = "Cold, detached, and matter-of-fact. Deliver with clinical precision, no emotional coloring. The flatness itself conveys the weight of what happened.";
        emotionLabel = '🧊 Cold & Detached';
        emotionReason = 'Cold precision can be more powerful than overt emotion for some betrayal stories.';
    } else if (/\b(betray|discover|shock|truth|reveal|stun)\b/.test(t)) {
        emotion = "Start calm and trusting, then let disbelief creep in. Build to a moment of stunned silence. Let the hurt land quietly, not loudly. End with a hollow, empty resolve.";
        emotionLabel = '💔 Betrayal Discovery';
        emotionReason = 'Calibrated for shock and quiet devastation — the hallmark of a betrayal arc.';
    } else if (/\b(anger|rage|simmering|furious|bitter|resentment)\b/.test(t)) {
        emotion = "Controlled anger simmering beneath every word. Speak with precision and restraint. Each sentence is measured, deliberate. The quietness is more terrifying than shouting.";
        emotionLabel = '😤 Controlled Rage';
        emotionReason = 'Restrained anger is more menacing and cinematic than explosive rage.';
    } else if (/\b(suspense|tense|thriller|mystery|secret|reveal)\b/.test(t)) {
        emotion = "Slow, deliberate, and suspenseful. Long pauses between key phrases. Build tension with pacing alone. Let the listener lean in.";
        emotionLabel = '⏳ Slow Burn Suspense';
        emotionReason = 'Pacing and silence create suspense naturally — ideal for mystery reveals.';
    } else if (/\b(resolv|fight back|determin|confident|empow|justice|win)\b/.test(t)) {
        emotion = "Authoritative and confident. Speak with the certainty of someone who has survived. Strong, grounded, and empowered. The voice of hard-won wisdom.";
        emotionLabel = '👑 Empowered Resolution';
        emotionReason = 'Conveys the confidence of a protagonist who has overcome — the satisfying payoff.';
    } else if (/\b(nostalgic|memory|remember|past|flashback|wistful)\b/.test(t)) {
        emotion = "Nostalgic and wistful. Speak as if recalling a distant memory. Bittersweet warmth mixed with longing. Gentle, slightly faded.";
        emotionLabel = '🌅 Nostalgic Flashback';
        emotionReason = 'Memory sequences need warmth with a hint of sadness — this delivers both.';
    } else {
        // Default cinematic
        emotion = "Deep, serious, and emotionally controlled. Speak slowly with gravitas and natural pauses. Begin calm and reflective, gradually build tension, express genuine hurt without melodrama, become intense during betrayal scenes, then finish with quiet confidence and emotional resolution.";
        emotionLabel = '🎭 Cinematic Narrator';
        emotionReason = 'Default cinematic preset — an all-purpose choice for dramatic narratives.';
    }

    // ── Speed recommendation ──────────────────────────────────
    let speed = 0.9;
    let speedReason = 'Slightly slower than default — allows emotional weight to land properly.';

    if (/\b(urgent|fast|quick|intense|energetic|punchy|breathless)\b/.test(t)) {
        speed = 1.1; speedReason = 'Faster pace matches the urgency and energy of the scene.';
    } else if (/\b(slow|deliberate|meditat|calm|reflective|pause|suspense|whisper)\b/.test(t)) {
        speed = 0.85; speedReason = 'Slower delivery lets pauses breathe and tension build naturally.';
    } else if (/\b(confession|intimate|personal|vulnerable|raw)\b/.test(t)) {
        speed = 0.9; speedReason = 'Measured pace feels authentic for personal confessional narration.';
    } else if (/\b(cinematic|narrat|story|film)\b/.test(t)) {
        speed = 0.95; speedReason = 'Near-natural speed keeps the cinematic flow smooth and grounded.';
    }

    // ── Tone prompt (emotion textarea) ──────────────────────
    const tonePrompt = emotion;

    return {
        voice,
        voiceData: VOICE_PICKER_DATA.find(v => v.id === voice),
        voiceReason,
        emotionLabel,
        emotionPreset: emotion,
        emotionReason,
        speed,
        speedReason,
        tonePrompt,
    };
}

let _lastSuggestion = null;

function initVoiceSuggestModal() {
    const modal      = document.getElementById('voice-suggest-modal');
    const closeBtn   = document.getElementById('voice-suggest-close');
    const openBtn    = document.getElementById('btn-open-suggest');
    const runBtn     = document.getElementById('btn-run-suggestion');
    const applyBtn   = document.getElementById('btn-apply-suggestion');
    const againBtn   = document.getElementById('btn-suggest-again');
    const inputTA    = document.getElementById('suggest-summary-input');
    const resultsDiv = document.getElementById('suggest-results');
    const cardsDiv   = document.getElementById('suggest-cards-container');

    if (!modal || !openBtn) return;

    openBtn.addEventListener('click', () => {
        modal.classList.remove('hidden');
        resultsDiv.classList.add('hidden');
        inputTA.focus();
    });
    closeBtn.addEventListener('click', () => modal.classList.add('hidden'));
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.classList.add('hidden'); });

    runBtn.addEventListener('click', async () => {
        const summary = inputTA.value.trim();
        if (!summary) {
            inputTA.focus();
            inputTA.style.borderColor = 'var(--danger)';
            setTimeout(() => inputTA.style.borderColor = '', 1200);
            return;
        }

        // Show loading state
        runBtn.classList.add('loading');
        runBtn.disabled = true;
        document.getElementById('suggest-btn-label').textContent = 'Analyzing…';
        resultsDiv.classList.add('hidden');

        // Small artificial delay for UX polish
        await new Promise(r => setTimeout(r, 800));

        const suggestion = analyzeScriptSummaryForVoice(summary);
        _lastSuggestion = suggestion;

        // Render result cards
        const vd = suggestion.voiceData || { name: suggestion.voice, avatar: '🎙', tag: '—' };
        cardsDiv.innerHTML = `
            <div class="suggest-card">
                <div class="suggest-card-icon">${vd.avatar || '🎙'}</div>
                <div class="suggest-card-body">
                    <div class="suggest-card-label">Recommended Voice</div>
                    <div class="suggest-card-value">${vd.name} <span style="font-size:0.68rem;color:var(--text-muted);font-weight:500;">(${suggestion.voice})</span></div>
                    <div class="suggest-card-reason">${suggestion.voiceReason}</div>
                </div>
            </div>
            <div class="suggest-card emotion-card">
                <div class="suggest-card-icon">🎭</div>
                <div class="suggest-card-body">
                    <div class="suggest-card-label">Emotion Preset</div>
                    <div class="suggest-card-value">${suggestion.emotionLabel}</div>
                    <div class="suggest-card-reason">${suggestion.emotionReason}</div>
                </div>
            </div>
            <div class="suggest-card speed-card">
                <div class="suggest-card-icon">⏱</div>
                <div class="suggest-card-body">
                    <div class="suggest-card-label">Narration Speed</div>
                    <div class="suggest-card-value">${suggestion.speed}×</div>
                    <div class="suggest-card-reason">${suggestion.speedReason}</div>
                </div>
            </div>
            <div class="suggest-card" style="border-color:rgba(163,163,163,0.15);">
                <div class="suggest-card-icon">📝</div>
                <div class="suggest-card-body">
                    <div class="suggest-card-label">Tone Prompt Preview</div>
                    <div class="suggest-card-reason" style="font-style:italic;color:var(--text-grey);">"${suggestion.tonePrompt.slice(0, 140)}…"</div>
                </div>
            </div>
        `;

        resultsDiv.classList.remove('hidden');

        // Reset button
        runBtn.classList.remove('loading');
        runBtn.disabled = false;
        document.getElementById('suggest-btn-label').textContent = '🤖 Generate Suggestions';
    });

    applyBtn.addEventListener('click', () => {
        if (!_lastSuggestion) return;

        // Apply voice
        DOM.selectVoice.value = _lastSuggestion.voice;
        DOM.selectVoice.dispatchEvent(new Event('change'));

        // Apply speed
        DOM.sliderSpeed.value = _lastSuggestion.speed;
        DOM.lblSpeed.textContent = _lastSuggestion.speed + 'x';

        // Apply emotion
        DOM.txtEmotion.value = _lastSuggestion.emotionPreset;
        syncEmotionDropdown(_lastSuggestion.emotionPreset);

        // Persist to server
        triggerSaveConfig();

        showToast(`Settings applied: ${_lastSuggestion.voiceData?.name || _lastSuggestion.voice} — ${_lastSuggestion.emotionLabel}`, 'ok');
        modal.classList.add('hidden');
    });

    againBtn.addEventListener('click', () => {
        resultsDiv.classList.add('hidden');
        inputTA.focus();
        inputTA.select();
    });
}

// ── Bootstrap both modals after DOM is ready ─────────────────
document.addEventListener('DOMContentLoaded', () => {
    initVoicePickerModal();
    initVoiceSuggestModal();
    initHistoryDrawer();
    initStatsDrawer();
});


// ============================================================
// GENERATION HISTORY DRAWER
// Loads every archived generation from /api/history and renders
// a rich card list with: inline audio player, tags, rename,
// download (WAV / video), and individual delete.
// ============================================================

let _historyEntries    = [];   // full list from server
let _historyAudioEl    = null; // single shared <audio> for history playback
let _historyPlayingId  = null; // currently playing entry id

function _historyFmt(secs) {
    if (!secs) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s.toString().padStart(2,'0')}`;
}

function _historyFormatDate(iso) {
    try {
        const d = new Date(iso);
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
               ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch(_) { return iso || ''; }
}

function _historyFormatBytes(b) {
    if (!b) return '';
    if (b < 1024 * 1024) return `${(b/1024).toFixed(0)} KB`;
    return `${(b/1024/1024).toFixed(1)} MB`;
}

async function loadHistory() {
    const data = await apiFetch('/api/history');
    if (!data) return;
    _historyEntries = data.entries || [];
    renderHistoryEntries(_historyEntries);
    // Update toolbar badge
    const badge = document.getElementById('history-count-badge');
    if (badge) badge.textContent = _historyEntries.length > 0 ? _historyEntries.length : '';
}

function renderHistoryEntries(entries) {
    const list    = document.getElementById('history-list');
    const empty   = document.getElementById('history-empty');
    if (!list) return;

    list.innerHTML = '';

    if (!entries || entries.length === 0) {
        if (empty) empty.classList.remove('hidden');
        return;
    }
    if (empty) empty.classList.add('hidden');

    entries.forEach(entry => {
        const card = buildHistoryCard(entry);
        list.appendChild(card);
    });
}

function buildHistoryCard(entry) {
    const wrap = document.createElement('div');
    wrap.className = `history-entry${entry.has_video ? ' has-video' : ''}`;
    wrap.dataset.entryId = entry.id;

    const voiceLabel = KOKORO_VOICE_LABELS[entry.voice] || entry.voice || '—';
    const speedLabel = entry.speed ? `${entry.speed}x` : '1.0x';
    const dateLabel  = _historyFormatDate(entry.created);
    const audioSize  = _historyFormatBytes(entry.audio_size);

    wrap.innerHTML = `
        <div class="history-entry-top">
            <div class="history-entry-row1">
                <input class="history-title-edit" type="text" value="${escapeHtml(entry.title || entry.id)}" title="Click to rename">
                <button class="history-entry-del-btn" title="Delete this generation">🗑</button>
            </div>
            <div class="history-entry-meta">
                <span class="hist-tag voice">🎙 ${voiceLabel.split(' (')[0]}</span>
                <span class="hist-tag speed">⏱ ${speedLabel}</span>
                ${entry.duration ? `<span class="hist-tag dur">⏳ ${entry.duration}</span>` : ''}
                ${audioSize ? `<span class="hist-tag dur">${audioSize}</span>` : ''}
                ${entry.has_video ? `<span class="hist-tag video-tag">🎬 +Video</span>` : ''}
                <span class="hist-tag date-tag">${dateLabel}</span>
            </div>
            <div class="history-mini-player">
                <button class="hist-play-btn" data-entry-id="${entry.id}">▶</button>
                <div class="hist-progress-track" data-entry-id="${entry.id}">
                    <div class="hist-progress-fill" id="hist-fill-${entry.id}"></div>
                </div>
                <span class="hist-time-label" id="hist-time-${entry.id}">0:00</span>
            </div>
        </div>
        <div class="history-entry-actions">
            <a class="hist-dl-btn" href="/api/history/${entry.id}/audio?fmt=wav" download="${entry.id}.wav" title="Download WAV">⬇ WAV</a>
            ${entry.has_video ? `<a class="hist-dl-btn video-dl" href="/api/history/${entry.id}/video" download="${entry.id}.mp4" title="Download MP4">🎬 MP4</a>` : ''}
        </div>
    `;

    // ── Play / pause button ──────────────────────────────────
    const playBtn  = wrap.querySelector('.hist-play-btn');
    const fill     = wrap.querySelector('.hist-progress-fill');
    const timeEl   = wrap.querySelector('.hist-time-label');
    const track    = wrap.querySelector('.hist-progress-track');

    playBtn.addEventListener('click', () => {
        if (!_historyAudioEl) {
            _historyAudioEl = document.createElement('audio');
            _historyAudioEl.preload = 'none';
            document.body.appendChild(_historyAudioEl);
        }

        // If already playing this one → pause it
        if (_historyPlayingId === entry.id && !_historyAudioEl.paused) {
            _historyAudioEl.pause();
            playBtn.textContent = '▶';
            playBtn.classList.remove('playing');
            return;
        }

        // Stop current if different entry
        if (_historyPlayingId && _historyPlayingId !== entry.id) {
            _historyAudioEl.pause();
            // Reset old play button
            const oldBtn = document.querySelector(`.hist-play-btn[data-entry-id="${_historyPlayingId}"]`);
            if (oldBtn) { oldBtn.textContent = '▶'; oldBtn.classList.remove('playing'); }
            const oldFill = document.getElementById(`hist-fill-${_historyPlayingId}`);
            if (oldFill) oldFill.style.width = '0%';
            const oldTime = document.getElementById(`hist-time-${_historyPlayingId}`);
            if (oldTime) oldTime.textContent = '0:00';
        }

        _historyPlayingId = entry.id;
        _historyAudioEl.src = `/api/history/${entry.id}/audio`;
        _historyAudioEl.play();
        playBtn.textContent = '⏸';
        playBtn.classList.add('playing');

        // Progress update
        _historyAudioEl.ontimeupdate = () => {
            if (!_historyAudioEl.duration) return;
            const pct = (_historyAudioEl.currentTime / _historyAudioEl.duration) * 100;
            fill.style.width = pct + '%';
            timeEl.textContent = _historyFmt(_historyAudioEl.currentTime);
        };

        _historyAudioEl.onended = () => {
            playBtn.textContent = '▶';
            playBtn.classList.remove('playing');
            fill.style.width = '0%';
            timeEl.textContent = '0:00';
            _historyPlayingId = null;
        };

        _historyAudioEl.onpause = () => {
            if (_historyPlayingId === entry.id) {
                playBtn.textContent = '▶';
                playBtn.classList.remove('playing');
            }
        };
    });

    // Click progress track to seek
    track.addEventListener('click', (e) => {
        if (!_historyAudioEl || _historyPlayingId !== entry.id || !_historyAudioEl.duration) return;
        const rect = track.getBoundingClientRect();
        const pct  = (e.clientX - rect.left) / rect.width;
        _historyAudioEl.currentTime = pct * _historyAudioEl.duration;
    });

    // ── Rename on blur ──────────────────────────────────────
    const titleInput = wrap.querySelector('.history-title-edit');
    titleInput.addEventListener('blur', async () => {
        const newTitle = titleInput.value.trim();
        if (!newTitle || newTitle === entry.title) return;
        const res = await apiFetch(`/api/history/${entry.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle }),
        });
        if (res && res.ok) {
            entry.title = newTitle;
            showToast('Title saved', 'ok');
        }
    });
    titleInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); titleInput.blur(); }
        if (e.key === 'Escape') { titleInput.value = entry.title; titleInput.blur(); }
    });

    // ── Delete button ───────────────────────────────────────
    const delBtn = wrap.querySelector('.history-entry-del-btn');
    delBtn.addEventListener('click', async () => {
        if (!confirm(`Delete "${entry.title || entry.id}"?\nThis will permanently remove the audio${entry.has_video ? ' and video' : ''} file.`)) return;

        // Stop audio if playing this one
        if (_historyPlayingId === entry.id && _historyAudioEl) {
            _historyAudioEl.pause();
            _historyPlayingId = null;
        }

        const res = await apiFetch(`/api/history/${entry.id}`, { method: 'DELETE' });
        if (res && res.ok) {
            wrap.style.opacity = '0';
            wrap.style.transform = 'translateX(20px)';
            wrap.style.transition = 'all 0.2s ease';
            setTimeout(() => {
                wrap.remove();
                // Reload fully to keep state accurate
                loadHistory();
            }, 200);
            showToast('Entry deleted', 'ok');
        } else {
            showToast('Failed to delete entry', 'err');
        }
    });

    return wrap;
}

function initHistoryDrawer() {
    const openBtn  = document.getElementById('btn-open-history');
    const drawer   = document.getElementById('history-drawer');
    const backdrop = document.getElementById('history-backdrop');
    const closeBtn = document.getElementById('history-drawer-close');
    const search   = document.getElementById('history-search');

    if (!openBtn || !drawer) return;

    function openDrawer() {
        drawer.classList.remove('hidden');
        backdrop.classList.remove('hidden');
        loadHistory();
    }

    function closeDrawer() {
        drawer.classList.add('hidden');
        backdrop.classList.add('hidden');
        // Pause audio on close
        if (_historyAudioEl && !_historyAudioEl.paused) {
            _historyAudioEl.pause();
        }
    }

    openBtn.addEventListener('click', openDrawer);
    closeBtn.addEventListener('click', closeDrawer);
    backdrop.addEventListener('click', closeDrawer);

    // Keyboard ESC to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !drawer.classList.contains('hidden')) closeDrawer();
    });

    // Search / filter
    search.addEventListener('input', () => {
        const q = search.value.toLowerCase();
        if (!q) {
            renderHistoryEntries(_historyEntries);
            return;
        }
        const filtered = _historyEntries.filter(e =>
            (e.title || '').toLowerCase().includes(q) ||
            (e.voice || '').toLowerCase().includes(q) ||
            (KOKORO_VOICE_LABELS[e.voice] || '').toLowerCase().includes(q)
        );
        renderHistoryEntries(filtered);
    });

    // Auto-refresh history badge on page load
    loadHistory();
}

// ── B-Roll Review Drawer (70% Wide) ──────────────────────────

function setupReviewDrawer() {
    const openBtn  = document.getElementById('btn-open-review-drawer');
    const closeBtn = document.getElementById('review-drawer-close');
    const drawer   = document.getElementById('review-drawer');
    const backdrop = document.getElementById('review-backdrop');

    if (!drawer || !backdrop) return;

    function openDrawer() {
        drawer.classList.remove('hidden');
        backdrop.classList.remove('hidden');
    }

    function closeDrawer() {
        drawer.classList.add('hidden');
        backdrop.classList.add('hidden');
    }

    if (openBtn) openBtn.addEventListener('click', openDrawer);
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
    backdrop.addEventListener('click', closeDrawer);

    // Keyboard ESC to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !drawer.classList.contains('hidden')) {
            closeDrawer();
        }
    });
}


// ── Statistics Drawer (📊 Stats) ─────────────────────────────

function initStatsDrawer() {
    const openBtn  = document.getElementById('btn-open-stats');
    const drawer   = document.getElementById('stats-drawer');
    const backdrop = document.getElementById('stats-backdrop');
    const closeBtn = document.getElementById('stats-drawer-close');

    if (!openBtn || !drawer) return;

    function openDrawer() {
        drawer.classList.remove('hidden');
        backdrop.classList.remove('hidden');
        loadStats();
    }

    function closeDrawer() {
        drawer.classList.add('hidden');
        backdrop.classList.add('hidden');
    }

    openBtn.addEventListener('click', openDrawer);
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
    backdrop.addEventListener('click', closeDrawer);

    // Keyboard ESC to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !drawer.classList.contains('hidden')) {
            closeDrawer();
        }
    });
}

async function loadStats() {
    try {
        const r = await fetch('/api/video/stats');
        if (!r.ok) throw new Error('Failed to fetch stats');
        const data = await r.json();

        // 1. Populate Groq summary
        document.getElementById('stat-groq-total').textContent = data.groq.total_requests || 0;
        document.getElementById('stat-groq-success').textContent = data.groq.successful_requests || 0;
        document.getElementById('stat-groq-limits').textContent = data.groq.rate_limits_hit || 0;

        // 2. Populate Groq keys status list
        const keysList = document.getElementById('stats-keys-list');
        keysList.innerHTML = '';
        
        const keysMap = data.groq.keys || {};
        const keyIds = Object.keys(keysMap);
        if (keyIds.length === 0) {
            keysList.innerHTML = `<div style="font-size: 0.8rem; color: rgba(255,255,255,0.4); text-align: center; padding: 8px;">No keys used yet. Run a generation!</div>`;
        } else {
            keyIds.forEach((kid, idx) => {
                const kinfo = keysMap[kid];
                const statusColor = kinfo.status.includes('rate_limited') ? '#f5222d' : '#52c41a';
                const keyRow = document.createElement('div');
                keyRow.style = "display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.15); padding: 8px 12px; border-radius: 6px; font-size: 0.8rem;";
                
                // Format last used date
                let lastUsedStr = 'Never';
                if (kinfo.last_used) {
                    try {
                        const date = new Date(kinfo.last_used);
                        lastUsedStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    } catch(e) {}
                }

                keyRow.innerHTML = `
                    <div>
                        <div style="font-weight: 600; color: #fff;">Key #${idx + 1}: <span style="font-family: monospace; color: rgba(255,255,255,0.7);">${kinfo.prefix}</span></div>
                        <div style="font-size: 0.7rem; color: rgba(255,255,255,0.4); margin-top: 2px;">Last call: ${lastUsedStr}</div>
                    </div>
                    <div style="text-align: right;">
                        <span style="display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; background: rgba(${statusColor === '#52c41a' ? '82,196,26' : '245,34,45'}, 0.15); color: ${statusColor};">${kinfo.status.toUpperCase()}</span>
                        <div style="font-size: 0.7rem; color: rgba(255,255,255,0.5); margin-top: 2px;">Calls: ${kinfo.requests}</div>
                    </div>
                `;
                keysList.appendChild(keyRow);
            });
        }

        // 3. Populate general resources
        document.getElementById('stat-word-count').textContent = data.script.word_count || 0;
        document.getElementById('stat-segments-count').textContent = data.script.segments_count || 0;
        document.getElementById('stat-segments-size').textContent = `${data.script.segments_size_mb || 0} MB`;
        document.getElementById('stat-cache-size').textContent = `${data.script.cache_size_mb || 0} MB`;

        // 4. Populate stock status
        const stockEl = document.getElementById('stat-stock-status');
        const activeApis = [];
        if (data.apis.pexels_loaded) activeApis.push('Pexels');
        if (data.apis.pixabay_loaded) activeApis.push('Pixabay');
        if (data.apis.coverr_loaded) activeApis.push('Coverr');
        
        if (activeApis.length > 0) {
            stockEl.textContent = activeApis.join(' / ');
            stockEl.style.color = '#52c41a';
        } else {
            stockEl.textContent = 'None Loaded';
            stockEl.style.color = '#f5222d';
        }

    } catch (err) {
        console.error('Stats load error:', err);
    }
}
