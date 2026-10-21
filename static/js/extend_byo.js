/**
 * Bring-your-own MP4 for video extend (Studios, Arena, Motion).
 * Sets window._extendInput = { file } | { url } — same contract as video_extend.js.
 */
(function (global) {
  function wire(opts) {
    const zone = document.getElementById(opts.zoneId);
    if (!zone) return;

    const fileInput = document.getElementById(opts.fileInputId);
    const urlInput = document.getElementById(opts.urlInputId);
    const preview = opts.previewId ? document.getElementById(opts.previewId) : null;
    const label = opts.labelId ? document.getElementById(opts.labelId) : null;
    const setInput = opts.setInput || ((src) => { global._extendInput = src; });

    function showPreview(src, text) {
      if (preview) {
        preview.src = src;
        preview.style.display = 'block';
      }
      if (label) label.textContent = text || 'Video ready';
      zone.classList.add('has-video');
      if (opts.videoId) {
        const vid = document.getElementById(opts.videoId);
        if (vid) {
          vid.src = src;
          vid.style.display = 'block';
          if (opts.placeholderId) {
            const ph = document.getElementById(opts.placeholderId);
            if (ph) ph.style.display = 'none';
          }
          if (opts.actionsId) {
            const actions = document.getElementById(opts.actionsId);
            if (actions) actions.style.display = 'flex';
          }
          if (opts.downloadId) {
            const dl = document.getElementById(opts.downloadId);
            if (dl && !src.startsWith('blob:')) dl.dataset.url = src;
          }
        }
      }
    }

    function loadFile(file) {
      if (!file) return;
      if (!file.type.startsWith('video/') && !/\.(mp4|mov|webm|mkv)$/i.test(file.name)) return;
      setInput({ file });
      if (urlInput) urlInput.value = '';
      showPreview(URL.createObjectURL(file), '✓ ' + file.name);
    }

    function loadUrl(url) {
      if (!url) return;
      setInput({ url });
      showPreview(url, 'Video URL');
    }

    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) loadFile(f);
    });

    if (fileInput) {
      fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files[0]) loadFile(fileInput.files[0]);
      });
    }

    if (global.PercfectPasteDrop) {
      PercfectPasteDrop.bind({
        zone: opts.zoneId,
        accept: 'video',
        urlInputId: opts.urlInputId,
        onFile: loadFile,
        onUrl: loadUrl,
      });
    }

    return { loadFile, loadUrl, setInput };
  }

  function getSource(opts) {
    const input = global._extendInput;
    if (input && (input.file || input.url)) return input;
    if (opts.downloadId) {
      const dl = document.getElementById(opts.downloadId)?.dataset?.url;
      if (dl && dl !== '#' && !dl.startsWith('blob:')) return { url: dl };
    }
    if (opts.videoId) {
      const url = document.getElementById(opts.videoId)?.src;
      if (url && !url.startsWith('blob:')) return { url };
    }
    if (opts.urlInputId) {
      const pasted = document.getElementById(opts.urlInputId)?.value?.trim();
      if (pasted) return { url: pasted };
    }
    return null;
  }

  global.PercfectExtendByo = { wire, getSource };
})(window);