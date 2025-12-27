/**
 * Corvid Cache - yt-dlp Web Interface
 *
 * Main JavaScript application for the Corvid Cache web UI.
 * Handles all frontend functionality including:
 * - WebSocket connection for real-time progress updates
 * - Download management (create, cancel, retry)
 * - Playlist/channel browsing and video selection
 * - File browsing
 * - Theme switching (dark/light mode)
 * - Settings persistence
 */

/**
 * Main application class.
 * Manages UI state, WebSocket connection, and API interactions.
 */
class YtdlApp {
    /** @type {string} Default output path template for downloads */
    static DEFAULT_OUTPUT_TEMPLATE = '%(channel)s/%(upload_date)s_%(title)s.%(ext)s';

    constructor() {
        /** @type {WebSocket|null} WebSocket connection for real-time updates */
        this.ws = null;
        /** @type {Map<number, object>} Map of download ID to download data */
        this.downloads = new Map();
        /** @type {object|null} Currently displayed playlist data */
        this.currentPlaylist = null;
        /** @type {number} Current page number for downloads pagination */
        this.currentPage = 1;
        /** @type {number} Total number of pages for downloads */
        this.totalPages = 1;
        this.init();
    }

    /**
     * Initialize the application.
     * Sets up theme, WebSocket, event listeners, and loads initial data.
     */
    init() {
        this.initTheme();
        this.setupWebSocket();
        this.setupEventListeners();
        this.loadDownloads();
        this.loadFiles();
        this.loadCookieStatus();
        this.loadSubscriptions();
        this.loadDownloadOptions();
        this.checkYtdlpVersion();
        this.initTooltips();
    }

    initTooltips() {
        // Initialize all Bootstrap tooltips with auto-hide settings
        const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
        tooltipTriggerList.forEach(el => {
            // Dispose any existing tooltip first
            const existing = bootstrap.Tooltip.getInstance(el);
            if (existing) existing.dispose();

            new bootstrap.Tooltip(el, {
                trigger: 'hover',
                delay: { show: 500, hide: 0 }
            });
        });

        // Hide all tooltips when clicking anywhere
        document.addEventListener('click', () => this.hideAllTooltips(), { capture: true });
    }

