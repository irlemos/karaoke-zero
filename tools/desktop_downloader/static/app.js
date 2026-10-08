/**
 * KaraokeZero Desktop Downloader - Frontend Controller
 * Pure Vanilla JavaScript (Zero External Dependencies)
 */

document.addEventListener('DOMContentLoaded', () => {
  // =========================================================================
  // DOM Elements
  // =========================================================================
  const searchInput = document.getElementById('searchInput');
  const searchBtn = document.getElementById('searchBtn');
  const searchLoader = document.getElementById('searchLoader');
  const resultsGrid = document.getElementById('resultsGrid');
  const resultsTitle = document.getElementById('resultsTitle');
  const resultsCount = document.getElementById('resultsCount');

  // Queue Elements
  const queueList = document.getElementById('queueList');
  const emptyQueueMsg = document.getElementById('emptyQueueMsg');
  const queueBadgeCount = document.getElementById('queueBadgeCount');
  const queuePanelBadge = document.getElementById('queuePanelBadge');
  const statActive = document.getElementById('statActive');
  const statQueued = document.getElementById('statQueued');
  const statCompleted = document.getElementById('statCompleted');
  const pauseQueueBtn = document.getElementById('pauseQueueBtn');
  const pauseBtnText = document.getElementById('pauseBtnText');
  const clearCompletedBtn = document.getElementById('clearCompletedBtn');
  const retryAllFailedBtn = document.getElementById('retryAllFailedBtn');
  const retryAllFailedText = document.getElementById('retryAllFailedText');
  const toggleQueueBtn = document.getElementById('toggleQueueBtn');
  const queuePanel = document.getElementById('queuePanel');

  // Error Modal Elements
  const errorModal = document.getElementById('errorModal');
  const closeErrorModal = document.getElementById('closeErrorModal');
  const closeErrorModalBtn = document.getElementById('closeErrorModalBtn');
  const copyErrorLogBtn = document.getElementById('copyErrorLogBtn');
  const retryErrorModalBtn = document.getElementById('retryErrorModalBtn');
  const errorSongTitle = document.getElementById('errorSongTitle');
  const errorSummaryText = document.getElementById('errorSummaryText');
  const errorLogOutput = document.getElementById('errorLogOutput');

  let activeModalTaskId = null;
  let currentTasksMap = new Map();

  // Nav & Settings Elements
  const qualitySelect = document.getElementById('qualitySelect');
  const openStorageBtn = document.getElementById('openStorageBtn');
  const currentStorageLabel = document.getElementById('currentStorageLabel');
  const openSettingsBtn = document.getElementById('openSettingsBtn');
  const settingsModal = document.getElementById('settingsModal');
  const closeSettingsModal = document.getElementById('closeSettingsModal');
  const cancelSettingsBtn = document.getElementById('cancelSettingsBtn');
  const saveSettingsBtn = document.getElementById('saveSettingsBtn');
  const detectedDrivesList = document.getElementById('detectedDrivesList');
  const customOutputDirInput = document.getElementById('customOutputDirInput');

  // Search Type Tabs
  const tabSongsBtn = document.getElementById('tabSongsBtn');
  const tabPlaylistsBtn = document.getElementById('tabPlaylistsBtn');

  // Playlist Modal Elements
  const openPlaylistModalBtn = document.getElementById('openPlaylistModalBtn');
  const playlistModal = document.getElementById('playlistModal');
  const closePlaylistModal = document.getElementById('closePlaylistModal');
  const cancelPlaylistBtn = document.getElementById('cancelPlaylistBtn');
  const playlistUrlInput = document.getElementById('playlistUrlInput');
  const inspectPlaylistBtn = document.getElementById('inspectPlaylistBtn');
  const playlistLoader = document.getElementById('playlistLoader');
  const playlistContent = document.getElementById('playlistContent');
  const playlistTitle = document.getElementById('playlistTitle');
  const playlistStats = document.getElementById('playlistStats');
  const playlistItemsList = document.getElementById('playlistItemsList');
  const selectAllPlaylistBtn = document.getElementById('selectAllPlaylistBtn');
  const deselectAllPlaylistBtn = document.getElementById('deselectAllPlaylistBtn');
  const enqueuePlaylistBtn = document.getElementById('enqueuePlaylistBtn');
  const downloadEntirePlaylistBtn = document.getElementById('downloadEntirePlaylistBtn');
  const selectedPlaylistCount = document.getElementById('selectedPlaylistCount');

  // Batch Modal Elements
  const openBatchModalBtn = document.getElementById('openBatchModalBtn');
  const batchModal = document.getElementById('batchModal');
  const closeBatchModal = document.getElementById('closeBatchModal');
  const cancelBatchBtn = document.getElementById('cancelBatchBtn');
  const batchTextArea = document.getElementById('batchTextArea');
  const batchLineCount = document.getElementById('batchLineCount');
  const enqueueBatchBtn = document.getElementById('enqueueBatchBtn');

  // Toast Container
  const toastContainer = document.getElementById('toastContainer');

  // State Variables
  let currentSettings = {
    output_dir: '',
    quality: '480',
    available_drives: []
  };
  let currentSearchType = 'videos';
  let currentPlaylistTracks = [];
  let isQueuePaused = false;
  let enqueuedVideoUrls = new Set();
  let enqueuedPlaylistUrls = new Set();

  // =========================================================================
  // Toast Notifications
  // =========================================================================
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);

    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 4000);
  }

  // =========================================================================
  // Settings & Storage Management
  // =========================================================================
  async function loadSettings() {
    try {
      const res = await fetch('/api/settings');
      if (!res.ok) throw new Error('Failed to load settings');
      const data = await res.json();
      currentSettings = data;

      if (data.quality) {
        qualitySelect.value = data.quality;
      }

      if (data.output_dir) {
        const parts = data.output_dir.split('/');
        const dirName = parts[parts.length - 1] || parts[parts.length - 2] || data.output_dir;
        currentStorageLabel.textContent = dirName;
        currentStorageLabel.title = data.output_dir;
        customOutputDirInput.value = data.output_dir;
      }

      renderDetectedDrives(data.available_drives || [], data.output_dir);
    } catch (err) {
      console.error('Error fetching settings:', err);
    }
  }

  function renderDetectedDrives(drives, selectedPath) {
    detectedDrivesList.innerHTML = '';
    if (!drives || drives.length === 0) {
      detectedDrivesList.innerHTML = '<p class="settings-subtext">No external USB drives detected. Using local storage.</p>';
      return;
    }

    drives.forEach(drive => {
      const card = document.createElement('div');
      const normSelected = (selectedPath || '').replace(/\\/g, '/').toLowerCase();
      const normDrive = (drive.path || '').replace(/\\/g, '/').toLowerCase();
      const isSelected = normSelected.startsWith(normDrive);
      card.className = `drive-card ${isSelected ? 'selected' : ''}`;
      card.innerHTML = `
        <div class="drive-card-left">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
            <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
            <line x1="6" y1="6" x2="6.01" y2="6"/>
            <line x1="6" y1="18" x2="6.01" y2="18"/>
          </svg>
          <div>
            <div class="drive-card-title">${escapeHtml(drive.label)}</div>
            <div class="drive-card-path">${escapeHtml(drive.path)}</div>
          </div>
        </div>
        <span class="drive-card-badge">${drive.is_karaoke ? 'Karaoke Drive' : 'USB Drive'}</span>
      `;

      card.addEventListener('click', () => {
        document.querySelectorAll('.drive-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        // Default to /songs subfolder on selected drive
        const normPath = (drive.path || '').replace(/\\/g, '/').toLowerCase();
        let targetPath = drive.path;
        if (!normPath.endsWith('/songs')) {
          if (drive.path.includes('\\')) {
            targetPath = drive.path.endsWith('\\') ? `${drive.path}songs` : `${drive.path}\\songs`;
          } else {
            targetPath = drive.path.endsWith('/') ? `${drive.path}songs` : `${drive.path}/songs`;
          }
        }
        customOutputDirInput.value = targetPath;
      });

      detectedDrivesList.appendChild(card);
    });
  }

  async function saveSettings() {
    const newDir = customOutputDirInput.value.trim();
    const newQuality = qualitySelect.value;

    if (!newDir) {
      showToast('Destination path cannot be empty', 'warning');
      return;
    }

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          output_dir: newDir,
          quality: newQuality
        })
      });

      const data = await res.json();
      if (data.status === 'ok') {
        currentSettings.output_dir = newDir;
        currentSettings.quality = newQuality;
        const parts = newDir.split('/');
        currentStorageLabel.textContent = parts[parts.length - 1] || newDir;
        currentStorageLabel.title = newDir;
        settingsModal.classList.add('hidden');
        showToast('Settings saved successfully', 'success');
      } else {
        showToast(data.message || 'Error saving settings', 'error');
      }
    } catch (err) {
      showToast('Failed to reach server: ' + err.message, 'error');
    }
  }

  // Quality dropdown change
  qualitySelect.addEventListener('change', () => {
    saveSettings();
  });

  // Open settings
  openStorageBtn.addEventListener('click', () => {
    loadSettings();
    settingsModal.classList.remove('hidden');
  });

  openSettingsBtn.addEventListener('click', () => {
    loadSettings();
    settingsModal.classList.remove('hidden');
  });

  closeSettingsModal.addEventListener('click', () => settingsModal.classList.add('hidden'));
  cancelSettingsBtn.addEventListener('click', () => settingsModal.classList.add('hidden'));
  saveSettingsBtn.addEventListener('click', saveSettings);

  // =========================================================================
  // Search Mode Tabs (Songs vs Playlists)
  // =========================================================================
  function setSearchType(type) {
    currentSearchType = type;
    if (type === 'playlists') {
      tabPlaylistsBtn.classList.add('active');
      tabSongsBtn.classList.remove('active');
      searchInput.placeholder = "Search complete karaoke playlists (e.g. Queen, Anos 80, Sertanejo)...";
      resultsTitle.textContent = "Recommended Playlists";
    } else {
      tabSongsBtn.classList.add('active');
      tabPlaylistsBtn.classList.remove('active');
      searchInput.placeholder = "Search karaoke songs, artists or paste YouTube video / playlist link...";
      resultsTitle.textContent = "Recommended Songs";
    }

    const q = searchInput.value.trim();
    if (q) {
      performSearch(q);
    }
  }

  if (tabSongsBtn) tabSongsBtn.addEventListener('click', () => setSearchType('videos'));
  if (tabPlaylistsBtn) tabPlaylistsBtn.addEventListener('click', () => setSearchType('playlists'));

  // =========================================================================
  // YouTube Search & Results
  // =========================================================================
  async function performSearch(query) {
    const q = (query || searchInput.value).trim();
    if (!q) return;

    // Check if user pasted a YouTube playlist link directly in search bar
    if (q.includes('youtube.com/playlist') || q.includes('list=')) {
      playlistUrlInput.value = q;
      playlistModal.classList.remove('hidden');
      inspectPlaylist();
      return;
    }

    resultsTitle.textContent = currentSearchType === 'playlists' ? `Playlists for "${q}"` : `Results for "${q}"`;
    resultsCount.textContent = 'Searching...';
    searchLoader.classList.remove('hidden');
    resultsGrid.innerHTML = '';

    try {
      const res = await fetch(`/api/search?type=${currentSearchType}&q=${encodeURIComponent(q)}`);
      const data = await res.json();
      searchLoader.classList.add('hidden');

      if (!data.results || data.results.length === 0) {
        resultsCount.textContent = 'No results found';
        resultsGrid.innerHTML = `
          <div class="empty-queue-placeholder" style="grid-column: 1 / -1; padding: 3rem 1rem;">
            <p>No ${currentSearchType === 'playlists' ? 'playlists' : 'karaoke tracks'} found for "${escapeHtml(q)}"</p>
            <span>Try searching for artist name, genre, or band</span>
          </div>
        `;
        return;
      }

      resultsCount.textContent = `${data.results.length} ${currentSearchType === 'playlists' ? 'playlists' : 'songs'} found`;
      if (currentSearchType === 'playlists') {
        renderPlaylistResults(data.results);
      } else {
        renderSearchResults(data.results);
      }
    } catch (err) {
      searchLoader.classList.add('hidden');
      resultsCount.textContent = 'Search failed';
      showToast('Search error: ' + err.message, 'error');
    }
  }

  function renderSearchResults(items) {
    resultsGrid.innerHTML = '';
    items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'video-card';

      const isEnqueued = enqueuedVideoUrls.has(item.url);

      card.innerHTML = `
        <div class="thumbnail-container">
          <img class="thumbnail-img" src="${escapeHtml(item.thumbnail)}" alt="${escapeHtml(item.title)}" loading="lazy">
          <span class="pi-tag">Pi Zero Ready</span>
          <span class="duration-badge">${escapeHtml(item.duration)}</span>
        </div>
        <div class="card-details">
          <h3 class="card-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h3>
          <span class="card-channel">${escapeHtml(item.channel || 'YouTube')}</span>
          <div class="card-footer">
            <button class="card-btn ${isEnqueued ? 'enqueued' : ''}" data-url="${escapeHtml(item.url)}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              <span>${isEnqueued ? 'In Queue' : 'Add to Queue'}</span>
            </button>
          </div>
        </div>
      `;

      const addBtn = card.querySelector('.card-btn');
      addBtn.addEventListener('click', () => {
        enqueueSingleTrack(item, addBtn);
      });

      resultsGrid.appendChild(card);
    });
  }

  function renderPlaylistResults(items) {
    resultsGrid.innerHTML = '';
    items.forEach(pl => {
      const card = document.createElement('div');
      card.className = 'video-card playlist-card';

      const isEnqueued = enqueuedPlaylistUrls.has(pl.url);

      card.innerHTML = `
        <div class="thumbnail-container">
          <img class="thumbnail-img" src="${escapeHtml(pl.thumbnail)}" alt="${escapeHtml(pl.title)}" loading="lazy">
          <span class="playlist-tag">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="8" y1="6" x2="21" y2="6"/>
              <line x1="8" y1="12" x2="21" y2="12"/>
              <line x1="8" y1="18" x2="21" y2="18"/>
              <line x1="3" y1="6" x2="3.01" y2="6"/>
              <line x1="3" y1="12" x2="3.01" y2="12"/>
              <line x1="3" y1="18" x2="3.01" y2="18"/>
            </svg>
            Playlist
          </span>
          <span class="playlist-count-badge">${escapeHtml(pl.video_count || 'Full List')}</span>
        </div>
        <div class="card-details">
          <h3 class="card-title" title="${escapeHtml(pl.title)}">${escapeHtml(pl.title)}</h3>
          <span class="card-channel">${escapeHtml(pl.channel || pl.uploader || 'YouTube Playlist')}</span>
          <div class="card-footer">
            <div class="playlist-card-actions">
              <button class="card-btn inspect-pl-btn" data-url="${escapeHtml(pl.url)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
                <span>Inspect</span>
              </button>
              <button class="card-btn btn-accent download-pl-btn ${isEnqueued ? 'enqueued' : ''}" data-url="${escapeHtml(pl.url)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="8 17 12 21 16 17"/>
                  <line x1="12" y1="12" x2="12" y2="21"/>
                  <path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"/>
                </svg>
                <span>${isEnqueued ? 'Enqueued' : 'Download All'}</span>
              </button>
            </div>
          </div>
        </div>
      `;

      const inspectBtn = card.querySelector('.inspect-pl-btn');
      inspectBtn.addEventListener('click', () => {
        playlistUrlInput.value = pl.url;
        playlistModal.classList.remove('hidden');
        inspectPlaylist();
      });

      const dlAllBtn = card.querySelector('.download-pl-btn');
      dlAllBtn.addEventListener('click', () => {
        enqueueEntirePlaylist(pl.url, pl.title, dlAllBtn);
      });

      resultsGrid.appendChild(card);
    });
  }

  async function enqueueSingleTrack(item, buttonEl) {
    try {
      const res = await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: item.url,
          title: item.title,
          thumbnail: item.thumbnail,
          quality: qualitySelect.value
        })
      });

      const data = await res.json();
      if (data.status === 'ok') {
        enqueuedVideoUrls.add(item.url);
        if (buttonEl) {
          buttonEl.classList.add('enqueued');
          buttonEl.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            <span>In Queue</span>
          `;
        }
        showToast(`Added "${item.title.substring(0, 32)}..." to queue`, 'success');
        fetchQueueStatus();
      } else {
        showToast(data.message || 'Error enqueuing track', 'error');
      }
    } catch (err) {
      showToast('Failed to enqueue: ' + err.message, 'error');
    }
  }

  // Search input events
  searchBtn.addEventListener('click', () => performSearch());
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') performSearch();
  });

  // Popular tag clicks
  document.querySelectorAll('.genre-tag').forEach(tag => {
    tag.addEventListener('click', () => {
      const query = tag.dataset.tag;
      searchInput.value = query;
      performSearch(query);
    });
  });

  // =========================================================================
  // Download Queue Engine & Real-Time Polling
  // =========================================================================
  async function fetchQueueStatus() {
    try {
      const res = await fetch('/api/queue');
      if (!res.ok) return;
      const data = await res.json();

      updateQueueUI(data);
    } catch (err) {
      console.warn('Queue polling failed:', err);
    }
  }

  function updateQueueUI(data) {
    const tasks = data.queue || [];
    const stats = data.stats || { queued: 0, downloading: 0, completed: 0, total: 0 };
    isQueuePaused = !!data.is_paused;

    // Update pause button
    pauseBtnText.textContent = isQueuePaused ? 'Resume' : 'Pause';

    // Update badges & stats
    const activeAndQueued = stats.downloading + stats.queued;
    queueBadgeCount.textContent = activeAndQueued;
    queuePanelBadge.textContent = activeAndQueued;
    statActive.textContent = stats.downloading;
    statQueued.textContent = stats.queued;
    statCompleted.textContent = stats.completed;

    if (tasks.length === 0) {
      emptyQueueMsg.style.display = 'flex';
      // Remove any existing queue cards
      const cards = queueList.querySelectorAll('.queue-item');
      cards.forEach(c => c.remove());
      return;
    }

    emptyQueueMsg.style.display = 'none';

    // Reconcile queue list items
    const existingElements = new Map();
    queueList.querySelectorAll('.queue-item').forEach(el => {
      existingElements.set(el.dataset.id, el);
    });

    tasks.forEach(task => {
      let itemEl = existingElements.get(task.id);

      if (!itemEl) {
        itemEl = document.createElement('div');
        itemEl.className = `queue-item ${task.status}`;
        itemEl.dataset.id = task.id;
        queueList.appendChild(itemEl);
      } else {
        itemEl.className = `queue-item ${task.status}`;
        existingElements.delete(task.id);
      }

      if (task.status === 'cancelled') {
        if (itemEl) itemEl.remove();
        return;
      }

      // Update card content
      const percent = Math.min(100, Math.max(0, task.progress || 0));
      const speedText = task.speed || '';
      const etaText = task.eta ? `ETA: ${task.eta}` : '';
      const sizeText = task.total_bytes_str || '';

      let statusDescription = 'Waiting in queue...';
      if (task.status === 'downloading') {
        statusDescription = `${percent.toFixed(1)}% • ${speedText} • ${etaText}`;
      } else if (task.status === 'completed') {
        statusDescription = `Completed ✓ (${sizeText || 'H.264 MP4'})`;
        // Schedule auto-leave from download queue after a brief completion confirmation
        setTimeout(() => {
          const el = queueList.querySelector(`.queue-item[data-id="${task.id}"]`);
          if (el) {
            el.style.opacity = '0';
            el.style.transform = 'translateY(-12px)';
            setTimeout(() => el.remove(), 250);
          }
        }, 1200);
      } else if (task.status === 'error') {
        statusDescription = `Failed: ${task.error || 'Download error'}`;
      }

      let actionsHtml = '';
      if (task.status === 'error') {
        actionsHtml = `
          <div class="queue-item-actions">
            <button class="queue-action-btn queue-details-btn" title="View Error Details" data-id="${task.id}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
              </svg>
            </button>
            <button class="queue-action-btn queue-retry-btn" title="Retry Download" data-id="${task.id}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
              </svg>
            </button>
            <button class="queue-cancel-btn" title="Remove from Queue" data-id="${task.id}" data-url="${escapeHtml(task.url || '')}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        `;
      } else {
        actionsHtml = `
          <button class="queue-cancel-btn" title="Remove from Queue" data-id="${task.id}" data-url="${escapeHtml(task.url || '')}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        `;
      }

      itemEl.innerHTML = `
        <div class="queue-item-top">
          <img class="queue-thumb" src="${escapeHtml(task.thumbnail || 'https://i.ytimg.com/vi/default/hqdefault.jpg')}" alt="thumb">
          <div class="queue-meta">
            <div class="queue-title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</div>
            <div class="queue-status-text">${escapeHtml(statusDescription)}</div>
          </div>
          ${actionsHtml}
        </div>
        <div class="progress-container">
          <div class="progress-bar ${task.status}" style="width: ${percent}%"></div>
        </div>
        ${task.status === 'downloading' ? `
          <div class="queue-details-row">
            <span>${escapeHtml(task.downloaded_bytes_str || '0 MB')} / ${escapeHtml(task.total_bytes_str || '...')}</span>
            <span>H.264 Pi-Optimized</span>
          </div>
        ` : ''}
      `;
    });

    // Toggle Retry Failed button in queue header
    const errorCount = (data.errors || []).length;
    if (errorCount > 0) {
      retryAllFailedBtn.classList.remove('hidden');
      retryAllFailedText.textContent = `Retry Failed (${errorCount})`;
    } else {
      retryAllFailedBtn.classList.add('hidden');
    }

    // Keep map updated
    currentTasksMap.clear();
    tasks.forEach(t => currentTasksMap.set(t.id, t));

    // Remove deleted tasks from DOM
    existingElements.forEach(el => el.remove());
  }

  // Delegated event listener for queue item actions (cancel, retry, details)
  queueList.addEventListener('click', (e) => {
    // 1. Details button
    const detailsBtn = e.target.closest('.queue-details-btn');
    if (detailsBtn) {
      e.preventDefault();
      e.stopPropagation();
      const taskId = detailsBtn.dataset.id;
      const task = currentTasksMap.get(taskId);
      if (task) {
        openErrorModal(task);
      }
      return;
    }

    // 2. Retry button
    const retryBtn = e.target.closest('.queue-retry-btn');
    if (retryBtn) {
      e.preventDefault();
      e.stopPropagation();
      const taskId = retryBtn.dataset.id;
      if (taskId) {
        retryTask(taskId);
      }
      return;
    }

    // 3. Cancel button
    const cancelBtn = e.target.closest('.queue-cancel-btn');
    if (!cancelBtn) return;
    e.preventDefault();
    e.stopPropagation();

    const taskId = cancelBtn.dataset.id;
    const taskUrl = cancelBtn.dataset.url;
    if (!taskId) return;

    // Optimistic UI removal: immediately fade out and remove card from DOM
    const card = cancelBtn.closest('.queue-item');
    if (card) {
      card.style.opacity = '0';
      card.style.transform = 'translateX(24px)';
      setTimeout(() => card.remove(), 200);
    }

    // Reset search button if visible
    if (taskUrl) {
      enqueuedVideoUrls.delete(taskUrl);
      enqueuedPlaylistUrls.delete(taskUrl);
      const searchBtns = document.querySelectorAll(`.card-btn[data-url="${escapeHtml(taskUrl)}"]`);
      searchBtns.forEach(btn => {
        btn.classList.remove('enqueued');
        const span = btn.querySelector('span');
        if (span) span.textContent = 'Add to Queue';
      });
    }

    cancelTask(taskId);
  });

  function openErrorModal(task) {
    activeModalTaskId = task.id;
    errorSongTitle.textContent = task.title || 'Unknown Song';
    errorSummaryText.textContent = task.error || 'Download failed with yt-dlp error';
    errorLogOutput.textContent = task.error_details || task.error || 'No detailed yt-dlp log output available.';
    errorModal.classList.remove('hidden');
  }

  function closeErrorDetailsModal() {
    errorModal.classList.add('hidden');
    activeModalTaskId = null;
  }

  closeErrorModal.addEventListener('click', closeErrorDetailsModal);
  closeErrorModalBtn.addEventListener('click', closeErrorDetailsModal);

  copyErrorLogBtn.addEventListener('click', () => {
    const text = errorLogOutput.textContent;
    navigator.clipboard.writeText(text).then(() => {
      showToast('Error log copied to clipboard', 'info');
    }).catch(() => {
      showToast('Could not copy to clipboard', 'warning');
    });
  });

  retryErrorModalBtn.addEventListener('click', () => {
    if (activeModalTaskId) {
      retryTask(activeModalTaskId);
      closeErrorDetailsModal();
    }
  });

  async function retryTask(taskId) {
    // Optimistic status update in UI
    const card = queueList.querySelector(`.queue-item[data-id="${taskId}"]`);
    if (card) {
      card.className = 'queue-item queued';
      const statusText = card.querySelector('.queue-status-text');
      if (statusText) statusText.textContent = 'Re-queued for download...';
      const bar = card.querySelector('.progress-bar');
      if (bar) {
        bar.className = 'progress-bar queued';
        bar.style.width = '0%';
      }
    }

    try {
      const res = await fetch('/api/queue/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('Download re-queued successfully', 'success');
        fetchQueueStatus();
      } else {
        showToast(data.error || 'Failed to retry download', 'error');
      }
    } catch (err) {
      showToast('Failed to retry download: ' + err.message, 'error');
    }
  }

  retryAllFailedBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/queue/retry-all', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        const count = data.retried_count || 0;
        showToast(count > 0 ? `Re-queued ${count} failed download(s)` : 'No failed downloads to retry', 'success');
        fetchQueueStatus();
      } else {
        showToast(data.error || 'Error retrying downloads', 'error');
      }
    } catch (err) {
      showToast('Failed to retry downloads: ' + err.message, 'error');
    }
  });

  async function cancelTask(taskId) {
    try {
      const res = await fetch('/api/queue/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        fetchQueueStatus();
        showToast('Item removed from download list', 'info');
      }
    } catch (err) {
      showToast('Failed to remove item: ' + err.message, 'error');
    }
  }

  // Pause / Resume queue
  pauseQueueBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/queue/pause', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        isQueuePaused = data.is_paused;
        pauseBtnText.textContent = isQueuePaused ? 'Resume' : 'Pause';
        showToast(isQueuePaused ? 'Queue paused' : 'Queue resumed', 'info');
      }
    } catch (err) {
      showToast('Error toggling queue pause', 'error');
    }
  });

  // Clear completed tasks
  clearCompletedBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/queue/clear', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        fetchQueueStatus();
        showToast('Cleared completed downloads', 'info');
      }
    } catch (err) {
      showToast('Error clearing queue', 'error');
    }
  });

  // Toggle mobile queue panel
  toggleQueueBtn.addEventListener('click', () => {
    queuePanel.classList.toggle('open');
  });

  // =========================================================================
  // Playlist Inspector & Modal Import
  // =========================================================================
  openPlaylistModalBtn.addEventListener('click', () => {
    playlistModal.classList.remove('hidden');
    playlistUrlInput.focus();
  });

  closePlaylistModal.addEventListener('click', () => playlistModal.classList.add('hidden'));
  cancelPlaylistBtn.addEventListener('click', () => playlistModal.classList.add('hidden'));

  async function inspectPlaylist() {
    const url = playlistUrlInput.value.trim();
    if (!url) {
      showToast('Please enter a playlist URL', 'warning');
      return;
    }

    playlistLoader.classList.remove('hidden');
    playlistContent.classList.add('hidden');

    try {
      const res = await fetch(`/api/playlist?url=${encodeURIComponent(url)}`);
      const data = await res.json();
      playlistLoader.classList.add('hidden');

      if (!res.ok || data.error) {
        showToast(data.error || 'Failed to inspect playlist', 'error');
        return;
      }

      currentPlaylistTracks = data.items || [];
      playlistTitle.textContent = data.title || 'YouTube Playlist';
      playlistStats.textContent = `${currentPlaylistTracks.length} tracks found`;
      playlistContent.classList.remove('hidden');

      renderPlaylistItems(currentPlaylistTracks);
      updateSelectedPlaylistCount();
    } catch (err) {
      playlistLoader.classList.add('hidden');
      showToast('Error loading playlist: ' + err.message, 'error');
    }
  }

  function renderPlaylistItems(items) {
    playlistItemsList.innerHTML = '';
    items.forEach((track, idx) => {
      const row = document.createElement('label');
      row.className = 'playlist-item-row';
      row.innerHTML = `
        <input type="checkbox" class="playlist-check" data-index="${idx}" checked>
        <img class="playlist-row-thumb" src="${escapeHtml(track.thumbnail)}" alt="thumb">
        <span class="playlist-row-title">${escapeHtml(track.title)}</span>
        <span class="playlist-row-duration">${escapeHtml(track.duration || '')}</span>
      `;

      const check = row.querySelector('.playlist-check');
      check.addEventListener('change', updateSelectedPlaylistCount);

      playlistItemsList.appendChild(row);
    });
  }

  function updateSelectedPlaylistCount() {
    const checked = playlistItemsList.querySelectorAll('.playlist-check:checked');
    selectedPlaylistCount.textContent = checked.length;
    enqueuePlaylistBtn.disabled = checked.length === 0;
  }

  selectAllPlaylistBtn.addEventListener('click', () => {
    playlistItemsList.querySelectorAll('.playlist-check').forEach(c => (c.checked = true));
    updateSelectedPlaylistCount();
  });

  deselectAllPlaylistBtn.addEventListener('click', () => {
    playlistItemsList.querySelectorAll('.playlist-check').forEach(c => (c.checked = false));
    updateSelectedPlaylistCount();
  });

  inspectPlaylistBtn.addEventListener('click', inspectPlaylist);
  playlistUrlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') inspectPlaylist();
  });

  enqueuePlaylistBtn.addEventListener('click', async () => {
    const checked = playlistItemsList.querySelectorAll('.playlist-check:checked');
    if (checked.length === 0) return;

    const selectedTracks = [];
    checked.forEach(c => {
      const idx = parseInt(c.dataset.index, 10);
      if (currentPlaylistTracks[idx]) {
        selectedTracks.push(currentPlaylistTracks[idx]);
      }
    });

    try {
      const res = await fetch('/api/download/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: selectedTracks,
          quality: qualitySelect.value
        })
      });

      const data = await res.json();
      if (data.status === 'ok') {
        playlistModal.classList.add('hidden');
        showToast(`Enqueued ${selectedTracks.length} tracks from playlist!`, 'success');
        fetchQueueStatus();
      } else {
        showToast(data.message || 'Error enqueuing playlist', 'error');
      }
    } catch (err) {
      showToast('Batch error: ' + err.message, 'error');
    }
  });

  async function enqueueEntirePlaylist(playlistUrl, playlistTitle, buttonEl) {
    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.innerHTML = `<span>Analyzing...</span>`;
    }
    showToast(`Analyzing and enqueuing complete playlist...`, 'info');

    try {
      const res = await fetch('/api/download/playlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: playlistUrl,
          quality: qualitySelect.value
        })
      });

      const data = await res.json();
      if (data.status === 'ok') {
        enqueuedPlaylistUrls.add(playlistUrl);
        showToast(`Enqueued complete playlist "${data.playlist_title || playlistTitle}" (${data.enqueued_count} songs)!`, 'success');
        fetchQueueStatus();
        if (buttonEl) {
          buttonEl.classList.add('enqueued');
          buttonEl.innerHTML = `<span>Enqueued (${data.enqueued_count})</span>`;
        }
        playlistModal.classList.add('hidden');
      } else {
        showToast(data.error || 'Failed to enqueue playlist', 'error');
        if (buttonEl) {
          buttonEl.disabled = false;
          buttonEl.innerHTML = `<span>Download All</span>`;
        }
      }
    } catch (err) {
      showToast('Playlist error: ' + err.message, 'error');
      if (buttonEl) {
        buttonEl.disabled = false;
        buttonEl.innerHTML = `<span>Download All</span>`;
      }
    }
  }

  if (downloadEntirePlaylistBtn) {
    downloadEntirePlaylistBtn.addEventListener('click', () => {
      const url = playlistUrlInput.value.trim();
      const title = playlistTitle.textContent;
      if (url) {
        enqueueEntirePlaylist(url, title, downloadEntirePlaylistBtn);
      }
    });
  }

  // =========================================================================
  // Batch Text List Import Modal
  // =========================================================================
  openBatchModalBtn.addEventListener('click', () => {
    batchModal.classList.remove('hidden');
    batchTextArea.focus();
  });

  closeBatchModal.addEventListener('click', () => batchModal.classList.add('hidden'));
  cancelBatchBtn.addEventListener('click', () => batchModal.classList.add('hidden'));

  batchTextArea.addEventListener('input', () => {
    const lines = batchTextArea.value.split('\n').filter(l => l.trim().length > 0);
    batchLineCount.textContent = `${lines.length} songs detected`;
  });

  enqueueBatchBtn.addEventListener('click', async () => {
    const lines = batchTextArea.value.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    if (lines.length === 0) {
      showToast('Please paste at least one song or link', 'warning');
      return;
    }

    const items = lines.map(line => {
      if (line.startsWith('http://') || line.startsWith('https://')) {
        return { url: line, title: line, thumbnail: '' };
      }
      return { url: `ytsearch1:${line}`, title: line, thumbnail: '' };
    });

    try {
      const res = await fetch('/api/download/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: items,
          quality: qualitySelect.value
        })
      });

      const data = await res.json();
      if (data.status === 'ok') {
        batchModal.classList.add('hidden');
        batchTextArea.value = '';
        batchLineCount.textContent = '0 songs detected';
        showToast(`Enqueued ${items.length} songs from list!`, 'success');
        fetchQueueStatus();
      } else {
        showToast(data.message || 'Error enqueuing batch list', 'error');
      }
    } catch (err) {
      showToast('Error submitting batch: ' + err.message, 'error');
    }
  });

  // =========================================================================
  // Utilities
  // =========================================================================
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // =========================================================================
  // Initial Run
  // =========================================================================
  loadSettings();
  fetchQueueStatus();
  // Poll queue every 1 second
  setInterval(fetchQueueStatus, 1000);

  // Trigger default popular search on startup for instant visual engagement
  performSearch('Queen Karaoke');
});
