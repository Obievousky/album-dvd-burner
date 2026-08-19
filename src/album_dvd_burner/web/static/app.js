const SESSION_JOB_KEY = "album-dvd-burner:active-job";

const state = {
  albums: [],
  activeJobId: null,
  pollTimer: null,
  pollIntervalMs: 1000,
  jobTerminalHandled: false,
  deletionCountdownTimer: null,
  currentJob: null,
};

const apiKey = new URLSearchParams(window.location.search).get("key") || "";

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function downloadUrl(path) {
  const url = new URL(path, window.location.origin);
  if (apiKey) url.searchParams.set("key", apiKey);
  return url.toString();
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (apiKey) headers["X-API-Key"] = apiKey;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function showBanner(message, type = "error") {
  const banner = document.getElementById("api-banner");
  if (!banner) return;
  banner.textContent = message;
  banner.className = `api-banner ${type}`;
  banner.classList.remove("hidden");
}

function hideBanner() {
  const banner = document.getElementById("api-banner");
  if (banner) banner.classList.add("hidden");
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function setProgress(prefix, percent, label) {
  const block = document.getElementById(`${prefix}-progress-block`);
  const fill = document.getElementById(`${prefix}-progress-fill`);
  const percentEl = document.getElementById(`${prefix}-progress-percent`);
  const labelEl = document.getElementById(`${prefix}-progress-label`);

  block.classList.remove("hidden");
  fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  percentEl.textContent = `${Math.round(percent)}%`;
  if (label) labelEl.textContent = label;
}

function hideProgress(prefix) {
  document.getElementById(`${prefix}-progress-block`).classList.add("hidden");
}

function uploadWithProgress(url, formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    if (apiKey) xhr.setRequestHeader("X-API-Key", apiKey);

    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      const percent = (event.loaded / event.total) * 100;
      setProgress("upload", percent, `Uploading… ${formatBytes(event.loaded)} / ${formatBytes(event.total)}`);
    });

    xhr.addEventListener("load", () => {
      hideProgress("upload");
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
        return;
      }
      let detail = "Upload failed";
      try {
        detail = JSON.parse(xhr.responseText).detail || detail;
      } catch (_) {
        /* ignore */
      }
      reject(new Error(detail));
    });

    xhr.addEventListener("error", () => {
      hideProgress("upload");
      reject(new Error("Upload failed"));
    });

    setProgress("upload", 0, "Uploading…");
    xhr.send(formData);
  });
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function toggleRetentionOptions() {
  const persistent = document.getElementById("persistent").checked;
  const options = document.getElementById("retention-options");
  options.classList.toggle("disabled", !persistent);
  options.querySelectorAll("input").forEach((input) => {
    input.disabled = !persistent;
  });
}

function retentionPayload() {
  const persistent = document.getElementById("persistent").checked;
  if (!persistent) {
    return { persistent: false };
  }
  return {
    persistent: true,
    keep_source: document.getElementById("keep-source").checked,
    keep_converted: document.getElementById("keep-converted").checked,
    keep_artwork: document.getElementById("keep-artwork").checked,
    keep_iso: document.getElementById("keep-iso").checked,
    keep_video_ts: document.getElementById("keep-video-ts").checked,
  };
}

