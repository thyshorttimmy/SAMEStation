const state = {
  localAlerts: [],
  serverAlerts: [],
  activity: [],
  serverActivity: [],
  audioContext: null,
  audioWorkletNode: null,
  audioWorkletModulePromise: null,
  currentSourceNode: null,
  mediaElementSource: null,
  currentMode: "idle",
  worker: null,
  serverStatus: null,
  eventsSource: null,
  eventsReconnectTimer: null,
  lastAlertsSignature: "",
  sameCodeMap: {},
  serverLiveAudioEnabled: false,
  serverLiveConnectPromise: null,
  autoLivePlaybackOnAlert: false,
  autoLivePlaybackArmedRecordId: null,
  autoLivePlaybackStartedByAlert: false,
  autoLivePlaybackActiveRecordId: null,
};

const elements = {
  decoderState: document.querySelector("#decoder-state"),
  sourceState: document.querySelector("#source-state"),
  serverMonitorStatus: document.querySelector("#server-monitor-status"),
  alertCount: document.querySelector("#alert-count"),
  fileInput: document.querySelector("#file-input"),
  decodeFileButton: document.querySelector("#decode-file-button"),
  urlInput: document.querySelector("#url-input"),
  decodeUrlButton: document.querySelector("#decode-url-button"),
  startStreamButton: document.querySelector("#start-stream-button"),
  stopStreamButton: document.querySelector("#stop-stream-button"),
  deviceSelect: document.querySelector("#device-select"),
  preRollSeconds: document.querySelector("#pre-roll-seconds"),
  maxRecordSeconds: document.querySelector("#max-record-seconds"),
  refreshDevicesButton: document.querySelector("#refresh-devices-button"),
  startDeviceButton: document.querySelector("#start-device-button"),
  stopDeviceButton: document.querySelector("#stop-device-button"),
  clearResultsButton: document.querySelector("#clear-results-button"),
  alertsList: document.querySelector("#alerts-list"),
  activityLog: document.querySelector("#activity-log"),
  streamAudio: document.querySelector("#stream-audio"),
  startLiveMonitorButton: document.querySelector("#start-live-monitor-button"),
  stopLiveMonitorButton: document.querySelector("#stop-live-monitor-button"),
  autoLivePlaybackOnAlert: document.querySelector("#auto-live-playback-on-alert"),
  ntfyEnabled: document.querySelector("#ntfy-enabled"),
  ntfyBaseUrl: document.querySelector("#ntfy-base-url"),
  ntfyTopic: document.querySelector("#ntfy-topic"),
  ntfyPriority: document.querySelector("#ntfy-priority"),
  ntfyTags: document.querySelector("#ntfy-tags"),
  ntfyClickUrl: document.querySelector("#ntfy-click-url"),
  ntfyNotifyOnDetected: document.querySelector("#ntfy-notify-on-detected"),
  ntfyNotifyOnCompleted: document.querySelector("#ntfy-notify-on-completed"),
  monitorCopy: document.querySelector("#monitor-copy"),
  rssLink: document.querySelector("#rss-link"),
};

boot();

async function boot() {
  state.worker = new Worker("./decoder-worker.js", { type: "module" });
  state.worker.addEventListener("message", handleWorkerMessage);

  elements.decodeFileButton.addEventListener("click", handleDecodeFile);
  elements.decodeUrlButton.addEventListener("click", handleDecodeUrlFile);
  elements.startStreamButton.addEventListener("click", handleStartStream);
  elements.stopStreamButton.addEventListener("click", stopBrowserStreamCapture);
  elements.refreshDevicesButton.addEventListener("click", handleRefreshDevices);
  elements.startDeviceButton.addEventListener("click", handleStartServerMonitor);
  elements.stopDeviceButton.addEventListener("click", handleStopServerMonitor);
  elements.startLiveMonitorButton.addEventListener("click", handleStartServerLiveAudio);
  elements.stopLiveMonitorButton.addEventListener("click", handleStopServerLiveAudio);
  elements.clearResultsButton.addEventListener("click", handleClearAlerts);
  elements.deviceSelect.addEventListener("change", persistServerSettings);
  elements.preRollSeconds.addEventListener("change", persistServerSettings);
  elements.maxRecordSeconds.addEventListener("change", persistServerSettings);
  elements.autoLivePlaybackOnAlert.addEventListener("change", persistServerSettings);
  elements.ntfyEnabled.addEventListener("change", persistServerSettings);
  elements.ntfyBaseUrl.addEventListener("change", persistServerSettings);
  elements.ntfyTopic.addEventListener("change", persistServerSettings);
  elements.ntfyPriority.addEventListener("change", persistServerSettings);
  elements.ntfyTags.addEventListener("change", persistServerSettings);
  elements.ntfyClickUrl.addEventListener("change", persistServerSettings);
  elements.ntfyNotifyOnDetected.addEventListener("change", persistServerSettings);
  elements.ntfyNotifyOnCompleted.addEventListener("change", persistServerSettings);

  await Promise.all([loadSameCodeMap(), handleRefreshDevices(true)]);
  connectServerEvents();
  render();
}

