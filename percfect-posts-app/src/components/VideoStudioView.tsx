import React, { useState, useRef, useEffect } from 'react';
import {
  Video as VideoIcon,
  Play,
  Pause,
  Scissors,
  Camera,
  Layers,
  Crop,
  Sparkles,
  Send,
  Upload,
  Crown,
  Download,
  Plus,
  Trash2,
  MoveUp,
  MoveDown,
  Maximize2,
  Check,
  Film,
  Zap,
  Clock,
  Sliders,
  ShieldCheck,
  Volume2,
  VolumeX,
  ExternalLink,
} from 'lucide-react';
import {
  MediaItem,
  VideoFormat,
  VideoClip,
  FreezeFrameItem,
  UserSubscription,
  WatermarkSettings,
} from '../types.ts';

interface VideoStudioViewProps {
  mediaList: MediaItem[];
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
  onSendToCompose: (videoUrl: string) => void;
  onAddMedia: (item: MediaItem) => void;
  watermarkSettings: WatermarkSettings;
}

export const VideoStudioView: React.FC<VideoStudioViewProps> = ({
  mediaList,
  subscription,
  onOpenUpgrade,
  onSendToCompose,
  onAddMedia,
  watermarkSettings,
}) => {
  // Filter for video assets
  const videoItems = mediaList.filter((m) => m.type === 'video');

  // Active selected video
  const [activeVideo, setActiveVideo] = useState<MediaItem | null>(
    videoItems[0] || null
  );

  // Player state
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(15);
  const [isMuted, setIsMuted] = useState(false);

  // 1. Reformatting state
  const [aspectFormat, setAspectFormat] = useState<VideoFormat>('9:16');
  const [cropMode, setCropMode] = useState<'contain' | 'cover'>('cover');

  // 2. Cropping & Trimming state
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(15);

  // 3. Freeze Frame state
  const [freezeDuration, setFreezeDuration] = useState(3);
  const [isFreezeActive, setIsFreezeActive] = useState(false);
  const [capturedFrames, setCapturedFrames] = useState<FreezeFrameItem[]>([]);
  const [screenshotSuccess, setScreenshotSuccess] = useState(false);

  // 4. Stitching Sequencer state
  const [stitchedClips, setStitchedClips] = useState<VideoClip[]>([
    {
      id: 'clip-1',
      name: 'Intro Hook (ForBiggerBlazes)',
      url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
      duration: 15,
      trimStart: 0,
      trimEnd: 5,
      title: 'Viral Hook Cut',
    },
    {
      id: 'clip-2',
      name: 'Main Showcase (WeAreGoingOnBullrun)',
      url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WeAreGoingOnBullrun.mp4',
      duration: 20,
      trimStart: 2,
      trimEnd: 10,
      title: 'Feature Deep-Dive',
    },
  ]);
  const [activeClipIndex, setActiveClipIndex] = useState(0);
  const [stitchTransition, setStitchTransition] = useState<'cut' | 'fade' | 'black'>('fade');
  const [isStitchingPreview, setIsStitchingPreview] = useState(false);

  // Video and Canvas refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const hiddenCanvasRef = useRef<HTMLCanvasElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isPro = subscription.plan !== 'free';

  // Handle video metadata loaded
  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      const vidDur = Math.round(videoRef.current.duration || 15);
      setDuration(vidDur);
      setTrimEnd(vidDur);
    }
  };

  // Scrubber time update
  const handleTimeUpdate = () => {
    if (videoRef.current) {
      const curr = videoRef.current.currentTime;
      setCurrentTime(curr);

      // Loop within trim range if trimming is enabled
      if (curr >= trimEnd) {
        videoRef.current.currentTime = trimStart;
        if (!isPlaying) {
          videoRef.current.pause();
        }
      }
    }
  };

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    } else {
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  // 1. Screenshot / Capture Frame at current timestamp
  const handleCaptureScreenshot = () => {
    if (!videoRef.current) return;

    const video = videoRef.current;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // If watermark enabled, overlay title & disclaimer
    if (watermarkSettings.enabled) {
      ctx.fillStyle = 'rgba(15, 23, 42, 0.8)';
      ctx.fillRect(0, canvas.height - 60, canvas.width, 60);
      ctx.fillStyle = '#FFFFFF';
      ctx.font = 'bold 20px "Plus Jakarta Sans", sans-serif';
      ctx.fillText(
        `SCREENSHOT @ ${formatTime(currentTime)} • ${watermarkSettings.watermarkText || 'MASS POST STUDIO'}`,
        30,
        canvas.height - 24
      );
    }

    const dataUrl = canvas.toDataURL('image/jpeg', 0.95);
    const frameItem: FreezeFrameItem = {
      id: `frame-${Date.now()}`,
      timestamp: currentTime,
      capturedImageUrl: dataUrl,
      title: `Snapshot @ ${formatTime(currentTime)}`,
      createdAt: new Date().toLocaleTimeString(),
    };

    setCapturedFrames((prev) => [frameItem, ...prev]);

    // Also automatically add to vault as an image asset
    const newMedia: MediaItem = {
      id: `media-snapshot-${Date.now()}`,
      name: `screenshot-${formatTime(currentTime).replace(':', '-')}.jpg`,
      url: dataUrl,
      type: 'image',
      dimensions: { width: canvas.width, height: canvas.height },
      size: '1.2 MB',
      timestamp: new Date().toISOString(),
      titleStamp: `SNAPSHOT @ ${formatTime(currentTime)}`,
      disclaimerStamp: 'Captured via Video Studio',
    };
    onAddMedia(newMedia);

    setScreenshotSuccess(true);
    setTimeout(() => setScreenshotSuccess(false), 2500);
  };

  // 2. Freeze frame trigger
  const handleTriggerFreezeFrame = () => {
    if (!videoRef.current) return;
    videoRef.current.pause();
    setIsPlaying(false);
    setIsFreezeActive(true);

    // Auto-unfreeze after freezeDuration seconds
    setTimeout(() => {
      setIsFreezeActive(false);
    }, freezeDuration * 1000);
  };

  // 3. Video upload handler
  const handleVideoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const url = URL.createObjectURL(file);
    const newVideo: MediaItem = {
      id: `media-v-${Date.now()}`,
      name: file.name,
      url,
      type: 'video',
      dimensions: { width: 1920, height: 1080 },
      size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
      timestamp: new Date().toISOString(),
      titleStamp: 'VIRAL CREATOR CLIP',
      disclaimerStamp: 'Original Media Stamped',
    };

    onAddMedia(newVideo);
    setActiveVideo(newVideo);
  };

  // 4. Stitching sequence controls
  const handleAddClipToStitch = (item: MediaItem) => {
    const newClip: VideoClip = {
      id: `clip-${Date.now()}`,
      name: item.name,
      url: item.url,
      duration: 15,
      trimStart: 0,
      trimEnd: 15,
      title: item.name.replace(/\.[^/.]+$/, ''),
    };
    setStitchedClips((prev) => [...prev, newClip]);
  };

  const handleRemoveStitchClip = (id: string) => {
    setStitchedClips((prev) => prev.filter((c) => c.id !== id));
  };

  const handleMoveClip = (index: number, direction: 'up' | 'down') => {
    const targetIdx = direction === 'up' ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= stitchedClips.length) return;
    const newArr = [...stitchedClips];
    const temp = newArr[index];
    newArr[index] = newArr[targetIdx];
    newArr[targetIdx] = temp;
    setStitchedClips(newArr);
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 10);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms}`;
  };

  // Aspect ratio styling calculation for simulator
  const getAspectRatioClasses = () => {
    switch (aspectFormat) {
      case '9:16':
        return 'aspect-[9/16] max-h-[500px]';
      case '16:9':
        return 'aspect-[16/9] max-h-[380px]';
      case '1:1':
        return 'aspect-square max-h-[440px]';
      case '4:5':
        return 'aspect-[4/5] max-h-[480px]';
      default:
        return 'aspect-[16/9] max-h-[400px]';
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Banner & Pro Monetization Badge */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-xl p-4 sm:p-5">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-pink-600 to-rose-500 flex items-center justify-center text-white shadow-lg shadow-pink-500/20">
              <Film className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                Video Studio & Mass Dispatch
                <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 uppercase tracking-wider flex items-center gap-1 shadow">
                  <Crown className="w-3 h-3" /> Pro Feature
                </span>
              </h2>
            </div>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Reformat to 9:16 TikTok/Reels, capture high-res frame screenshots, freeze-frame timestamps, crop/trim, and stitch multi-clip videos to mass post.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleVideoUpload}
            accept="video/*"
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-pink-600 hover:bg-pink-500 text-white text-xs font-semibold shadow transition"
          >
            <Upload className="w-3.5 h-3.5" />
            Upload Video
          </button>

          {!isPro && (
            <button
              onClick={onOpenUpgrade}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-bold hover:bg-amber-500/25 transition"
            >
              <Crown className="w-3.5 h-3.5 text-amber-400" />
              Upgrade for 25GB Storage
            </button>
          )}
        </div>
      </div>

      {/* Main Studio Workspace Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Video Library & Sequencer (3 cols) */}
        <div className="lg:col-span-3 space-y-4">
          {/* Storage Meter */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between mb-2 text-xs">
              <span className="font-semibold text-slate-300">Cloud Storage Vault</span>
              <span className="text-purple-400 font-mono text-[11px]">
                {subscription.storageLabel}
              </span>
            </div>
            <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden mb-2">
              <div
                className="h-full bg-gradient-to-r from-purple-500 to-pink-500 rounded-full"
                style={{
                  width: `${Math.min(
                    100,
                    (subscription.storageUsedBytes / subscription.storageLimitBytes) * 100
                  )}%`,
                }}
              ></div>
            </div>
            <p className="text-[10px] text-slate-500 flex items-center justify-between">
              <span>{isPro ? 'Pro Creator Vault (25 GB)' : 'Free Tier (500 MB)'}</span>
              {!isPro && (
                <button
                  onClick={onOpenUpgrade}
                  className="text-amber-400 hover:underline font-semibold"
                >
                  Expand
                </button>
              )}
            </p>
          </div>

          {/* Video Vault Clips */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                Video Clips ({videoItems.length})
              </span>
              <span className="text-[10px] text-slate-500">Ready to Edit</span>
            </div>

            <div className="space-y-2 max-h-[300px] overflow-y-auto no-scrollbar pr-1">
              {videoItems.map((item) => {
                const isSelected = activeVideo?.id === item.id;
                return (
                  <div
                    key={item.id}
                    onClick={() => {
                      setActiveVideo(item);
                      setIsPlaying(false);
                    }}
                    className={`p-2.5 rounded-lg border cursor-pointer transition flex items-center justify-between ${
                      isSelected
                        ? 'bg-pink-950/40 border-pink-500 text-white'
                        : 'bg-slate-950/60 border-slate-800 text-slate-300 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="w-8 h-8 rounded bg-slate-800 flex items-center justify-center text-pink-400 shrink-0">
                        <Film className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs font-semibold truncate">{item.name}</p>
                        <p className="text-[10px] text-slate-500">{item.size}</p>
                      </div>
                    </div>
                    {isSelected && <span className="w-2 h-2 rounded-full bg-pink-500"></span>}
                  </div>
                );
              })}
            </div>

            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-full py-2 rounded-lg border border-dashed border-slate-700 hover:border-pink-500/80 text-slate-400 hover:text-slate-200 text-xs font-medium flex items-center justify-center gap-1.5 transition"
            >
              <Plus className="w-3.5 h-3.5" />
              Add More Video Files
            </button>
          </div>

          {/* Captured Screenshots Strip */}
          {capturedFrames.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2.5">
              <span className="text-xs font-bold text-slate-300 uppercase tracking-wider block">
                Captured Frames ({capturedFrames.length})
              </span>
              <div className="grid grid-cols-2 gap-2 max-h-[160px] overflow-y-auto">
                {capturedFrames.map((frame) => (
                  <div
                    key={frame.id}
                    className="relative group rounded-lg overflow-hidden border border-slate-800 aspect-video"
                  >
                    <img
                      src={frame.capturedImageUrl}
                      alt={frame.title}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 flex items-center justify-center gap-1 transition">
                      <button
                        onClick={() => onSendToCompose(frame.capturedImageUrl)}
                        className="p-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-500 text-[10px] font-bold"
                        title="Mass Post Snapshot"
                      >
                        <Send className="w-3 h-3" />
                      </button>
                    </div>
                    <span className="absolute bottom-1 left-1 px-1 py-0.2 rounded bg-black/75 text-[9px] text-white">
                      {formatTime(frame.timestamp)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Center: Live Video Player & Aspect Ratio Simulator (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col items-center">
            {/* Header info */}
            <div className="w-full flex items-center justify-between pb-3 border-b border-slate-800 mb-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-white truncate max-w-[200px]">
                  {activeVideo?.name || 'Select Video Clip'}
                </span>
                <span className="px-2 py-0.5 rounded bg-pink-500/20 text-pink-300 font-mono text-[10px] border border-pink-500/30 uppercase">
                  Format: {aspectFormat}
                </span>
              </div>
              <span className="font-mono text-slate-400 text-xs">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            </div>

            {/* Video Stage with Aspect Ratio Simulator Container */}
            <div className="relative w-full bg-slate-950 rounded-xl border border-slate-800 overflow-hidden flex items-center justify-center p-2 min-h-[380px]">
              {/* Freeze Frame Overlay Banner */}
              {isFreezeActive && (
                <div className="absolute inset-0 bg-cyan-950/70 backdrop-blur-xs z-30 flex flex-col items-center justify-center gap-2 animate-in fade-in">
                  <div className="px-3 py-1.5 rounded-full bg-cyan-500 text-slate-950 text-xs font-black uppercase tracking-widest shadow-lg flex items-center gap-1.5 animate-pulse">
                    <Clock className="w-4 h-4" />
                    FREEZE FRAME ACTIVE ({freezeDuration}s)
                  </div>
                  <span className="text-xs text-cyan-200 font-mono">
                    Holding frame at {formatTime(currentTime)}
                  </span>
                </div>
              )}

              {/* Watermark Overlay on video */}
              {watermarkSettings.enabled && (
                <div className="absolute top-4 right-4 z-20 pointer-events-none px-2.5 py-1 rounded bg-black/75 border border-white/20 text-[10px] font-bold text-white shadow-md">
                  {watermarkSettings.watermarkText || '@MassPostStudio'}
                </div>
              )}

              {/* Video Element inside Aspect ratio container */}
              <div
                className={`relative overflow-hidden rounded-lg bg-black flex items-center justify-center transition-all duration-300 ${getAspectRatioClasses()}`}
              >
                {activeVideo ? (
                  <video
                    ref={videoRef}
                    src={activeVideo.url}
                    onLoadedMetadata={handleLoadedMetadata}
                    onTimeUpdate={handleTimeUpdate}
                    muted={isMuted}
                    playsInline
                    className={`w-full h-full ${
                      cropMode === 'cover' ? 'object-cover' : 'object-contain'
                    }`}
                  />
                ) : (
                  <div className="text-slate-500 text-xs">Select a video clip</div>
                )}

                {/* Safe zone overlay for 9:16 vertical TikTok/Reels */}
                {aspectFormat === '9:16' && (
                  <div className="absolute inset-0 pointer-events-none border-2 border-dashed border-white/20 rounded-lg flex flex-col justify-between p-3 text-[9px] text-white/50">
                    <span className="self-center bg-black/40 px-2 py-0.5 rounded">
                      Safe Top Header
                    </span>
                    <span className="self-center bg-black/40 px-2 py-0.5 rounded">
                      Caption & Audio Safe Zone
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Playback Controls & Scrubber */}
            <div className="w-full space-y-3 mt-3">
              {/* Scrubber Range Slider */}
              <div className="space-y-1">
                <input
                  type="range"
                  min={0}
                  max={duration || 15}
                  step={0.1}
                  value={currentTime}
                  onChange={(e) => {
                    const t = parseFloat(e.target.value);
                    setCurrentTime(t);
                    if (videoRef.current) {
                      videoRef.current.currentTime = t;
                    }
                  }}
                  className="w-full accent-pink-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
                />
                <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                  <span>In: {formatTime(trimStart)}</span>
                  <span>Scrubber: {formatTime(currentTime)}</span>
                  <span>Out: {formatTime(trimEnd)}</span>
                </div>
              </div>

              {/* Action Buttons Bar */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={togglePlay}
                    className="p-2.5 rounded-lg bg-pink-600 hover:bg-pink-500 text-white font-bold transition shadow"
                    title={isPlaying ? 'Pause' : 'Play'}
                  >
                    {isPlaying ? (
                      <Pause className="w-4 h-4" />
                    ) : (
                      <Play className="w-4 h-4 fill-white" />
                    )}
                  </button>

                  <button
                    onClick={() => setIsMuted(!isMuted)}
                    className="p-2.5 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-300 transition"
                    title={isMuted ? 'Unmute' : 'Mute'}
                  >
                    {isMuted ? (
                      <VolumeX className="w-4 h-4 text-rose-400" />
                    ) : (
                      <Volume2 className="w-4 h-4" />
                    )}
                  </button>
                </div>

                {/* Screenshot Frame Capture */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleCaptureScreenshot}
                    className="py-2 px-3 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700 text-xs font-semibold flex items-center gap-1.5 transition"
                    title="Capture current frame as photo"
                  >
                    {screenshotSuccess ? (
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <Camera className="w-3.5 h-3.5 text-pink-400" />
                    )}
                    <span>{screenshotSuccess ? 'Captured!' : 'Capture Frame'}</span>
                  </button>

                  <button
                    onClick={handleTriggerFreezeFrame}
                    className="py-2 px-3 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700 text-xs font-semibold flex items-center gap-1.5 transition"
                    title="Freeze frame for N seconds"
                  >
                    <Clock className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Freeze ({freezeDuration}s)</span>
                  </button>
                </div>
              </div>

              {/* Direct Post Stitched/Active Video & Percfect AI Render Action */}
              <div className="w-full pt-2 flex flex-col sm:flex-row gap-2">
                <button
                  onClick={() => onSendToCompose(activeVideo?.url || '')}
                  className="flex-1 py-3 px-4 rounded-xl bg-gradient-to-r from-pink-600 via-rose-600 to-indigo-600 hover:brightness-110 text-white font-extrabold text-xs flex items-center justify-center gap-2 shadow-lg shadow-pink-600/25 transition"
                >
                  <Send className="w-4 h-4" />
                  <span>Attach Video to Mass Post (TikTok, Reels, Shorts, X)</span>
                </button>

                <a
                  href="https://percfectai.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="py-3 px-3.5 rounded-xl bg-slate-800 hover:bg-slate-750 text-purple-300 border border-purple-500/40 font-bold text-xs flex items-center justify-center gap-1.5 transition shrink-0"
                  title="Generate or render AI avatars with your backend at percfectai.com"
                >
                  <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                  <span>percfectai.com Studio</span>
                  <ExternalLink className="w-3 h-3 text-slate-400" />
                </a>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Reformatting, Trimming & Multi-Clip Stitching Suite (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          {/* 1. Reformatting Suite */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Crop className="w-4 h-4 text-pink-400" />
              1. Platform Reformatting
            </span>
            <p className="text-[11px] text-slate-400">
              Instantly adjust aspect ratio for viral short-form feeds or widescreen channels.
            </p>

            <div className="grid grid-cols-2 gap-2">
              {[
                { id: '9:16' as VideoFormat, label: '9:16 Vertical', sub: 'TikTok, Reels, Shorts' },
                { id: '16:9' as VideoFormat, label: '16:9 Widescreen', sub: 'YouTube, X, LinkedIn' },
                { id: '1:1' as VideoFormat, label: '1:1 Square', sub: 'Instagram, Feed' },
                { id: '4:5' as VideoFormat, label: '4:5 Portrait', sub: 'Instagram Carousel' },
              ].map((fmt) => (
                <button
                  key={fmt.id}
                  onClick={() => setAspectFormat(fmt.id)}
                  className={`p-2.5 rounded-lg border text-left transition ${
                    aspectFormat === fmt.id
                      ? 'bg-pink-900/30 border-pink-500 text-white ring-1 ring-pink-500/40'
                      : 'bg-slate-950/60 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                  }`}
                >
                  <span className="text-xs font-bold block">{fmt.label}</span>
                  <span className="text-[9px] text-slate-500 block truncate">{fmt.sub}</span>
                </button>
              ))}
            </div>

            <div className="flex items-center justify-between pt-1 border-t border-slate-800 text-xs text-slate-300">
              <span>Crop Mode:</span>
              <div className="flex gap-1">
                <button
                  onClick={() => setCropMode('cover')}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium ${
                    cropMode === 'cover' ? 'bg-pink-600 text-white' : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  Cover Fill
                </button>
                <button
                  onClick={() => setCropMode('contain')}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium ${
                    cropMode === 'contain' ? 'bg-pink-600 text-white' : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  Letterbox
                </button>
              </div>
            </div>
          </div>

          {/* 2. Cropping & Trimming Suite */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Scissors className="w-4 h-4 text-cyan-400" />
              2. Trim & Clip In/Out Points
            </span>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-300">
                <span>Start Time (Trim In):</span>
                <span className="font-mono text-cyan-300">{formatTime(trimStart)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={Math.max(0, trimEnd - 1)}
                step={0.5}
                value={trimStart}
                onChange={(e) => setTrimStart(parseFloat(e.target.value))}
                className="w-full accent-cyan-500 h-1.5 bg-slate-800 rounded"
              />

              <div className="flex items-center justify-between text-xs text-slate-300 pt-1">
                <span>End Time (Trim Out):</span>
                <span className="font-mono text-cyan-300">{formatTime(trimEnd)}</span>
              </div>
              <input
                type="range"
                min={trimStart + 1}
                max={duration || 15}
                step={0.5}
                value={trimEnd}
                onChange={(e) => setTrimEnd(parseFloat(e.target.value))}
                className="w-full accent-cyan-500 h-1.5 bg-slate-800 rounded"
              />
            </div>

            <div className="p-2 rounded bg-slate-950/60 border border-slate-800 text-[11px] text-slate-400 flex items-center justify-between">
              <span>Trimmed Video Duration:</span>
              <strong className="text-white font-mono">{formatTime(trimEnd - trimStart)}</strong>
            </div>
          </div>

          {/* 3. Multi-Video Stitching Sequencer */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                <Layers className="w-4 h-4 text-purple-400" />
                3. Multi-Video Stitching
              </span>
              <span className="text-[10px] text-purple-400 font-semibold">
                {stitchedClips.length} Clips Queued
              </span>
            </div>

            <p className="text-[11px] text-slate-400">
              Combine multiple clips in sequence with custom transitions to form a full-length video.
            </p>

            {/* Sequence Timeline */}
            <div className="space-y-2 max-h-[220px] overflow-y-auto no-scrollbar">
              {stitchedClips.map((clip, idx) => (
                <div
                  key={clip.id}
                  className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="w-5 h-5 rounded-full bg-purple-600/30 text-purple-300 font-bold flex items-center justify-center text-[10px] shrink-0">
                      {idx + 1}
                    </span>
                    <div className="min-w-0">
                      <p className="font-semibold text-white truncate">{clip.name}</p>
                      <p className="text-[10px] text-slate-500 font-mono">
                        Duration: {clip.trimEnd - clip.trimStart}s
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleMoveClip(idx, 'up')}
                      disabled={idx === 0}
                      className="p-1 rounded text-slate-400 hover:text-white disabled:opacity-30"
                    >
                      <MoveUp className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => handleMoveClip(idx, 'down')}
                      disabled={idx === stitchedClips.length - 1}
                      className="p-1 rounded text-slate-400 hover:text-white disabled:opacity-30"
                    >
                      <MoveDown className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => handleRemoveStitchClip(clip.id)}
                      className="p-1 rounded text-rose-400 hover:text-rose-300"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Transition selector */}
            <div className="flex items-center justify-between text-xs text-slate-300 pt-1 border-t border-slate-800">
              <span>Transition:</span>
              <div className="flex gap-1">
                {(['cut', 'fade', 'black'] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setStitchTransition(t)}
                    className={`px-2 py-0.5 rounded capitalize text-[11px] font-medium ${
                      stitchTransition === t
                        ? 'bg-purple-600 text-white'
                        : 'bg-slate-800 text-slate-400'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            {/* Quick add clip button */}
            {activeVideo && (
              <button
                onClick={() => handleAddClipToStitch(activeVideo)}
                className="w-full py-2 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700 text-xs font-semibold flex items-center justify-center gap-1.5 transition"
              >
                <Plus className="w-3.5 h-3.5 text-purple-400" />
                Add Active Video to Stitch Timeline
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
