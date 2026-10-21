import React, { useState, useRef, useEffect } from 'react';
import {
  Bot,
  Send,
  Sparkles,
  Flame,
  Zap,
  Key,
  ExternalLink,
  Check,
  Brain,
  ShieldCheck,
  Lightbulb,
  CornerDownLeft,
  ChevronRight,
  TrendingUp,
} from 'lucide-react';
import {
  AIProvider,
  AIProviderInfo,
  ChatMessage,
  UserSubscription,
} from '../types.ts';

interface AIChatProviderViewProps {
  providers: AIProviderInfo[];
  activeProviderId: AIProvider;
  onSelectProvider: (id: AIProvider) => void;
  onUpdateProviderKey: (id: AIProvider, key: string) => void;
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
  onSendToComposer: (text: string) => void;
}

export const AIChatProviderView: React.FC<AIChatProviderViewProps> = ({
  providers,
  activeProviderId,
  onSelectProvider,
  onUpdateProviderKey,
  subscription,
  onOpenUpgrade,
  onSendToComposer,
}) => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'msg-init',
      role: 'model',
      text: "Hello! I'm your Gemini Cross-Platform Social Strategist. Ask me to formulate viral hooks, design multi-network content calendars, analyze hashtag algorithms, or review disclaimer compliance.",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      modelUsed: 'gemini-3.5-flash',
      persona: 'strategist',
    },
  ]);

  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedRole, setSelectedRole] = useState<'strategist' | 'copywriter' | 'compliance' | 'growth'>('strategist');
  const [modelSpeed, setModelSpeed] = useState<'fast' | 'balanced' | 'complex'>('balanced');
  const [highThinkingEnabled, setHighThinkingEnabled] = useState(false);

  // Guide accordion state
  const [expandedProvider, setExpandedProvider] = useState<AIProvider>(activeProviderId);
  const [keyInputValues, setKeyInputValues] = useState<Record<string, string>>({});
  const [keySaved, setKeySaved] = useState<Record<string, boolean>>({});

  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleSendMessage = async (customPrompt?: string) => {
    const textToSend = customPrompt || inputMessage;
    if (!textToSend.trim() || isLoading) return;

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    const updatedHistory = [...messages, userMsg];
    setMessages(updatedHistory);
    setInputMessage('');
    setIsLoading(true);

    try {
      const activeP = providers.find((p) => p.id === activeProviderId);
      const response = await fetch('/api/gemini/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: updatedHistory.map((m) => ({ role: m.role, text: m.text })),
          role: selectedRole,
          useHighThinking: highThinkingEnabled,
          modelSpeed,
          provider: activeProviderId,
          apiKey: activeP?.apiKey || '',
        }),
      });

      const data = await response.json();
      if (data.reply) {
        const botMsg: ChatMessage = {
          id: `msg-${Date.now() + 1}`,
          role: 'model',
          text: data.reply,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelUsed: data.modelUsed,
          thinking: data.thinkingEnabled,
          persona: selectedRole,
        };
        setMessages((prev) => [...prev, botMsg]);
      } else {
        throw new Error(data.error || 'No response received from Gemini server.');
      }
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        role: 'model',
        text: `⚠️ Error: ${err.message || 'Unable to connect to Gemini API.'}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveKey = (providerId: AIProvider) => {
    const val = keyInputValues[providerId] || '';
    onUpdateProviderKey(providerId, val);
    setKeySaved((prev) => ({ ...prev, [providerId]: true }));
    setTimeout(() => setKeySaved((prev) => ({ ...prev, [providerId]: false })), 2000);
  };

  const quickPrompts = [
    'Create a 3-part viral hook for an AI tech video',
    'What are the optimal hashtag counts for LinkedIn vs Instagram?',
    'Write a compliant disclaimer for an affiliate sponsored post',
    'How do I repurpose 1 master asset across 6 platforms simultaneously?',
  ];

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* View Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Bot className="w-5 h-5 text-indigo-400" />
            Gemini Assistant & Multi-AI Provider Hub
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Engage with specialized Gemini personas using high thinking or configure custom API keys for other models.
          </p>
        </div>

        {/* High thinking switch */}
        <div className="flex items-center gap-3 bg-slate-950 p-2 rounded-lg border border-slate-800">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
            <Flame className={`w-4 h-4 ${highThinkingEnabled ? 'text-orange-400' : 'text-slate-500'}`} />
            <span>High Thinking Mode</span>
          </div>
          <button
            onClick={() => {
              if (!highThinkingEnabled && subscription.plan === 'free') {
                onOpenUpgrade();
                return;
              }
              const next = !highThinkingEnabled;
              setHighThinkingEnabled(next);
              if (next) setModelSpeed('complex');
            }}
            className={`w-9 h-5 rounded-full transition relative p-0.5 ${
              highThinkingEnabled ? 'bg-orange-500' : 'bg-slate-700'
            }`}
          >
            <div
              className={`w-4 h-4 rounded-full bg-white transition transform ${
                highThinkingEnabled ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>

      {/* Main Grid: Gemini Chatbot (7 cols) + AI Key Guides (5 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Gemini Chatbot Thread (7 cols) */}
        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-[640px] overflow-hidden shadow-xl">
          {/* Chat Header & Persona Selector */}
          <div className="p-3.5 border-b border-slate-800 bg-slate-850 flex flex-wrap items-center justify-between gap-2.5">
            {/* Persona chips */}
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mr-1">
                Persona:
              </span>
              {[
                { id: 'strategist' as const, label: 'Strategist', icon: '📈' },
                { id: 'copywriter' as const, label: 'Copywriter', icon: '✍️' },
                { id: 'compliance' as const, label: 'Compliance', icon: '🛡️' },
                { id: 'growth' as const, label: 'Growth', icon: '🚀' },
              ].map((role) => (
                <button
                  key={role.id}
                  onClick={() => setSelectedRole(role.id)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition flex items-center gap-1 ${
                    selectedRole === role.id
                      ? 'bg-indigo-600 text-white font-bold shadow'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-750'
                  }`}
                >
                  <span>{role.icon}</span>
                  <span>{role.label}</span>
                </button>
              ))}
            </div>

            {/* Model Speed */}
            <div className="flex items-center gap-1 text-[11px] bg-slate-950 p-1 rounded-md border border-slate-800">
              <button
                onClick={() => {
                  setModelSpeed('fast');
                  setHighThinkingEnabled(false);
                }}
                className={`px-2 py-0.5 rounded font-medium ${
                  modelSpeed === 'fast'
                    ? 'bg-indigo-600 text-white'
                    : 'text-slate-400 hover:text-white'
                }`}
                title="gemini-3.1-flash-lite"
              >
                ⚡ Fast
              </button>
              <button
                onClick={() => setModelSpeed('balanced')}
                className={`px-2 py-0.5 rounded font-medium ${
                  modelSpeed === 'balanced'
                    ? 'bg-indigo-600 text-white'
                    : 'text-slate-400 hover:text-white'
                }`}
                title="gemini-3.5-flash"
              >
                ⚖️ Balanced
              </button>
              <button
                onClick={() => {
                  if (subscription.plan === 'free') {
                    onOpenUpgrade();
                    return;
                  }
                  setModelSpeed('complex');
                }}
                className={`px-2 py-0.5 rounded font-medium ${
                  modelSpeed === 'complex'
                    ? 'bg-orange-600 text-white font-bold'
                    : 'text-slate-400 hover:text-white'
                }`}
                title="gemini-3.1-pro-preview"
              >
                🧠 Deep
              </button>
            </div>
          </div>

          {/* Scrollable Message Thread */}
          <div className="flex-1 p-4 overflow-y-auto space-y-4 no-scrollbar">
            {messages.map((msg) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}
                >
                  <div className="flex items-center gap-2 mb-1 px-1 text-[11px] text-slate-500">
                    <span className="font-semibold text-slate-400">
                      {isUser ? 'You' : 'Gemini Social Strategist'}
                    </span>
                    <span>{msg.timestamp}</span>
                    {msg.modelUsed && (
                      <span className="px-1.5 py-0.2 rounded bg-slate-800 font-mono text-[9px] text-indigo-300">
                        {msg.modelUsed}
                      </span>
                    )}
                    {msg.thinking && (
                      <span className="flex items-center gap-0.5 px-1 py-0.2 rounded bg-orange-500/20 text-orange-300 font-semibold text-[9px]">
                        <Flame className="w-2.5 h-2.5" /> High Thinking
                      </span>
                    )}
                  </div>

                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 text-xs leading-relaxed ${
                      isUser
                        ? 'bg-indigo-600 text-white rounded-tr-sm shadow-md'
                        : 'bg-slate-800/90 text-slate-200 border border-slate-700/80 rounded-tl-sm shadow'
                    }`}
                  >
                    <div className="whitespace-pre-wrap">{msg.text}</div>

                    {!isUser && (
                      <div className="mt-2.5 pt-2 border-t border-slate-700/60 flex items-center justify-end">
                        <button
                          onClick={() => onSendToComposer(msg.text)}
                          className="text-[11px] font-semibold text-indigo-300 hover:text-indigo-200 hover:underline flex items-center gap-1"
                        >
                          <CornerDownLeft className="w-3 h-3" />
                          Insert into Mass Post Composer
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {isLoading && (
              <div className="flex items-center gap-2 p-3 bg-slate-850 rounded-xl max-w-xs border border-slate-800 animate-pulse">
                <Brain className="w-4 h-4 text-indigo-400 animate-spin" />
                <span className="text-xs text-slate-400">
                  {highThinkingEnabled
                    ? 'Gemini 3.1 Pro is deep reasoning (Thinking: HIGH)...'
                    : 'Synthesizing cross-platform response...'}
                </span>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Quick Prompts Bar */}
          <div className="p-2 border-t border-slate-800 bg-slate-950/60 overflow-x-auto no-scrollbar flex items-center gap-1.5">
            <span className="text-[10px] text-slate-500 font-semibold px-2">Prompt:</span>
            {quickPrompts.map((qp, i) => (
              <button
                key={i}
                onClick={() => handleSendMessage(qp)}
                className="px-2.5 py-1 rounded-full bg-slate-800 hover:bg-slate-750 text-[11px] text-slate-300 whitespace-nowrap border border-slate-700 transition shrink-0"
              >
                {qp}
              </button>
            ))}
          </div>

          {/* Input Box */}
          <div className="p-3 border-t border-slate-800 bg-slate-900 flex items-center gap-2">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              placeholder="Ask for platform strategy, viral hooks, hashtag clusters..."
              className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
            <button
              onClick={() => handleSendMessage()}
              disabled={isLoading || !inputMessage.trim()}
              className="p-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white transition disabled:opacity-40 disabled:cursor-not-allowed shadow"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* AI Provider Hub & API Key Guides (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Key className="w-4 h-4 text-amber-400" />
                AI Services & Fetch Guides
              </h3>
              <span className="text-[11px] text-slate-400">Select & Configure</span>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Select your desired AI brain for generating mass-post copy and tags. Follow the step-by-step guides to retrieve your API keys.
            </p>

            {/* Providers Accordion List */}
            <div className="space-y-3 max-h-[510px] overflow-y-auto no-scrollbar pr-1">
              {providers.map((p) => {
                const isSelected = activeProviderId === p.id;
                const isExpanded = expandedProvider === p.id;

                return (
                  <div
                    key={p.id}
                    className={`rounded-xl border transition-all ${
                      isSelected
                        ? 'bg-slate-850 border-indigo-500/80 shadow-lg shadow-indigo-500/10'
                        : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    {/* Header */}
                    <div
                      onClick={() => {
                        onSelectProvider(p.id);
                        setExpandedProvider(p.id);
                      }}
                      className="p-3.5 flex items-center justify-between cursor-pointer"
                    >
                      <div className="flex items-center gap-2.5">
                        <div
                          className={`w-3 h-3 rounded-full border-2 transition ${
                            isSelected
                              ? 'border-indigo-500 bg-indigo-400 ring-2 ring-indigo-500/30'
                              : 'border-slate-600 bg-transparent'
                          }`}
                        />
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold text-white">{p.name}</span>
                            {p.id === 'gemini' && (
                              <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                Pre-Configured
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] font-mono text-slate-400">
                            {p.defaultModel}
                          </span>
                        </div>
                      </div>

                      <ChevronRight
                        className={`w-4 h-4 text-slate-400 transition transform ${
                          isExpanded ? 'rotate-90' : ''
                        }`}
                      />
                    </div>

                    {/* Collapsible Details & Guide */}
                    {isExpanded && (
                      <div className="p-3.5 pt-0 border-t border-slate-800/80 space-y-3 text-xs">
                        <p className="text-slate-300 text-[11px] leading-relaxed">
                          {p.description}
                        </p>

                        <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-amber-300 text-[11px]">
                              How to fetch API Key:
                            </span>
                            <a
                              href={p.keyUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[11px] text-indigo-400 hover:underline flex items-center gap-1"
                            >
                              <span>Get Key</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          </div>

                          <ol className="list-decimal list-inside space-y-1 text-[11px] text-slate-400">
                            {p.guideSteps.map((s, idx) => (
                              <li key={idx} className="leading-snug">
                                {s}
                              </li>
                            ))}
                          </ol>
                        </div>

                        {/* API Key Input Form (unless server-managed Gemini) */}
                        {p.id !== 'gemini' ? (
                          <div className="space-y-3 pt-1">
                            <div className="space-y-1">
                              <label className="text-[11px] font-medium text-slate-300 flex items-center justify-between">
                                <span>Your {p.name} Text & Copy Key:</span>
                                <span className="text-[10px] text-slate-500 font-mono">
                                  {p.defaultModel}
                                </span>
                              </label>
                              <div className="flex items-center gap-1.5">
                                <input
                                  type="password"
                                  value={
                                    keyInputValues[p.id] !== undefined
                                      ? keyInputValues[p.id]
                                      : p.apiKey
                                  }
                                  onChange={(e) =>
                                    setKeyInputValues({
                                      ...keyInputValues,
                                      [p.id]: e.target.value,
                                    })
                                  }
                                  placeholder={`Paste ${p.id.toUpperCase()} API key`}
                                  className="flex-1 bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500 font-mono"
                                />
                                <button
                                  onClick={() => handleSaveKey(p.id)}
                                  className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center gap-1 transition"
                                >
                                  {keySaved[p.id] ? (
                                    <Check className="w-3.5 h-3.5 text-emerald-300" />
                                  ) : (
                                    'Save'
                                  )}
                                </button>
                              </div>
                            </div>

                            {/* Image Generation Linking Notice */}
                            {p.supportsImageGen && (
                              <div className="p-2 rounded bg-purple-950/30 border border-purple-800/40 text-[11px] text-purple-200 flex items-start gap-2">
                                <Sparkles className="w-3.5 h-3.5 text-purple-400 shrink-0 mt-0.5" />
                                <div>
                                  <span className="font-semibold text-purple-300">
                                    Enables AI Photo Edit & Tweaker Button
                                  </span>
                                  <p className="text-[10px] text-purple-400/90 mt-0.5">
                                    Saving this key unlocks the "Edit Photo with AI" button on all your media vault photos using {p.imageGenModel || p.name}.
                                  </p>
                                </div>
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className="space-y-2">
                            <div className="p-2 rounded bg-emerald-500/10 border border-emerald-500/20 text-[11px] text-emerald-300 flex items-center gap-2">
                              <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                              <span>
                                Gemini 3.5, 3.1 Flash Lite, 3.1 Pro, and Imagen 3 are seamlessly initialized on the backend.
                              </span>
                            </div>
                            <div className="p-2 rounded bg-purple-950/30 border border-purple-800/40 text-[11px] text-purple-200 flex items-center gap-2">
                              <Sparkles className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                              <span>
                                Built-in Imagen 3 photo tweaking & AI Edit button enabled by default!
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