function renderAlbums() {
  const list = document.getElementById("album-list");
  if (!state.albums.length) {
    list.innerHTML = '<p class="album-details">No albums yet. Upload a folder or ZIP.</p>';
    return;
  }

  list.innerHTML = state.albums.map((album) => {
    const audio = album.audio_info
      ? `${album.audio_info.bit_depth}-bit / ${(album.audio_info.sample_rate / 1000).toFixed(1)} kHz`
      : "No audio detected";
    const artwork = album.has_artwork
      ? '<span class="badge ok">artwork</span>'
      : '<span class="badge warn">no cover image</span>';
    const convertedLabel = album.converted_label || "16/48";
    const converted = album.converted ? `<span class="badge ok">${convertedLabel}</span>` : "";
    const output = album.has_output ? '<span class="badge ok">has ISO</span>' : "";
    const tags = [album.artist, album.album].filter(Boolean).join(" · ");
    const artworkUrl = downloadUrl(`/api/albums/${encodeURIComponent(album.name)}/artwork`);
    const cover = album.has_artwork
      ? `<div class="album-cover"><img src="${escapeHtml(artworkUrl)}" alt="" loading="lazy" /></div>`
      : '<div class="album-cover missing" aria-label="No album cover">No cover</div>';
    const isSingleAlbum = state.albums.length === 1;

    return `
      <div class="album-row">
        <label class="album-card">
          <input type="checkbox" class="album-select${isSingleAlbum ? " hidden" : ""}" name="album" value="${escapeHtml(album.name)}" checked />
          ${cover}
          <div class="album-meta">
            <div class="album-title" data-name="${escapeHtml(album.name)}" title="Double-click to rename">${escapeHtml(album.name)}</div>
            ${tags ? `<div class="album-tags">${escapeHtml(tags)}</div>` : ""}
            <div class="album-details">
              ${album.track_count} tracks · ${escapeHtml(audio)}
              <div>${artwork}${converted}${output}</div>
            </div>
          </div>
          <div class="album-actions">
            <button type="button" class="btn ghost album-rename" data-name="${escapeHtml(album.name)}" title="Rename album">Rename</button>
            <button type="button" class="btn ghost danger album-delete" data-name="${escapeHtml(album.name)}" title="Delete album">Delete</button>
          </div>
        </label>
      </div>
    `;
  }).join("");
}

function renderBurnHistory(rows) {
  const tbody = document.getElementById("burn-history");
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No burns yet.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row) => {
    const albums = (row.albums || []).map((a) => escapeHtml(a.name || a)).join(", ");
    const output = escapeHtml(row.metadata?.output_dir || row.iso_path || "—");
    return `
      <tr>
        <td>${escapeHtml(row.burn_code)}</td>
        <td>${albums}</td>
        <td>${formatDate(row.created_at)}</td>
        <td>${row.burned_at ? formatDate(row.burned_at) : "ISO only"}</td>
        <td><code>${output}</code></td>
      </tr>
    `;
  }).join("");
}

function persistActiveJob(jobId) {
  if (jobId) sessionStorage.setItem(SESSION_JOB_KEY, jobId);
  else sessionStorage.removeItem(SESSION_JOB_KEY);
}

function isJobRunning(job) {
  return job && (job.status === "queued" || job.status === "running");
}

function renderJobProgress(job) {
  if (!job?.progress) {
    hideProgress("job");
    return;
  }

  const { label, percent } = job.progress;
  if (job.status === "completed") {
    setProgress("job", 100, "Complete");
    return;
  }
  if (job.status === "failed" || job.status === "interrupted") {
    setProgress("job", 100, job.status === "interrupted" ? "Interrupted" : "Failed");
    return;
  }

  setProgress("job", percent || 0, label || job.progress.stage || "Working…");
}

