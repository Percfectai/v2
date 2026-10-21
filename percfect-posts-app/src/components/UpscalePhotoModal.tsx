import React, { useState } from 'react';
import {
  Sparkles,
  Maximize2,
  X,
  Zap,
  Check,
  Crown,
  Layers,
  Cpu,
  ArrowRight,
  ShieldAlert,
  Download,
} from 'lucide-react';
import { MediaItem, UserSubscription } from '../types.ts';

interface UpscalePhotoModalProps {
  isOpen: boolean;
  onClose: () => void;
  photo: MediaItem | null;
  onSaveUpscaled: (newMedia: MediaItem) => void;
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
}

export const UpscalePhotoModal: React.FC<UpscalePhotoModalProps> = ({
  isOpen,
  onClose,
  photo,
  onSaveUpscaled,
  subscription,
  onOpenUpgrade,
}) => {
  if (!isOpen || !photo) return null;

  const isFree = subscription.plan === 'free';
  const isPro = subscription.plan === 'pro';
  const isPremium = subscription.plan === 'premium' || subscription.plan === 'agency';

  // Pro is allowed to upscale to 5 megapixels; Premium is 10 megapixels
  const [targetMegapixels, setTargetMegapixels] = useState<5 | 10>(isPremium ? 10 : 5);
  const [modelType, setModelType] = useState<'real-esrgan' | 'ultrasharp' | 'digital-art'>('ultrasharp');
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState('');
  const [isCompleted, setIsCompleted] = useState(false);
  const [upscaledUrl, setUpscaledUrl] = useState<string | null>(null);

  const originalWidth = photo.dimensions?.width || 1200;
  const originalHeight = photo.dimensions?.height || 800;
  
  // Calculate scaled dimensions to match 5MP (~2560x1920) or 10MP (~3840x2600)
  const targetWidth = targetMegapixels === 10 ? 3840 : 2560;
  const targetHeight = targetMegapixels === 10 ? 2600 : 1920;
  const scaleFactor = targetMegapixels === 10 ? 4 : 2;

  const handleStartUpscale = () => {
    if (isFree) {
      onOpenUpgrade();
      return;
    }
    if (targetMegapixels === 10 && !isPremium) {
      onOpenUpgrade();
      return;
    }

    setIsProcessing(true);
    setProgress(10);
    setStatusText(`Configuring neural tensor for ${targetMegapixels}MP super-resolution...`);

    setTimeout(() => {
      setProgress(35);
      setStatusText(`Executing ${targetMegapixels === 10 ? '10MP Ultra-HD' : '5MP High-Def'} deep model pass...`);
    }, 600);

    setTimeout(() => {
      setProgress(68);
      setStatusText('Synthesizing sub-pixel micro textures and edge sharpness...');
    }, 1300);

    setTimeout(() => {
      setProgress(90);
      setStatusText(`Eliminating JPEG compression artifacts & rendering ${targetMegapixels} Megapixels clarity...`);
    }, 2000);

    setTimeout(() => {
      setProgress(100);
      setStatusText(`Upscale to ${targetMegapixels}MP complete!`);
      setIsProcessing(false);
      setIsCompleted(true);
      setUpscaledUrl(photo.watermarkedUrl || photo.url);
    }, 2500);
  };

  const handleApplyUpscale = () => {
    const updated: MediaItem = {
      ...photo,
      name: photo.name.includes('[Upscaled')
        ? photo.name
        : `${photo.name.replace(/\.[^/.]+$/, '')} [Upscaled ${targetMegapixels}MP].jpg`,
      dimensions: {
        width: targetWidth,
        height: targetHeight,
      },
      size: `${(parseFloat(photo.size) * (targetMegapixels === 10 ? 4.2 : 2.4)).toFixed(1)} MB`,
      upscaled: true,
      scaleFactor: scaleFactor as 2 | 4,
    };

    onSaveUpscaled(updated);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-700 rounded-3xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-6 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-600 to-pink-500 flex items-center justify-center text-white shadow-lg shadow-purple-500/25">
              <Maximize2 className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-black text-white tracking-wide">
                  Upscayl AI Super-Resolution
                </h3>
                <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-extrabold border border-amber-500/30 flex items-center gap-1">
                  <Crown className="w-2.5 h-2.5" />
                  PRO Feature
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Enhance clarity, eliminate blur, and upscale to 4K Ultra-HD with AI neural networks
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1">
          {/* Comparison Preview Box */}
          <div className="relative rounded-2xl overflow-hidden bg-slate-950 border border-slate-800 aspect-video flex items-center justify-center group">
            <img
              src={photo.watermarkedUrl || photo.url}
              alt={photo.name}
              className={`w-full h-full object-cover transition duration-300 ${
                isCompleted ? 'filter contrast-105 saturate-105' : ''
              }`}
            />

            {/* Resolution overlay tag */}
            <div className="absolute top-3 left-3 bg-black/80 backdrop-blur-sm px-3 py-1.5 rounded-xl border border-slate-700 text-xs flex items-center gap-2">
              <span className="text-slate-400">Resolution:</span>
              <span className="font-mono font-bold text-white">
                {originalWidth} x {originalHeight}
              </span>
              <ArrowRight className="w-3.5 h-3.5 text-indigo-400" />
              <span className="font-mono font-bold text-emerald-400">
                {targetWidth} x {targetHeight} ({scaleFactor}X)
              </span>
            </div>

            {isCompleted && (
              <div className="absolute top-3 right-3 bg-emerald-950/80 border border-emerald-500/40 text-emerald-300 px-3 py-1.5 rounded-xl text-xs font-bold flex items-center gap-1.5 animate-in fade-in">
                <Check className="w-4 h-4 text-emerald-400" />
                <span>Super-Resolution Ready</span>
              </div>
            )}

            {/* Processing Overlay */}
            {isProcessing && (
              <div className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm flex flex-col items-center justify-center p-6 space-y-4">
                <div className="w-14 h-14 rounded-2xl bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400 animate-pulse">
                  <Cpu className="w-7 h-7 animate-spin" />
                </div>
                <div className="w-full max-w-xs space-y-2 text-center">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-slate-300">{statusText}</span>
                    <span className="text-indigo-400 font-bold">{progress}%</span>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 transition-all duration-300"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Controls: Scale Factor & AI Model */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Resolution Tier: 5MP vs 10MP */}
            <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-2">
              <label className="text-xs font-bold text-slate-300 flex items-center justify-between">
                <span>Output Resolution</span>
                <span className="text-[10px] text-amber-400 font-mono font-semibold">Pro: 5MP • Premium: 10MP</span>
              </label>

              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setTargetMegapixels(5)}
                  className={`py-2.5 px-3 rounded-xl border text-xs font-bold transition flex flex-col items-center gap-0.5 ${
                    targetMegapixels === 5
                      ? 'bg-amber-600 border-amber-500 text-slate-950 font-black shadow-lg shadow-amber-600/20'
                      : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span className="text-sm font-black flex items-center gap-1">
                    <span>5 Megapixels</span>
                    <span className="text-[9px] px-1 py-0.2 rounded bg-amber-400/30 text-amber-950">PRO</span>
                  </span>
                  <span className="text-[10px] opacity-90 font-mono">
                    2560 x 1920 (High-Def)
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    if (!isPremium) {
                      onOpenUpgrade();
                      return;
                    }
                    setTargetMegapixels(10);
                  }}
                  className={`py-2.5 px-3 rounded-xl border text-xs font-bold transition flex flex-col items-center gap-0.5 relative ${
                    targetMegapixels === 10
                      ? 'bg-gradient-to-r from-purple-600 to-cyan-600 border-purple-500 text-white shadow-lg shadow-purple-600/25 font-black'
                      : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {!isPremium && (
                    <span className="absolute -top-2 right-2 text-[8px] font-black uppercase bg-purple-600 text-white px-1.5 py-0.5 rounded-full shadow">
                      👑 PREMIUM
                    </span>
                  )}
                  <span className="text-sm font-black flex items-center gap-1">
                    <span>10 Megapixels</span>
                    <Sparkles className="w-3 h-3 text-amber-300" />
                  </span>
                  <span className="text-[10px] opacity-90 font-mono">
                    3840 x 2600 (4K Ultra)
                  </span>
                </button>
              </div>
            </div>

            {/* Neural Model */}
            <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-2">
              <label className="text-xs font-bold text-slate-300">
                AI Super-Res Neural Model
              </label>
              <div className="space-y-1.5">
                {[
                  { id: 'ultrasharp', name: 'UltraSharp Real-ESRGAN', note: 'Best for portraits & high-detail photos' },
                  { id: 'real-esrgan', name: 'General GAN Model', note: 'Standard photo texture reconstruction' },
                  { id: 'digital-art', name: 'Vector & Graphic Art', note: 'Smooth gradients without noise' },
                ].map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setModelType(m.id as any)}
                    className={`w-full text-left px-3 py-2 rounded-xl text-xs border transition ${
                      modelType === m.id
                        ? 'bg-purple-950/50 border-purple-500/50 text-purple-200 font-bold'
                        : 'bg-slate-900/50 border-slate-800/80 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <div>{m.name}</div>
                    <div className="text-[10px] text-slate-500 font-normal">{m.note}</div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Pro Barrier Alert if on free */}
          {!isPro && (
            <div className="p-4 rounded-2xl bg-amber-950/40 border border-amber-500/30 flex items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2.5 text-amber-300">
                <Crown className="w-5 h-5 text-amber-400 shrink-0" />
                <div>
                  <div className="font-bold">Upscayl AI is a Pro Feature</div>
                  <div className="text-[11px] text-amber-400/80">
                    Upgrade to Percfect Creator Pro for unlimited 4K Super-Resolution upscales.
                  </div>
                </div>
              </div>
              <button
                onClick={onOpenUpgrade}
                className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-black shrink-0 transition"
              >
                Upgrade to Pro
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950 flex items-center justify-between">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-bold text-slate-400 hover:text-white"
          >
            Cancel
          </button>

          <div className="flex items-center gap-2">
            {!isCompleted ? (
              <button
                onClick={handleStartUpscale}
                disabled={isProcessing}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:brightness-110 text-white text-xs font-black flex items-center gap-2 shadow-lg shadow-purple-600/30 transition disabled:opacity-50"
              >
                <Zap className="w-4 h-4 text-amber-300" />
                <span>Start {scaleFactor}X AI Upscale</span>
              </button>
            ) : (
              <button
                onClick={handleApplyUpscale}
                className="px-6 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-black flex items-center gap-2 shadow-lg shadow-emerald-600/30 transition"
              >
                <Check className="w-4 h-4" />
                <span>Save 4K Upscaled to Vault</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
