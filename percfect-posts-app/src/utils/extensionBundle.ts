import JSZip from 'jszip';

export interface ExtensionFile {
  name: string;
  description: string;
  content: string;
}

export function getExtensionFiles(appOrigin: string = window.location.origin): Record<string, ExtensionFile> {
  const manifest = {
    manifest_version: 3,
    name: 'The Percfect Post Companion',
    version: '3.0.0',
    description:
      'Download or upload photos and videos directly from any webpage into The Percfect Post. Edit photos with linked AI engines (Grok, DALL-E, Imagen) and reformat videos in 9:16 Video Studio.',
    permissions: ['activeTab', 'storage', 'contextMenus', 'tabs', 'downloads'],
    host_permissions: ['<all_urls>'],
    action: {
      default_popup: 'popup.html',
      default_title: 'The Percfect Post Web Clipper',
      default_icon: {
        '16': 'icon.png',
        '48': 'icon.png',
        '128': 'icon.png',
      },
    },
    background: {
      service_worker: 'background.js',
    },
    content_scripts: [
      {
        matches: ['<all_urls>'],
        js: ['content.js'],
        css: ['content.css'],
      },
    ],
  };

  const popupHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>The Percfect Post Web Clipper</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    body { width: 380px; background: #090d16; color: #f1f5f9; padding: 16px; font-size: 13px; }
    .header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #1e293b; padding-bottom: 12px; margin-bottom: 12px; }
    .logo-badge { display: flex; align-items: center; gap: 8px; font-weight: 800; color: #818cf8; font-size: 14px; letter-spacing: -0.02em; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981; box-shadow: 0 0 8px #10b981; }
    .plan-badge { background: linear-gradient(135deg, #4f46e5, #7c3aed); color: #fff; font-size: 10px; padding: 2px 8px; border-radius: 9999px; font-weight: 700; text-transform: uppercase; }
    .tabs { display: flex; gap: 4px; background: #111827; padding: 3px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #1f2937; }
    .tab-btn { flex: 1; padding: 6px 8px; border-radius: 6px; border: none; background: transparent; color: #94a3b8; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
    .tab-btn.active { background: #4f46e5; color: #ffffff; }
    .section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
    .preview-box { background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 10px; text-align: center; margin-bottom: 12px; min-height: 100px; display: flex; flex-direction: column; align-items: center; justify-content: center; position: relative; overflow: hidden; }
    .preview-box img, .preview-box video { max-width: 100%; max-height: 140px; border-radius: 6px; margin-bottom: 6px; object-fit: contain; }
    .media-meta { font-size: 10px; color: #64748b; font-family: monospace; }
    .btn-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 10px; }
    .btn { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; padding: 8px 12px; border: none; border-radius: 6px; font-weight: 700; cursor: pointer; transition: all 0.2s; font-size: 11px; }
    .btn-download { background: #1e293b; color: #f8fafc; border: 1px solid #334155; }
    .btn-download:hover { background: #334155; }
    .btn-upload { background: #4f46e5; color: white; }
    .btn-upload:hover { background: #4338ca; }
    .btn-ai { background: linear-gradient(135deg, #9333ea, #6366f1); color: white; margin-bottom: 6px; }
    .btn-ai:hover { opacity: 0.95; }
    .btn-video { background: linear-gradient(135deg, #e11d48, #be185d); color: white; margin-bottom: 6px; }
    .btn-video:hover { opacity: 0.95; }
    .network-checks { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 12px; }
    .net-pill { font-size: 9px; font-weight: 700; padding: 3px 6px; border-radius: 9999px; border: 1px solid #334155; background: #0f172a; color: #cbd5e1; cursor: pointer; }
    .net-pill.checked { background: #10b981; border-color: #059669; color: white; }
    .textarea { width: 100%; height: 50px; background: #111827; border: 1px solid #1f2937; border-radius: 6px; color: #fff; padding: 8px; font-size: 11px; resize: none; margin-bottom: 10px; }
    .footer-bar { display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #1e293b; padding-top: 10px; font-size: 11px; color: #64748b; }
    .footer-bar a { color: #818cf8; text-decoration: none; font-weight: 600; }
  </style>
</head>
<body>
  <div class="header">
    <div class="logo-badge">
      <span class="status-dot"></span>
      The Percfect Post
    </div>
    <span class="plan-badge">Web Clipper</span>
  </div>

  <div class="tabs">
    <button class="tab-btn active" id="tabPhotos">📸 Photos on Page (<span id="photoCount">0</span>)</button>
    <button class="tab-btn" id="tabVideos">🎬 Videos on Page (<span id="videoCount">0</span>)</button>
  </div>

  <div class="preview-box" id="captureContainer">
    <p id="placeholderText" style="color: #64748b; font-size: 11px;">Scanning webpage for photos and video clips...</p>
  </div>

  <!-- Download & Upload Actions -->
  <div class="btn-row">
    <button class="btn btn-download" id="btnDownload">
      ⬇️ Download to Disk
    </button>
    <button class="btn btn-upload" id="btnUploadToApp">
      ☁️ Upload to Percfect Post
    </button>
  </div>

  <!-- Special Action Buttons based on Media Type and API Keys -->
  <button class="btn btn-ai" id="btnAITweak" style="display:none;">
    ✨ Edit Photo with AI (Grok / DALL-E / Imagen)
  </button>
  <button class="btn btn-video" id="btnVideoStudio" style="display:none;">
    🎬 Open in Video Studio (9:16 Reformat & Stitch)
  </button>

  <div class="section-title">
    <span>Track Social Network Posts:</span>
    <span style="font-size:9px; color:#a5b4fc;">Colored Checkmarks</span>
  </div>
  <div class="network-checks">
    <span class="net-pill checked" style="background:#000; border-color:#fff;">✓ 𝕏 X</span>
    <span class="net-pill checked" style="background:#E1306C; border-color:#fff;">✓ IG Instagram</span>
    <span class="net-pill checked" style="background:#0A66C2; border-color:#fff;">✓ LI LinkedIn</span>
    <span class="net-pill checked" style="background:#000; color:#00f2fe; border-color:#ff0050;">✓ TT TikTok</span>
    <span class="net-pill" style="border-color:#FF0000; color:#FF0000;">+ YT Shorts</span>
    <span class="net-pill" style="border-color:#BD081C; color:#BD081C;">+ PIN Pinterest</span>
  </div>

  <textarea class="textarea" id="quickCaption" placeholder="Add custom notes or topic for AI caption generation..."></textarea>

  <div class="footer-bar">
    <span>Bridge Connected</span>
    <a href="${appOrigin}" target="_blank" id="openAppBtn">Launch Percfect Post &rarr;</a>
  </div>

  <script src="popup.js"></script>
</body>
</html>`;

  const popupJs = `// The Percfect Post Chrome Extension Script
const APP_ORIGIN = "${appOrigin}";

let discoveredPhotos = [];
let discoveredVideos = [];
let currentTabType = 'photo'; // 'photo' | 'video'
let activeMediaIndex = 0;

document.addEventListener('DOMContentLoaded', async () => {
  const tabPhotos = document.getElementById('tabPhotos');
  const tabVideos = document.getElementById('tabVideos');
  const btnDownload = document.getElementById('btnDownload');
  const btnUpload = document.getElementById('btnUploadToApp');
  const btnAITweak = document.getElementById('btnAITweak');
  const btnVideoStudio = document.getElementById('btnVideoStudio');
  const captureBox = document.getElementById('captureContainer');
  const openAppBtn = document.getElementById('openAppBtn');

  // Query active tab to scrape media
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) {
    chrome.tabs.sendMessage(tab.id, { action: "scanMediaOnPage" }, (res) => {
      if (res) {
        discoveredPhotos = res.photos || [];
        discoveredVideos = res.videos || [];
        document.getElementById('photoCount').innerText = discoveredPhotos.length;
        document.getElementById('videoCount').innerText = discoveredVideos.length;

        if (discoveredPhotos.length > 0) {
          renderActiveMedia();
        } else if (discoveredVideos.length > 0) {
          currentTabType = 'video';
          tabVideos.classList.add('active');
          tabPhotos.classList.remove('active');
          renderActiveMedia();
        }
      }
    });
  }

  tabPhotos.addEventListener('click', () => {
    currentTabType = 'photo';
    activeMediaIndex = 0;
    tabPhotos.classList.add('active');
    tabVideos.classList.remove('active');
    renderActiveMedia();
  });

  tabVideos.addEventListener('click', () => {
    currentTabType = 'video';
    activeMediaIndex = 0;
    tabVideos.classList.add('active');
    tabPhotos.classList.remove('active');
    renderActiveMedia();
  });

  function renderActiveMedia() {
    const list = currentTabType === 'photo' ? discoveredPhotos : discoveredVideos;
    if (!list || list.length === 0) {
      captureBox.innerHTML = \`<p style="color:#64748b; font-size:11px;">No \${currentTabType}s found on this webpage.</p>\`;
      btnAITweak.style.display = 'none';
      btnVideoStudio.style.display = 'none';
      return;
    }

    const item = list[activeMediaIndex] || list[0];
    if (currentTabType === 'photo') {
      captureBox.innerHTML = \`
        <img src="\${item.url}" alt="Page Photo" />
        <div class="media-meta">\${item.width || 'HD'}x\${item.height || 'Photo'} • \${item.name || 'Web Image'}</div>
      \`;
      btnAITweak.style.display = 'flex';
      btnVideoStudio.style.display = 'none';
    } else {
      captureBox.innerHTML = \`
        <video src="\${item.url}" controls></video>
        <div class="media-meta">\${item.duration ? item.duration + 's • ' : ''}\${item.name || 'Web Video Clip'}</div>
      \`;
      btnAITweak.style.display = 'none';
      btnVideoStudio.style.display = 'flex';
    }
  }

  // 1. Download to local disk
  btnDownload.addEventListener('click', () => {
    const list = currentTabType === 'photo' ? discoveredPhotos : discoveredVideos;
    const item = list[activeMediaIndex];
    if (!item) return;

    btnDownload.innerText = "Downloading...";
    const filename = (currentTabType === 'photo' ? 'percfect-photo-' : 'percfect-video-') + Date.now() + (currentTabType === 'photo' ? '.jpg' : '.mp4');
    chrome.downloads.download({ url: item.url, filename: filename }, () => {
      btnDownload.innerText = "✅ Downloaded!";
      setTimeout(() => { btnDownload.innerText = "⬇️ Download to Disk"; }, 2000);
    });
  });

  // 2. Upload directly to The Percfect Post app
  btnUpload.addEventListener('click', () => {
    const list = currentTabType === 'photo' ? discoveredPhotos : discoveredVideos;
    const item = list[activeMediaIndex];
    if (!item) return;

    btnUpload.innerText = "Uploading to Vault...";
    
    // Send post message or open app with imported media
    const targetUrl = \`\${APP_ORIGIN}/?importMedia=\${encodeURIComponent(item.url)}&type=\${currentTabType}&name=\${encodeURIComponent(item.name || 'Web Asset')}\`;
    chrome.tabs.create({ url: targetUrl });

    btnUpload.innerText = "✅ Uploaded to Percfect Post!";
    setTimeout(() => { btnUpload.innerText = "☁️ Upload to Percfect Post"; }, 2500);
  });

  // 3. Edit Photo with AI directly in the app
  btnAITweak.addEventListener('click', () => {
    const item = discoveredPhotos[activeMediaIndex];
    if (!item) return;
    const targetUrl = \`\${APP_ORIGIN}/?action=ai-tweak&mediaUrl=\${encodeURIComponent(item.url)}\`;
    chrome.tabs.create({ url: targetUrl });
  });

  // 4. Open in Video Studio
  btnVideoStudio.addEventListener('click', () => {
    const item = discoveredVideos[activeMediaIndex];
    if (!item) return;
    const targetUrl = \`\${APP_ORIGIN}/?action=video-studio&mediaUrl=\${encodeURIComponent(item.url)}\`;
    chrome.tabs.create({ url: targetUrl });
  });
});`;

  const backgroundJs = `// The Percfect Post Background Service Worker
chrome.runtime.onInstalled.addListener(() => {
  // Context menus for photos and videos
  chrome.contextMenus.create({
    id: "percfectUploadPhoto",
    title: "The Percfect Post: Upload Photo to Vault",
    contexts: ["image"]
  });

  chrome.contextMenus.create({
    id: "percfectAITweakPhoto",
    title: "The Percfect Post: Edit Photo with AI (Grok, DALL-E, Imagen)",
    contexts: ["image"]
  });

  chrome.contextMenus.create({
    id: "percfectVideoStudio",
    title: "The Percfect Post: Open Video in 9:16 Studio",
    contexts: ["video"]
  });

  chrome.contextMenus.create({
    id: "percfectDownloadMedia",
    title: "The Percfect Post: Download Media Directly",
    contexts: ["image", "video"]
  });

  console.log("The Percfect Post Extension Installed & Context Menus Registered");
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const mediaUrl = info.srcUrl || info.linkUrl;
  if (!mediaUrl) return;

  if (info.menuItemId === "percfectUploadPhoto" || info.menuItemId === "percfectAITweakPhoto") {
    const action = info.menuItemId === "percfectAITweakPhoto" ? "ai-tweak" : "upload";
    const appUrl = "${appOrigin}/?action=" + action + "&mediaUrl=" + encodeURIComponent(mediaUrl);
    chrome.tabs.create({ url: appUrl });
  } else if (info.menuItemId === "percfectVideoStudio") {
    const appUrl = "${appOrigin}/?action=video-studio&mediaUrl=" + encodeURIComponent(mediaUrl);
    chrome.tabs.create({ url: appUrl });
  } else if (info.menuItemId === "percfectDownloadMedia") {
    const isVideo = info.mediaType === "video";
    const filename = (isVideo ? "percfect-video-" : "percfect-photo-") + Date.now() + (isVideo ? ".mp4" : ".jpg");
    chrome.downloads.download({ url: mediaUrl, filename });
  }
});`;

  const contentJs = `// The Percfect Post Web Page Media Scraper
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "scanMediaOnPage") {
    const photos = [];
    const videos = [];

    // 1. Collect all images on page
    document.querySelectorAll('img').forEach((img, i) => {
      const src = img.currentSrc || img.src;
      if (src && src.startsWith('http') && img.naturalWidth > 150) {
        photos.push({
          url: src,
          width: img.naturalWidth,
          height: img.naturalHeight,
          name: img.alt || ('Web Photo ' + (i + 1)),
        });
      }
    });

    // 2. Collect all videos on page
    document.querySelectorAll('video').forEach((vid, i) => {
      const src = vid.currentSrc || vid.src || vid.querySelector('source')?.src;
      if (src && src.startsWith('http')) {
        videos.push({
          url: src,
          name: 'Web Video Clip ' + (i + 1),
          duration: Math.round(vid.duration || 15),
        });
      }
    });

    sendResponse({ photos, videos });
  }
  return true;
});`;

  const contentCss = `/* The Percfect Post In-Page Overlay Styles */
.percfect-post-clipper-badge {
  position: absolute;
  z-index: 9999999;
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  color: #fff;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
  cursor: pointer;
}`;

  return {
    'manifest.json': {
      name: 'manifest.json',
      description: 'Chrome Extension Manifest V3 for The Percfect Post with download and upload permissions',
      content: JSON.stringify(manifest, null, 2),
    },
    'popup.html': {
      name: 'popup.html',
      description: 'The Percfect Post popup UI with photo/video tabs, download/upload buttons, and social checkmarks',
      content: popupHtml,
    },
    'popup.js': {
      name: 'popup.js',
      description: 'Scrapes webpage media, executes downloads, uploads to app, and triggers AI photo editor & video studio',
      content: popupJs,
    },
    'background.js': {
      name: 'background.js',
      description: 'Service worker with context menus for downloading, uploading, AI editing, and video studio',
      content: backgroundJs,
    },
    'content.js': {
      name: 'content.js',
      description: 'Scans active page for photos and video clips on demand',
      content: contentJs,
    },
    'content.css': {
      name: 'content.css',
      description: 'Styling for in-page overlays and badges',
      content: contentCss,
    },
  };
}

export async function createExtensionZipBlob(appOrigin: string = window.location.origin): Promise<Blob> {
  const zip = new JSZip();
  const files = getExtensionFiles(appOrigin);

  Object.keys(files).forEach((filename) => {
    zip.file(filename, files[filename].content);
  });

  // Create a minimal 1x1 png for icon.png placeholder
  const iconBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
  zip.file('icon.png', iconBase64, { base64: true });

  const blob = await zip.generateAsync({ type: 'blob' });
  return blob;
}

export function triggerDownloadBlob(blob: Blob, filename: string = 'the-percfect-post-chrome-extension.zip') {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
