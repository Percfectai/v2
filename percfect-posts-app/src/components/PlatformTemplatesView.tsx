import React, { useState } from 'react';
import {
  Sliders,
  Check,
  Key,
  ExternalLink,
  ShieldCheck,
  Plus,
  Trash2,
  HelpCircle,
  Sparkles,
  Lock,
  Eye,
  EyeOff,
  Radio,
  FileCheck,
  Crop,
  Layers,
  Palette,
  Globe,
} from 'lucide-react';
import {
  PlatformConfig,
  SocialTemplate,
  SocialPlatform,
  UserSubscription,
} from '../types.ts';
import { AddCustomNetworkModal } from './AddCustomNetworkModal.tsx';
import { NetworkAdvancedSettingsEditor } from './NetworkAdvancedSettingsEditor.tsx';
import { getPlatformVisual } from './SocialNetworkCheckmarks.tsx';

interface PlatformTemplatesViewProps {
  platforms: PlatformConfig[];
  templates: SocialTemplate[];
  onUpdatePlatform: (platform: PlatformConfig) => void;
  onUpdateTemplate: (template: SocialTemplate) => void;
  onCreateTemplate: (template: SocialTemplate) => void;
  onDeleteTemplate: (id: string) => void;
  onAddPlatform?: (platform: PlatformConfig, initialTemplate: SocialTemplate) => void;
  onDeletePlatform?: (platformId: SocialPlatform) => void;
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
}