function formatDuration(seconds) {
  if (seconds <= 0) return "due now";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function secondsUntil(isoTimestamp) {
  return Math.max(0, Math.floor((new Date(isoTimestamp) - Date.now()) / 1000));
}

function stopDeletionCountdown() {
  if (state.deletionCountdownTimer) {
    clearInterval(state.deletionCountdownTimer);
    state.deletionCountdownTimer = null;
  }
}

function tickDeletionCountdown() {
  const nodes = document.querySelectorAll("[data-deletion-countdown]");
  let anyRemaining = false;
  nodes.forEach((node) => {
    const remaining = secondsUntil(node.dataset.deleteAt);
    node.textContent = `deletes in ${formatDuration(remaining)}`;
    if (remaining > 0) anyRemaining = true;
  });
  if (!anyRemaining) stopDeletionCountdown();
}

function startDeletionCountdown() {
  stopDeletionCountdown();
  if (!document.querySelector("[data-deletion-countdown]")) return;
  state.deletionCountdownTimer = setInterval(tickDeletionCountdown, 1000);
}

function stopJobPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function startJobPolling(jobId, intervalMs = 1000) {
  stopJobPolling();
  state.pollIntervalMs = intervalMs;
  state.pollTimer = setInterval(() => pollJob(jobId), intervalMs);
}

function renderJobDownloads(job) {
  const actions = document.getElementById("job-actions");
  const logLink = document.getElementById("download-log");
  const downloads = document.getElementById("job-downloads");

  if (!job || (!job.logs?.length && !job.error)) {
    actions.classList.add("hidden");
    logLink.classList.add("hidden");
    downloads.classList.add("hidden");
    downloads.innerHTML = "";
    stopDeletionCountdown();
    return;
  }

  actions.classList.remove("hidden");
  logLink.classList.remove("hidden");
  logLink.href = downloadUrl(job.log_download_url || `/api/jobs/${job.id}/log/download`);

  const outputs = job.outputs || [];
  if (!outputs.length && !(job.scheduled_deletions || []).length) {
    downloads.classList.add("hidden");
    downloads.innerHTML = "";
    return;
  }

  downloads.classList.remove("hidden");
  const scheduled = (job.scheduled_deletions || []).map((entry) => `
    <div class="download-item scheduled">
      <div>
        <div>${escapeHtml(entry.label)} — <span data-deletion-countdown data-delete-at="${escapeHtml(entry.delete_at)}">deletes in ${formatDuration(entry.seconds_remaining)}</span></div>
        <div class="download-meta">${escapeHtml(entry.path)}</div>
      </div>
    </div>
  `).join("");

  downloads.innerHTML = scheduled + outputs.map((output) => `
    <div class="download-item">
      <div>
        <div>${escapeHtml(output.label)}</div>
        <div class="download-meta">${formatBytes(output.size)}</div>
      </div>
      <a class="btn" href="${downloadUrl(output.download_url)}">Download</a>
    </div>
  `).join("");
  startDeletionCountdown();
}

function renderJobLog(job) {
  state.currentJob = job;
  const output = document.getElementById("job-log-output");
  if (!job) {
    output.textContent = "No active job.";
    renderJobDownloads(null);
    return;
  }

  renderJobProgress(job);
  renderJobDownloads(job);

  const lines = job.logs.map((log) => {
    const time = new Date(log.timestamp).toLocaleTimeString();
    return `${time} [${log.stage}] ${log.message}`;
  });
  if (job.error) lines.push(`[error] ${job.error}`);
  if (job.status === "completed") {
    lines.push(`\nCompleted: ${job.burn_code}`);
    if (job.output_dir) lines.push(`Output: ${job.output_dir}`);
    if (job.iso_path) lines.push(`ISO: ${job.iso_path}`);
  }
  if (job.status === "interrupted") {
    lines.push(`\nInterrupted: ${job.error || "Job did not finish"}`);
  }
  output.textContent = lines.join("\n") || `Status: ${job.status}`;
  output.scrollTop = output.scrollHeight;
}

async function refreshHealth() {
  const health = await api("/api/health");
  hideBanner();
  const pill = document.getElementById("drive-status");
  const delayHint = document.getElementById("retention-delay-hint");
  const burnDisc = document.getElementById("burn-disc");
  const standard = document.getElementById("standard");

  if (standard && health.dvd_standard) {
    standard.value = health.dvd_standard;
  }
  if (delayHint && health.retention_delay_hours != null) {
    const hours = health.retention_delay_hours;
    delayHint.textContent = hours > 0
      ? `Unchecked files are deleted after ${hours} hour(s), giving you time to download.`
      : "Unchecked files are deleted immediately after the job.";
  }
  if (health.drive_ready) {
    pill.textContent = `Drive ready (${health.dvd_device})`;
    pill.className = "status-pill ready";
    if (burnDisc) burnDisc.disabled = false;
  } else {
    pill.textContent = `No drive at ${health.dvd_device} — ISO only`;
    pill.className = "status-pill missing";
    if (burnDisc) {
      burnDisc.checked = false;
      burnDisc.disabled = true;
    }
  }
}

async function refreshAlbums() {
  state.albums = await api("/api/albums");
  renderAlbums();
}

async function refreshBurns() {
  const burns = await api("/api/burns");
  renderBurnHistory(burns);
}

async function refreshNextBurnCode() {
  const data = await api("/api/next-burn-code");
  document.getElementById("next-burn-code").textContent = data.burn_code;
}

function selectedAlbums() {
  return [...document.querySelectorAll('input[name="album"]:checked')].map((el) => el.value);
}

async function pollJob(jobId) {
  try {
    const job = await api(`/api/jobs/${jobId}`);
    renderJobLog(job);

    const terminal = ["completed", "failed", "interrupted"].includes(job.status);
    const pendingDeletion = (job.scheduled_deletions || []).some(
      (entry) => secondsUntil(entry.delete_at) > 0,
    );

    if (terminal) {
      if (!state.jobTerminalHandled) {
        state.jobTerminalHandled = true;
        state.activeJobId = null;
        persistActiveJob(null);
        document.getElementById("start-job").disabled = false;
        await refreshBurns();
        await refreshAlbums();
        await refreshNextBurnCode();
      }

      if (pendingDeletion) {
        if (state.pollIntervalMs !== 60000) {
          startJobPolling(jobId, 60000);
        }
        return;
      }

      stopJobPolling();
      return;
    }
  } catch (error) {
    stopJobPolling();
    document.getElementById("start-job").disabled = false;
    showBanner(error.message);
    const output = document.getElementById("job-log-output");
    if (output) output.textContent = `Polling failed: ${error.message}`;
  }
}

async function restoreSession() {
  const storedId = sessionStorage.getItem(SESSION_JOB_KEY);
  let job = null;

  if (storedId) {
    try {
      job = await api(`/api/jobs/${storedId}`);
    } catch {
      persistActiveJob(null);
    }
  }

  if (!job) {
    const active = await api("/api/jobs/active");
    job = active.job;
  }

  if (!job) return;

  renderJobLog(job);

  if (isJobRunning(job)) {
    state.activeJobId = job.id;
    persistActiveJob(job.id);
    document.getElementById("start-job").disabled = true;
    if (!state.pollTimer) {
      state.jobTerminalHandled = false;
      startJobPolling(job.id, 1000);
    }
  } else {
    persistActiveJob(job.id);
    const pendingDeletion = (job.scheduled_deletions || []).some(
      (entry) => secondsUntil(entry.delete_at) > 0,
    );
    if (pendingDeletion && !state.pollTimer) {
      state.jobTerminalHandled = true;
      startJobPolling(job.id, 60000);
    }
  }
}

async function startJob(event) {
  event.preventDefault();
  const albums = selectedAlbums();
  if (!albums.length) {
    alert("Select at least one album.");
    return;
  }

  const burn = document.getElementById("burn-disc").checked;
  const ejectAfterBurn = document.getElementById("eject-after-burn").checked;
  const standard = document.getElementById("standard").value;
  const button = document.getElementById("start-job");
  button.disabled = true;
  setProgress("job", 0, "Starting job…");
  state.jobTerminalHandled = false;
  stopJobPolling();

  const job = await api("/api/jobs", {
    method: "POST",
    body: JSON.stringify({
      albums,
      burn,
      standard,
      retention: retentionPayload(),
    }),
  }).catch((error) => {
    button.disabled = false;
    hideProgress("job");
    throw error;
  });

  state.activeJobId = job.id;
  state.currentJob = job;
  persistActiveJob(job.id);
  renderJobLog(job);
  startJobPolling(job.id, 1000);
}

function registerUploadedAlbum(result) {
  document.getElementById("album-name").value = "";
  showBanner(`Saved as: ${result.name} (${result.naming_source || "detected"})`, "success");
  setTimeout(hideBanner, 5000);
  // Insert uploaded album into UI immediately; remove any duplicate name first.
  state.albums = state.albums.filter((a) => a.name !== result.name);
  state.albums.unshift(result);
  renderAlbums();
  // Refresh in background to pick up any other changes.
  refreshAlbums().catch(() => {});
}

async function uploadAlbumFiles(filesWithPaths, override, fallback) {
  const form = new FormData();
  if (override) form.append("album_name", override);
  if (fallback) form.append("album_fallback", fallback);
  for (const { file, relativePath } of filesWithPaths) {
    form.append("files", file, relativePath);
  }
  return uploadWithProgress("/api/upload/folder", form);
}

async function uploadZip(file) {
  const override = document.getElementById("album-name").value.trim();
  const form = new FormData();
  form.append("file", file);
  if (override) form.append("album_name", override);
  const result = await uploadWithProgress("/api/upload/zip", form);
  registerUploadedAlbum(result);
}

function groupFilesByFolder(files) {
  const groups = new Map();
  for (const file of files) {
    const parts = (file.webkitRelativePath || "").split("/");
    const folderName = parts[0] || null;
    const relativePath = parts.slice(1).join("/") || file.name;
    if (!groups.has(folderName)) groups.set(folderName, []);
    groups.get(folderName).push({ file, relativePath });
  }
  return groups;
}

async function uploadFolder(files) {
  const override = document.getElementById("album-name").value.trim();
  const groups = groupFilesByFolder(files);
  for (const [folderName, filesWithPaths] of groups) {
    const result = await uploadAlbumFiles(filesWithPaths, override, folderName || null);
    registerUploadedAlbum(result);
  }
}

function readAllEntries(dirReader) {
  return new Promise((resolve, reject) => {
    const entries = [];
    const readBatch = () => {
      dirReader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries);
          return;
        }
        entries.push(...batch);
        readBatch();
      }, reject);
    };
    readBatch();
  });
}