function handleWorkerMessage(event) {
  const { type } = event.data;

  if (type === "offline-results") {
    state.localAlerts = event.data.alerts.map((alert) => ({
      ...augmentAlertLocations(alert),
      sourceKind: "browser-offline",
      sourceLabel: event.data.sourceLabel,
      detectedAt: new Date().toISOString(),
    }));
    addActivity(
      "Offline decode finished",
      `${event.data.alerts.length} header${event.data.alerts.length === 1 ? "" : "s"} decoded from ${event.data.sourceLabel}.`,
      "info",
    );
    setDecoderState(event.data.alerts.length ? "Decoded" : "No header found");
    render();
    return;
  }

  if (type === "stream-results") {
    state.localAlerts = event.data.alerts.map((alert) => ({
      ...augmentAlertLocations(alert),
      sourceKind: "browser-stream",
      sourceLabel: elements.urlInput.value.trim() || "Live stream",
      detectedAt: new Date().toISOString(),
    }));
    setDecoderState(event.data.alerts.length ? "Monitoring / matched" : "Monitoring");
    render();
    return;
  }

  if (type === "status") {
    addActivity("Decoder status", event.data.message, event.data.level || "info");
    render();
    return;
  }

  if (type === "error") {
    addActivity("Decoder error", event.data.message, "error");
    setDecoderState("Error");
    render();
  }
}

async function handleDecodeFile() {
  const file = elements.fileInput.files?.[0];
  if (!file) {
    addActivity("No file selected", "Choose an audio file first.", "warn");
    render();
    return;
  }

  setDecoderState("Decoding file");
  elements.sourceState.textContent = file.name;

  try {
    const arrayBuffer = await file.arrayBuffer();
    await decodeArrayBuffer(arrayBuffer, file.name);
  } catch (error) {
    failWithError("Unable to decode the selected file.", error);
  }
}

async function handleDecodeUrlFile() {
  const rawUrl = elements.urlInput.value.trim();
  if (!rawUrl) {
    addActivity("Missing URL", "Enter an audio file URL first.", "warn");
    render();
    return;
  }

  setDecoderState("Fetching URL");
  elements.sourceState.textContent = "Remote file";

  try {
    const response = await fetch(proxyUrl(rawUrl));
    if (!response.ok) {
      throw new Error(`Remote fetch failed with ${response.status}.`);
    }
    const arrayBuffer = await response.arrayBuffer();
    await decodeArrayBuffer(arrayBuffer, rawUrl);
  } catch (error) {
    failWithError("Unable to fetch or decode the remote file URL.", error);
  }
}

async function handleStartStream() {
  const rawUrl = elements.urlInput.value.trim();
  if (!rawUrl) {
    addActivity("Missing URL", "Enter a live stream URL first.", "warn");
    render();
    return;
  }

  try {
    state.serverLiveAudioEnabled = false;
    disconnectServerDeviceMonitorAudio();
    await stopBrowserStreamCapture();
    await ensureAudioPipeline();
    await ensureCaptureWorklet();

    elements.streamAudio.src = proxyUrl(rawUrl);
    elements.streamAudio.crossOrigin = "anonymous";
    elements.streamAudio.muted = false;
    await elements.streamAudio.play();

    if (!state.mediaElementSource) {
      state.mediaElementSource = state.audioContext.createMediaElementSource(elements.streamAudio);
    }

      connectSource(state.mediaElementSource, true, true);
    state.worker.postMessage({ type: "start-stream", sourceLabel: rawUrl });
    state.currentMode = "browser-stream";
    elements.sourceState.textContent = "Live stream";
    elements.monitorCopy.textContent = rawUrl;
    setDecoderState("Monitoring");
    addActivity("Live stream started", `Monitoring ${rawUrl}`, "info");
    render();
  } catch (error) {
    failWithError("Unable to start live stream monitoring.", error);
  }
}

