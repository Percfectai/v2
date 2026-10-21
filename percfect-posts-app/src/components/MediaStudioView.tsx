import React, { useState, useEffect, useRef } from 'react';
import {
  Image as ImageIcon,
  Upload,
  Sparkles,
  Download,
  Check,
  Zap,
  Layers,
  Crop,
  ShieldCheck,
  Type,
  Maximize2,
  RefreshCw,
  Sliders,
  Send,
  Trash2,
  Wand2,
  Film,
  Key,
} from 'lucide-react';
import {
  MediaItem,
  WatermarkSettings,
  WatermarkPosition,
  UserSubscription,
  AIProviderInfo,
  AIProvider,
} from '../types.ts';
import { processCanvasImage } from '../utils/imageProcessor.ts';
import { AIPhotoTweakerModal } from './AIPhotoTweakerModal.tsx';
import {
  PhotoPostedBadges,
  SocialNetworkPostedTracker,
} from './SocialNetworkCheckmarks.tsx';

interface MediaStudioViewProps {
  mediaList: MediaItem[];
  activeMedia: MediaItem | null;
  onSelectMedia: (item: MediaItem) => void;
  onAddMedia: (item: MediaItem) => void;
  onDeleteMedia: (id: string) => void;
  onUpdateMedia?: (item: MediaItem) => void;
  watermarkSettings: WatermarkSettings;
  onUpdateWatermark: (settings: WatermarkSettings) => void;
  onSendToCompose: (mediaUrl: string) => void;
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
  aiProviders?: AIProviderInfo[];
  onUpdateProviderKey?: (id: AIProvider, key: string) => void;
  onSwitchToVideoStudio?: () => void;
}

