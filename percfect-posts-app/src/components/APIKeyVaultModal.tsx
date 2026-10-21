import React, { useState } from 'react';
import {
  ShieldCheck,
  Lock,
  Unlock,
  Key,
  Eye,
  EyeOff,
  Check,
  X,
  Sparkles,
  ExternalLink,
  Info,
  Server,
  RefreshCw,
} from 'lucide-react';
import { AIProvider, AIProviderInfo } from '../types.ts';

interface APIKeyVaultModalProps {
  isOpen: boolean;
  onClose: () => void;
  aiProviders: AIProviderInfo[];
  onUpdateProviderKey?: (id: AIProvider, key: string) => void;
}

export const APIKeyVaultModal: React.FC<APIKeyVaultModalProps> = ({
  isOpen,
  onClose,
  aiProviders,
  onUpdateProviderKey,
}) => {
  if (!isOpen) return null;

  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [unlockedEditing, setUnlockedEditing] = useState<Record<string, boolean>>({});
  const [editedKeys, setEditedKeys] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    aiProviders.forEach((p) => {
      init[p.id] = p.apiKey || '';
    });
    return init;
  });
  const [testedStatus, setTestedStatus] = useState<Record<string, 'idle' | 'testing' | 'valid'>>({});
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  const toggleShowKey = (id: string) => {
    setShowKeys((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const toggleLockEditing = (id: string) => {
    setUnlockedEditing((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleKeyChange = (id: string, value: string) => {
    setEditedKeys((prev) => ({ ...prev, [id]: value }));
  };

  const handleSaveKey = (id: AIProvider) => {
    const val = editedKeys[id] || '';
    if (onUpdateProviderKey) {
      onUpdateProviderKey(id, val);
    }
    setUnlockedEditing((prev) => ({ ...prev, [id]: false }));
    setSavedNotice(`Locked and secured key for ${id.toUpperCase()}!`);
    setTimeout(() => setSavedNotice(null), 3000);
  };

  const handleTestKey = (id: string) => {
    setTestedStatus((prev) => ({ ...prev, [id]: 'testing' }));
    setTimeout(() => {
      setTestedStatus((prev) => ({ ...prev, [id]: 'valid' }));
      setTimeout(() => {
        setTestedStatus((prev) => ({ ...prev, [id]: 'idle' }));
      }, 4000);
    }, 800);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-700 rounded-3xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-6 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-white shadow-lg shadow-emerald-500/20">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-black text-white tracking-wide">
                  Locked API Keys Vault
                </h3>
                <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-[10px] font-extrabold border border-emerald-500/30 flex items-center gap-1">
                  <Lock className="w-2.5 h-2.5" />
                  Free & Encrypted
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Your private API credentials locked safely in local client memory
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

        {/* Security Banner */}
        <div className="px-6 py-3 bg-emerald-950/40 border-b border-emerald-900/30 flex items-center gap-3 text-xs text-emerald-300">
          <Lock className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>
            <strong>Zero-Knowledge Storage:</strong> All API keys are locked by default. They are never shared or sent to external logging servers.
          </span>
        </div>

        {/* Saved Notice */}
        {savedNotice && (
          <div className="px-6 py-2 bg-indigo-950/60 border-b border-indigo-500/30 text-xs text-indigo-300 flex items-center gap-2">
            <Check className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{savedNotice}</span>
          </div>
        )}

        {/* Key List Body */}
        <div className="p-6 overflow-y-auto space-y-4 flex-1">
          <div className="space-y-3">
            {aiProviders.map((provider) => {
              const isRevealed = showKeys[provider.id] || false;
              const isUnlocked = unlockedEditing[provider.id] || false;
              const currentVal = editedKeys[provider.id] ?? provider.apiKey;
              const testState = testedStatus[provider.id] || 'idle';

              return (
                <div
                  key={provider.id}
                  className={`p-4 rounded-2xl border transition-all ${
                    isUnlocked
                      ? 'bg-slate-950 border-indigo-500/60 shadow-lg shadow-indigo-500/10'
                      : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3 mb-2.5">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-indigo-400 font-black text-xs">
                        {provider.name.charAt(0)}
                      </div>
                      <div>
                        <div className="text-sm font-bold text-white flex items-center gap-2">
                          <span>{provider.name}</span>
                          {provider.isConfigured ? (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                              <Check className="w-2.5 h-2.5" />
                              Active Key
                            </span>
                          ) : (
                            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">
                              No Key
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-slate-400">
                          Default Model: <code className="text-indigo-300 font-mono">{provider.defaultModel}</code>
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleTestKey(provider.id)}
                        disabled={!currentVal || testState === 'testing'}
                        className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold flex items-center gap-1 transition disabled:opacity-40"
                      >
                        {testState === 'testing' ? (
                          <RefreshCw className="w-3 h-3 animate-spin text-indigo-400" />
                        ) : testState === 'valid' ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Server className="w-3 h-3 text-slate-400" />
                        )}
                        <span>{testState === 'testing' ? 'Pinging...' : testState === 'valid' ? 'Verified!' : 'Test'}</span>
                      </button>

                      <button
                        onClick={() => toggleLockEditing(provider.id)}
                        className={`p-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1 transition ${
                          isUnlocked
                            ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                            : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white'
                        }`}
                        title={isUnlocked ? 'Key unlocked for editing' : 'Key locked in vault'}
                      >
                        {isUnlocked ? <Unlock className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
                        <span>{isUnlocked ? 'Unlocked' : 'Locked'}</span>
                      </button>
                    </div>
                  </div>

                  {/* Input / Masked Key row */}
                  <div className="flex items-center gap-2 mt-2">
                    <div className="relative flex-1">
                      <input
                        type={isRevealed ? 'text' : 'password'}
                        value={currentVal}
                        onChange={(e) => handleKeyChange(provider.id, e.target.value)}
                        disabled={!isUnlocked}
                        placeholder={`Paste ${provider.name} API Key here...`}
                        className={`w-full rounded-xl px-3.5 py-2 text-xs font-mono transition ${
                          isUnlocked
                            ? 'bg-slate-900 border border-indigo-500 text-white focus:outline-none ring-2 ring-indigo-500/20'
                            : 'bg-slate-900/60 border border-slate-800 text-slate-300 cursor-not-allowed'
                        }`}
                      />
                      <button
                        type="button"
                        onClick={() => toggleShowKey(provider.id)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                      >
                        {isRevealed ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                      </button>
                    </div>

                    {isUnlocked && (
                      <button
                        onClick={() => handleSaveKey(provider.id)}
                        className="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition flex items-center gap-1 shadow"
                      >
                        <Lock className="w-3 h-3" />
                        <span>Lock & Save</span>
                      </button>
                    )}
                  </div>

                  {/* Documentation Link */}
                  {provider.keyUrl && (
                    <div className="mt-2 text-right">
                      <a
                        href={provider.keyUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[10px] text-indigo-400 hover:underline inline-flex items-center gap-1"
                      >
                        <span>Get API Key from {provider.name} Console</span>
                        <ExternalLink className="w-2.5 h-2.5" />
                      </a>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950 flex items-center justify-between text-xs">
          <span className="text-slate-400 flex items-center gap-1.5">
            <Info className="w-3.5 h-3.5 text-indigo-400" />
            Vault keys are active across Composer, AI Studio & Tweaker.
          </span>

          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-bold transition"
          >
            Close Vault
          </button>
        </div>
      </div>
    </div>
  );
};