async function handleRefreshDevices(silent = false) {
  try {
    const response = await fetch("/api/devices");
    if (!response.ok) {
      throw new Error(`Device request failed with ${response.status}.`);
    }
    const payload = await response.json();
    renderDeviceOptions(payload.devices || []);
    if (!silent) {
      addActivity("Server device list refreshed", "Available server-side input devices were updated.", "info");
    }
    render();
  } catch (error) {
    if (!silent) {
      failWithError("Unable to refresh server audio devices.", error);
    }
  }
}

async function handleStartServerMonitor() {
  try {
    const deviceId = Number(elements.deviceSelect.value);
    await persistServerSettings(true);
    const response = await fetch("/api/monitor/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        deviceId,
        preRollSeconds: Number(elements.preRollSeconds.value || 10),
        maxRecordSeconds: Number(elements.maxRecordSeconds.value || 180),
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `Monitor start failed with ${response.status}.`);
    }
    const payload = await response.json();
    if (payload.monitor) {
      applyServerStatus(payload.monitor);
    }
    addActivity("Server monitor started", currentServerDeviceLabel(), "info");
    render();
  } catch (error) {
    failWithError("Unable to start the server monitor.", error);
  }
}

async function handleStartServerLiveAudio() {
  if (!(state.serverStatus && state.serverStatus.running)) {
    addActivity("Server monitor not running", "Start the server audio monitor before listening to the device feed.", "warn");
    render();
    return;
  }

    try {
      state.serverLiveAudioEnabled = true;
      state.autoLivePlaybackStartedByAlert = false;
      state.autoLivePlaybackActiveRecordId = null;
      if (state.currentMode === "browser-stream") {
        await stopBrowserStreamCapture();
      }
    await connectServerDeviceMonitorAudio();
    elements.monitorCopy.textContent = `Listening live to ${state.serverStatus.deviceName || "server audio device"}.`;
    addActivity("Server live monitor started", state.serverStatus.deviceName || "Server audio device", "info");
    render();
  } catch (error) {
    failWithError("Unable to start server live monitoring.", error);
  }
}

function handleStopServerLiveAudio() {
  state.serverLiveAudioEnabled = false;
  state.autoLivePlaybackStartedByAlert = false;
  state.autoLivePlaybackActiveRecordId = null;
  disconnectServerDeviceMonitorAudio();
  elements.monitorCopy.textContent = state.serverStatus?.running
    ? `Server monitor running on ${state.serverStatus.deviceName || "server audio device"}, audio playback stopped.`
    : "Waiting for a stream or server-side device monitor.";
  addActivity("Server live monitor stopped", "Live playback of the server device was stopped.", "info");
  render();
}

async function handleClearAlerts() {
  try {
    const response = await fetch("/api/alerts/clear", { method: "POST" });
    if (!response.ok) {
      throw new Error(`Clear alerts failed with ${response.status}.`);
    }
    const payload = await response.json();
    state.localAlerts = [];
    state.activity = [];
    state.serverAlerts = [];
    state.serverActivity = [];
    state.lastAlertsSignature = "";
    if (payload.monitor) {
      applyServerStatus(payload.monitor);
    }
    addActivity("Alerts cleared", "Server and browser alert history were cleared.", "info");
    render();
  } catch (error) {
    failWithError("Unable to clear alerts.", error);
  }
}

async function handleStopServerMonitor() {
  try {
    state.serverLiveAudioEnabled = false;
    state.autoLivePlaybackStartedByAlert = false;
    state.autoLivePlaybackActiveRecordId = null;
    disconnectServerDeviceMonitorAudio();
    const response = await fetch("/api/monitor/stop", { method: "POST" });
    if (!response.ok) {
      throw new Error(`Monitor stop failed with ${response.status}.`);
    }
    const payload = await response.json();
    if (payload.monitor) {
      applyServerStatus(payload.monitor);
    }
    addActivity("Server monitor stopped", "The always-on device monitor was stopped.", "info");
    render();
  } catch (error) {
    failWithError("Unable to stop the server monitor.", error);
  }
}