export const MediaStudioView: React.FC<MediaStudioViewProps> = ({
  mediaList,
  activeMedia,
  onSelectMedia,
  onAddMedia,
  onDeleteMedia,
  onUpdateMedia,
  watermarkSettings,
  onUpdateWatermark,
  onSendToCompose,
  subscription,
  onOpenUpgrade,
  aiProviders = [],
  onUpdateProviderKey = () => {},
  onSwitchToVideoStudio,
}) => {
  const [upscaleFactor, setUpscaleFactor] = useState<1 | 2 | 4>(1);
  const [aspectRatio, setAspectRatio] = useState<'original' | '1:1' | '4:5' | '9:16' | '16:9'>(
    'original'
  );
  const [customTitle, setCustomTitle] = useState(watermarkSettings.titleText || 'STUDIO EXCLUSIVE');
  const [customDisclaimer, setCustomDisclaimer] = useState(
    watermarkSettings.disclaimerText || '© 2026 • ALL RIGHTS RESERVED'
  );

  const [processedUrl, setProcessedUrl] = useState<string>('');
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [downloadSuccess, setDownloadSuccess] = useState<boolean>(false);
  const [isTweakerOpen, setIsTweakerOpen] = useState(false);
  const [mediaToTweak, setMediaToTweak] = useState<MediaItem | null>(null);
  const [vaultFilter, setVaultFilter] = useState<'all' | 'image' | 'video'>('all');

  const fileInputRef = useRef<HTMLInputElement>(null);
  const logoInputRef = useRef<HTMLInputElement>(null);

  // Re-run image processing when settings or active media changes
  useEffect(() => {
    if (!activeMedia) return;

    let isMounted = true;
    setIsProcessing(true);

    const timer = setTimeout(async () => {
      try {
        const result = await processCanvasImage({
          imageUrl: activeMedia.url,
          watermark: watermarkSettings,
          upscaleFactor,
          aspectRatio,
          title: customTitle,
          disclaimer: customDisclaimer,
        });

        if (isMounted) {
          setProcessedUrl(result);
          setIsProcessing(false);
        }
      } catch (err) {
        console.error('Error in canvas processing:', err);
        if (isMounted) {
          setProcessedUrl(activeMedia.url);
          setIsProcessing(false);
        }
      }
    }, 250);

    return () => {
      isMounted = false;
      clearTimeout(timer);
    };
  }, [activeMedia, watermarkSettings, upscaleFactor, aspectRatio, customTitle, customDisclaimer]);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const dataUrl = event.target?.result as string;
      const newItem: MediaItem = {
        id: `media-${Date.now()}`,
        name: file.name,
        url: dataUrl,
        type: 'image',
        dimensions: { width: 1200, height: 1200 },
        size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
        timestamp: new Date().toISOString(),
        upscaled: false,
        titleStamp: customTitle,
        disclaimerStamp: customDisclaimer,
      };
      onAddMedia(newItem);
      onSelectMedia(newItem);
    };
    reader.readAsDataURL(file);
  };

  const handleLogoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const dataUrl = event.target?.result as string;
      onUpdateWatermark({
        ...watermarkSettings,
        logoUrl: dataUrl,
      });
    };
    reader.readAsDataURL(file);
  };

  const handleDownloadStamped = () => {
    if (!processedUrl) return;
    const a = document.createElement('a');
    a.href = processedUrl;
    a.download = `stamped-${activeMedia?.name || 'media'}.jpg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setDownloadSuccess(true);
    setTimeout(() => setDownloadSuccess(false), 2500);
  };

  const handleUpscaleSelect = (factor: 1 | 2 | 4) => {
    if (factor > 1 && subscription.plan === 'free') {
      onOpenUpgrade();
      return;
    }
    setUpscaleFactor(factor);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Banner */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-xl p-4 sm:p-5">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <ImageIcon className="w-5 h-5 text-indigo-400" />
            Media & Watermark Studio
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time canvas engine for super-resolution upscaling, logo stamping, disclaimers, and platform aspect ratio framing.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept="image/*"
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow transition"
          >
            <Upload className="w-3.5 h-3.5" />
            Upload New Media
          </button>
        </div>
      </div>

      {/* Main Studio Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Media Library Drawer (3 cols) */}
        <div className="lg:col-span-3 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                Asset Vault ({mediaList.length})
              </span>
              <span className="text-[10px] text-slate-500">Stored</span>
            </div>

            {/* Filter Tabs */}
            <div className="flex items-center gap-1 mb-3 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
              <button
                onClick={() => setVaultFilter('all')}
                className={`flex-1 py-1 rounded text-[11px] font-medium transition ${
                  vaultFilter === 'all'
                    ? 'bg-indigo-600 text-white shadow'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                All
              </button>
              <button
                onClick={() => setVaultFilter('image')}
                className={`flex-1 py-1 rounded text-[11px] font-medium transition ${
                  vaultFilter === 'image'
                    ? 'bg-indigo-600 text-white shadow'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Photos
              </button>
              <button
                onClick={() => setVaultFilter('video')}
                className={`flex-1 py-1 rounded text-[11px] font-medium transition ${
                  vaultFilter === 'video'
                    ? 'bg-indigo-600 text-white shadow'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Videos
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2.5 max-h-[460px] overflow-y-auto no-scrollbar pr-1">
              {mediaList
                .filter((item) => {
                  if (vaultFilter === 'image') return item.type === 'image';
                  if (vaultFilter === 'video') return item.type === 'video';
                  return true;
                })
                .map((item) => {
                  const isSelected = activeMedia?.id === item.id;
                  const isVideo = item.type === 'video';
                  return (
                    <div
                      key={item.id}
                      onClick={() => onSelectMedia(item)}
                      className={`group relative rounded-lg overflow-hidden border aspect-square cursor-pointer transition ${
                        isSelected
                          ? 'border-indigo-500 ring-2 ring-indigo-500/50'
                          : 'border-slate-800 hover:border-slate-700 opacity-85 hover:opacity-100'
                      }`}
                    >
                      {isVideo ? (
                        <div className="w-full h-full bg-slate-950 flex flex-col items-center justify-center p-2 text-pink-400">
                          <Film className="w-6 h-6 mb-1" />
                          <span className="text-[9px] text-slate-400 text-center truncate w-full">
                            {item.name}
                          </span>
                        </div>
                      ) : (
                        <img
                          src={item.url}
                          alt={item.name}
                          className="w-full h-full object-cover"
                        />
                      )}

                      {/* Colored Network Checkmarks for each platform posted */}
                      <div className="absolute top-1.5 left-1.5 z-10 max-w-[70%]">
                        {item.postedNetworks && item.postedNetworks.length > 0 ? (
                          <PhotoPostedBadges
                            postedNetworks={item.postedNetworks}
                            size="xs"
                            interactive={true}
                            onTogglePlatform={(plat) => {
                              const curr = item.postedNetworks || [];
                              const upd = curr.filter((p) => p !== plat);
                              onUpdateMedia?.({ ...item, postedNetworks: upd });
                            }}
                          />
                        ) : (
                          <span className="text-[8px] font-semibold px-1.5 py-0.5 rounded bg-black/60 text-slate-400 border border-slate-700/60 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition">
                            Unposted
                          </span>
                        )}
                      </div>

                      {/* Floating edit button on photos */}
                      {!isVideo && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setMediaToTweak(item);
                            setIsTweakerOpen(true);
                          }}
                          className="absolute top-1.5 right-1.5 z-10 p-1 rounded-md bg-purple-600/90 hover:bg-purple-500 text-white text-[10px] opacity-0 group-hover:opacity-100 transition shadow flex items-center gap-0.5"
                          title="Tweak with AI"
                        >
                          <Wand2 className="w-3 h-3" />
                          <span>Edit</span>
                        </button>
                      )}

                      {isVideo && (
                        <div className="absolute top-1.5 right-1.5 z-10 px-1.5 py-0.5 rounded bg-pink-600/90 text-[9px] font-bold text-white uppercase">
                          Video
                        </div>
                      )}

                      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/60 to-transparent p-1.5 flex items-center justify-between">
                        <div className="flex flex-col min-w-0 pr-1">
                          <span className="text-[10px] text-white truncate max-w-[80px]">
                            {item.name}
                          </span>
                          {item.postedNetworks && item.postedNetworks.length > 0 && (
                            <span className="text-[8px] text-emerald-400 font-medium">
                              {item.postedNetworks.length} posted
                            </span>
                          )}
                        </div>
                        {isSelected && (
                          <span className="w-2 h-2 rounded-full bg-emerald-400 ring-2 ring-emerald-400/40"></span>
                        )}
                      </div>
                    </div>
                  );
                })}
            </div>

            {/* Quick upload zone */}
            <div
              onClick={() => fileInputRef.current?.click()}
              className="mt-3 border border-dashed border-slate-750 hover:border-indigo-500/80 rounded-lg p-3 text-center cursor-pointer transition bg-slate-950/40"
            >
              <Upload className="w-4 h-4 text-slate-400 mx-auto mb-1" />
              <p className="text-[11px] text-slate-300 font-medium">Drop media or Browse</p>
              <p className="text-[9px] text-slate-500">PNG, JPG, MP4 up to 50MB</p>
            </div>
          </div>
        </div>

        {/* Center: Live Interactive Canvas Preview (5 cols) */}
        <div className="lg:col-span-5 space-y-3">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col items-center">
            <div className="w-full flex items-center justify-between pb-3 border-b border-slate-800 mb-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-white truncate max-w-[180px]">
                  {activeMedia?.name || 'Selected Asset'}
                </span>
                {upscaleFactor > 1 && (
                  <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono text-[10px] border border-emerald-500/30">
                    {upscaleFactor}x HD Crisp
                  </span>
                )}
              </div>
              <span className="text-slate-400 text-[11px]">
                {isProcessing ? 'Rendering...' : 'Live Preview'}
              </span>
            </div>

            {/* Canvas Preview Container */}
            <div className="relative w-full aspect-square max-h-[460px] bg-slate-950 rounded-lg border border-slate-800 overflow-hidden flex items-center justify-center p-2">
              {isProcessing && (
                <div className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm z-20 flex flex-col items-center justify-center gap-2">
                  <Zap className="w-6 h-6 text-indigo-400 animate-spin" />
                  <span className="text-xs text-indigo-200 font-medium">Applying Canvas Stamps...</span>
                </div>
              )}

              {processedUrl ? (
                <img
                  src={processedUrl}
                  alt="Processed Master Asset"
                  className="max-h-full max-w-full object-contain rounded shadow-2xl"
                />
              ) : (
                <div className="text-slate-500 text-xs">Select an asset from the vault</div>
              )}
            </div>

            {/* Social Network Posted Colored Checkmarks */}
            {activeMedia && (
              <div className="w-full mt-3">
                <SocialNetworkPostedTracker
                  postedNetworks={activeMedia.postedNetworks || []}
                  onTogglePlatform={(platform) => {
                    const current = activeMedia.postedNetworks || [];
                    const updated = current.includes(platform)
                      ? current.filter((p) => p !== platform)
                      : [...current, platform];
                    const updatedItem = { ...activeMedia, postedNetworks: updated };
                    onSelectMedia(updatedItem);
                    onUpdateMedia?.(updatedItem);
                  }}
                  title="Social Networks Published"
                />
              </div>
            )}

            {/* Quick Actions Bar */}
            <div className="w-full space-y-2 mt-4">
              {/* AI Tweak Button */}
              {activeMedia?.type !== 'video' && (
                <button
                  onClick={() => {
                    setMediaToTweak(activeMedia);
                    setIsTweakerOpen(true);
                  }}
                  className="w-full py-2.5 px-3 rounded-lg bg-gradient-to-r from-purple-600 via-indigo-600 to-purple-700 hover:brightness-110 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-purple-600/20 transition"
                >
                  <Wand2 className="w-4 h-4 text-purple-200" />
                  <span>Edit Photo with AI (Grok, DALL-E, Imagen, Claude)</span>
                </button>
              )}

              {activeMedia?.type === 'video' && onSwitchToVideoStudio && (
                <button
                  onClick={onSwitchToVideoStudio}
                  className="w-full py-2.5 px-3 rounded-lg bg-gradient-to-r from-pink-600 to-rose-600 hover:brightness-110 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-pink-600/20 transition"
                >
                  <Film className="w-4 h-4" />
                  <span>Open in Video Studio (9:16 Reformat, Trim, Stitch)</span>
                </button>
              )}

              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => onSendToCompose(processedUrl || activeMedia?.url || '')}
                  className="py-2.5 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center justify-center gap-1.5 shadow transition"
                >
                  <Send className="w-3.5 h-3.5" />
                  Attach to Mass Post
                </button>

                <button
                  onClick={handleDownloadStamped}
                  className="py-2.5 px-3 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700 font-semibold text-xs flex items-center justify-center gap-1.5 transition"
                >
                  {downloadSuccess ? (
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <Download className="w-3.5 h-3.5 text-slate-400" />
                  )}
                  <span>{downloadSuccess ? 'Downloaded!' : 'Download High-Res'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Watermark, Logo & Upscale Controls (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          {/* Watermark & Logo Section */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 text-indigo-400" />
                Watermark & Logo Stamper
              </span>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={watermarkSettings.enabled}
                  onChange={(e) =>
                    onUpdateWatermark({
                      ...watermarkSettings,
                      enabled: e.target.checked,
                    })
                  }
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
              </label>
            </div>

            {/* Watermark Type Selector */}
            <div className="grid grid-cols-3 gap-1.5 text-xs">
              {(['logo', 'text', 'both'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => onUpdateWatermark({ ...watermarkSettings, type: t })}
                  className={`py-1.5 rounded-md capitalize font-medium transition ${
                    watermarkSettings.type === t
                      ? 'bg-indigo-600 text-white font-bold'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-750'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            {/* Logo Image Picker */}
            {(watermarkSettings.type === 'logo' || watermarkSettings.type === 'both') && (
              <div className="space-y-2 pt-1">
                <div className="flex items-center justify-between text-xs text-slate-300">
                  <span className="font-medium">Logo Stamped:</span>
                  <input
                    type="file"
                    ref={logoInputRef}
                    onChange={handleLogoUpload}
                    accept="image/*"
                    className="hidden"
                  />
                  <button
                    onClick={() => logoInputRef.current?.click()}
                    className="text-indigo-400 hover:underline text-[11px]"
                  >
                    Change Logo
                  </button>
                </div>
                <div className="flex items-center gap-3 bg-slate-950 p-2 rounded-lg border border-slate-800">
                  <div className="w-10 h-10 rounded bg-slate-800 flex items-center justify-center overflow-hidden border border-slate-700 shrink-0">
                    <img
                      src={watermarkSettings.logoUrl}
                      alt="Watermark Logo"
                      className="w-full h-full object-contain"
                    />
                  </div>
                  <div className="flex-1 space-y-1 text-xs">
                    <div className="flex justify-between text-slate-400 text-[10px]">
                      <span>Size: {watermarkSettings.logoScale}%</span>
                      <span>Opacity: {Math.round(watermarkSettings.logoOpacity * 100)}%</span>
                    </div>
                    <input
                      type="range"
                      min="8"
                      max="35"
                      value={watermarkSettings.logoScale}
                      onChange={(e) =>
                        onUpdateWatermark({
                          ...watermarkSettings,
                          logoScale: Number(e.target.value),
                        })
                      }
                      className="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Title Stamp */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
                <span>Top Title Badge Stamp:</span>
                <span className="text-[10px] text-slate-500">Optional</span>
              </label>
              <input
                type="text"
                value={customTitle}
                onChange={(e) => setCustomTitle(e.target.value)}
                placeholder="e.g. BREAKING NEWS or PRODUCT RELEASE"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
              />
            </div>

            {/* Legal / Disclaimer Stamp */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
                <span>Bottom Disclaimer Strip:</span>
                <span className="text-[10px] text-slate-500">FTC / Copyright</span>
              </label>
              <input
                type="text"
                value={customDisclaimer}
                onChange={(e) => setCustomDisclaimer(e.target.value)}
                placeholder="e.g. © 2026 Studio • #Sponsored #Ad"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
              />
            </div>

            {/* Watermark Position Grid */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">Logo/Handle Position:</label>
              <div className="grid grid-cols-3 gap-1 text-[11px]">
                {[
                  { id: 'top-left' as WatermarkPosition, label: 'Top Left' },
                  { id: 'center' as WatermarkPosition, label: 'Center' },
                  { id: 'top-right' as WatermarkPosition, label: 'Top Right' },
                  { id: 'bottom-left' as WatermarkPosition, label: 'Bottom Left' },
                  { id: 'bottom-right' as WatermarkPosition, label: 'Bottom Right' },
                ].map((pos) => (
                  <button
                    key={pos.id}
                    onClick={() =>
                      onUpdateWatermark({ ...watermarkSettings, position: pos.id })
                    }
                    className={`py-1.5 px-1 rounded text-center transition ${
                      watermarkSettings.position === pos.id
                        ? 'bg-indigo-600 text-white font-semibold'
                        : 'bg-slate-800 text-slate-400 hover:bg-slate-750'
                    }`}
                  >
                    {pos.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Super Resolution Upscale & Aspect Ratio */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-white flex items-center gap-1.5">
                  <Maximize2 className="w-4 h-4 text-emerald-400" />
                  Super-Resolution Upscaling
                </span>
                {subscription.plan === 'free' && (
                  <span className="text-[10px] text-amber-400 font-semibold bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                    Pro Feature
                  </span>
                )}
              </div>
              <div className="grid grid-cols-3 gap-1.5 text-xs">
                {([1, 2, 4] as const).map((factor) => (
                  <button
                    key={factor}
                    onClick={() => handleUpscaleSelect(factor)}
                    className={`py-2 rounded-lg font-bold transition flex items-center justify-center gap-1 ${
                      upscaleFactor === factor
                        ? 'bg-emerald-600 text-white'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-750'
                    }`}
                  >
                    <span>{factor}x</span>
                    <span className="text-[10px] opacity-80 font-normal">
                      {factor === 1 ? 'Native' : factor === 2 ? '2K HD' : '4K Ultra'}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Social Aspect Ratio Crop */}
            <div>
              <label className="block text-xs font-bold text-white mb-2 flex items-center gap-1.5">
                <Crop className="w-4 h-4 text-sky-400" />
                Format for Social Platform:
              </label>
              <div className="grid grid-cols-3 gap-1.5 text-[11px]">
                {[
                  { id: 'original' as const, label: 'Original', sub: 'Native' },
                  { id: '1:1' as const, label: '1:1 Square', sub: 'IG / X' },
                  { id: '4:5' as const, label: '4:5 Portrait', sub: 'IG Feed' },
                  { id: '9:16' as const, label: '9:16 Story', sub: 'Reels/TikTok' },
                  { id: '16:9' as const, label: '16:9 Wide', sub: 'YouTube/X' },
                ].map((ratio) => (
                  <button
                    key={ratio.id}
                    onClick={() => setAspectRatio(ratio.id)}
                    className={`p-1.5 rounded-md text-center transition ${
                      aspectRatio === ratio.id
                        ? 'bg-indigo-600 text-white font-bold'
                        : 'bg-slate-800 text-slate-400 hover:bg-slate-750'
                    }`}
                  >
                    <div>{ratio.label}</div>
                    <div className="text-[9px] opacity-75">{ratio.sub}</div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* AI Photo Tweaker Modal */}
      <AIPhotoTweakerModal
        isOpen={isTweakerOpen}
        onClose={() => setIsTweakerOpen(false)}
        photo={mediaToTweak || activeMedia}
        aiProviders={aiProviders}
        onUpdateProviderKey={onUpdateProviderKey}
        onSaveTweakedPhoto={(tweakedItem) => {
          onAddMedia(tweakedItem);
          onSelectMedia(tweakedItem);
        }}
        onSendToCompose={onSendToCompose}
        subscription={subscription}
        onOpenUpgrade={onOpenUpgrade}
      />
    </div>
  );
};