async function directoryFiles(dirEntry) {
  const files = [];
  const walk = async (entry, prefix) => {
    const reader = entry.createReader();
    const children = await readAllEntries(reader);
    for (const child of children) {
      const rel = prefix ? `${prefix}/${child.name}` : child.name;
      if (child.isFile) {
        const file = await new Promise((resolve, reject) => child.file(resolve, reject));
        files.push({ file, relativePath: rel });
      } else if (child.isDirectory) {
        await walk(child, rel);
      }
    }
  };
  await walk(dirEntry, "");
  return files;
}

async function droppedJobs(items) {
  const entries = [];
  for (const item of items) {
    const getEntry = item.webkitGetAsEntry || item.getAsEntry;
    const entry = getEntry ? getEntry.call(item) : null;
    if (entry) entries.push(entry);
    else {
      const file = item.getAsFile();
      if (file) entries.push(file);
    }
  }

  const jobs = [];
  const looseFiles = [];
  for (const entry of entries) {
    if (entry instanceof File) {
      if (entry.name.toLowerCase().endsWith(".zip")) jobs.push({ kind: "zip", file: entry });
      else looseFiles.push({ file: entry, relativePath: entry.name });
    } else if (entry.isDirectory) {
      jobs.push({ kind: "folder", files: await directoryFiles(entry), fallback: entry.name });
    } else if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      if (file.name.toLowerCase().endsWith(".zip")) jobs.push({ kind: "zip", file });
      else looseFiles.push({ file, relativePath: file.name });
    }
  }
  if (looseFiles.length) jobs.push({ kind: "folder", files: looseFiles, fallback: null });
  return jobs;
}