function connectServerEvents() {
  if (state.eventsSource) {
    state.eventsSource.close();
  }
  if (state.eventsReconnectTimer) {
    window.clearTimeout(state.eventsReconnectTimer);
    state.eventsReconnectTimer = null;
  }

  const eventsSource = new EventSource("/api/events");
  state.eventsSource = eventsSource;

  eventsSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.status) {
        applyServerStatus(payload.status);
        render();
      }
    } catch (error) {
      console.warn("Unable to parse server event payload.", error);
    }
  };

  eventsSource.onerror = () => {
    if (state.eventsSource === eventsSource) {
      state.eventsSource.close();
      state.eventsSource = null;
    }
    if (!state.eventsReconnectTimer) {
      state.eventsReconnectTimer = window.setTimeout(() => {
        state.eventsReconnectTimer = null;
        connectServerEvents();
      }, 2000);
    }
  };
}

function applyServerStatus(payload) {
  state.serverStatus = payload;
  state.serverAlerts = (payload.alerts || []).map((alert) => augmentAlertLocations(alert));
  state.serverActivity = payload.activity || [];
  applyServerSettings(payload.settings || payload);
  elements.serverMonitorStatus.textContent = payload.running ? "Running" : "Stopped";
  elements.rssLink.href = "/alerts.xml";

  if (payload.running) {
    elements.sourceState.textContent = payload.deviceName || "Server audio device";
    setDecoderState(payload.currentRecording ? "Recording alert" : "Server monitoring");
    if (payload.currentRecording?.recordId) {
      maybeAutoStartLivePlayback(payload.currentRecording.recordId);
    } else {
      maybeAutoStopLivePlaybackAfterAlert(state.serverAlerts);
    }
    elements.monitorCopy.textContent = payload.currentRecording
      ? `Recording active: ${payload.currentRecording.rawHeader}`
      : state.serverLiveAudioEnabled
        ? `Listening live to ${payload.deviceName || "server audio device"}.`
        : `Server monitor running on ${payload.deviceName || "server audio device"}, audio playback stopped.`;
    if (state.serverLiveAudioEnabled && state.currentMode !== "server-device" && !state.serverLiveConnectPromise) {
      connectServerDeviceMonitorAudio().catch((error) => {
        failWithError("Unable to keep server live monitoring active.", error);
      });
    } else if (!state.serverLiveAudioEnabled) {
      disconnectServerDeviceMonitorAudio();
    }
    return;
  }

  if (state.currentMode !== "browser-stream") {
    elements.monitorCopy.textContent = "Waiting for a stream or server-side device monitor.";
    if (!state.localAlerts.length) {
      elements.sourceState.textContent = "None";
      setDecoderState("Idle");
    }
    disconnectServerDeviceMonitorAudio();
  }
}

async function loadSameCodeMap() {
  try {
    const response = await fetch("/api/same-codes");
    if (!response.ok) {
      throw new Error(`SAME code map request failed with ${response.status}.`);
    }
    const payload = await response.json();
    state.sameCodeMap = payload.codes || {};
  } catch (error) {
    addActivity("County lookup unavailable", error instanceof Error ? error.message : String(error), "warn");
  }
}

async function persistServerSettings(silent = true) {
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        deviceId: Number(elements.deviceSelect.value),
        preRollSeconds: Number(elements.preRollSeconds.value || 10),
        maxRecordSeconds: Number(elements.maxRecordSeconds.value || 180),
        autoLivePlaybackOnAlert: elements.autoLivePlaybackOnAlert.checked,
        ntfyEnabled: elements.ntfyEnabled.checked,
        ntfyBaseUrl: elements.ntfyBaseUrl.value.trim(),
        ntfyTopic: elements.ntfyTopic.value.trim(),
        ntfyPriority: elements.ntfyPriority.value,
        ntfyTags: elements.ntfyTags.value.trim(),
        ntfyClickUrl: elements.ntfyClickUrl.value.trim(),
        ntfyNotifyOnDetected: elements.ntfyNotifyOnDetected.checked,
        ntfyNotifyOnCompleted: elements.ntfyNotifyOnCompleted.checked,
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `Settings save failed with ${response.status}.`);
    }
    const payload = await response.json();
    applyServerSettings(payload.settings);
    if (!silent) {
      addActivity("Settings saved", "Server-side monitor settings were updated.", "info");
      render();
    }
  } catch (error) {
    if (!silent) {
      failWithError("Unable to save server settings.", error);
    }
  }
}

