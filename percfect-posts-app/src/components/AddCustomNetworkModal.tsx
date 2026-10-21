import React, { useState } from 'react';
import {
  X,
  Sparkles,
  Palette,
  Hash,
  Globe,
  Key,
  HelpCircle,
  Check,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { PlatformConfig, SocialTemplate } from '../types.ts';

interface AddCustomNetworkModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAddPlatform: (platform: PlatformConfig, initialTemplate: SocialTemplate) => void;
  existingPlatformIds: string[];
}

const PRESET_NETWORKS = [
  { name: 'Patreon', color: '#FF424D', short: 'PAT' },
  { name: 'Discord', color: '#5865F2', short: 'DISC' },
  { name: 'Substack', color: '#FF6719', short: 'SUB' },
  { name: 'Reddit', color: '#FF4500', short: 'RD' },
  { name: 'Medium', color: '#00AB6C', short: 'MED' },
  { name: 'Mastodon', color: '#6364FF', short: 'MAST' },
  { name: 'Twitch', color: '#9146FF', short: 'TTV' },
  { name: 'OnlyFans', color: '#00AFF0', short: 'OF' },
];

export const AddCustomNetworkModal: React.FC<AddCustomNetworkModalProps> = ({
  isOpen,
  onClose,
  onAddPlatform,
  existingPlatformIds,
}) => {
  const [networkName, setNetworkName] = useState('');
  const [brandColor, setBrandColor] = useState('#FF424D');
  const [shortLabel, setShortLabel] = useState('PAT');
  const [tagline, setTagline] = useState('Membership & creator updates');
  const [maxChars, setMaxChars] = useState(10000);
  const [method, setMethod] = useState<'api_key' | 'oauth' | 'extension'>('api_key');
  const [guideTitle, setGuideTitle] = useState('API & Webhook Setup');
  const [apiDocUrl, setApiDocUrl] = useState('https://docs.patreon.com/');
  const [authKey, setAuthKey] = useState('');
  const [accountHandle, setAccountHandle] = useState('');
  const [steps, setSteps] = useState<string[]>([
    'Create an API token in your account developer portal.',
    'Grant post publication & media permissions.',
    'Copy and paste your credential key below.',
  ]);

  // Template defaults
  const [titlePrefix, setTitlePrefix] = useState('🎙️ Exclusive: ');
  const [cta, setCta] = useState('Support our work and unlock bonuses!');
  const [hashtags, setHashtags] = useState('#Community, #Creator');
  const [privacySetting, setPrivacySetting] = useState<'public' | 'followers' | 'private'>('followers');

  const [isLoadingAI, setIsLoadingAI] = useState(false);
  const [aiStatusMessage, setAiStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSelectPreset = (preset: { name: string; color: string; short: string }) => {
    setNetworkName(preset.name);
    setBrandColor(preset.color);
    setShortLabel(preset.short);
    triggerAILookup(preset.name);
  };

  const triggerAILookup = async (nameToLookup?: string) => {
    const target = (nameToLookup || networkName).trim();
    if (!target) {
      setErrorMessage('Please enter a network name first.');
      return;
    }

    setIsLoadingAI(true);
    setErrorMessage(null);
    setAiStatusMessage(`Looking up API specifications & templates for ${target}...`);

    try {
      const res = await fetch('/api/ai/lookup-network', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ networkName: target }),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      const data = await res.json();
      if (data.data) {
        const d = data.data;
        if (d.name) setNetworkName(d.name);
        if (d.brandColor) setBrandColor(d.brandColor);
        if (d.shortLabel) setShortLabel(d.shortLabel);
        if (d.tagline) setTagline(d.tagline);
        if (d.maxChars) setMaxChars(d.maxChars);
        if (d.method) setMethod(d.method);
        if (d.guideTitle) setGuideTitle(d.guideTitle);
        if (d.apiDocUrl) setApiDocUrl(d.apiDocUrl);
        if (Array.isArray(d.steps) && d.steps.length > 0) setSteps(d.steps);
        if (d.defaultTitlePrefix) setTitlePrefix(d.defaultTitlePrefix);
        if (d.defaultCta) setCta(d.defaultCta);
        if (Array.isArray(d.defaultHashtags)) setHashtags(d.defaultHashtags.join(', '));
        if (d.advancedSettings?.customPrivacy) setPrivacySetting(d.advancedSettings.customPrivacy);

        setAiStatusMessage(`Auto-configured ${d.name} specs, colors & template rules!`);
        setTimeout(() => setAiStatusMessage(null), 3000);
      }
    } catch (err: any) {
      console.warn('AI lookup error:', err);
      setErrorMessage('AI lookup unavailable. You can still customize specs manually below.');
    } finally {
      setIsLoadingAI(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cleanName = networkName.trim();
    if (!cleanName) {
      setErrorMessage('Please specify the network name.');
      return;
    }

    const platformId = cleanName.toLowerCase().replace(/[^a-z0-9]/g, '');
    if (existingPlatformIds.includes(platformId)) {
      setErrorMessage(`A network with ID "${platformId}" already exists. Please choose a different name.`);
      return;
    }

    const isPatreon = platformId === 'patreon';

    const newPlatform: PlatformConfig = {
      id: platformId,
      name: cleanName,
      tagline,
      maxChars: Number(maxChars) || 5000,
      bestAspectRatios: ['1:1', '16:9'],
      method,
      guideTitle,
      apiDocUrl: apiDocUrl || 'https://google.com',
      steps: steps.length > 0 ? steps : ['Enter your API key or token to connect.'],
      authKey,
      connected: Boolean(authKey),
      accountHandle: accountHandle || `@${platformId}_creator`,
      avatar:
        'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=150&auto=format&fit=crop&q=80',
      rateLimitNote: 'Standard platform API rates apply.',
      isCustom: true,
      brandColor,
      shortLabel: shortLabel.toUpperCase().slice(0, 4),
    };

    const newTemplate: SocialTemplate = {
      id: `tpl-${platformId}-default`,
      name: `${cleanName} Master Template`,
      platform: platformId,
      titlePrefix,
      disclaimer: '#Content #Community',
      hashtagPreset: hashtags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      cta,
      watermarkEnabled: true,
      autoUpscale: false,
      aspectRatio: '16:9',
      advancedSettings: {
        customPrivacy: privacySetting,
        ...(isPatreon
          ? {
              patreonTierAccess: 'all_patrons',
              patreonEarlyAccessHours: 24,
              patreonIsPaidPost: false,
              patreonTeaserText: '🔒 Exclusive to active patrons. Become a supporter to unlock full 4K access!',
            }
          : {}),
      },
    };

    onAddPlatform(newPlatform, newTemplate);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm overflow-y-auto">
      <div className="relative w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl p-6 text-slate-100 my-8">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div
              style={{ backgroundColor: brandColor }}
              className="w-9 h-9 rounded-xl flex items-center justify-center font-black text-white text-xs shadow-md border border-white/20 transition-colors"
            >
              {shortLabel || 'NEW'}
            </div>
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                Add Custom Social Network
                <span className="text-[10px] px-2 py-0.5 rounded-full font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  AI Auto-Template
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Connect custom platforms like Patreon, Substack, Discord, Reddit, or private creator clubs.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Quick Presets */}
        <div className="pt-4 pb-2">
          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center justify-between">
            <span>Popular Creator & Community Presets:</span>
            <span className="text-[10px] text-slate-500 font-normal">Click to auto-fill</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {PRESET_NETWORKS.map((preset) => (
              <button
                key={preset.name}
                type="button"
                onClick={() => handleSelectPreset(preset)}
                style={{
                  borderColor: networkName.toLowerCase() === preset.name.toLowerCase() ? preset.color : undefined,
                }}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold border flex items-center gap-1.5 transition ${
                  networkName.toLowerCase() === preset.name.toLowerCase()
                    ? 'bg-slate-800 text-white ring-1'
                    : 'bg-slate-950/70 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <span
                  style={{ backgroundColor: preset.color }}
                  className="w-2.5 h-2.5 rounded-full"
                />
                <span>{preset.name}</span>
              </button>
            ))}
          </div>
        </div>

        {/* AI status banner */}
        {aiStatusMessage && (
          <div className="mt-2 p-2.5 rounded-lg bg-indigo-950/60 border border-indigo-500/40 text-xs text-indigo-300 flex items-center gap-2">
            <Sparkles className="w-4 h-4 shrink-0 text-indigo-400 animate-pulse" />
            <span>{aiStatusMessage}</span>
          </div>
        )}

        {errorMessage && (
          <div className="mt-2 p-2.5 rounded-lg bg-rose-950/60 border border-rose-500/40 text-xs text-rose-300 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="space-y-4 pt-3">
          {/* Row 1: Name + AI Lookup */}
          <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
            <div className="sm:col-span-8 space-y-1">
              <label className="text-xs font-semibold text-slate-300">
                Network Name: <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={networkName}
                onChange={(e) => setNetworkName(e.target.value)}
                placeholder="e.g. Patreon, Discord, Substack, Reddit"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                required
              />
            </div>

            <div className="sm:col-span-4">
              <button
                type="button"
                disabled={isLoadingAI || !networkName.trim()}
                onClick={() => triggerAILookup()}
                className="w-full py-2 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-bold text-xs flex items-center justify-center gap-1.5 shadow transition"
              >
                {isLoadingAI ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Looking up...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                    AI Auto-Lookup
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Row 2: Brand Color, Short Label, Max Chars */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {/* Color */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1">
                <Palette className="w-3 h-3 text-indigo-400" />
                Brand Color:
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={brandColor}
                  onChange={(e) => setBrandColor(e.target.value)}
                  className="w-8 h-8 rounded border-0 cursor-pointer bg-transparent"
                />
                <input
                  type="text"
                  value={brandColor}
                  onChange={(e) => setBrandColor(e.target.value)}
                  className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            {/* Short label */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1">
                <Hash className="w-3 h-3 text-emerald-400" />
                Badge Label (2-4 chars):
              </label>
              <input
                type="text"
                maxLength={4}
                value={shortLabel}
                onChange={(e) => setShortLabel(e.target.value.toUpperCase())}
                placeholder="PAT"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white font-mono uppercase focus:outline-none focus:border-indigo-500"
              />
            </div>

            {/* Character limit */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300">
                Max Characters:
              </label>
              <input
                type="number"
                value={maxChars}
                onChange={(e) => setMaxChars(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          {/* Row 3: Account Handle & Credentials */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300">
                Creator Account Handle:
              </label>
              <input
                type="text"
                value={accountHandle}
                onChange={(e) => setAccountHandle(e.target.value)}
                placeholder="e.g. @creativestudio or /c/patreon"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 flex items-center justify-between">
                <span>API Key / Webhook URL:</span>
                <span className="text-[10px] text-slate-500">Optional for setup</span>
              </label>
              <input
                type="password"
                value={authKey}
                onChange={(e) => setAuthKey(e.target.value)}
                placeholder="Paste API token or Webhook URL"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          {/* Template Generator Section */}
          <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-3">
            <div className="text-[11px] font-bold text-indigo-300 uppercase tracking-wider flex items-center justify-between">
              <span>Auto-Generated Format Template</span>
              <span className="text-[10px] text-slate-400 font-normal">Customizable anytime</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">Title Prefix / Hook:</label>
                <input
                  type="text"
                  value={titlePrefix}
                  onChange={(e) => setTitlePrefix(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">Default Call-To-Action (CTA):</label>
                <input
                  type="text"
                  value={cta}
                  onChange={(e) => setCta(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="sm:col-span-2 space-y-1">
                <label className="text-[11px] font-medium text-slate-300">Default Hashtags:</label>
                <input
                  type="text"
                  value={hashtags}
                  onChange={(e) => setHashtags(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="sm:col-span-2 space-y-1">
                <label className="text-[11px] font-medium text-slate-300">Default Audience Privacy:</label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setPrivacySetting('public')}
                    className={`py-1.5 px-2 rounded-lg text-xs font-semibold border ${
                      privacySetting === 'public'
                        ? 'bg-emerald-600/20 border-emerald-500 text-emerald-300'
                        : 'bg-slate-900 border-slate-800 text-slate-400'
                    }`}
                  >
                    🌐 Public
                  </button>
                  <button
                    type="button"
                    onClick={() => setPrivacySetting('followers')}
                    className={`py-1.5 px-2 rounded-lg text-xs font-semibold border ${
                      privacySetting === 'followers'
                        ? 'bg-indigo-600/20 border-indigo-500 text-indigo-300'
                        : 'bg-slate-900 border-slate-800 text-slate-400'
                    }`}
                  >
                    👥 Patrons / Members Only
                  </button>
                  <button
                    type="button"
                    onClick={() => setPrivacySetting('private')}
                    className={`py-1.5 px-2 rounded-lg text-xs font-semibold border ${
                      privacySetting === 'private'
                        ? 'bg-amber-600/20 border-amber-500 text-amber-300'
                        : 'bg-slate-900 border-slate-800 text-slate-400'
                    }`}
                  >
                    🔒 Private Archive
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-slate-800 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs flex items-center gap-1.5 shadow transition"
            >
              <Check className="w-4 h-4" />
              Save Network & Build Template
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