async function processDroppedJobs(jobs) {
  const errors = [];
  for (const job of jobs) {
    try {
      const override = document.getElementById("album-name").value.trim();
      if (job.kind === "zip") {
        const form = new FormData();
        form.append("file", job.file);
        if (override) form.append("album_name", override);
        registerUploadedAlbum(await uploadWithProgress("/api/upload/zip", form));
      } else {
        registerUploadedAlbum(await uploadAlbumFiles(job.files, override, job.fallback || null));
      }
    } catch (error) {
      const label = job.kind === "zip"
        ? job.file.name
        : (job.fallback || job.files[0]?.relativePath?.split("/")[0] || "upload");
      errors.push(`${label}: ${error.message}`);
    }
  }
  if (errors.length) showBanner(`Upload finished with errors: ${errors.join("; ")}`, "error");
}

function bindDropZone() {
  const zone = document.getElementById("drop-zone");
  if (!zone) return;
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", async (event) => {
    event.preventDefault();
    zone.classList.remove("dragover");
    const jobs = await droppedJobs(event.dataTransfer.items);
    if (!jobs.length) return;
    await processDroppedJobs(jobs);
  });
}

async function deleteAlbum(name) {
  if (!confirm(`Delete "${name}" and all its files?`)) return;
  await api(`/api/albums/${encodeURIComponent(name)}`, { method: "DELETE" });
  await refreshAlbums();
}