async function ensureAudioPipeline() {
  if (!state.audioContext) {
    state.audioContext = new AudioContext();
  }

  if (state.audioContext.state === "suspended") {
    await state.audioContext.resume();
  }
}

async function ensureCaptureWorklet() {
  await ensureAudioPipeline();

  if (!state.audioWorkletModulePromise) {
    state.audioWorkletModulePromise = state.audioContext.audioWorklet.addModule("./audio-capture-worklet.js");
  }

  try {
    await state.audioWorkletModulePromise;
  } catch (error) {
    state.audioWorkletModulePromise = null;
    throw error;
  }

  if (!state.audioWorkletNode) {
    state.audioWorkletNode = new AudioWorkletNode(state.audioContext, "audio-capture-processor");
    state.audioWorkletNode.port.onmessage = (event) => {
      const samples = event.data.samples;
      state.worker.postMessage(
        {
          type: "append-stream-samples",
          samples,
          sampleRate: state.audioContext.sampleRate,
        },
        [samples.buffer],
      );
    };
  }
}

function connectSource(sourceNode, alsoMonitorOutput, captureInput = true) {
  disconnectCurrentSource();
  state.currentSourceNode = sourceNode;
  if (captureInput) {
    if (!state.audioWorkletNode) {
      throw new Error("Capture worklet is not ready.");
    }
    sourceNode.connect(state.audioWorkletNode);
  }
  if (alsoMonitorOutput) {
    sourceNode.connect(state.audioContext.destination);
  }
}

function disconnectCurrentSource() {
  if (!state.currentSourceNode) {
    return;
  }

  try {
    state.currentSourceNode.disconnect();
  } catch {
    // Some browser nodes throw when already disconnected.
  }
  state.currentSourceNode = null;
}

async function stopBrowserStreamCapture() {
  disconnectCurrentSource();
  elements.streamAudio.pause();
  elements.streamAudio.removeAttribute("src");
  elements.streamAudio.load();
  if (state.currentMode === "browser-stream") {
    state.currentMode = "idle";
  }
  state.worker.postMessage({ type: "stop-stream" });
  if (!(state.serverStatus && state.serverStatus.running)) {
    elements.monitorCopy.textContent = "Waiting for a stream or server-side device monitor.";
    elements.sourceState.textContent = state.serverStatus?.running ? state.serverStatus.deviceName : "None";
    setDecoderState(state.serverStatus?.running ? "Server monitoring" : "Idle");
  } else if (state.serverLiveAudioEnabled) {
    connectServerDeviceMonitorAudio().catch((error) => {
      failWithError("Unable to resume server live monitoring.", error);
    });
    elements.monitorCopy.textContent = `Listening live to ${state.serverStatus.deviceName || "server audio device"}.`;
  } else {
    elements.monitorCopy.textContent = `Server monitor running on ${state.serverStatus.deviceName || "server audio device"}, audio playback stopped.`;
  }
  render();
}

async function decodeArrayBuffer(arrayBuffer, sourceLabel) {
  await ensureAudioPipeline();
  const workingCopy = arrayBuffer.slice(0);
  const audioBuffer = await state.audioContext.decodeAudioData(workingCopy);
  const monoSamples = mixToMono(audioBuffer);

  state.worker.postMessage(
    {
      type: "decode-offline",
      sourceLabel,
      samples: monoSamples,
      sampleRate: audioBuffer.sampleRate,
    },
    [monoSamples.buffer],
  );
}

function mixToMono(audioBuffer) {
  const { numberOfChannels, length } = audioBuffer;
  const mono = new Float32Array(length);

  for (let channel = 0; channel < numberOfChannels; channel += 1) {
    const samples = audioBuffer.getChannelData(channel);
    for (let index = 0; index < length; index += 1) {
      mono[index] += samples[index];
    }
  }

  const scale = 1 / Math.max(1, numberOfChannels);
  for (let index = 0; index < length; index += 1) {
    mono[index] *= scale;
  }

  return mono;
}