export const PlatformTemplatesView: React.FC<PlatformTemplatesViewProps> = ({
  platforms,
  templates,
  onUpdatePlatform,
  onUpdateTemplate,
  onCreateTemplate,
  onDeleteTemplate,
  onAddPlatform,
  onDeletePlatform,
  subscription,
  onOpenUpgrade,
}) => {
  const [selectedPlatformId, setSelectedPlatformId] = useState<SocialPlatform>('twitter');
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [handleInputs, setHandleInputs] = useState<Record<string, string>>({});
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [isAddCustomModalOpen, setIsAddCustomModalOpen] = useState(false);

  const selectedPlatform =
    platforms.find((p) => p.id === selectedPlatformId) || platforms[0];
  const platformTemplates = templates.filter(
    (t) => t.platform === selectedPlatformId
  );
  const activeTemplate =
    platformTemplates[0] || {
      id: `tpl-${selectedPlatformId}-default`,
      name: `${selectedPlatform.name} Default`,
      platform: selectedPlatformId,
      titlePrefix: '',
      disclaimer: '',
      hashtagPreset: [],
      cta: '',
      watermarkEnabled: true,
      autoUpscale: false,
      aspectRatio: '16:9',
      advancedSettings: {},
    };

  const handleSaveCredentials = (platformId: SocialPlatform) => {
    const key = keyInputs[platformId] !== undefined ? keyInputs[platformId] : selectedPlatform.authKey;
    const handle = handleInputs[platformId] !== undefined ? handleInputs[platformId] : selectedPlatform.accountHandle;

    onUpdatePlatform({
      ...selectedPlatform,
      authKey: key,
      accountHandle: handle || `@${selectedPlatform.id}_creator`,
      connected: true,
    });

    setSaveSuccess(platformId);
    setTimeout(() => setSaveSuccess(null), 2500);
  };

  const handleToggleConnection = (platform: PlatformConfig) => {
    onUpdatePlatform({
      ...platform,
      connected: !platform.connected,
    });
  };

  const handleUpdateActiveTemplate = (field: keyof SocialTemplate, value: any) => {
    const updated = {
      ...activeTemplate,
      [field]: value,
    };
    if (platformTemplates.length === 0) {
      onCreateTemplate(updated);
    } else {
      onUpdateTemplate(updated);
    }
  };

  const handleAddPlatformWithTemplate = (newPlatform: PlatformConfig, newTemplate: SocialTemplate) => {
    if (onAddPlatform) {
      onAddPlatform(newPlatform, newTemplate);
    }
    onCreateTemplate(newTemplate);
    setSelectedPlatformId(newPlatform.id);
  };

  const handleDeleteCustomPlatform = (pId: SocialPlatform, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm(`Are you sure you want to remove ${pId} and its templates?`)) {
      if (onDeletePlatform) {
        onDeletePlatform(pId);
      }
      const remaining = platforms.filter((p) => p.id !== pId);
      if (remaining.length > 0) {
        setSelectedPlatformId(remaining[0].id);
      }
    }
  };

  const activeVisual = getPlatformVisual(selectedPlatform.id, platforms);

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Sliders className="w-5 h-5 text-indigo-400" />
            Social Accounts, API Keys & Format Templates
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Set up platform-specific posting templates, audience & privacy rules, mature content flags, disclaimers, watermarks, and secure API/OAuth credentials.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-400">Connected Platforms:</span>
            <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-bold border border-emerald-500/30">
              {platforms.filter((p) => p.connected).length} / {platforms.length}
            </span>
          </div>

          <button
            type="button"
            onClick={() => setIsAddCustomModalOpen(true)}
            className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-indigo-600 to-pink-600 hover:from-indigo-500 hover:to-pink-500 text-white font-bold text-xs flex items-center gap-1.5 shadow-md transition"
          >
            <Plus className="w-4 h-4" />
            Add Custom Network
          </button>
        </div>
      </div>

      {/* Main Grid: Platform Selector (4 cols) + Template & Auth Configuration (8 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Platform List (4 cols) */}
        <div className="lg:col-span-4 space-y-3">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
            <div className="flex items-center justify-between px-2 py-1 mb-2">
              <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                Select Network ({platforms.length})
              </span>
              <button
                type="button"
                onClick={() => setIsAddCustomModalOpen(true)}
                className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" />
                Add
              </button>
            </div>

            <div className="space-y-1.5 max-h-[620px] overflow-y-auto pr-1">
              {platforms.map((p) => {
                const isSelected = selectedPlatformId === p.id;
                const visual = getPlatformVisual(p.id, platforms);

                return (
                  <div
                    key={p.id}
                    onClick={() => setSelectedPlatformId(p.id)}
                    className={`p-3 rounded-xl border flex items-center justify-between cursor-pointer transition ${
                      isSelected
                        ? 'bg-indigo-600/20 border-indigo-500 text-white shadow-md'
                        : 'bg-slate-950/60 border-slate-850 hover:border-slate-700 text-slate-300'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="relative">
                        <div
                          style={{ backgroundColor: visual.accentColor }}
                          className="w-9 h-9 rounded-lg flex items-center justify-center font-black text-white text-xs shadow-sm border border-white/20"
                        >
                          {visual.shortLabel}
                        </div>
                        <span
                          className={`absolute -bottom-1 -right-1 w-3 h-3 rounded-full border-2 border-slate-900 ${
                            p.connected ? 'bg-emerald-400' : 'bg-slate-600'
                          }`}
                        />
                      </div>
                      <div>
                        <div className="text-xs font-bold flex items-center gap-1.5">
                          <span>{p.name}</span>
                          {p.isCustom && (
                            <span className="text-[9px] px-1 py-0.2 rounded bg-indigo-500/30 text-indigo-300 font-mono">
                              Custom
                            </span>
                          )}
                        </div>
                        <p className="text-[10px] text-slate-400 truncate max-w-[130px]">
                          {p.accountHandle || 'No handle connected'}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <div className="text-right">
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            p.connected
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : 'bg-slate-800 text-slate-400'
                          }`}
                        >
                          {p.connected ? 'Linked' : 'Offline'}
                        </span>
                        <div className="text-[9px] text-slate-500 mt-1 uppercase">
                          {p.method.replace('_', ' ')}
                        </div>
                      </div>

                      {p.isCustom && (
                        <button
                          type="button"
                          onClick={(e) => handleDeleteCustomPlatform(p.id, e)}
                          title={`Delete custom network ${p.name}`}
                          className="p-1.5 text-slate-500 hover:text-rose-400 rounded hover:bg-slate-800 transition"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Quick add custom button */}
            <div className="pt-2 mt-2 border-t border-slate-800/80">
              <button
                type="button"
                onClick={() => setIsAddCustomModalOpen(true)}
                className="w-full py-2 px-3 rounded-lg border border-dashed border-slate-700 hover:border-indigo-500 hover:bg-indigo-950/20 text-slate-400 hover:text-indigo-300 text-xs font-semibold flex items-center justify-center gap-1.5 transition"
              >
                <Plus className="w-4 h-4" />
                Add Custom Social Network (e.g. Patreon)
              </button>
            </div>
          </div>
        </div>

        {/* Right: Template & API Key Details (8 cols) */}
        <div className="lg:col-span-8 space-y-6">
          {/* Card 1: API Key & Integration Setup Walkthrough */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-2">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <span
                    style={{ backgroundColor: activeVisual.accentColor }}
                    className="w-3 h-3 rounded-full inline-block"
                  />
                  <Key className="w-4 h-4 text-amber-400" />
                  {selectedPlatform.name} API & Auto-Posting Credentials
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  {selectedPlatform.tagline}
                </p>
              </div>

              <div className="flex items-center gap-2">
                <a
                  href={selectedPlatform.apiDocUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1 bg-indigo-950/50 px-2.5 py-1 rounded border border-indigo-800/40"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Developer Portal
                </a>
              </div>
            </div>

            {/* Setup instructions */}
            <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 space-y-2">
              <h4 className="text-xs font-bold text-slate-200 flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                {selectedPlatform.guideTitle}
              </h4>
              <ol className="list-decimal list-inside space-y-1 text-xs text-slate-400">
                {selectedPlatform.steps.map((step, idx) => (
                  <li key={idx} className="leading-relaxed">
                    <span className="text-slate-300">{step}</span>
                  </li>
                ))}
              </ol>
            </div>

            {/* Credential Inputs */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-300">
                  Account Handle or Channel ID:
                </label>
                <input
                  type="text"
                  value={
                    handleInputs[selectedPlatform.id] !== undefined
                      ? handleInputs[selectedPlatform.id]
                      : selectedPlatform.accountHandle
                  }
                  onChange={(e) =>
                    setHandleInputs({
                      ...handleInputs,
                      [selectedPlatform.id]: e.target.value,
                    })
                  }
                  placeholder={`e.g. @${selectedPlatform.id}_creator`}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-300 flex items-center justify-between">
                  <span>API Key / Personal Access Token / Webhook:</span>
                  <button
                    type="button"
                    onClick={() =>
                      setShowKey({
                        ...showKey,
                        [selectedPlatform.id]: !showKey[selectedPlatform.id],
                      })
                    }
                    className="text-[10px] text-slate-400 hover:text-indigo-400 flex items-center gap-1"
                  >
                    {showKey[selectedPlatform.id] ? (
                      <>
                        <EyeOff className="w-3 h-3" /> Hide
                      </>
                    ) : (
                      <>
                        <Eye className="w-3 h-3" /> Show
                      </>
                    )}
                  </button>
                </label>
                <input
                  type={showKey[selectedPlatform.id] ? 'text' : 'password'}
                  value={
                    keyInputs[selectedPlatform.id] !== undefined
                      ? keyInputs[selectedPlatform.id]
                      : selectedPlatform.authKey
                  }
                  onChange={(e) =>
                    setKeyInputs({
                      ...keyInputs,
                      [selectedPlatform.id]: e.target.value,
                    })
                  }
                  placeholder="Enter API Key, Access Token or Webhook URL"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <span className="text-[11px] text-slate-500 font-mono">
                {selectedPlatform.rateLimitNote}
              </span>

              <button
                onClick={() => handleSaveCredentials(selectedPlatform.id)}
                className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center gap-2 shadow transition"
              >
                {saveSuccess === selectedPlatform.id ? (
                  <>
                    <Check className="w-4 h-4 text-emerald-300" />
                    Credentials Saved!
                  </>
                ) : (
                  <>
                    <Lock className="w-3.5 h-3.5" />
                    Save Secure Credentials
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Card 2: Network Format Template Manager */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <FileCheck className="w-4 h-4 text-emerald-400" />
                  Format Template & Rules for {selectedPlatform.name}
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Applied automatically whenever mass-posting or scheduling to {selectedPlatform.name}.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <span
                  style={{ backgroundColor: activeVisual.accentColor }}
                  className="w-2.5 h-2.5 rounded-full"
                />
                <span className="text-xs font-mono text-indigo-300 bg-indigo-950/60 px-2.5 py-1 rounded border border-indigo-800/50">
                  {activeTemplate.name}
                </span>
              </div>
            </div>

            {/* Network Native Advanced Settings Section */}
            <NetworkAdvancedSettingsEditor
              platform={selectedPlatform}
              template={activeTemplate}
              onUpdateSettings={(newSettings) =>
                handleUpdateActiveTemplate('advancedSettings', newSettings)
              }
            />

            {/* Standard Copy & Tag Templates */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
              {/* Title Prefix */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300">
                  Title Prefix / Header Hook:
                </label>
                <input
                  type="text"
                  value={activeTemplate.titlePrefix}
                  onChange={(e) =>
                    handleUpdateActiveTemplate('titlePrefix', e.target.value)
                  }
                  placeholder="e.g. 🚨 JUST IN: or 🎙️ Exclusive: "
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              {/* Call to Action */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300">
                  Default Call-to-Action (CTA):
                </label>
                <input
                  type="text"
                  value={activeTemplate.cta}
                  onChange={(e) => handleUpdateActiveTemplate('cta', e.target.value)}
                  placeholder="e.g. Reply below with your thoughts! 👇"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              {/* Disclaimer text */}
              <div className="space-y-1.5 sm:col-span-2">
                <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
                  <span>Standard Legal / Compliance Disclaimer:</span>
                  <span className="text-[10px] text-slate-500">Appended to copy or stamped</span>
                </label>
                <input
                  type="text"
                  value={activeTemplate.disclaimer}
                  onChange={(e) =>
                    handleUpdateActiveTemplate('disclaimer', e.target.value)
                  }
                  placeholder="e.g. #Ad #Sponsored • Opinions are my own."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              {/* Hashtag preset */}
              <div className="space-y-1.5 sm:col-span-2">
                <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
                  <span>Default Hashtag Cluster:</span>
                  <span className="text-[10px] text-slate-500">Comma-separated</span>
                </label>
                <input
                  type="text"
                  value={activeTemplate.hashtagPreset.join(', ')}
                  onChange={(e) => {
                    const tags = e.target.value
                      .split(',')
                      .map((t) => t.trim())
                      .filter(Boolean);
                    handleUpdateActiveTemplate('hashtagPreset', tags);
                  }}
                  placeholder="#Tech, #AI, #Growth, #Creator"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              {/* Aspect Ratio Preference */}
              <div className="space-y-1.5 sm:col-span-2">
                <label className="text-xs font-medium text-slate-300">
                  Target Aspect Ratio Preset:
                </label>
                <div className="flex flex-wrap gap-2">
                  {[
                    { id: '16:9', label: '16:9 Landscape' },
                    { id: '1:1', label: '1:1 Square' },
                    { id: '4:5', label: '4:5 Portrait Feed' },
                    { id: '9:16', label: '9:16 Story / Reel' },
                    { id: 'original', label: 'Original Ratio' },
                  ].map((ratio) => (
                    <button
                      key={ratio.id}
                      type="button"
                      onClick={() => handleUpdateActiveTemplate('aspectRatio', ratio.id)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
                        activeTemplate.aspectRatio === ratio.id
                          ? 'bg-indigo-600/30 border-indigo-500 text-indigo-300'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                      }`}
                    >
                      {ratio.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Toggles */}
              <div className="flex flex-wrap items-center gap-6 sm:col-span-2 pt-2 border-t border-slate-800/80">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={activeTemplate.watermarkEnabled}
                    onChange={(e) =>
                      handleUpdateActiveTemplate('watermarkEnabled', e.target.checked)
                    }
                    className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-800 border-slate-700"
                  />
                  <span>Automatically watermark media for this network</span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={activeTemplate.autoUpscale}
                    onChange={(e) =>
                      handleUpdateActiveTemplate('autoUpscale', e.target.checked)
                    }
                    className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-800 border-slate-700"
                  />
                  <span>Auto-upscale to 2K resolution</span>
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Add Custom Network Modal */}
      <AddCustomNetworkModal
        isOpen={isAddCustomModalOpen}
        onClose={() => setIsAddCustomModalOpen(false)}
        onAddPlatform={handleAddPlatformWithTemplate}
        existingPlatformIds={platforms.map((p) => p.id)}
      />
    </div>
  );
};