    // Theme Management
    initTheme() {
        // Check for saved theme preference or use system preference
        const savedTheme = localStorage.getItem('theme');
        const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

        if (savedTheme) {
            this.setTheme(savedTheme);
        } else if (systemPrefersDark) {
            this.setTheme('dark');
        } else {
            this.setTheme('light');
        }

        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (!localStorage.getItem('theme')) {
                this.setTheme(e.matches ? 'dark' : 'light');
            }
        });
    }

    setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        const icon = document.querySelector('#theme-toggle i');
        if (theme === 'dark') {
            icon.classList.remove('bi-moon-fill');
            icon.classList.add('bi-sun-fill');
        } else {
            icon.classList.remove('bi-sun-fill');
            icon.classList.add('bi-moon-fill');
        }
    }

    toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        this.setTheme(newTheme);
        localStorage.setItem('theme', newTheme);
    }

    // WebSocket
    setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            document.getElementById('ws-status').classList.remove('bg-danger');
            document.getElementById('ws-status').classList.add('bg-success');
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            document.getElementById('ws-status').classList.remove('bg-success');
            document.getElementById('ws-status').classList.add('bg-danger');
            // Reconnect after 3 seconds
            setTimeout(() => this.setupWebSocket(), 3000);
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
    }

    handleWebSocketMessage(data) {
        const card = document.querySelector(`[data-download-id="${data.id}"]`);
        if (!card) return;

        // Debug logging for state transitions
        if (data.type !== 'progress' || data.progress >= 99) {
            console.log(`[WS ${data.id}] type=${data.type} status=${data.status} progress=${data.progress}`);
        }

        switch (data.type) {
            case 'status':
            case 'info':
                if (data.title) {
                    card.querySelector('.title').textContent = data.title;
                }
                if (data.thumbnail) {
                    const container = card.querySelector('.download-thumbnail-container');
                    if (container) {
                        container.innerHTML = `<img src="${data.thumbnail}" class="download-thumbnail" alt="" onerror="this.style.display='none'">`;
                    }
                }
                if (data.source) {
                    const badgeContainer = card.querySelector('.d-flex.gap-1');
                    if (badgeContainer && !badgeContainer.querySelector('.source-badge')) {
                        badgeContainer.insertAdjacentHTML('afterbegin', this.getSourceBadge(data.source));
                    }
                }
                this.updateStatus(card, data.status);
                break;

            case 'progress':
                const progressBar = card.querySelector('.progress-bar');
                const statsEl = card.querySelector('.stats');
                progressBar.style.width = `${data.progress}%`;
                progressBar.textContent = `${data.progress.toFixed(1)}%`;

                let statsText = '';
                if (data.speed) statsText += `Speed: ${data.speed}`;
                if (data.eta) statsText += ` | ETA: ${data.eta}`;
                statsEl.textContent = statsText;
                break;

            case 'processing':
                this.updateStatus(card, 'processing');
                const procProgressBar = card.querySelector('.progress-bar');
                const procStatsEl = card.querySelector('.stats');
                procProgressBar.style.width = '100%';
                procProgressBar.textContent = '100%';
                procStatsEl.textContent = data.processing_step || 'Processing...';
                break;

            case 'completed':
                this.updateStatus(card, 'completed');
                card.querySelector('.progress-bar').style.width = '100%';
                card.querySelector('.progress-bar').textContent = '100%';
                card.querySelector('.stats').textContent = 'Download complete';
                this.loadFiles(); // Refresh file list
                break;

            case 'error':
                this.updateStatus(card, 'failed');
                card.querySelector('.stats').textContent = `Error: ${data.error}`;
                this.updateCardButtons(card, data.id, 'failed');
                break;

            case 'cancelled':
                this.updateStatus(card, 'cancelled');
                card.querySelector('.stats').textContent = 'Download cancelled';
                card.querySelector('.progress-bar').style.width = '0%';
                card.querySelector('.progress-bar').textContent = '';
                this.updateCardButtons(card, data.id, 'cancelled');
                break;
        }
    }

    updateStatus(card, status) {
        const badge = card.querySelector('.status-badge');
        const downloadId = card.getAttribute('data-download-id');
        console.log(`[Badge ${downloadId}] Updating to: ${status}`);
        badge.className = `badge status-badge status-${status}`;
        badge.textContent = status.replace('_', ' ');
    }

    updateCardButtons(card, downloadId, status) {
        const btnContainer = card.querySelector('.d-flex.gap-2');
        if (!btnContainer) return;

        const canRetry = status === 'failed' || status === 'cancelled';
        const existingRetryBtn = btnContainer.querySelector('.btn-outline-primary');

        if (canRetry && !existingRetryBtn) {
            const retryBtn = document.createElement('button');
            retryBtn.className = 'btn btn-sm btn-outline-primary';
            retryBtn.title = 'Retry download';
            retryBtn.setAttribute('data-bs-toggle', 'tooltip');
            retryBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
            retryBtn.onclick = () => this.retryDownload(downloadId);
            btnContainer.insertBefore(retryBtn, btnContainer.firstChild);

            // Initialize tooltip for new button
            new bootstrap.Tooltip(retryBtn, {
                trigger: 'hover',
                delay: { show: 500, hide: 0 }
            });
        }

        // Update delete button title
        const deleteBtn = btnContainer.querySelector('.btn-outline-danger');
        if (deleteBtn) {
            deleteBtn.title = 'Remove from list';
            // Refresh tooltip
            const tooltip = bootstrap.Tooltip.getInstance(deleteBtn);
            if (tooltip) {
                tooltip.dispose();
            }
            new bootstrap.Tooltip(deleteBtn, {
                trigger: 'hover',
                delay: { show: 500, hide: 0 }
            });
        }
    }

    // Event Listeners
    setupEventListeners() {
        // URL form submission
        document.getElementById('url-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleUrlSubmit();
        });

        // Tab switching
        document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                if (e.target.id === 'files-tab') {
                    this.loadFiles();
                } else if (e.target.id === 'downloads-tab') {
                    this.loadDownloads();
                }
            });
        });

        // Playlist modal buttons
        document.getElementById('select-all-btn').addEventListener('click', () => {
            document.querySelectorAll('#playlist-entries input[type="checkbox"]').forEach(cb => {
                cb.checked = true;
            });
            this.updateSelectedCount();
        });

        document.getElementById('select-none-btn').addEventListener('click', () => {
            document.querySelectorAll('#playlist-entries input[type="checkbox"]').forEach(cb => {
                cb.checked = false;
            });
            this.updateSelectedCount();
        });

        document.getElementById('select-new-btn').addEventListener('click', () => {
            document.querySelectorAll('#playlist-entries input[type="checkbox"]').forEach(cb => {
                const entry = cb.closest('.playlist-entry');
                cb.checked = !entry.classList.contains('already-downloaded');
            });
            this.updateSelectedCount();
        });

        document.getElementById('deselect-members-btn').addEventListener('click', () => {
            document.querySelectorAll('#playlist-entries .members-only input[type="checkbox"]').forEach(cb => {
                cb.checked = false;
            });
            this.updateSelectedCount();
        });

        document.getElementById('download-selected-btn').addEventListener('click', () => {
            this.downloadSelectedFromPlaylist();
        });

        // Cookie management
        document.getElementById('upload-cookies-btn').addEventListener('click', () => {
            this.uploadCookies();
        });

        document.getElementById('verify-cookies-btn').addEventListener('click', () => {
            this.verifyCookies();
        });

        document.getElementById('delete-cookies-btn').addEventListener('click', () => {
            this.deleteCookies();
        });

        // Refresh cookie status when modal opens
        document.getElementById('cookies-modal').addEventListener('show.bs.modal', () => {
            this.loadCookieStatus();
        });

        // Auto-switch output format when quality changes
        document.getElementById('format-select').addEventListener('change', (e) => {
            const outputFormat = document.getElementById('output-format-select');
            const isAudioOnly = e.target.value.includes('bestaudio') && !e.target.value.includes('bestvideo');

            if (isAudioOnly) {
                // Switch to MP3 if currently on a video format
                const videoFormats = ['mp4', 'mkv', 'webm', 'avi', 'mov'];
                if (videoFormats.includes(outputFormat.value)) {
                    outputFormat.value = 'mp3';
                }
            } else {
                // Switch to MP4 if currently on an audio format
                const audioFormats = ['mp3', 'm4a', 'opus', 'flac', 'wav'];
                if (audioFormats.includes(outputFormat.value)) {
                    outputFormat.value = 'mp4';
                }
            }
        });

        // Theme toggle
        document.getElementById('theme-toggle').addEventListener('click', () => {
            this.toggleTheme();
        });

        // Subscription management
        document.getElementById('add-subscription-btn').addEventListener('click', () => {
            this.addSubscription();
        });

        // Tab switching for subscriptions
        document.getElementById('subscriptions-tab').addEventListener('shown.bs.tab', () => {
            this.loadSubscriptions();
        });

        // yt-dlp version management
        document.getElementById('check-version-btn').addEventListener('click', () => {
            this.checkYtdlpVersion(true);
        });

        document.getElementById('update-ytdlp-btn').addEventListener('click', () => {
            this.updateYtdlp();
        });

        // Maintenance modal
        document.getElementById('maintenance-modal').addEventListener('show.bs.modal', () => {
            this.loadMaintenanceStats();
            this.loadLogSize();
        });
    }

    // URL Handling
    async handleUrlSubmit() {
        const urlInput = document.getElementById('url-input');
        const url = urlInput.value.trim();
        if (!url) return;

        this.showLoading(true);

        try {
            // First, extract info to determine type
            const response = await fetch('/api/extract', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });

            if (!response.ok) {
                throw new Error('Failed to extract info');
            }

            const info = await response.json();

            if (info.type === 'video') {
                // Single video - download directly
                await this.createDownload(url);
                urlInput.value = '';
            } else {
                // Playlist or channel - show selection modal
                this.showPlaylistModal(url, info);
            }
        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            this.showLoading(false);
        }
    }

    async showPlaylistModal(url, info) {
        this.currentPlaylist = { url, info };

        document.getElementById('playlist-title').textContent = info.title;
        document.getElementById('playlist-count').textContent = `${info.count} videos`;

        // Show loading state
        document.getElementById('playlist-entries').innerHTML = `
            <div class="text-center py-4">
                <div class="spinner-border" role="status"></div>
                <div class="mt-2">Loading playlist...</div>
            </div>
        `;

        const modal = new bootstrap.Modal(document.getElementById('playlist-modal'));
        modal.show();

        // Fetch full playlist
        try {
            const response = await fetch('/api/playlist', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });

            if (!response.ok) throw new Error('Failed to load playlist');

            const playlist = await response.json();
            this.renderPlaylistEntries(playlist.entries);
        } catch (error) {
            document.getElementById('playlist-entries').innerHTML = `
                <div class="alert alert-danger">Error loading playlist: ${error.message}</div>
            `;
        }
    }

    renderPlaylistEntries(entries) {
        const container = document.getElementById('playlist-entries');
        container.innerHTML = '';

        entries.forEach((entry, index) => {
            const div = document.createElement('div');
            let classes = 'playlist-entry';
            if (entry.already_downloaded) classes += ' already-downloaded';
            if (entry.members_only) classes += ' members-only';
            div.className = classes;

            div.innerHTML = `
                <input type="checkbox" class="form-check-input me-3"
                    data-video-id="${entry.video_id}"
                    ${!entry.already_downloaded ? 'checked' : ''}>
                <img src="${entry.thumbnail || '/static/img/placeholder.png'}"
                    class="thumbnail" alt=""
                    onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22120%22 height=%2268%22><rect fill=%22%23e9ecef%22 width=%22100%%22 height=%22100%%22/></svg>'">
                <div class="info">
                    <div class="title">${entry.title}</div>
                    <div class="meta">
                        ${entry.duration_string || ''}
                        ${entry.uploader ? `| ${entry.uploader}` : ''}
                        ${entry.members_only ? '<span class="members-badge ms-2"><i class="bi bi-star-fill"></i> Members Only</span>' : ''}
                        ${entry.already_downloaded ? '<span class="downloaded-badge ms-2"><i class="bi bi-check-circle-fill"></i> Downloaded</span>' : ''}
                    </div>
                </div>
            `;

            div.querySelector('input').addEventListener('change', () => this.updateSelectedCount());
            container.appendChild(div);
        });

        this.updateSelectedCount();
    }

    updateSelectedCount() {
        const checked = document.querySelectorAll('#playlist-entries input[type="checkbox"]:checked').length;
        const total = document.querySelectorAll('#playlist-entries input[type="checkbox"]').length;
        document.getElementById('selected-count').textContent = `${checked} of ${total} selected`;
    }

    async downloadSelectedFromPlaylist() {
        const checkboxes = document.querySelectorAll('#playlist-entries input[type="checkbox"]:checked');
        if (checkboxes.length === 0) {
            alert('Please select at least one video');
            return;
        }

        const options = this.getDownloadOptions();

        // Save options for next session
        this.saveDownloadOptions(options);

        const urls = [];

        checkboxes.forEach(cb => {
            const videoId = cb.dataset.videoId;
            urls.push(`https://www.youtube.com/watch?v=${videoId}`);
        });

        this.showLoading(true);

        try {
            const response = await fetch('/api/downloads/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls, options })
            });

            if (!response.ok) throw new Error('Failed to create downloads');

            // Close modal and clear input
            bootstrap.Modal.getInstance(document.getElementById('playlist-modal')).hide();
            document.getElementById('url-input').value = '';

            // Switch to downloads tab and refresh list with pagination
            document.getElementById('downloads-tab').click();
            this.loadDownloads();
        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            this.showLoading(false);
        }
    }

    // Downloads
    async createDownload(url) {
        const options = this.getDownloadOptions();

        // Save options for next session
        this.saveDownloadOptions(options);

        const response = await fetch('/api/downloads', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, options })
        });

        if (!response.ok) throw new Error('Failed to create download');

        // Switch to downloads tab and refresh list with pagination
        document.getElementById('downloads-tab').click();
        this.loadDownloads();
    }

    getDownloadOptions() {
        return {
            format: document.getElementById('format-select').value,
            output_format: document.getElementById('output-format-select').value,
            output_template: document.getElementById('output-template').value || YtdlApp.DEFAULT_OUTPUT_TEMPLATE,
            subtitles: document.getElementById('subtitles-check').checked,
            subtitle_langs: ['en'],
            embed_thumbnail: document.getElementById('thumbnail-check').checked,
            embed_metadata: document.getElementById('metadata-check').checked
        };
    }

    async loadDownloadOptions() {
        try {
            const response = await fetch('/api/settings/download-options');
            const options = await response.json();

            if (options.format) {
                document.getElementById('format-select').value = options.format;
            }
            if (options.output_format) {
                document.getElementById('output-format-select').value = options.output_format;
            }
            if (options.output_template) {
                document.getElementById('output-template').value = options.output_template;
            }
            if (options.subtitles !== undefined) {
                document.getElementById('subtitles-check').checked = options.subtitles;
            }
            if (options.embed_thumbnail !== undefined) {
                document.getElementById('thumbnail-check').checked = options.embed_thumbnail;
            }
            if (options.embed_metadata !== undefined) {
                document.getElementById('metadata-check').checked = options.embed_metadata;
            }
        } catch (error) {
            console.error('Failed to load download options:', error);
        }
    }

    async saveDownloadOptions(options) {
        try {
            await fetch('/api/settings/download-options', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(options)
            });
        } catch (error) {
            console.error('Failed to save download options:', error);
        }
    }

    resetOutputPath() {
        document.getElementById('output-template').value = YtdlApp.DEFAULT_OUTPUT_TEMPLATE;
    }

    async loadDownloads(page = 1) {
        try {
            const response = await fetch(`/api/downloads?page=${page}&limit=25`);
            const data = await response.json();

            this.currentPage = data.page;
            this.totalPages = data.pages;

            const container = document.getElementById('downloads-list');
            container.innerHTML = '';

            if (data.downloads.length === 0 && data.total === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <i class="bi bi-download"></i>
                        <p>No downloads yet</p>
                    </div>
                `;
                this.updatePaginationControls();
                return;
            }

            // Sort downloads: active first, then by newest
            const activeStatuses = ['downloading', 'processing', 'fetching_info', 'queued'];
            const sortedDownloads = data.downloads.sort((a, b) => {
                const aActive = activeStatuses.includes(a.status);
                const bActive = activeStatuses.includes(b.status);

                // Active downloads come first
                if (aActive && !bActive) return -1;
                if (!aActive && bActive) return 1;

                // Within same group, sort by ID descending (newest first)
                return b.id - a.id;
            });

            sortedDownloads.forEach(dl => this.addDownloadCard(dl, container));

            this.updatePaginationControls();
        } catch (error) {
            console.error('Failed to load downloads:', error);
        }
    }

    updatePaginationControls() {
        const actionsDiv = document.getElementById('downloads-actions');
        let paginationDiv = document.getElementById('downloads-pagination');

        if (this.totalPages <= 1) {
            if (paginationDiv) paginationDiv.remove();
            return;
        }

        if (!paginationDiv) {
            paginationDiv = document.createElement('div');
            paginationDiv.id = 'downloads-pagination';
            paginationDiv.className = 'd-flex justify-content-center mt-3';
            document.getElementById('downloads-list').after(paginationDiv);
        }

        let paginationHtml = '<nav><ul class="pagination pagination-sm mb-0">';

        // Previous button
        paginationHtml += `
            <li class="page-item ${this.currentPage === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" onclick="app.loadDownloads(${this.currentPage - 1}); return false;">
                    <i class="bi bi-chevron-left"></i>
                </a>
            </li>
        `;

        // Page numbers
        const maxVisible = 5;
        let startPage = Math.max(1, this.currentPage - Math.floor(maxVisible / 2));
        let endPage = Math.min(this.totalPages, startPage + maxVisible - 1);
        startPage = Math.max(1, endPage - maxVisible + 1);

        if (startPage > 1) {
            paginationHtml += `<li class="page-item"><a class="page-link" href="#" onclick="app.loadDownloads(1); return false;">1</a></li>`;
            if (startPage > 2) {
                paginationHtml += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            paginationHtml += `
                <li class="page-item ${i === this.currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="app.loadDownloads(${i}); return false;">${i}</a>
                </li>
            `;
        }

        if (endPage < this.totalPages) {
            if (endPage < this.totalPages - 1) {
                paginationHtml += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
            }
            paginationHtml += `<li class="page-item"><a class="page-link" href="#" onclick="app.loadDownloads(${this.totalPages}); return false;">${this.totalPages}</a></li>`;
        }

        // Next button
        paginationHtml += `
            <li class="page-item ${this.currentPage === this.totalPages ? 'disabled' : ''}">
                <a class="page-link" href="#" onclick="app.loadDownloads(${this.currentPage + 1}); return false;">
                    <i class="bi bi-chevron-right"></i>
                </a>
            </li>
        `;

        paginationHtml += '</ul></nav>';
        paginationDiv.innerHTML = paginationHtml;
    }

    addDownloadCard(download, container = null) {
        if (!container) {
            container = document.getElementById('downloads-list');
        }

        // Remove empty state if present
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) emptyState.remove();

        // Check if card already exists
        const existingCard = container.querySelector(`[data-download-id="${download.id}"]`);
        if (existingCard) return;

        const card = document.createElement('div');
        card.className = 'download-card';
        card.dataset.downloadId = download.id;
        const canRetry = download.status === 'failed' || download.status === 'cancelled';
        const isActive = ['queued', 'fetching_info', 'downloading', 'processing'].includes(download.status);

        const thumbnailHtml = download.thumbnail
            ? `<img src="${download.thumbnail}" class="download-thumbnail" alt="" onerror="this.style.display='none'">`
            : '<div class="download-thumbnail-placeholder"><i class="bi bi-film"></i></div>';

        const sourceHtml = download.source ? this.getSourceBadge(download.source) : '';

        card.innerHTML = `
            <div class="d-flex gap-3">
                <div class="download-thumbnail-container">
                    ${thumbnailHtml}
                </div>
                <div class="flex-grow-1">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <div class="title">${download.title || 'Fetching info...'}</div>
                        <div class="d-flex gap-1">
                            ${sourceHtml}
                            <span class="badge status-badge status-${download.status}">${download.status.replace('_', ' ')}</span>
                        </div>
                    </div>
                    <div class="url">${download.url}</div>
                    <div class="progress mb-2">
                        <div class="progress-bar bg-danger" role="progressbar" style="width: ${download.progress}%">${download.progress.toFixed(1)}%</div>
                    </div>
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="stats">
                            ${download.speed ? `Speed: ${download.speed}` : ''}
                            ${download.eta ? ` | ETA: ${download.eta}` : ''}
                            ${download.status === 'completed' ? 'Download complete' : ''}
                            ${download.error_message ? `Error: ${download.error_message}` : ''}
                        </div>
                        <div class="d-flex gap-2">
                            ${canRetry ? `
                                <button class="btn btn-sm btn-outline-primary" onclick="app.retryDownload(${download.id})" title="Retry download" data-bs-toggle="tooltip">
                                    <i class="bi bi-arrow-clockwise"></i>
                                </button>
                            ` : ''}
                            <button class="btn btn-sm btn-outline-danger" onclick="app.cancelDownload(${download.id})" title="${isActive ? 'Cancel download' : 'Remove from list'}" data-bs-toggle="tooltip">
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        container.prepend(card);

        // Initialize tooltips for the new card
        card.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            new bootstrap.Tooltip(el, {
                trigger: 'hover',
                delay: { show: 500, hide: 0 }
            });
        });
    }

    async cancelDownload(id) {
        // Hide any open tooltips before action
        this.hideAllTooltips();

        const card = document.querySelector(`[data-download-id="${id}"]`);
        const statusBadge = card?.querySelector('.status-badge');
        const isActive = statusBadge && ['queued', 'fetching info', 'downloading', 'processing'].includes(statusBadge.textContent.toLowerCase());

        const message = isActive ? 'Cancel this download?' : 'Remove this download from the list?';
        if (!confirm(message)) return;

        try {
            const response = await fetch(`/api/downloads/${id}`, { method: 'DELETE' });
            const data = await response.json();

            if (data.status === 'deleted') {
                // Remove card for deleted downloads
                if (card) card.remove();
            }
            // For cancelled downloads, the WebSocket will update the UI
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    async retryDownload(id, event) {
        // Hide any open tooltips before action
        this.hideAllTooltips();

        try {
            const response = await fetch(`/api/downloads/${id}/retry`, { method: 'POST' });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to retry download');
            }

            // Refresh the downloads list to show updated status
            this.loadDownloads();
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    /**
     * Cancel all active downloads (queued, fetching_info, downloading, processing).
     */
    async cancelAllActive() {
        if (!confirm('Cancel all active downloads?')) return;

        try {
            const response = await fetch('/api/downloads/cancel-all', { method: 'POST' });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to cancel downloads');
            }

            const result = await response.json();
            console.log(`Cancelled ${result.cancelled} downloads`);

            // Refresh the downloads list
            this.loadDownloads();

        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    async clearDownloads(status = null) {
        const statusLabels = {
            'completed': 'completed',
            'cancelled': 'cancelled',
            'failed': 'failed'
        };

        const label = status ? statusLabels[status] : 'all finished';
        if (!confirm(`Clear ${label} downloads?`)) return;

        try {
            const url = status ? `/api/downloads?status=${status}` : '/api/downloads';
            const response = await fetch(url, { method: 'DELETE' });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to clear downloads');
            }

            // Refresh the downloads list
            this.loadDownloads();

        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    hideAllTooltips() {
        // Hide and dispose all tooltips
        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            const tooltip = bootstrap.Tooltip.getInstance(el);
            if (tooltip) {
                tooltip.hide();
                tooltip.dispose();
            }
        });
        // Also remove any orphaned tooltip elements
        document.querySelectorAll('.tooltip').forEach(el => el.remove());
    }

    // Files
    async loadFiles() {
        try {
            const response = await fetch('/api/files');
            const files = await response.json();

            const container = document.getElementById('files-list');
            container.innerHTML = '';

            if (files.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <i class="bi bi-folder2-open"></i>
                        <p>No downloaded files</p>
                    </div>
                `;
                return;
            }

            // Build tree structure from flat file list
            const tree = this.buildFileTree(files);

            // Render the tree
            const treeHtml = this.renderFileTree(tree, 0);
            container.innerHTML = treeHtml;

            // Add click handlers for folder toggles
            container.querySelectorAll('.folder-toggle').forEach(toggle => {
                toggle.addEventListener('click', (e) => {
                    e.preventDefault();
                    const folderItem = toggle.closest('.folder-item');
                    const contents = folderItem.querySelector('.folder-contents');
                    const icon = toggle.querySelector('i');

                    if (contents.style.display === 'none') {
                        contents.style.display = 'block';
                        icon.className = 'bi bi-chevron-down me-1';
                        folderItem.classList.add('expanded');
                    } else {
                        contents.style.display = 'none';
                        icon.className = 'bi bi-chevron-right me-1';
                        folderItem.classList.remove('expanded');
                    }
                });
            });
        } catch (error) {
            console.error('Failed to load files:', error);
        }
    }

    buildFileTree(files) {
        const tree = { folders: {}, files: [] };

        files.forEach(file => {
            const parts = file.name.split(/[/\\]/);
            let current = tree;

            // Navigate/create folder structure
            for (let i = 0; i < parts.length - 1; i++) {
                const folderName = parts[i];
                if (!current.folders[folderName]) {
                    current.folders[folderName] = { folders: {}, files: [] };
                }
                current = current.folders[folderName];
            }

            // Add file to current folder
            current.files.push({
                name: parts[parts.length - 1],
                fullPath: file.name,
                size: file.size,
                modified: file.modified,
                thumbnail: file.thumbnail,
                source: file.source
            });
        });

        return tree;
    }

    renderFileTree(node, depth) {
        let html = '';
        const indent = depth * 20;

        // Sort folders alphabetically
        const folderNames = Object.keys(node.folders).sort((a, b) =>
            a.toLowerCase().localeCompare(b.toLowerCase())
        );

        // Render folders first
        folderNames.forEach(folderName => {
            const folder = node.folders[folderName];
            const fileCount = this.countFilesInFolder(folder);
            const isExpanded = false; // Start collapsed

            html += `
                <div class="folder-item ${isExpanded ? 'expanded' : ''}" style="margin-left: ${indent}px;">
                    <div class="folder-header folder-toggle">
                        <i class="bi bi-chevron-${isExpanded ? 'down' : 'right'} me-1"></i>
                        <i class="bi bi-folder-fill text-warning me-2"></i>
                        <span class="folder-name">${folderName}</span>
                        <span class="folder-count text-muted ms-2">(${fileCount} file${fileCount !== 1 ? 's' : ''})</span>
                    </div>
                    <div class="folder-contents" style="display: ${isExpanded ? 'block' : 'none'};">
                        ${this.renderFileTree(folder, depth + 1)}
                    </div>
                </div>
            `;
        });

        // Sort files by modified date (newest first)
        const sortedFiles = [...node.files].sort((a, b) =>
            new Date(b.modified) - new Date(a.modified)
        );

        // Render files
        sortedFiles.forEach(file => {
            const thumbnailHtml = file.thumbnail
                ? `<img src="${file.thumbnail}" class="file-thumbnail" alt="" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                   <div class="file-thumbnail-placeholder" style="display: none;"><i class="bi bi-file-earmark-play"></i></div>`
                : `<div class="file-thumbnail-placeholder"><i class="bi bi-file-earmark-play"></i></div>`;

            const sourceHtml = file.source ? this.getSourceBadge(file.source) : '';

            html += `
                <div class="file-item" style="margin-left: ${indent}px;">
                    <div class="file-thumbnail-container">
                        ${thumbnailHtml}
                    </div>
                    <div class="file-info">
                        <div class="file-name">${sourceHtml} ${file.name}</div>
                        <div class="file-meta">
                            ${this.formatFileSize(file.size)} | ${new Date(file.modified).toLocaleString()}
                        </div>
                    </div>
                    <a href="/api/files/${encodeURIComponent(file.fullPath)}" class="btn btn-sm btn-outline-primary" download title="Download">
                        <i class="bi bi-download"></i>
                    </a>
                </div>
            `;
        });

        return html;
    }

    countFilesInFolder(folder) {
        let count = folder.files.length;
        for (const subFolder of Object.values(folder.folders)) {
            count += this.countFilesInFolder(subFolder);
        }
        return count;
    }

    // Utilities
    showLoading(show) {
        document.getElementById('loading-overlay').style.display = show ? 'flex' : 'none';
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    getSourceBadge(source) {
        if (!source) return '';

        // Map source names to display info
        const sources = {
            'Youtube': { icon: 'bi-youtube', color: '#ff0000', name: 'YouTube' },
            'youtube': { icon: 'bi-youtube', color: '#ff0000', name: 'YouTube' },
            'Vimeo': { icon: 'bi-vimeo', color: '#1ab7ea', name: 'Vimeo' },
            'vimeo': { icon: 'bi-vimeo', color: '#1ab7ea', name: 'Vimeo' },
            'Twitch': { icon: 'bi-twitch', color: '#9146ff', name: 'Twitch' },
            'twitch': { icon: 'bi-twitch', color: '#9146ff', name: 'Twitch' },
            'Twitter': { icon: 'bi-twitter-x', color: '#000000', name: 'Twitter/X' },
            'twitter': { icon: 'bi-twitter-x', color: '#000000', name: 'Twitter/X' },
            'Reddit': { icon: 'bi-reddit', color: '#ff4500', name: 'Reddit' },
            'reddit': { icon: 'bi-reddit', color: '#ff4500', name: 'Reddit' },
            'TikTok': { icon: 'bi-tiktok', color: '#000000', name: 'TikTok' },
            'tiktok': { icon: 'bi-tiktok', color: '#000000', name: 'TikTok' },
            'Facebook': { icon: 'bi-facebook', color: '#1877f2', name: 'Facebook' },
            'facebook': { icon: 'bi-facebook', color: '#1877f2', name: 'Facebook' },
            'Instagram': { icon: 'bi-instagram', color: '#e4405f', name: 'Instagram' },
            'instagram': { icon: 'bi-instagram', color: '#e4405f', name: 'Instagram' },
            'Dailymotion': { icon: 'bi-play-circle', color: '#00aaff', name: 'Dailymotion' },
            'SoundCloud': { icon: 'bi-soundwave', color: '#ff5500', name: 'SoundCloud' },
            'Spotify': { icon: 'bi-spotify', color: '#1db954', name: 'Spotify' },
        };

        const info = sources[source] || { icon: 'bi-globe', color: '#6c757d', name: source };

        return `<span class="badge source-badge" style="background-color: ${info.color};" title="${info.name}"><i class="${info.icon}"></i></span>`;
    }

    // Cookie Management
    async loadCookieStatus() {
        const statusContent = document.getElementById('cookies-status-content');
        const cookieStatus = document.getElementById('cookie-status');
        const cookieStatusText = document.getElementById('cookie-status-text');

        try {
            const response = await fetch('/api/cookies');
            const data = await response.json();

            if (data.has_cookies) {
                statusContent.innerHTML = `
                    <div class="alert alert-success mb-0">
                        <i class="bi bi-check-circle-fill me-2"></i>
                        <strong>Cookies uploaded</strong><br>
                        <small>File size: ${this.formatFileSize(data.file_size)} | Last modified: ${new Date(data.modified).toLocaleString()}</small>
                    </div>
                `;
                cookieStatus.classList.remove('bg-secondary', 'bg-danger');
                cookieStatus.classList.add('bg-success');
                cookieStatusText.textContent = 'Authenticated';
            } else {
                statusContent.innerHTML = `
                    <div class="alert alert-warning mb-0">
                        <i class="bi bi-exclamation-triangle-fill me-2"></i>
                        <strong>No cookies uploaded</strong><br>
                        <small>Upload cookies to access age-restricted and private content</small>
                    </div>
                `;
                cookieStatus.classList.remove('bg-success', 'bg-danger');
                cookieStatus.classList.add('bg-secondary');
                cookieStatusText.textContent = 'No Auth';
            }
        } catch (error) {
            statusContent.innerHTML = `
                <div class="alert alert-danger mb-0">
                    <i class="bi bi-x-circle-fill me-2"></i>
                    Error checking cookie status
                </div>
            `;
        }
    }

    async uploadCookies() {
        const fileInput = document.getElementById('cookies-file');
        const resultDiv = document.getElementById('cookies-upload-result');

        if (!fileInput.files || fileInput.files.length === 0) {
            resultDiv.innerHTML = '<div class="alert alert-warning py-2">Please select a file</div>';
            return;
        }

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        resultDiv.innerHTML = '<div class="d-flex align-items-center"><div class="spinner-border spinner-border-sm me-2"></div>Uploading...</div>';

        try {
            const response = await fetch('/api/cookies', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                resultDiv.innerHTML = `<div class="alert alert-success py-2"><i class="bi bi-check-circle me-1"></i>${data.message}</div>`;
                fileInput.value = '';
                this.loadCookieStatus();
            } else {
                resultDiv.innerHTML = `<div class="alert alert-danger py-2"><i class="bi bi-x-circle me-1"></i>${data.detail || 'Upload failed'}</div>`;
            }
        } catch (error) {
            resultDiv.innerHTML = `<div class="alert alert-danger py-2"><i class="bi bi-x-circle me-1"></i>Upload failed: ${error.message}</div>`;
        }
    }

    async verifyCookies() {
        const statusContent = document.getElementById('cookies-status-content');
        const cookieStatus = document.getElementById('cookie-status');
        const cookieStatusText = document.getElementById('cookie-status-text');

        statusContent.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                Verifying cookies (this may take a moment)...
            </div>
        `;

        try {
            const response = await fetch('/api/cookies/verify', { method: 'POST' });
            const data = await response.json();

            if (data.valid) {
                statusContent.innerHTML = `
                    <div class="alert alert-success mb-0">
                        <i class="bi bi-check-circle-fill me-2"></i>
                        <strong>Cookies are valid!</strong><br>
                        <small>Successfully authenticated with YouTube</small>
                    </div>
                `;
                cookieStatus.classList.remove('bg-secondary', 'bg-danger');
                cookieStatus.classList.add('bg-success');
                cookieStatusText.textContent = 'Authenticated';
            } else if (!data.has_cookies) {
                statusContent.innerHTML = `
                    <div class="alert alert-warning mb-0">
                        <i class="bi bi-exclamation-triangle-fill me-2"></i>
                        <strong>No cookies uploaded</strong><br>
                        <small>Upload cookies to access age-restricted and private content</small>
                    </div>
                `;
                cookieStatus.classList.remove('bg-success', 'bg-danger');
                cookieStatus.classList.add('bg-secondary');
                cookieStatusText.textContent = 'No Auth';
            } else {
                statusContent.innerHTML = `
                    <div class="alert alert-danger mb-0">
                        <i class="bi bi-x-circle-fill me-2"></i>
                        <strong>Cookies are invalid or expired</strong><br>
                        <small>${data.error || 'Please re-export cookies from your browser'}</small>
                    </div>
                `;
                cookieStatus.classList.remove('bg-success', 'bg-secondary');
                cookieStatus.classList.add('bg-danger');
                cookieStatusText.textContent = 'Expired';
            }
        } catch (error) {
            statusContent.innerHTML = `
                <div class="alert alert-danger mb-0">
                    <i class="bi bi-x-circle-fill me-2"></i>
                    Error verifying cookies: ${error.message}
                </div>
            `;
        }
    }

    async deleteCookies() {
        if (!confirm('Are you sure you want to delete the cookies?')) return;

        try {
            const response = await fetch('/api/cookies', { method: 'DELETE' });
            const data = await response.json();

            if (data.success) {
                this.loadCookieStatus();
                document.getElementById('cookies-upload-result').innerHTML =
                    '<div class="alert alert-info py-2"><i class="bi bi-info-circle me-1"></i>Cookies deleted</div>';
            }
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    // yt-dlp Version Management
    async checkYtdlpVersion(showModal = false) {
        const versionBadge = document.getElementById('ytdlp-version');
        const versionText = document.getElementById('ytdlp-version-text');
        const versionInfo = document.getElementById('version-info');
        const updateBtn = document.getElementById('update-ytdlp-btn');

        if (showModal) {
            versionInfo.innerHTML = `
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                    Checking version...
                </div>
            `;
        }

        try {
            const response = await fetch('/api/yt-dlp/version');
            const data = await response.json();

            this.ytdlpVersionData = data;

            // Update navbar badge
            versionText.textContent = data.current_version;

            if (data.update_available) {
                versionBadge.classList.remove('bg-secondary', 'bg-success');
                versionBadge.classList.add('bg-warning', 'text-dark');
                versionBadge.title = `Update available: ${data.latest_version}`;
            } else {
                versionBadge.classList.remove('bg-secondary', 'bg-warning', 'text-dark');
                versionBadge.classList.add('bg-success');
                versionBadge.title = 'yt-dlp is up to date';
            }

            // Update modal content if visible
            if (showModal || document.getElementById('version-modal').classList.contains('show')) {
                this.renderVersionInfo(data);
            }
        } catch (error) {
            console.error('Failed to check yt-dlp version:', error);
            versionText.textContent = 'Error';
            if (showModal) {
                versionInfo.innerHTML = `
                    <div class="alert alert-danger mb-0">
                        <i class="bi bi-x-circle me-2"></i>Failed to check version
                    </div>
                `;
            }
        }
    }

    renderVersionInfo(data) {
        const versionInfo = document.getElementById('version-info');
        const updateBtn = document.getElementById('update-ytdlp-btn');
        const restartOption = document.getElementById('restart-option');
        const restartCheckbox = document.getElementById('restart-after-update');
        const restartLabel = document.querySelector('label[for="restart-after-update"]');
        const restartHint = restartOption.querySelector('.form-text');

        // Set checkbox default based on Docker detection
        restartCheckbox.checked = data.running_in_docker;

        // Update label and hint based on environment
        if (data.running_in_docker) {
            restartLabel.textContent = 'Restart server after update';
            restartHint.textContent = 'Docker will automatically restart the container';
        } else {
            restartLabel.textContent = 'Exit server after update';
            restartHint.textContent = 'You will need to manually restart the server';
        }

        if (data.update_available) {
            versionInfo.innerHTML = `
                <div class="alert alert-warning mb-3">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    <strong>Update available!</strong>
                </div>
                <div class="row">
                    <div class="col-6">
                        <div class="text-muted small">Current Version</div>
                        <div class="fs-5">${data.current_version}</div>
                    </div>
                    <div class="col-6">
                        <div class="text-muted small">Latest Version</div>
                        <div class="fs-5 text-success">${data.latest_version}</div>
                    </div>
                </div>
                <div class="mt-3 text-muted small">
                    <i class="bi bi-info-circle me-1"></i>
                    Updating yt-dlp helps fix download issues and adds support for new sites.
                </div>
            `;
            updateBtn.style.display = 'inline-block';
            restartOption.style.display = 'block';
        } else {
            versionInfo.innerHTML = `
                <div class="alert alert-success mb-3">
                    <i class="bi bi-check-circle me-2"></i>
                    <strong>yt-dlp is up to date!</strong>
                </div>
                <div class="text-center">
                    <div class="text-muted small">Current Version</div>
                    <div class="fs-4">${data.current_version}</div>
                </div>
            `;
            updateBtn.style.display = 'none';
            restartOption.style.display = 'none';
        }
    }

    showVersionInfo() {
        const modal = new bootstrap.Modal(document.getElementById('version-modal'));
        modal.show();

        if (this.ytdlpVersionData) {
            this.renderVersionInfo(this.ytdlpVersionData);
        }
        // Also refresh the check
        this.checkYtdlpVersion(true);
    }

    async updateYtdlp() {
        const versionInfo = document.getElementById('version-info');
        const updateBtn = document.getElementById('update-ytdlp-btn');
        const restartOption = document.getElementById('restart-option');
        const restartCheckbox = document.getElementById('restart-after-update');
        const shouldRestart = restartCheckbox.checked;

        updateBtn.disabled = true;
        updateBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Updating...';
        restartOption.style.display = 'none';

        versionInfo.innerHTML = `
            <div class="text-center py-3">
                <div class="spinner-border text-primary mb-2" role="status"></div>
                <div>Updating yt-dlp...</div>
                <div class="text-muted small">This may take a moment</div>
            </div>
        `;

        try {
            const response = await fetch(`/api/yt-dlp/update?restart=${shouldRestart}`, { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                if (data.restarting) {
                    versionInfo.innerHTML = `
                        <div class="alert alert-success mb-3">
                            <i class="bi bi-check-circle me-2"></i>
                            <strong>Update successful!</strong>
                        </div>
                        <div class="text-center">
                            <div class="spinner-border text-primary mb-2" role="status"></div>
                            <div>Server is restarting...</div>
                            <div class="text-muted small">Page will reload automatically</div>
                        </div>
                    `;
                    updateBtn.style.display = 'none';

                    // Poll for server to come back up, then reload
                    this.waitForServerAndReload();
                } else {
                    versionInfo.innerHTML = `
                        <div class="alert alert-success mb-0">
                            <i class="bi bi-check-circle me-2"></i>
                            <strong>Update successful!</strong><br>
                            <small>${data.message}</small>
                        </div>
                    `;
                    updateBtn.style.display = 'none';

                    // Update badge to show restart needed
                    const versionBadge = document.getElementById('ytdlp-version');
                    versionBadge.classList.remove('bg-warning');
                    versionBadge.classList.add('bg-info');
                    versionBadge.title = 'Restart server to apply update';
                }
            } else {
                versionInfo.innerHTML = `
                    <div class="alert alert-danger mb-0">
                        <i class="bi bi-x-circle me-2"></i>
                        <strong>Update failed</strong><br>
                        <small>${data.error || data.message}</small>
                    </div>
                `;
                restartOption.style.display = 'block';
            }
        } catch (error) {
            versionInfo.innerHTML = `
                <div class="alert alert-danger mb-0">
                    <i class="bi bi-x-circle me-2"></i>
                    <strong>Update failed</strong><br>
                    <small>${error.message}</small>
                </div>
            `;
            restartOption.style.display = 'block';
        } finally {
            updateBtn.disabled = false;
            updateBtn.innerHTML = '<i class="bi bi-arrow-up-circle me-1"></i>Update yt-dlp';
        }
    }

    async waitForServerAndReload() {
        const maxAttempts = 30;
        const delay = 2000;

        for (let i = 0; i < maxAttempts; i++) {
            await new Promise(resolve => setTimeout(resolve, delay));

            try {
                const response = await fetch('/api/yt-dlp/version', { method: 'GET' });
                if (response.ok) {
                    // Server is back up, reload the page
                    window.location.reload();
                    return;
                }
            } catch (e) {
                // Server not ready yet, continue waiting
            }
        }

        // If we get here, server didn't come back up
        document.getElementById('version-info').innerHTML = `
            <div class="alert alert-warning mb-0">
                <i class="bi bi-exclamation-triangle me-2"></i>
                <strong>Server restart taking longer than expected</strong><br>
                <small>Please refresh the page manually</small>
            </div>
        `;
    }

    // Database Maintenance
    async loadMaintenanceStats() {
        const statsDiv = document.getElementById('db-stats');
        const resultDiv = document.getElementById('cleanup-result');
        resultDiv.innerHTML = '';

        // Load max concurrent downloads setting
        try {
            const concurrentResponse = await fetch('/api/settings/max-concurrent');
            const concurrentData = await concurrentResponse.json();
            const select = document.getElementById('max-concurrent-downloads');
            if (select) {
                select.value = concurrentData.value.toString();
            }
        } catch (error) {
            console.error('Failed to load max concurrent setting:', error);
        }

        try {
            const response = await fetch('/api/maintenance/stats');
            const data = await response.json();

            const statusLabels = {
                'DownloadStatus.COMPLETED': { label: 'Completed', class: 'success' },
                'DownloadStatus.FAILED': { label: 'Failed', class: 'danger' },
                'DownloadStatus.CANCELLED': { label: 'Cancelled', class: 'warning' },
                'DownloadStatus.DOWNLOADING': { label: 'Downloading', class: 'primary' },
                'DownloadStatus.QUEUED': { label: 'Queued', class: 'secondary' },
                'DownloadStatus.FETCHING_INFO': { label: 'Fetching Info', class: 'info' }
            };

            let statusHtml = '';
            for (const [status, count] of Object.entries(data.downloads.by_status)) {
                const info = statusLabels[status] || { label: status, class: 'secondary' };
                statusHtml += `<span class="badge bg-${info.class} me-1">${info.label}: ${count}</span>`;
            }

            statsDiv.innerHTML = `
                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-body py-2">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span class="text-muted">Download Records</span>
                                    <strong>${data.downloads.total}</strong>
                                </div>
                                <div class="mt-2">${statusHtml || '<span class="text-muted small">No records</span>'}</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-body py-2">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span class="text-muted">Download History</span>
                                    <strong>${data.download_history.total}</strong>
                                </div>
                                <div class="mt-2 text-muted small">Videos tracked to avoid re-downloading</div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        } catch (error) {
            statsDiv.innerHTML = `
                <div class="alert alert-danger py-2 mb-0">
                    <i class="bi bi-x-circle me-1"></i>Failed to load stats
                </div>
            `;
        }

        // Also load channel history
        this.loadChannelHistory();
    }

    async loadChannelHistory() {
        const listDiv = document.getElementById('channel-history-list');

        try {
            const response = await fetch('/api/maintenance/history/channels');
            const channels = await response.json();

            if (channels.length === 0) {
                listDiv.innerHTML = '<div class="text-muted small">No channels in download history</div>';
                return;
            }

            let html = '<div class="list-group list-group-flush" style="max-height: 200px; overflow-y: auto;">';
            for (const channel of channels) {
                html += `
                    <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-0">
                        <div>
                            <i class="bi bi-person-video3 me-2"></i>
                            <span>${this.escapeHtml(channel.channel)}</span>
                            <span class="badge bg-secondary ms-2">${channel.count} video${channel.count !== 1 ? 's' : ''}</span>
                        </div>
                        <button class="btn btn-sm btn-outline-danger" onclick="app.deleteChannelHistory('${this.escapeHtml(channel.channel.replace(/'/g, "\\'"))}')">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                `;
            }
            html += '</div>';

            listDiv.innerHTML = html;
        } catch (error) {
            listDiv.innerHTML = `
                <div class="text-danger small">
                    <i class="bi bi-x-circle me-1"></i>Failed to load channels
                </div>
            `;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async deleteChannelHistory(channelName) {
        const resultDiv = document.getElementById('cleanup-result');

        if (!confirm(`Delete download history for "${channelName}"? This will allow re-downloading videos from this channel.`)) {
            return;
        }

        resultDiv.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                Deleting...
            </div>
        `;

        try {
            const response = await fetch(`/api/maintenance/history/channel/${encodeURIComponent(channelName)}`, {
                method: 'DELETE'
            });
            const data = await response.json();

            resultDiv.innerHTML = `
                <div class="alert alert-success py-2 mb-0">
                    <i class="bi bi-check-circle me-1"></i>
                    Deleted ${data.deleted} video(s) from "${channelName}" history
                </div>
            `;

            this.loadMaintenanceStats();
        } catch (error) {
            resultDiv.innerHTML = `
                <div class="alert alert-danger py-2 mb-0">
                    <i class="bi bi-x-circle me-1"></i>Delete failed: ${error.message}
                </div>
            `;
        }
    }

    async saveMaxConcurrentDownloads() {
        const select = document.getElementById('max-concurrent-downloads');
        const value = parseInt(select.value, 10);

        try {
            const response = await fetch('/api/settings/max-concurrent', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value })
            });

            if (!response.ok) {
                throw new Error('Failed to save setting');
            }

            console.log(`Max concurrent downloads set to ${value}`);
        } catch (error) {
            console.error('Failed to save max concurrent setting:', error);
            alert('Failed to save setting: ' + error.message);
        }
    }

    async cleanupDownloads() {
        const days = document.getElementById('cleanup-downloads-days').value;
        const resultDiv = document.getElementById('cleanup-result');

        if (!confirm(`Delete all completed, cancelled, and failed downloads older than ${days} days?`)) {
            return;
        }

        resultDiv.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                Cleaning up...
            </div>
        `;

        try {
            const response = await fetch(`/api/maintenance/downloads?days=${days}`, {
                method: 'DELETE'
            });
            const data = await response.json();

            resultDiv.innerHTML = `
                <div class="alert alert-success py-2 mb-0">
                    <i class="bi bi-check-circle me-1"></i>
                    Deleted ${data.deleted} download record(s) older than ${days} days
                </div>
            `;

            this.loadMaintenanceStats();
            this.loadDownloads();
        } catch (error) {
            resultDiv.innerHTML = `
                <div class="alert alert-danger py-2 mb-0">
                    <i class="bi bi-x-circle me-1"></i>Cleanup failed: ${error.message}
                </div>
            `;
        }
    }

    async cleanupHistory() {
        const daysSelect = document.getElementById('cleanup-history-days');
        const days = daysSelect.value;
        const resultDiv = document.getElementById('cleanup-result');

        const timeLabel = days ? `older than ${daysSelect.options[daysSelect.selectedIndex].text}` : 'all history';

        if (!confirm(`Clear download history ${timeLabel}? This will allow those videos to be re-selected in playlist views.`)) {
            return;
        }

        resultDiv.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                Clearing history...
            </div>
        `;

        try {
            const url = days ? `/api/maintenance/history?days=${days}` : '/api/maintenance/history';
            const response = await fetch(url, { method: 'DELETE' });
            const data = await response.json();

            resultDiv.innerHTML = `
                <div class="alert alert-success py-2 mb-0">
                    <i class="bi bi-check-circle me-1"></i>
                    Cleared ${data.deleted} video(s) from download history
                </div>
            `;

            this.loadMaintenanceStats();
        } catch (error) {
            resultDiv.innerHTML = `
                <div class="alert alert-danger py-2 mb-0">
                    <i class="bi bi-x-circle me-1"></i>Cleanup failed: ${error.message}
                </div>
            `;
        }
    }

    // Logs Management
    logSearchTimeout = null;

    debounceLogSearch() {
        clearTimeout(this.logSearchTimeout);
        this.logSearchTimeout = setTimeout(() => this.loadLogs(), 300);
    }

    async loadLogs() {
        const logContent = document.getElementById('log-content');
        const logStats = document.getElementById('log-stats');
        const levelFilter = document.getElementById('log-level-filter')?.value || '';
        const searchFilter = document.getElementById('log-search')?.value || '';
        const lines = document.getElementById('log-lines')?.value || 500;

        logContent.innerHTML = `
            <div class="d-flex align-items-center justify-content-center p-4">
                <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                Loading logs...
            </div>
        `;

        try {
            const params = new URLSearchParams({ lines });
            if (levelFilter) params.append('level', levelFilter);
            if (searchFilter) params.append('search', searchFilter);

            const response = await fetch(`/api/logs?${params}`);
            const data = await response.json();

            logStats.textContent = `Showing ${data.showing} of ${data.filtered_lines} filtered lines (${data.total_lines} total)`;

            if (data.logs.length === 0) {
                logContent.innerHTML = `
                    <div class="text-center text-muted p-4">
                        <i class="bi bi-journal-x" style="font-size: 2rem;"></i>
                        <p class="mt-2 mb-0">No logs found</p>
                    </div>
                `;
                return;
            }

            // Format logs with syntax highlighting
            const formattedLogs = data.logs.map(line => this.formatLogLine(line)).join('');
            logContent.innerHTML = formattedLogs;

            // Scroll to bottom (most recent)
            logContent.scrollTop = logContent.scrollHeight;

        } catch (error) {
            logContent.innerHTML = `
                <div class="text-center text-danger p-4">
                    <i class="bi bi-exclamation-triangle" style="font-size: 2rem;"></i>
                    <p class="mt-2 mb-0">Failed to load logs: ${error.message}</p>
                </div>
            `;
        }
    }

    formatLogLine(line) {
        // Parse log line: 2024-01-15 10:30:45,123 - module - LEVEL - message
        const match = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - ([^ ]+) - (\w+) - (.*)$/);

        if (match) {
            const [, timestamp, module, level, message] = match;
            const levelClass = `log-level-${level.toLowerCase()}`;
            return `<div class="log-line"><span class="log-timestamp">${timestamp}</span> - <span class="log-module">${module}</span> - <span class="${levelClass}">${level}</span> - ${this.escapeHtml(message)}</div>`;
        }

        // Fallback for lines that don't match the pattern
        return `<div class="log-line">${this.escapeHtml(line)}</div>`;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async clearLogs() {
        if (!confirm('Clear all application logs? This cannot be undone.')) {
            return;
        }

        try {
            const response = await fetch('/api/logs', { method: 'DELETE' });
            const data = await response.json();

            if (data.success) {
                // Refresh logs view if open
                const logContent = document.getElementById('log-content');
                if (logContent) {
                    logContent.innerHTML = `
                        <div class="text-center text-muted p-4">
                            <i class="bi bi-journal-x" style="font-size: 2rem;"></i>
                            <p class="mt-2 mb-0">Logs cleared</p>
                        </div>
                    `;
                }

                // Update size info
                this.loadLogSize();

                // Show success in result area if in maintenance modal
                const resultDiv = document.getElementById('cleanup-result');
                if (resultDiv) {
                    resultDiv.innerHTML = `
                        <div class="alert alert-success py-2 mb-0">
                            <i class="bi bi-check-circle me-1"></i>
                            Logs cleared successfully
                        </div>
                    `;
                }
            }
        } catch (error) {
            alert('Failed to clear logs: ' + error.message);
        }
    }

    async loadLogSize() {
        try {
            const response = await fetch('/api/logs/size');
            const data = await response.json();

            const sizeInfo = document.getElementById('log-size-info');
            if (sizeInfo) {
                sizeInfo.textContent = `(${data.current_size_formatted})`;
            }
        } catch (error) {
            console.error('Failed to load log size:', error);
        }
    }

    // Subscription Management
    async loadSubscriptions() {
        try {
            const response = await fetch('/api/subscriptions');
            const subscriptions = await response.json();

            const container = document.getElementById('subscriptions-list');
            container.innerHTML = '';

            if (subscriptions.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <i class="bi bi-rss"></i>
                        <p>No subscriptions yet</p>
                        <small class="text-muted">Add a channel or playlist to automatically download new videos</small>
                    </div>
                `;
                return;
            }

            subscriptions.forEach(sub => this.addSubscriptionCard(sub, container));
        } catch (error) {
            console.error('Failed to load subscriptions:', error);
        }
    }

    addSubscriptionCard(subscription, container = null) {
        if (!container) {
            container = document.getElementById('subscriptions-list');
        }

        // Remove empty state if present
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) emptyState.remove();

        const card = document.createElement('div');
        card.className = 'subscription-card';
        card.dataset.subscriptionId = subscription.id;

        const lastChecked = subscription.last_checked
            ? new Date(subscription.last_checked).toLocaleString()
            : 'Never';

        const intervalText = {
            6: 'Every 6 hours',
            12: 'Every 12 hours',
            24: 'Once per day',
            168: 'Once per week'
        }[subscription.check_interval_hours] || `Every ${subscription.check_interval_hours}h`;

        const opts = subscription.options || {};
        const formatDisplay = opts.output_format ? opts.output_format.toUpperCase() : 'MP4';

        card.innerHTML = `
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <div class="title">${subscription.name}</div>
                    <div class="meta">
                        <i class="bi bi-clock me-1"></i>${intervalText}
                        <span class="mx-2">|</span>
                        <i class="bi bi-file-earmark-play me-1"></i>${formatDisplay}
                        <span class="mx-2">|</span>
                        <i class="bi bi-check2-circle me-1"></i>Last checked: ${lastChecked}
                        <span class="mx-2">|</span>
                        <i class="bi bi-collection-play me-1"></i>${subscription.last_video_count} videos
                    </div>
                    <div class="meta mt-1">
                        <small class="text-muted">${subscription.url}</small>
                    </div>
                </div>
                <div class="actions">
                    <button class="btn btn-sm btn-outline-primary" onclick="app.checkSubscriptionNow(${subscription.id})" title="Check now">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-${subscription.enabled ? 'warning' : 'success'}"
                            onclick="app.toggleSubscription(${subscription.id}, ${!subscription.enabled})"
                            title="${subscription.enabled ? 'Pause' : 'Resume'}">
                        <i class="bi bi-${subscription.enabled ? 'pause-fill' : 'play-fill'}"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="app.deleteSubscription(${subscription.id})" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
            ${!subscription.enabled ? '<div class="mt-2"><span class="badge bg-warning text-dark">Paused</span></div>' : ''}
        `;

        container.appendChild(card);
    }

    getSubscriptionOptions() {
        return {
            format: document.getElementById('sub-format-select').value,
            output_format: document.getElementById('sub-output-format-select').value,
            output_template: document.getElementById('sub-output-template').value || YtdlApp.DEFAULT_OUTPUT_TEMPLATE,
            subtitles: document.getElementById('sub-subtitles-check').checked,
            subtitle_langs: ['en'],
            embed_thumbnail: document.getElementById('sub-thumbnail-check').checked,
            embed_metadata: document.getElementById('sub-metadata-check').checked
        };
    }

    resetSubscriptionForm() {
        document.getElementById('subscription-url').value = '';
        document.getElementById('subscription-name').value = '';
        document.getElementById('subscription-interval').value = '24';
        document.getElementById('sub-format-select').value = 'best';
        document.getElementById('sub-output-format-select').value = 'mp4';
        document.getElementById('sub-output-template').value = '';
        document.getElementById('sub-subtitles-check').checked = false;
        document.getElementById('sub-thumbnail-check').checked = false;
        document.getElementById('sub-metadata-check').checked = true;
    }

    async addSubscription() {
        const urlInput = document.getElementById('subscription-url');
        const nameInput = document.getElementById('subscription-name');
        const intervalSelect = document.getElementById('subscription-interval');

        const url = urlInput.value.trim();
        if (!url) {
            alert('Please enter a URL');
            return;
        }

        this.showLoading(true);

        try {
            const response = await fetch('/api/subscriptions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: url,
                    name: nameInput.value.trim() || null,
                    check_interval_hours: parseInt(intervalSelect.value),
                    options: this.getSubscriptionOptions()
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to add subscription');
            }

            const subscription = await response.json();

            // Close modal and reset form
            bootstrap.Modal.getInstance(document.getElementById('add-subscription-modal')).hide();
            this.resetSubscriptionForm();

            // Refresh list
            this.loadSubscriptions();

            // Switch to subscriptions tab
            document.getElementById('subscriptions-tab').click();

        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            this.showLoading(false);
        }
    }

    async checkSubscriptionNow(id) {
        try {
            const response = await fetch(`/api/subscriptions/${id}/check`, { method: 'POST' });
            const data = await response.json();

            if (data.new_videos > 0) {
                alert(`Found ${data.new_videos} new video(s)! Downloads have been queued.`);
                this.loadDownloads();
            } else {
                alert('No new videos found.');
            }

            this.loadSubscriptions();
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    async toggleSubscription(id, enabled) {
        try {
            await fetch(`/api/subscriptions/${id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });
            this.loadSubscriptions();
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    async deleteSubscription(id) {
        if (!confirm('Delete this subscription?')) return;

        try {
            await fetch(`/api/subscriptions/${id}`, { method: 'DELETE' });
            this.loadSubscriptions();
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }
}

// Initialize app
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new YtdlApp();
});