function renderDeviceOptions(devices) {
  if (!devices.length) {
    elements.deviceSelect.innerHTML = `<option value="-1">No server audio inputs found</option>`;
    return;
  }

  const currentValue = elements.deviceSelect.value;
  elements.deviceSelect.innerHTML = devices
    .map(
      (device) =>
        `<option value="${escapeHtml(device.id)}">${escapeHtml(device.name)} (${escapeHtml(device.hostapi)})</option>`,
    )
    .join("");

  if (devices.some((device) => String(device.id) === currentValue)) {
    elements.deviceSelect.value = currentValue;
  }

  applyServerSettings(state.serverStatus?.settings || state.serverStatus);
}

function applyServerSettings(settings) {
  if (!settings) {
    return;
  }
  if (settings.preRollSeconds != null) {
    elements.preRollSeconds.value = String(settings.preRollSeconds);
  }
  if (settings.maxRecordSeconds != null) {
    elements.maxRecordSeconds.value = String(settings.maxRecordSeconds);
  }
  if (settings.autoLivePlaybackOnAlert != null) {
    state.autoLivePlaybackOnAlert = Boolean(settings.autoLivePlaybackOnAlert);
    elements.autoLivePlaybackOnAlert.checked = state.autoLivePlaybackOnAlert;
  }
  if (settings.ntfyEnabled != null) {
    elements.ntfyEnabled.checked = Boolean(settings.ntfyEnabled);
  }
  if (settings.ntfyBaseUrl != null) {
    elements.ntfyBaseUrl.value = String(settings.ntfyBaseUrl);
  }
  if (settings.ntfyTopic != null) {
    elements.ntfyTopic.value = String(settings.ntfyTopic);
  }
  if (settings.ntfyPriority != null) {
    elements.ntfyPriority.value = String(settings.ntfyPriority);
  }
  if (settings.ntfyTags != null) {
    elements.ntfyTags.value = String(settings.ntfyTags);
  }
  if (settings.ntfyClickUrl != null) {
    elements.ntfyClickUrl.value = String(settings.ntfyClickUrl);
  }
  if (settings.ntfyNotifyOnDetected != null) {
    elements.ntfyNotifyOnDetected.checked = Boolean(settings.ntfyNotifyOnDetected);
  }
  if (settings.ntfyNotifyOnCompleted != null) {
    elements.ntfyNotifyOnCompleted.checked = Boolean(settings.ntfyNotifyOnCompleted);
  }
  if (settings.deviceId != null) {
    const targetValue = String(settings.deviceId);
    if ([...elements.deviceSelect.options].some((option) => option.value === targetValue)) {
      elements.deviceSelect.value = targetValue;
    }
  }
}

function currentServerDeviceLabel() {
  const option = elements.deviceSelect.selectedOptions?.[0];
  return option?.textContent || "Server audio device";
}

function addActivity(title, detail, level = "info") {
  state.activity.unshift({
    title,
    detail,
    level,
    timestamp: new Date().toISOString(),
  });
  state.activity = state.activity.slice(0, 24);
}

function setDecoderState(value) {
  elements.decoderState.textContent = value;
}

function failWithError(prefix, error) {
  const detail = error instanceof Error ? error.message : String(error);
  addActivity(prefix, detail, "error");
  setDecoderState("Error");
  render();
}

function render() {
  const alerts = [...state.serverAlerts, ...state.localAlerts];
  elements.alertCount.textContent = String(alerts.length);
  renderAlerts(alerts);
  renderActivity();
}

