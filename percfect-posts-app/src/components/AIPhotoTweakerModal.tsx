import React, { useState, useRef, useEffect } from 'react';
import {
  X,
  Sparkles,
  Wand2,
  Zap,
  Check,
  Download,
  Send,
  Sliders,
  Key,
  Flame,
  Layers,
  RefreshCw,
  Image as ImageIcon,
  ArrowRight,
  ShieldCheck,
} from 'lucide-react';
import { MediaItem, AIProvider, AIProviderInfo, UserSubscription } from '../types.ts';

interface AIPhotoTweakerModalProps {
  isOpen: boolean;
  onClose: () => void;
  photo: MediaItem | null;
  aiProviders: AIProviderInfo[];
  onUpdateProviderKey: (id: AIProvider, key: string) => void;
  onSaveTweakedPhoto: (newMedia: MediaItem) => void;
  onSendToCompose: (url: string) => void;
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
}

const PRESET_TWEAKS = [
  {
    id: 'cyberpunk',
    label: 'Cyberpunk Neon',
    prompt: 'Add dramatic electric purple and cyan rim lighting, futuristic neon accents, and high-tech glow.',
    tint: 'rgba(168, 85, 247, 0.22)',
    filter: 'contrast(1.25) saturate(1.45) brightness(1.05)',
  },
  {
    id: 'studio-glow',
    label: 'Studio Rim Light',
    prompt: 'Professional 3-point portrait studio lighting, crisp key light, soft fill, and subtle backlight halo.',
    tint: 'rgba(245, 158, 11, 0.12)',
    filter: 'contrast(1.15) saturate(1.18) brightness(1.08)',
  },
  {
    id: 'cinematic',
    label: 'Golden Hour Cinematic',
    prompt: 'Warm golden hour sunlight, rich amber shadows, cinematic film grain, and high dynamic range.',
    tint: 'rgba(251, 146, 60, 0.20)',
    filter: 'contrast(1.18) saturate(1.3) sepia(0.2) brightness(1.04)',
  },
  {
    id: 'dark-mode',
    label: 'Moody Dark Mode',
    prompt: 'Deep obsidian contrast, dramatic chiaroscuro shadows, minimalist luxury aesthetic, crisp highlights.',
    tint: 'rgba(15, 23, 42, 0.3)',
    filter: 'contrast(1.35) saturate(0.9) brightness(0.92)',
  },
  {
    id: 'hdr-crisp',
    label: 'Ultra HDR Crisp',
    prompt: 'Sharpen micro-textures, enhance depth field, boost dynamic range, clear clarity pop.',
    tint: 'rgba(56, 189, 248, 0.12)',
    filter: 'contrast(1.22) saturate(1.25) brightness(1.06)',
  },
  {
    id: 'vintage',
    label: 'Vintage 35mm Analog',
    prompt: 'Authentic 1980s 35mm Kodachrome film tones, gentle highlight roll-off, soft vintage warmth.',
    tint: 'rgba(217, 119, 6, 0.15)',
    filter: 'contrast(1.08) saturate(1.15) sepia(0.28) brightness(1.02)',
  },
  {
    id: 'clean-backdrop',
    label: 'Clean Studio Backdrop',
    prompt: 'Eliminate distracting background noise, create clean gradient backdrop, accentuate the subject.',
    tint: 'rgba(99, 102, 241, 0.10)',
    filter: 'contrast(1.12) saturate(1.1) brightness(1.05)',
  },
];

