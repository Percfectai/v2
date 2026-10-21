import React, { useState } from 'react';
import {
  Chrome,
  Download,
  Copy,
  Check,
  ExternalLink,
  Laptop,
  Layers,
  Sparkles,
  Zap,
  Code2,
  FileCode,
  ShieldCheck,
  Send,
  Camera,
  Film,
  Wand2,
  Sliders,
  Upload,
  Key,
  ArrowRight,
  Globe,
  AlertCircle,
} from 'lucide-react';
import {
  getExtensionFiles,
  createExtensionZipBlob,
  triggerDownloadBlob,
  ExtensionFile,
} from '../utils/extensionBundle.ts';
import { MediaItem, AIProviderInfo, SocialPlatform } from '../types.ts';
import { PhotoPostedBadges, ALL_PLATFORMS, PLATFORM_VISUALS } from './SocialNetworkCheckmarks.tsx';

interface ChromeExtensionViewProps {
  onDispatchSimulatedPost: (title: string, caption: string, mediaUrl: string) => void;
  availableMediaUrls: string[];
  mediaList?: MediaItem[];
  onAddMedia?: (item: MediaItem) => void;
  onUpdateMedia?: (item: MediaItem) => void;
  onSelectMedia?: (item: MediaItem) => void;
  onOpenStudioWithMedia?: (item: MediaItem) => void;
  onOpenVideoStudioWithMedia?: (item: MediaItem) => void;
  onOpenAIProviderKeySetup?: () => void;
  aiProviders?: AIProviderInfo[];
}