function renderAlerts(alerts) {
  const signature = JSON.stringify(
    alerts.map((alert) => ({
      recordId: alert.recordId || null,
      rawHeader: alert.rawHeader,
      rawBursts: (alert.rawBursts || []).map((burst) => `${burst.kind}:${burst.rawText}`),
      repeatCount: alert.repeatCount || 1,
      confidence: Math.round((alert.confidence || 0) * 1000),
      recordingStatus: alert.recording?.status || null,
      recordingUrl: alert.recording?.url || null,
      endReason: alert.recording?.endReason || null,
      sourceLabel: alert.sourceLabel || null,
      completedAt: alert.completedAt || null,
    })),
  );

  if (signature === state.lastAlertsSignature) {
    return;
  }
  state.lastAlertsSignature = signature;

  if (!alerts.length) {
    elements.alertsList.className = "alerts-list empty-state";
    elements.alertsList.textContent = "No SAME headers decoded yet.";
    return;
  }

  elements.alertsList.className = "alerts-list";
  elements.alertsList.innerHTML = alerts
    .map((alert) => {
      const locationSummary = alert.locations.length
        ? alert.locations
            .map(
              (location) =>
                location.locationLabel
                  ? `${location.partitionLabel}, ${location.locationLabel}`
                  : `${location.partitionLabel}, ${location.stateLabel}, county ${location.countyCode}`,
            )
            .join("<br />")
        : "No location codes parsed";
      const confidencePercent = `${Math.round((alert.confidence || 0) * 100)}%`;
      const issueDisplay = alert.issued?.display || formatTimestamp(alert.detectedAt) || alert.issueCode || "Unknown";
      const sourceLabel = alert.sourceLabel || "Local decode";
      const rawBurstText = formatRawBursts(alert);
      const recordingMarkup = alert.recording?.url
        ? `
            <div class="recording-block">
              <span>Recording</span>
              <audio controls preload="none" src="${escapeHtml(alert.recording.url)}"></audio>
              <div class="muted">${escapeHtml(alert.recording.durationText || `${alert.recording.durationSeconds || 0}s`)} | Ended by ${escapeHtml(alert.recording.endReason || "unknown")}</div>
            </div>
          `
        : alert.recording?.status === "recording"
          ? `
              <div class="recording-block">
                <span>Recording</span>
                <div class="recording-status">Capture in progress. This alert will update when the file is finalized.</div>
              </div>
            `
        : "";
      const statusPillClass = alert.recording?.status === "recording" ? "warn" : alert.repeatCount >= 3 ? "" : "warn";
      const statusLabel = alert.recording?.status === "recording" ? "live capture" : `${alert.repeatCount || 1} repeat${alert.repeatCount === 1 ? "" : "s"}`;
      return `
        <article class="alert-card">
          <div class="alert-head">
            <div>
              <div class="alert-title">${escapeHtml(alert.eventLabel || "Decoded header")} <span class="muted">(${escapeHtml(alert.eventCode || "---")})</span></div>
              <div class="alert-meta">${escapeHtml(alert.originatorLabel || "Unknown originator")} from ${escapeHtml(alert.sender || sourceLabel)}</div>
            </div>
            <div class="pill ${statusPillClass}">${escapeHtml(statusLabel)} | ${confidencePercent}</div>
          </div>
          <div class="alert-grid">
            <div><span>Issued</span>${escapeHtml(issueDisplay)}</div>
            <div><span>Valid For</span>${escapeHtml(alert.durationText || "Unknown")}</div>
            <div><span>Source</span>${escapeHtml(sourceLabel)}</div>
            <div><span>Locations</span>${locationSummary}</div>
          </div>
          ${recordingMarkup}
          <div class="raw-header">${escapeHtml(rawBurstText)}</div>
        </article>
      `;
    })
    .join("");
}

function renderActivity() {
  const combined = [...state.activity, ...state.serverActivity]
    .sort((left, right) => String(right.timestamp).localeCompare(String(left.timestamp)))
    .slice(0, 24);

  if (!combined.length) {
    elements.activityLog.className = "activity-log empty-state";
    elements.activityLog.textContent = "Decoder events and status updates will appear here.";
    return;
  }

  elements.activityLog.className = "activity-log";
  elements.activityLog.innerHTML = combined
    .map(
      (entry) => `
        <article class="activity-entry">
          <strong>${escapeHtml(entry.title)}</strong>
          <div>${escapeHtml(entry.detail)}</div>
          <div class="muted">${escapeHtml(formatTimestamp(entry.timestamp) || entry.timestamp)}</div>
        </article>
      `,
    )
    .join("");
}

function proxyUrl(rawUrl) {
  return `/api/proxy?url=${encodeURIComponent(rawUrl)}`;
}

