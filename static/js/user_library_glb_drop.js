/**
 * Library 3D tab: OS drag-drop + multi-file Upload GLB (enhances user_library_sidebar.js).
 * Safe if main library script already wires a single-file uploader — re-binds cleanly.
 */
(function () {
  const MAX_GLB_BYTES = 45 * 1024 * 1024;

  function $(id) {
    return document.getElementById(id);
  }

  function toast(msg) {
    if (window.PercfectLibrary && typeof window.PercfectLibrary.toast === 'function') {
      try {
        window.PercfectLibrary.toast(msg);
        return;
      } catch (_e) { /* fall through */ }
    }
    let t = $('lib-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'lib-toast';
      t.className = 'lib-toast';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), 2200);
  }

  function isGlbFile(f) {
    if (!f) return false;
    const name = f.name || '';
    const type = (f.type || '').toLowerCase();
    return (
      /\.glb$/i.test(name) ||
      type === 'model/gltf-binary' ||
      (type === 'application/octet-stream' && /\.glb$/i.test(name))
    );
  }

  function activeTabIs3d() {
    const tab = document.querySelector('.lib-tab.active');
    return !!(tab && tab.dataset && tab.dataset.tab === '3d');
  }

  async function uploadGlbFiles(fileList) {
    const files = Array.from(fileList || []).filter(isGlbFile);
    if (!files.length) {
      toast('Drop or choose a .glb file');
      return;
    }
    let ok = 0;
    let fail = 0;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      if (f.size > MAX_GLB_BYTES) {
        toast(f.name + ': too large (max ~45MB)');
        fail += 1;
        continue;
      }
      toast(
        files.length > 1
          ? 'Uploading ' + (i + 1) + '/' + files.length + ': ' + f.name + '…'
          : 'Uploading ' + f.name + '…'
      );
      try {
        const fd = new FormData();
        fd.append('glb', f, f.name || 'body.glb');
        fd.append('name', (f.name || 'Body').replace(/\.glb$/i, ''));
        const res = await fetch('/api/3d/upload-character', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Upload failed (' + res.status + ')');
        ok += 1;
      } catch (err) {
        fail += 1;
        toast(err.message || 'Upload failed');
      }
    }
    if (ok) {
      toast(ok === 1 ? '3D body saved to library' : ok + ' 3D bodies saved to library');
      if (window.PercfectLibrary && typeof window.PercfectLibrary.reload === 'function') {
        await window.PercfectLibrary.reload();
      }
      const tab3d = document.querySelector('.lib-tab[data-tab="3d"]');
      if (tab3d) tab3d.click();
    }
  }

  function ensureEmptyDropZone() {
    if (!activeTabIs3d()) return;
    const body = $('lib-body');
    if (!body) return;
    const empty = body.querySelector('.lib-empty');
    if (!empty) return;
    if (body.querySelector('#lib-3d-empty-drop')) return;
    if (body.querySelector('.lib-item')) return;
    body.innerHTML =
      '<div class="lib-empty-3d-drop" id="lib-3d-empty-drop" role="button" tabindex="0">' +
      '<strong>Drop .glb files here</strong>' +
      '<span style="font-size:.8rem;color:var(--text-muted);line-height:1.45;display:block">' +
      'From Finder / Files — or click Upload GLB above.<br/>' +
      'Bodies open on the 3D stage. You can also generate on /3d (Meshy).' +
      '</span></div>';
    const emptyDrop = $('lib-3d-empty-drop');
    if (emptyDrop) {
      emptyDrop.addEventListener('click', () => {
        const fi = $('lib-3d-file');
        if (fi) fi.click();
      });
      emptyDrop.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          const fi = $('lib-3d-file');
          if (fi) fi.click();
        }
      });
    }
  }

  function wireUploadButton() {
    const uploadBtn = $('lib-3d-upload');
    const fileInput = $('lib-3d-file');
    if (!uploadBtn || !fileInput) return;
    if (fileInput._glbMultiBound) return;
    fileInput._glbMultiBound = true;
    fileInput.setAttribute('multiple', 'multiple');
    fileInput.setAttribute(
      'accept',
      '.glb,model/gltf-binary,application/octet-stream'
    );
    // Capture phase so we win over single-file handler in main script
    uploadBtn.addEventListener(
      'click',
      (e) => {
        e.preventDefault();
        e.stopImmediatePropagation();
        fileInput.click();
      },
      true
    );
    fileInput.addEventListener(
      'change',
      async (e) => {
        e.stopImmediatePropagation();
        const list = fileInput.files ? Array.from(fileInput.files) : [];
        fileInput.value = '';
        if (!list.length) return;
        await uploadGlbFiles(list);
      },
      true
    );
  }

  function wireFileDrop() {
    const panel = $('user-lib-panel');
    const body = $('lib-body');
    const tools = $('lib-3d-tools');
    const targets = [panel, body, tools].filter(Boolean);
    if (!targets.length) return;
    if (panel && panel._glbDropBound) return;
    if (panel) panel._glbDropBound = true;

    let dragDepth = 0;

    function isFileDrag(e) {
      const dt = e.dataTransfer;
      if (!dt) return false;
      if (
        dt.types &&
        (dt.types.includes('Files') ||
          (dt.types.contains && dt.types.contains('Files')))
      )
        return true;
      return !!(dt.files && dt.files.length);
    }

    targets.forEach((el) => {
      el.addEventListener('dragenter', (e) => {
        if (!activeTabIs3d()) return;
        if (!isFileDrag(e)) return;
        e.preventDefault();
        e.stopPropagation();
        dragDepth += 1;
        if (body) {
          body.classList.add('lib-3d-file-drop', 'lib-file-drag');
        }
      });
      el.addEventListener('dragover', (e) => {
        if (!activeTabIs3d()) return;
        if (!isFileDrag(e)) return;
        e.preventDefault();
        e.stopPropagation();
        try {
          e.dataTransfer.dropEffect = 'copy';
        } catch (_e) {}
        if (body) body.classList.add('lib-3d-file-drop', 'lib-file-drag');
      });
      el.addEventListener('dragleave', (e) => {
        if (!activeTabIs3d()) return;
        e.preventDefault();
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0 && body) body.classList.remove('lib-file-drag');
      });
      el.addEventListener('drop', async (e) => {
        if (!activeTabIs3d()) return;
        if (!isFileDrag(e)) return;
        e.preventDefault();
        e.stopPropagation();
        dragDepth = 0;
        if (body) body.classList.remove('lib-file-drag');
        const files = e.dataTransfer && e.dataTransfer.files;
        if (files && files.length) await uploadGlbFiles(files);
      });
    });
  }

  function observeTabAndBody() {
    const tabs = document.querySelector('.lib-tabs');
    if (tabs) {
      tabs.addEventListener('click', () => {
        setTimeout(ensureEmptyDropZone, 80);
      });
    }
    const body = $('lib-body');
    if (body && typeof MutationObserver !== 'undefined') {
      const mo = new MutationObserver(() => {
        if (activeTabIs3d()) ensureEmptyDropZone();
      });
      mo.observe(body, { childList: true, subtree: false });
    }
  }

  function init() {
    if (!$('user-lib-fab') && !$('user-lib-panel')) return;
    wireUploadButton();
    wireFileDrop();
    observeTabAndBody();
    ensureEmptyDropZone();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  // Re-init after late partials
  setTimeout(init, 400);
})();