export const ChromeExtensionView: React.FC<ChromeExtensionViewProps> = ({
  onDispatchSimulatedPost,
  availableMediaUrls,
  mediaList = [],
  onAddMedia,
  onUpdateMedia,
  onSelectMedia,
  onOpenStudioWithMedia,
  onOpenVideoStudioWithMedia,
  onOpenAIProviderKeySetup,
  aiProviders = [],
}) => {
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [activeFileKey, setActiveFileKey] = useState<string>('manifest.json');
  const [copied, setCopied] = useState(false);

  // Simulator state: media type switch (Photos vs Videos on webpage)
  const [simMediaType, setSimMediaType] = useState<'photo' | 'video'>('photo');
  
  // Sample scraped webpage photos
  const sampleWebPhotos: { title: string; url: string; width: number; height: number; size: string }[] = [
    {
      title: 'Cinematic High-Tech Workspace',
      url: 'https://images.unsplash.com/photo-1508739773434-c26b3d09e071?w=1200&auto=format&fit=crop&q=80',
      width: 1920,
      height: 1080,
      size: '1.8 MB',
    },
    {
      title: 'Minimalist Creator Studio Setup',
      url: 'https://images.unsplash.com/photo-1593062096033-9a26b09da705?w=1200&auto=format&fit=crop&q=80',
      width: 1200,
      height: 1500,
      size: '2.4 MB',
    },
    {
      title: 'Neon Cyberpunk Abstract Sphere',
      url: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1200&auto=format&fit=crop&q=80',
      width: 1080,
      height: 1080,
      size: '1.2 MB',
    },
  ];

  // Sample scraped webpage videos
  const sampleWebVideos: { title: string; url: string; duration: number; size: string }[] = [
    {
      title: 'Product Demonstration Reel',
      url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
      duration: 15,
      size: '14.2 MB',
    },
    {
      title: 'Dynamic Bullrun Motion Clip',
      url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WeAreGoingOnBullrun.mp4',
      duration: 10,
      size: '22.8 MB',
    },
  ];

  const [activePhotoIndex, setActivePhotoIndex] = useState(0);
  const [activeVideoIndex, setActiveVideoIndex] = useState(0);

  const activePhoto = sampleWebPhotos[activePhotoIndex];
  const activeVideo = sampleWebVideos[activeVideoIndex];

  // Download & upload status states
  const [isDownloadingLocal, setIsDownloadingLocal] = useState(false);
  const [localDownloadSuccess, setLocalDownloadSuccess] = useState(false);
  const [isUploadingToApp, setIsUploadingToApp] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  // Selected networks to simulate posting
  const [simActivePlatforms, setSimActivePlatforms] = useState<SocialPlatform[]>([
    'twitter',
    'instagram',
    'linkedin',
    'tiktok',
  ]);
  const [simCaption, setSimCaption] = useState(
    'Captured directly via The Percfect Post Chrome Clipper! Stamped with copyright and auto-adapted.'
  );
  const [simPosting, setSimPosting] = useState(false);
  const [simSuccess, setSimSuccess] = useState(false);

  // Check if user has an image generating API key linked (Grok, DALL-E/OpenAI, Gemini, Claude)
  const configuredImageAI = aiProviders.find(
    (p) => p.isImageConfigured || (p.id === 'gemini' && p.isConfigured) || (p.id === 'openai' && p.apiKey) || (p.id === 'grok' && p.apiKey)
  );
  const hasAIKeyLinked = Boolean(configuredImageAI);

  const extensionFiles = getExtensionFiles(window.location.origin);
  const activeFile = extensionFiles[activeFileKey];

  const handleDownloadZip = async () => {
    setDownloading(true);
    try {
      const blob = await createExtensionZipBlob(window.location.origin);
      triggerDownloadBlob(blob, 'the-percfect-post-chrome-extension.zip');
      setDownloaded(true);
      setTimeout(() => setDownloaded(false), 4000);
    } catch (e) {
      console.error('Error generating zip:', e);
    } finally {
      setDownloading(false);
    }
  };

  const handleCopyCode = () => {
    if (activeFile) {
      navigator.clipboard.writeText(activeFile.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const toggleSimPlatform = (p: SocialPlatform) => {
    setSimActivePlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]
    );
  };

  // 1. Simulator: Download straight to disk
  const handleSimDownloadToDisk = () => {
    setIsDownloadingLocal(true);
    const currentUrl = simMediaType === 'photo' ? activePhoto.url : activeVideo.url;
    const filename = simMediaType === 'photo' ? `percfect-photo-${Date.now()}.jpg` : `percfect-video-${Date.now()}.mp4`;

    try {
      const a = document.createElement('a');
      a.href = currentUrl;
      a.download = filename;
      a.target = '_blank';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch {
      // fallback
    }

    setTimeout(() => {
      setIsDownloadingLocal(false);
      setLocalDownloadSuccess(true);
      setActionNotice(
        `Downloaded ${simMediaType === 'photo' ? 'photo' : 'video'} straight to your computer!`
      );
      setTimeout(() => {
        setLocalDownloadSuccess(false);
        setActionNotice(null);
      }, 3500);
    }, 800);
  };

  // 2. Simulator: Upload rather photos/videos straight into The Percfect Post app
  const handleSimUploadToApp = () => {
    setIsUploadingToApp(true);
    const isPhoto = simMediaType === 'photo';
    const currentUrl = isPhoto ? activePhoto.url : activeVideo.url;
    const title = isPhoto ? activePhoto.title : activeVideo.title;

    const newMediaItem: MediaItem = {
      id: `clipped-${Date.now()}`,
      name: `${title}.${isPhoto ? 'jpg' : 'mp4'}`,
      url: currentUrl,
      type: isPhoto ? 'image' : 'video',
      dimensions: isPhoto
        ? { width: activePhoto.width, height: activePhoto.height }
        : { width: 1920, height: 1080 },
      size: isPhoto ? activePhoto.size : activeVideo.size,
      timestamp: new Date().toISOString(),
      sourcePageUrl: 'https://unsplash.com/photos/future-ai',
      postedNetworks: [],
    };

    if (onAddMedia) {
      onAddMedia(newMediaItem);
    }
    if (onSelectMedia) {
      onSelectMedia(newMediaItem);
    }

    setTimeout(() => {
      setIsUploadingToApp(false);
      setUploadSuccess(true);
      setActionNotice(
        `Successfully uploaded to The Percfect Post Media Vault! Available in all composers & studio tools.`
      );
      setTimeout(() => {
        setUploadSuccess(false);
        setActionNotice(null);
      }, 4000);
    }, 900);
  };

  // 3. Simulator: Trigger Edit Photo with AI right through the app
  const handleSimEditPhotoWithAI = () => {
    const item: MediaItem = {
      id: `ai-tweaked-${Date.now()}`,
      name: `${activePhoto.title}.jpg`,
      url: activePhoto.url,
      type: 'image',
      dimensions: { width: activePhoto.width, height: activePhoto.height },
      size: activePhoto.size,
      timestamp: new Date().toISOString(),
      sourcePageUrl: 'https://unsplash.com/photos/future-ai',
      postedNetworks: [],
    };

    if (onAddMedia) {
      onAddMedia(item);
    }
    if (onOpenStudioWithMedia) {
      onOpenStudioWithMedia(item);
    }
  };

  // 4. Simulator: Trigger 9:16 Video Studio
  const handleSimOpenVideoStudio = () => {
    const item: MediaItem = {
      id: `video-studio-${Date.now()}`,
      name: `${activeVideo.title}.mp4`,
      url: activeVideo.url,
      type: 'video',
      dimensions: { width: 1920, height: 1080 },
      size: activeVideo.size,
      timestamp: new Date().toISOString(),
      sourcePageUrl: 'https://commondatastorage.googleapis.com',
      postedNetworks: [],
    };

    if (onAddMedia) {
      onAddMedia(item);
    }
    if (onOpenVideoStudioWithMedia) {
      onOpenVideoStudioWithMedia(item);
    }
  };

  const handleSimulatePost = () => {
    setSimPosting(true);
    const mediaUrl = simMediaType === 'photo' ? activePhoto.url : activeVideo.url;

    setTimeout(() => {
      setSimPosting(false);
      setSimSuccess(true);
      onDispatchSimulatedPost('Captured via The Percfect Post Clipper', simCaption, mediaUrl);
      setTimeout(() => setSimSuccess(false), 3000);
    }, 1200);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Hero Banner */}
      <div className="bg-gradient-to-r from-indigo-950/80 via-slate-900 to-purple-950/40 border border-indigo-500/30 rounded-2xl p-6 sm:p-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 shadow-xl">
        <div className="space-y-3 max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gradient-to-r from-indigo-500/20 to-purple-500/20 text-indigo-300 border border-indigo-500/30 text-xs font-bold">
            <Chrome className="w-4 h-4 text-sky-400" />
            The Percfect Post Companion Extension • Manifest V3
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            Download & Upload Photos or Videos Straight from Any Webpage
          </h2>
          <p className="text-slate-300 text-xs sm:text-sm leading-relaxed">
            Clip visual assets from anywhere on the web. Download them straight to disk or upload them directly into <strong>The Percfect Post</strong> vault. If you have an image generating API key linked (Grok, DALL-E, Imagen), trigger AI photo edits right through the app with a single click—or reformat videos in the 9:16 Video Studio!
          </p>
        </div>

        <div className="flex flex-col sm:flex-row gap-3 w-full md:w-auto shrink-0">
          <button
            onClick={handleDownloadZip}
            disabled={downloading}
            className="flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-xl bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-700 hover:brightness-110 text-white font-bold text-sm shadow-lg shadow-indigo-600/30 transition hover:scale-[1.02] active:scale-[0.98]"
          >
            {downloading ? (
              <Zap className="w-4 h-4 animate-spin" />
            ) : downloaded ? (
              <Check className="w-4 h-4 text-emerald-300" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            <span>{downloaded ? 'Extension Zip Downloaded!' : 'Download Extension (.zip)'}</span>
          </button>
        </div>
      </div>

      {/* Extension Simulator & Web Clipper Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Interactive Live Extension Simulator (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Laptop className="w-4 h-4 text-indigo-400" />
              Live Interactive Web Clipper
            </h3>
            <span className="text-[11px] font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
              Bridge Online
            </span>
          </div>

          {/* Chrome Browser Frame Mockup */}
          <div className="rounded-2xl border border-slate-700 bg-slate-950 p-3 shadow-2xl">
            {/* Browser top mock */}
            <div className="flex items-center gap-2 px-2 py-1.5 border-b border-slate-800 text-xs text-slate-400 mb-3">
              <div className="flex gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80"></span>
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></span>
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></span>
              </div>
              <div className="flex-1 bg-slate-900 rounded-md px-3 py-1 text-[11px] text-slate-300 flex items-center justify-between">
                <span className="truncate flex items-center gap-1">
                  <Globe className="w-3 h-3 text-indigo-400" />
                  https://unsplash.com/trending-visuals
                </span>
                <span className="text-[10px] text-emerald-400 font-mono">200 OK</span>
              </div>
              <div className="w-6 h-6 rounded bg-indigo-600/30 border border-indigo-500/50 flex items-center justify-center text-indigo-300">
                <Chrome className="w-3.5 h-3.5" />
              </div>
            </div>

            {/* Popup window container */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-slate-200 space-y-3">
              <div className="flex items-center justify-between pb-2.5 border-b border-slate-800">
                <div className="flex items-center gap-2 font-extrabold text-xs text-white">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]"></span>
                  The Percfect Post Web Clipper
                </div>
                <span className="text-[10px] font-bold bg-indigo-900/60 text-indigo-300 px-2 py-0.5 rounded-full border border-indigo-700/50">
                  v3.0 Linked
                </span>
              </div>

              {/* Media Type Tabs: Photos on Webpage vs Videos on Webpage */}
              <div className="flex gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
                <button
                  onClick={() => setSimMediaType('photo')}
                  className={`flex-1 py-1.5 rounded-md font-bold text-[11px] flex items-center justify-center gap-1.5 transition ${
                    simMediaType === 'photo'
                      ? 'bg-indigo-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Camera className="w-3.5 h-3.5" />
                  <span>Photos ({sampleWebPhotos.length})</span>
                </button>
                <button
                  onClick={() => setSimMediaType('video')}
                  className={`flex-1 py-1.5 rounded-md font-bold text-[11px] flex items-center justify-center gap-1.5 transition ${
                    simMediaType === 'video'
                      ? 'bg-pink-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Film className="w-3.5 h-3.5" />
                  <span>Videos ({sampleWebVideos.length})</span>
                </button>
              </div>

              {/* Scraped Media Preview Card */}
              <div className="space-y-1.5">
                <div className="text-[11px] font-medium text-slate-400 flex items-center justify-between">
                  <span>Detected On Current Webpage:</span>
                  <button
                    onClick={() => {
                      if (simMediaType === 'photo') {
                        setActivePhotoIndex((prev) => (prev + 1) % sampleWebPhotos.length);
                      } else {
                        setActiveVideoIndex((prev) => (prev + 1) % sampleWebVideos.length);
                      }
                    }}
                    className="text-[10px] text-indigo-400 hover:underline flex items-center gap-1"
                  >
                    <span>Next Asset &rarr;</span>
                  </button>
                </div>

                <div className="relative rounded-lg overflow-hidden border border-slate-700 aspect-video bg-black/60 flex items-center justify-center">
                  {simMediaType === 'photo' ? (
                    <img
                      src={activePhoto.url}
                      alt={activePhoto.title}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <video
                      src={activeVideo.url}
                      controls
                      className="w-full h-full object-contain"
                    />
                  )}

                  {/* Stamp tag */}
                  <div className="absolute top-2 left-2 px-1.5 py-0.5 bg-black/80 backdrop-blur rounded text-[9px] font-mono text-indigo-300 border border-indigo-500/30">
                    {simMediaType === 'photo' ? 'Photo Detected' : 'Video Clip Detected'}
                  </div>

                  <div className="absolute bottom-2 right-2 px-1.5 py-0.5 bg-black/80 backdrop-blur rounded text-[9px] font-semibold text-slate-300">
                    {simMediaType === 'photo'
                      ? `${activePhoto.width}x${activePhoto.height} • ${activePhoto.size}`
                      : `${activeVideo.duration}s Clip • ${activeVideo.size}`}
                  </div>
                </div>
              </div>

              {/* Two Primary Web Actions: Download to Disk OR Upload to App */}
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={handleSimDownloadToDisk}
                  disabled={isDownloadingLocal}
                  className="py-2 px-2.5 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700 font-bold text-xs flex items-center justify-center gap-1.5 transition"
                >
                  <Download className="w-3.5 h-3.5 text-slate-400" />
                  <span>
                    {isDownloadingLocal
                      ? 'Downloading...'
                      : localDownloadSuccess
                      ? 'Downloaded!'
                      : 'Download to Disk'}
                  </span>
                </button>

                <button
                  onClick={handleSimUploadToApp}
                  disabled={isUploadingToApp}
                  className="py-2 px-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center justify-center gap-1.5 shadow transition"
                >
                  <Upload className="w-3.5 h-3.5" />
                  <span>
                    {isUploadingToApp
                      ? 'Uploading...'
                      : uploadSuccess
                      ? 'Uploaded to App!'
                      : 'Upload to App'}
                  </span>
                </button>
              </div>

              {/* Direct App Actions: Edit Photo with AI OR Open 9:16 Video Studio */}
              {simMediaType === 'photo' ? (
                <div className="pt-1">
                  {hasAIKeyLinked ? (
                    <button
                      onClick={handleSimEditPhotoWithAI}
                      className="w-full py-2 px-3 rounded-lg bg-gradient-to-r from-purple-600 via-indigo-600 to-purple-700 hover:brightness-110 text-white font-bold text-xs flex items-center justify-center gap-1.5 shadow-md shadow-purple-600/20 transition"
                    >
                      <Wand2 className="w-3.5 h-3.5 text-purple-200" />
                      <span>Edit Photo with AI (Grok, DALL-E, Imagen)</span>
                      <ArrowRight className="w-3 h-3 ml-auto" />
                    </button>
                  ) : (
                    <div className="p-2 rounded-lg bg-purple-950/40 border border-purple-800/40 text-xs flex items-center justify-between">
                      <div className="flex items-center gap-1.5 text-purple-300 text-[11px]">
                        <Key className="w-3.5 h-3.5 text-amber-400" />
                        <span>Link AI Key (Grok / DALL-E) for Instant Photo Editing</span>
                      </div>
                      <button
                        onClick={onOpenAIProviderKeySetup}
                        className="text-[10px] text-amber-400 font-bold hover:underline"
                      >
                        Link Key &rarr;
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="pt-1">
                  <button
                    onClick={handleSimOpenVideoStudio}
                    className="w-full py-2 px-3 rounded-lg bg-gradient-to-r from-pink-600 to-rose-600 hover:brightness-110 text-white font-bold text-xs flex items-center justify-center gap-1.5 shadow-md shadow-pink-600/20 transition"
                  >
                    <Film className="w-3.5 h-3.5 text-pink-200" />
                    <span>Open in Video Studio (9:16 Reformat, Trim, Stitch)</span>
                    <ArrowRight className="w-3 h-3 ml-auto" />
                  </button>
                </div>
              )}

              {/* Status Banner Notice */}
              {actionNotice && (
                <div className="p-2 rounded-lg bg-emerald-950/50 border border-emerald-500/40 text-[11px] text-emerald-300 flex items-center gap-1.5 animate-in fade-in">
                  <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>{actionNotice}</span>
                </div>
              )}

              {/* Colored Social Network Checkmarks Tracker in Extension */}
              <div className="space-y-1.5 pt-1 border-t border-slate-800">
                <label className="block text-[11px] font-semibold text-slate-300">
                  Checkmarks Coinciding With Social Networks:
                </label>
                <div className="grid grid-cols-4 gap-1.5 text-[10px]">
                  {(['twitter', 'instagram', 'linkedin', 'tiktok'] as SocialPlatform[]).map(
                    (plat) => {
                      const isSelected = simActivePlatforms.includes(plat);
                      const visual = PLATFORM_VISUALS[plat];
                      return (
                        <button
                          key={plat}
                          onClick={() => toggleSimPlatform(plat)}
                          className={`py-1 px-1 rounded-md text-center font-bold flex items-center justify-center gap-1 transition ${
                            isSelected
                              ? `${visual.badgeBg} ${visual.borderColor} border shadow-sm`
                              : 'bg-slate-800 text-slate-500 border border-transparent'
                          }`}
                        >
                          <Check className={`w-2.5 h-2.5 ${isSelected ? 'stroke-[3]' : 'opacity-30'}`} />
                          <span>{visual.shortLabel}</span>
                        </button>
                      );
                    }
                  )}
                </div>
              </div>

              {/* Caption Prompt */}
              <div>
                <textarea
                  value={simCaption}
                  onChange={(e) => setSimCaption(e.target.value)}
                  className="w-full h-14 bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-indigo-500 resize-none"
                  placeholder="Notes for AI distribution..."
                />
              </div>

              {/* Mass Post Dispatch */}
              <button
                onClick={handleSimulatePost}
                disabled={simPosting}
                className="w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-md transition disabled:opacity-50"
              >
                {simPosting ? (
                  <>
                    <Zap className="w-3.5 h-3.5 animate-spin" />
                    Watermarking & Auto-Posting...
                  </>
                ) : simSuccess ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-300" />
                    Dispatched to {simActivePlatforms.length} Networks!
                  </>
                ) : (
                  <>
                    <Send className="w-3.5 h-3.5" />
                    Mass Post Now ({simActivePlatforms.length} Networks)
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Installation & Code Inspector (Right 7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          {/* Quick Setup Guide Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              How to Install "The Percfect Post" Locally in Chrome
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="w-5 h-5 rounded-full bg-indigo-600/30 text-indigo-400 font-bold text-[11px] flex items-center justify-center mb-1">
                  1
                </span>
                <h4 className="font-semibold text-white">Download & Extract</h4>
                <p className="text-slate-400 text-[11px]">
                  Click <strong>Download Extension (.zip)</strong> above and unzip into any local folder.
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="w-5 h-5 rounded-full bg-indigo-600/30 text-indigo-400 font-bold text-[11px] flex items-center justify-center mb-1">
                  2
                </span>
                <h4 className="font-semibold text-white">Open chrome://extensions</h4>
                <p className="text-slate-400 text-[11px]">
                  Turn on <strong>Developer mode</strong> in top-right of Chrome extensions page.
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="w-5 h-5 rounded-full bg-indigo-600/30 text-indigo-400 font-bold text-[11px] flex items-center justify-center mb-1">
                  3
                </span>
                <h4 className="font-semibold text-white">Load Unpacked</h4>
                <p className="text-slate-400 text-[11px]">
                  Click <strong>Load unpacked</strong> and select the unzipped folder. Done!
                </p>
              </div>
            </div>

            {/* Chrome Web Store Publishing & Monetization Card */}
            <div className="p-4 rounded-xl bg-gradient-to-r from-amber-950/40 via-indigo-950/50 to-slate-950 border border-amber-500/40 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-amber-300 font-bold text-xs">
                  <Globe className="w-4 h-4 text-amber-400" />
                  <span>How to Publish to the Official Chrome Web Store & Monetize</span>
                </div>
                <span className="text-[10px] font-black px-2 py-0.5 rounded bg-amber-400 text-slate-950">
                  MONETIZATION FUNNEL
                </span>
              </div>

              <p className="text-slate-300 text-xs leading-relaxed">
                Publishing to the official Chrome Web Store gives you viral organic distribution from millions of daily Chrome users.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-[11px]">
                <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800 space-y-1">
                  <div className="font-bold text-indigo-300 flex items-center gap-1">
                    <span>1. Developer Account</span>
                  </div>
                  <p className="text-slate-400 leading-tight">
                    Visit Chrome Dev Console (one-time $5 Google fee) to activate your publisher license.
                  </p>
                </div>
                <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800 space-y-1">
                  <div className="font-bold text-amber-300 flex items-center gap-1">
                    <span>2. Upload .ZIP File</span>
                  </div>
                  <p className="text-slate-400 leading-tight">
                    Upload the exact <strong>.zip file</strong> generated above. It is pre-configured with Manifest V3.
                  </p>
                </div>
                <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800 space-y-1">
                  <div className="font-bold text-emerald-300 flex items-center gap-1">
                    <span>3. SaaS Funnel (100% Margin)</span>
                  </div>
                  <p className="text-slate-400 leading-tight">
                    Distribute free on the store. Users clip media into your web app and upgrade to Pro ($7) or Premium ($12 / $100/yr) via Stripe!
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-slate-800/80">
                <span className="text-[11px] text-slate-400">
                  Ready to submit? Open developer dashboard:
                </span>
                <a
                  href="https://chrome.google.com/webstore/devconsole"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs transition shadow"
                >
                  <span>Open Chrome Developer Dashboard</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            </div>

            {/* AI Image Generation & Video Studio Capabilities Callout */}
            <div className="p-3.5 rounded-lg bg-gradient-to-r from-purple-950/40 via-indigo-950/40 to-slate-950 border border-purple-800/40 space-y-2 text-xs">
              <div className="flex items-center gap-2 text-purple-300 font-bold">
                <Sparkles className="w-4 h-4 text-amber-400" />
                <span>Webpage Download & Direct AI Editing Workflow</span>
              </div>
              <p className="text-slate-300 text-[11px] leading-relaxed">
                When you browse any website, right-click any photo or click the extension popup to <strong>Upload Photo to Vault</strong>. If you have an image generating API key linked (Google Gemini Imagen 3, xAI Grok Imagine, OpenAI DALL-E 3), you can click <strong>Edit Photo with AI</strong> to instantly enhance, restyle, or modify the photo right through the app. For videos, you can open them in the 9:16 Video Studio for instant vertical reels, screenshotting, and timeline stitching.
              </p>
            </div>
          </div>

          {/* Extension Source Code Inspector */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Code2 className="w-4 h-4 text-indigo-400" />
                <span className="text-xs font-bold text-white">Extension Source Code</span>
              </div>
              <button
                onClick={handleCopyCode}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-750 text-slate-300 text-[11px] font-medium transition"
              >
                {copied ? (
                  <Check className="w-3 h-3 text-emerald-400" />
                ) : (
                  <Copy className="w-3 h-3 text-slate-400" />
                )}
                <span>{copied ? 'Copied' : 'Copy Code'}</span>
              </button>
            </div>

            {/* File tabs */}
            <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pb-1">
              {Object.keys(extensionFiles).map((fileKey) => {
                const isActive = activeFileKey === fileKey;
                return (
                  <button
                    key={fileKey}
                    onClick={() => setActiveFileKey(fileKey)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono transition ${
                      isActive
                        ? 'bg-indigo-600 text-white font-semibold'
                        : 'bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800'
                    }`}
                  >
                    <FileCode className="w-3.5 h-3.5" />
                    <span>{fileKey}</span>
                  </button>
                );
              })}
            </div>

            {/* Code Box */}
            <div className="rounded-lg bg-slate-950 border border-slate-850 p-3 max-h-[300px] overflow-y-auto font-mono text-[11px] text-slate-300 leading-relaxed no-scrollbar">
              <pre>{activeFile?.content}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