function augmentAlertLocations(alert) {
  return {
    ...alert,
    locations: (alert.locations || []).map((location) => {
      if (location.countyName || !location.code) {
        return location;
      }
      const sameEntry = state.sameCodeMap[location.code];
      if (!sameEntry) {
        return location;
      }
      return {
        ...location,
        countyName: sameEntry.countyName,
        stateAbbr: sameEntry.stateAbbr,
        locationLabel: `${sameEntry.countyName}, ${sameEntry.stateAbbr}`,
      };
    }),
  };
}

async function connectServerDeviceMonitorAudio() {
  if (!state.serverLiveAudioEnabled || state.currentMode === "browser-stream") {
    return;
  }
  if (state.serverLiveConnectPromise) {
    return state.serverLiveConnectPromise;
  }

  state.serverLiveConnectPromise = (async () => {
    await ensureAudioPipeline();

    elements.streamAudio.pause();
    elements.streamAudio.removeAttribute("src");
    elements.streamAudio.load();

    elements.streamAudio.src = `/api/monitor/live.wav?ts=${Date.now()}`;
    elements.streamAudio.crossOrigin = "anonymous";
    elements.streamAudio.muted = false;
    await elements.streamAudio.play();

    if (!state.mediaElementSource) {
      state.mediaElementSource = state.audioContext.createMediaElementSource(elements.streamAudio);
    }

    connectSource(state.mediaElementSource, true, false);
    state.currentMode = "server-device";
  })();

  try {
    await state.serverLiveConnectPromise;
  } finally {
    state.serverLiveConnectPromise = null;
  }
}

function disconnectServerDeviceMonitorAudio() {
  state.serverLiveConnectPromise = null;
  if (state.currentMode !== "server-device") {
    return;
  }
  disconnectCurrentSource();
  elements.streamAudio.pause();
  elements.streamAudio.removeAttribute("src");
  elements.streamAudio.load();
  state.currentMode = "idle";
}

function maybeAutoStartLivePlayback(recordId) {
  if (!state.autoLivePlaybackOnAlert || !recordId) {
    return;
  }
  if (state.autoLivePlaybackArmedRecordId === recordId) {
    return;
  }
  state.autoLivePlaybackArmedRecordId = recordId;
  if (state.currentMode === "browser-stream" || state.serverLiveAudioEnabled) {
    return;
  }
  state.serverLiveAudioEnabled = true;
  state.autoLivePlaybackStartedByAlert = true;
  state.autoLivePlaybackActiveRecordId = recordId;
  connectServerDeviceMonitorAudio()
    .then(() => {
      addActivity("Live monitor auto-started", "A detected alert started the server live monitor automatically.", "info");
      render();
    })
    .catch((error) => {
      state.serverLiveAudioEnabled = false;
      state.autoLivePlaybackStartedByAlert = false;
      state.autoLivePlaybackActiveRecordId = null;
      if (String(error?.message || error).includes("aborted by the user agent")) {
        return;
      }
      failWithError("Unable to auto-start the live monitor for the detected alert.", error);
    });
}

function maybeAutoStopLivePlaybackAfterAlert(alerts) {
  if (!state.autoLivePlaybackStartedByAlert || state.currentMode !== "server-device" || !state.autoLivePlaybackActiveRecordId) {
    return;
  }
  const completedAlert = (alerts || []).find(
    (alert) =>
      alert.recordId === state.autoLivePlaybackActiveRecordId &&
      alert.recording?.status === "complete",
  );
  if (!completedAlert) {
    return;
  }
  state.serverLiveAudioEnabled = false;
  state.autoLivePlaybackStartedByAlert = false;
  state.autoLivePlaybackActiveRecordId = null;
  state.autoLivePlaybackArmedRecordId = null;
  disconnectServerDeviceMonitorAudio();
  addActivity("Live monitor auto-stopped", "The alert finished, so the live monitor was stopped automatically.", "info");
}

function formatTimestamp(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatRawBursts(alert) {
  const bursts = Array.isArray(alert.rawBursts) ? alert.rawBursts : [];
  if (!bursts.length) {
    return alert.rawHeader || "";
  }
  return bursts
    .map((burst, index) => {
      const label = String(burst.kind || "burst").toUpperCase();
      return `${index + 1}. ${label}: ${burst.rawText || ""}`;
    })
    .join("\n");
}