async function performRename(oldName, newName) {
  const trimmed = newName.trim();
  if (!trimmed || trimmed === oldName) return;
  await api(`/api/albums/${encodeURIComponent(oldName)}`, {
    method: "PATCH",
    body: JSON.stringify({ name: trimmed }),
  });
  await refreshAlbums();
}

async function renameAlbum(name) {
  const newName = prompt("New album name", name);
  if (newName == null) return;
  await performRename(name, newName);
}

function beginRenameTitle(titleEl) {
  if (titleEl.querySelector("input")) return;
  const currentName = titleEl.dataset.name;
  const input = document.createElement("input");
  input.type = "text";
  input.value = currentName;
  input.className = "album-title-edit";
  input.setAttribute("aria-label", "Album name");
  titleEl.textContent = "";
  titleEl.appendChild(input);
  input.focus();
  input.select();

  let finished = false;
  let cancelled = false;

  const finish = async () => {
    if (finished) return;
    finished = true;
    const newName = input.value.trim();
    if (cancelled || !newName || newName === currentName) {
      await refreshAlbums();
      return;
    }
    try {
      await performRename(currentName, newName);
    } catch (error) {
      alert(error.message);
      await refreshAlbums();
    }
  };

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      input.blur();
    } else if (event.key === "Escape") {
      cancelled = true;
      event.preventDefault();
      input.blur();
    }
  });

  input.addEventListener("blur", finish);

  input.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
}

function bindEvents() {
  document.getElementById("refresh-albums").addEventListener("click", refreshAlbums);
  document.getElementById("refresh-burns")?.addEventListener("click", refreshBurns);
  document.getElementById("persistent").addEventListener("change", toggleRetentionOptions);
  document.getElementById("album-list").addEventListener("click", async (event) => {
    const renameButton = event.target.closest(".album-rename");
    if (renameButton) {
      event.preventDefault();
      event.stopPropagation();
      try {
        await renameAlbum(renameButton.dataset.name);
      } catch (error) {
        alert(error.message);
      }
      return;
    }

    const button = event.target.closest(".album-delete");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    try {
      await deleteAlbum(button.dataset.name);
    } catch (error) {
      alert(error.message);
    }
  });

  document.getElementById("album-list").addEventListener("dblclick", (event) => {
    const title = event.target.closest(".album-title");
    if (!title) return;
    event.preventDefault();
    event.stopPropagation();
    beginRenameTitle(title);
  });

  document.getElementById("zip-upload").addEventListener("change", async (event) => {
    const files = [...event.target.files];
    if (!files.length) return;
    for (const file of files) {
      try {
        await uploadZip(file);
      } catch (error) {
        alert(error.message);
      }
    }
    event.target.value = "";
  });

  document.getElementById("folder-upload").addEventListener("change", async (event) => {
    const files = [...event.target.files];
    if (!files.length) return;
    try {
      await uploadFolder(files);
    } catch (error) {
      alert(error.message);
    }
    event.target.value = "";
  });

  document.getElementById("job-form").addEventListener("submit", async (event) => {
    try {
      await startJob(event);
    } catch (error) {
      alert(error.message);
    }
  });
}

async function init() {
  bindEvents();
  bindDropZone();
  toggleRetentionOptions();
  try {
    await refreshHealth();
    await refreshAlbums();
    await refreshBurns();
    await refreshNextBurnCode();
    await restoreSession();
  } catch (error) {
    const health = await fetch("/api/health").then((r) => r.json()).catch(() => ({}));
    const hint = health.api_key_required
      ? "API key required — open this page with ?key=YOUR_KEY in the URL."
      : error.message;
    showBanner(hint);
    document.getElementById("job-log-output").textContent = `Failed to load: ${hint}`;
  }
}

init();