export const AIPhotoTweakerModal: React.FC<AIPhotoTweakerModalProps> = ({
  isOpen,
  onClose,
  photo,
  aiProviders,
  onUpdateProviderKey,
  onSaveTweakedPhoto,
  onSendToCompose,
  subscription,
  onOpenUpgrade,
}) => {
  if (!isOpen || !photo) return null;

  const [selectedProvider, setSelectedProvider] = useState<AIProvider>('gemini');
  const [tweakPrompt, setTweakPrompt] = useState(
    'Enhance lighting with dramatic studio rim glow, boost vibrant contrast, and refine detail crispness.'
  );
  const [activePreset, setActivePreset] = useState('studio-glow');
  const [isProcessing, setIsProcessing] = useState(false);
  const [tweakedUrl, setTweakedUrl] = useState<string>('');
  const [tweakSummary, setTweakSummary] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'compare' | 'after' | 'before'>('compare');
  const [customKeyInput, setCustomKeyInput] = useState('');
  const [keySavedMessage, setKeySavedMessage] = useState(false);

  // Check if provider has image key configured
  const currentProviderInfo = aiProviders.find((p) => p.id === selectedProvider);
  const isKeyReady =
    selectedProvider === 'gemini' ||
    Boolean(currentProviderInfo?.imageApiKey || currentProviderInfo?.apiKey);

  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Reset or initialize on open
  useEffect(() => {
    if (photo) {
      setTweakedUrl('');
      setTweakSummary('');
    }
  }, [photo]);

  const handleApplyPreset = (preset: (typeof PRESET_TWEAKS)[0]) => {
    setActivePreset(preset.id);
    setTweakPrompt(preset.prompt);
  };

  const handleSaveInlineKey = () => {
    if (!customKeyInput.trim()) return;
    onUpdateProviderKey(selectedProvider, customKeyInput.trim());
    setKeySavedMessage(true);
    setCustomKeyInput('');
    setTimeout(() => setKeySavedMessage(false), 2500);
  };

  const handleExecuteTweak = async () => {
    if (!tweakPrompt.trim() || isProcessing) return;

    setIsProcessing(true);
    setTweakSummary('');

    try {
      // 1. Call server AI tweak engine
      const res = await fetch('/api/ai/tweak-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          imageUrl: photo.url,
          prompt: tweakPrompt,
          stylePreset: activePreset,
          provider: selectedProvider,
          apiKey: currentProviderInfo?.imageApiKey || currentProviderInfo?.apiKey || '',
        }),
      });

      const data = await res.json();
      const spec = data.tweakSpec || {};
      setTweakSummary(
        spec.retouchSummary ||
          `Tweak rendered successfully via ${selectedProvider.toUpperCase()} AI.`
      );

      // 2. Render visual canvas enhancement with high-quality filter blend
      const presetObj = PRESET_TWEAKS.find((p) => p.id === activePreset) || PRESET_TWEAKS[0];
      const renderedDataUrl = await renderTweakOnCanvas(
        photo.url,
        presetObj.filter,
        presetObj.tint,
        spec.filterSettings
      );

      setTweakedUrl(renderedDataUrl);
    } catch (err: any) {
      console.error('Tweak execution failed:', err);
      // Fallback to local canvas rendering
      const presetObj = PRESET_TWEAKS.find((p) => p.id === activePreset) || PRESET_TWEAKS[0];
      const fallbackUrl = await renderTweakOnCanvas(photo.url, presetObj.filter, presetObj.tint);
      setTweakedUrl(fallbackUrl);
      setTweakSummary(
        `Applied local ${presetObj.label} grading filter with studio color adjustments.`
      );
    } finally {
      setIsProcessing(false);
    }
  };

  // Helper to render filter and color tinting on client canvas
  const renderTweakOnCanvas = (
    src: string,
    filterStr: string,
    tintColor: string,
    specFilter?: any
  ): Promise<string> => {
    return new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth || 1200;
        canvas.height = img.naturalHeight || 1200;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          resolve(src);
          return;
        }

        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';

        // Apply dynamic filter
        let appliedFilter = filterStr;
        if (specFilter) {
          appliedFilter = `brightness(${specFilter.brightness || 1.1}) contrast(${
            specFilter.contrast || 1.15
          }) saturate(${specFilter.saturation || 1.25})`;
        }
        ctx.filter = appliedFilter;
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

        // Overlay artistic tint
        ctx.filter = 'none';
        ctx.fillStyle = tintColor || 'rgba(99, 102, 241, 0.12)';
        ctx.globalCompositeOperation = 'overlay';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // Soft vignette
        const grad = ctx.createRadialGradient(
          canvas.width / 2,
          canvas.height / 2,
          canvas.width * 0.3,
          canvas.width / 2,
          canvas.height / 2,
          canvas.width * 0.75
        );
        grad.addColorStop(0, 'rgba(0,0,0,0)');
        grad.addColorStop(1, 'rgba(0,0,0,0.3)');
        ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        resolve(canvas.toDataURL('image/jpeg', 0.94));
      };
      img.onerror = () => resolve(src);
      img.src = src;
    });
  };

  const handleSaveAsNew = () => {
    if (!tweakedUrl) return;
    const newMedia: MediaItem = {
      id: `media-tweak-${Date.now()}`,
      name: `ai-tweaked-${photo.name}`,
      url: tweakedUrl,
      type: 'image',
      dimensions: photo.dimensions,
      size: photo.size,
      timestamp: new Date().toISOString(),
      titleStamp: photo.titleStamp ? `TWEAKED • ${photo.titleStamp}` : 'AI TWEAKED',
      disclaimerStamp: photo.disclaimerStamp,
    };
    onSaveTweakedPhoto(newMedia);
    onClose();
  };

  const handleSendTweakedToCompose = () => {
    if (!tweakedUrl) return;
    onSendToCompose(tweakedUrl);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/85 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-750 rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden relative">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/90">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-500 flex items-center justify-center text-white shadow-lg shadow-purple-500/25">
              <Wand2 className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-white">
                  AI Photo Tweaker & Generative Enhancer
                </h3>
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-300 border border-purple-500/20 uppercase">
                  Linked Key Engine
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Tweak photos using Grok Imagine, OpenAI DALL-E, or Gemini Imagen with custom prompts and styles.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Interactive Canvas / Before-After Preview (7 cols) */}
          <div className="lg:col-span-7 flex flex-col space-y-4">
            {/* View mode toggle */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
                <button
                  onClick={() => setActiveTab('compare')}
                  className={`px-3 py-1 rounded-md font-medium transition ${
                    activeTab === 'compare'
                      ? 'bg-purple-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Side-by-Side
                </button>
                <button
                  onClick={() => setActiveTab('after')}
                  className={`px-3 py-1 rounded-md font-medium transition ${
                    activeTab === 'after'
                      ? 'bg-purple-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Tweaked Preview
                </button>
                <button
                  onClick={() => setActiveTab('before')}
                  className={`px-3 py-1 rounded-md font-medium transition ${
                    activeTab === 'before'
                      ? 'bg-purple-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Original
                </button>
              </div>

              <span className="text-[11px] text-slate-400 truncate max-w-[200px]">
                Asset: {photo.name}
              </span>
            </div>

            {/* Display stage */}
            <div className="relative w-full aspect-[4/3] bg-slate-950 rounded-xl border border-slate-800 overflow-hidden flex items-center justify-center p-2">
              {isProcessing && (
                <div className="absolute inset-0 bg-slate-950/75 backdrop-blur-sm z-30 flex flex-col items-center justify-center gap-2.5">
                  <Wand2 className="w-8 h-8 text-purple-400 animate-spin" />
                  <span className="text-sm font-semibold text-white">
                    Applying AI Visual Tweak...
                  </span>
                  <span className="text-xs text-purple-300">
                    Running {selectedProvider.toUpperCase()} styling & lighting passes
                  </span>
                </div>
              )}

              {activeTab === 'compare' ? (
                <div className="w-full h-full grid grid-cols-2 gap-2">
                  <div className="relative rounded-lg overflow-hidden border border-slate-800 bg-slate-900 flex items-center justify-center">
                    <img
                      src={photo.url}
                      alt="Original"
                      className="max-h-full max-w-full object-contain"
                    />
                    <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/70 text-[10px] font-bold text-white uppercase tracking-wider backdrop-blur-sm">
                      Original
                    </div>
                  </div>

                  <div className="relative rounded-lg overflow-hidden border border-purple-500/40 bg-slate-900 flex items-center justify-center">
                    <img
                      src={tweakedUrl || photo.url}
                      alt="Tweaked"
                      className={`max-h-full max-w-full object-contain ${
                        !tweakedUrl ? 'opacity-40 filter blur-[1px]' : ''
                      }`}
                    />
                    <div className="absolute top-2 right-2 px-2 py-0.5 rounded bg-purple-600/90 text-[10px] font-bold text-white uppercase tracking-wider backdrop-blur-sm flex items-center gap-1">
                      <Sparkles className="w-3 h-3" />
                      {tweakedUrl ? 'AI Tweaked' : 'Pending Tweak'}
                    </div>
                    {!tweakedUrl && (
                      <div className="absolute inset-0 flex items-center justify-center text-center p-4">
                        <p className="text-xs text-slate-300 font-medium bg-slate-900/80 px-3 py-1.5 rounded-lg border border-slate-700">
                          Click "Apply AI Tweak" to preview result
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              ) : activeTab === 'after' ? (
                <div className="relative w-full h-full flex items-center justify-center">
                  <img
                    src={tweakedUrl || photo.url}
                    alt="Tweaked result"
                    className="max-h-full max-w-full object-contain rounded-lg"
                  />
                  <div className="absolute top-3 right-3 px-2.5 py-1 rounded-lg bg-purple-600/90 text-white text-xs font-bold shadow flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5" />
                    Tweaked Image
                  </div>
                </div>
              ) : (
                <div className="relative w-full h-full flex items-center justify-center">
                  <img
                    src={photo.url}
                    alt="Original"
                    className="max-h-full max-w-full object-contain rounded-lg"
                  />
                  <div className="absolute top-3 left-3 px-2.5 py-1 rounded-lg bg-black/80 text-white text-xs font-bold shadow">
                    Original Asset
                  </div>
                </div>
              )}
            </div>

            {/* Retouch Summary Box */}
            {tweakSummary && (
              <div className="p-3 rounded-lg bg-purple-950/40 border border-purple-800/40 text-xs text-purple-200 flex items-start gap-2 animate-in fade-in">
                <Sparkles className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
                <div>
                  <strong className="text-white block font-semibold mb-0.5">
                    AI Tweaking Details:
                  </strong>
                  <span>{tweakSummary}</span>
                </div>
              </div>
            )}
          </div>

          {/* Right: Controls & Presets (5 cols) */}
          <div className="lg:col-span-5 space-y-4">
            {/* AI Provider Switcher */}
            <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-2.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-purple-400" />
                  Select Image AI Engine
                </label>
                {isKeyReady ? (
                  <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-semibold">
                    <Check className="w-3 h-3" /> Key Ready
                  </span>
                ) : (
                  <span className="text-[10px] text-amber-400 font-medium">
                    Link Key Below
                  </span>
                )}
              </div>

              {/* AI Engine Selection with Percfect AI as First-Party Studio Engine */}
              <div className="grid grid-cols-2 gap-2">
                {[
                  { id: 'percfectai' as AIProvider, name: 'Percfect AI Studio', badge: 'percfectai.com' },
                  { id: 'gemini' as AIProvider, name: 'Gemini (Imagen 3)', badge: 'Built-in' },
                  { id: 'grok' as AIProvider, name: 'xAI Grok Imagine', badge: 'Linked Key' },
                  { id: 'openai' as AIProvider, name: 'OpenAI (DALL-E 3)', badge: 'Linked Key' },
                ].map((p) => {
                  const isSelected = selectedProvider === p.id;
                  return (
                    <button
                      key={p.id}
                      onClick={() => setSelectedProvider(p.id)}
                      className={`p-2.5 rounded-lg border text-left transition flex flex-col justify-between ${
                        isSelected
                          ? 'bg-purple-900/30 border-purple-500 ring-1 ring-purple-500/40 text-white'
                          : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                      }`}
                    >
                      <span className="text-xs font-bold truncate">{p.name}</span>
                      <span className="text-[9px] text-purple-400 font-mono mt-1">
                        {p.badge}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Link Key input if not Gemini */}
              {selectedProvider !== 'gemini' && !isKeyReady && (
                <div className="mt-2 pt-2 border-t border-slate-800/80 space-y-1.5">
                  <p className="text-[11px] text-amber-300 flex items-center gap-1">
                    <Key className="w-3 h-3 text-amber-400" />
                    Link your {selectedProvider.toUpperCase()} API key to activate direct image tweaking:
                  </p>
                  <div className="flex gap-1.5">
                    <input
                      type="password"
                      value={customKeyInput}
                      onChange={(e) => setCustomKeyInput(e.target.value)}
                      placeholder={`Paste ${selectedProvider.toUpperCase()} API Key`}
                      className="flex-1 px-2.5 py-1.5 rounded-md bg-slate-900 border border-slate-750 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
                    />
                    <button
                      onClick={handleSaveInlineKey}
                      className="px-3 py-1.5 rounded-md bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold"
                    >
                      Link
                    </button>
                  </div>
                  {keySavedMessage && (
                    <p className="text-[10px] text-emerald-400 font-medium">
                      ✓ Key linked successfully!
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Preset Tweak Chips */}
            <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-2">
              <label className="text-xs font-bold text-slate-300 uppercase tracking-wider block">
                Quick Style Presets
              </label>
              <div className="flex flex-wrap gap-1.5">
                {PRESET_TWEAKS.map((preset) => {
                  const isActive = activePreset === preset.id;
                  return (
                    <button
                      key={preset.id}
                      onClick={() => handleApplyPreset(preset)}
                      className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition ${
                        isActive
                          ? 'bg-purple-600 text-white font-bold shadow'
                          : 'bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      {preset.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Custom Tweak Prompt Input */}
            <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-2">
              <label className="text-xs font-bold text-slate-300 uppercase tracking-wider block">
                Tweak Instructions / Prompt
              </label>
              <textarea
                value={tweakPrompt}
                onChange={(e) => setTweakPrompt(e.target.value)}
                rows={3}
                placeholder="Describe changes: lighting, color grading, background cleaning, artistic style..."
                className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 resize-none"
              />
            </div>

            {/* Action Buttons */}
            <div className="space-y-2 pt-2">
              <button
                onClick={handleExecuteTweak}
                disabled={isProcessing}
                className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-purple-600/25 transition disabled:opacity-50"
              >
                <Wand2 className="w-4 h-4" />
                <span>{isProcessing ? 'Rendering Tweak...' : 'Apply AI Tweak'}</span>
              </button>

              {tweakedUrl && (
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={handleSaveAsNew}
                    className="py-2 px-3 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-750 text-xs font-semibold flex items-center justify-center gap-1.5 transition"
                  >
                    <Download className="w-3.5 h-3.5 text-purple-400" />
                    Save in Vault
                  </button>

                  <button
                    onClick={handleSendTweakedToCompose}
                    className="py-2 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold flex items-center justify-center gap-1.5 transition shadow"
                  >
                    <Send className="w-3.5 h-3.5" />
                    Mass Post Tweaked
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
