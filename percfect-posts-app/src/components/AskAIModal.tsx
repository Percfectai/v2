import React, { useState } from 'react';
import {
  X,
  Bot,
  Sparkles,
  Send,
  Zap,
  Lightbulb,
  CornerDownLeft,
  Copy,
  Check,
  ArrowRight,
  Flame,
  Brain,
} from 'lucide-react';
import { UserSubscription, AIProviderInfo } from '../types.ts';

interface AskAIModalProps {
  isOpen: boolean;
  onClose: () => void;
  onApplyTextToDescription?: (text: string) => void;
  selectedMediaName?: string;
  currentDescription?: string;
  activeTags?: string[];
  subscription: UserSubscription;
  initialPrompt?: string;
}

export const AskAIModal: React.FC<AskAIModalProps> = ({
  isOpen,
  onClose,
  onApplyTextToDescription,
  selectedMediaName,
  currentDescription,
  activeTags = [],
  subscription,
  initialPrompt,
}) => {
  const [promptInput, setPromptInput] = useState(initialPrompt || '');
  const [isLoading, setIsLoading] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  // Sync initialPrompt if provided
  React.useEffect(() => {
    if (initialPrompt) {
      setPromptInput(initialPrompt);
    }
  }, [initialPrompt]);

  const [chatHistory, setChatHistory] = useState<
    { role: 'user' | 'assistant'; text: string; timestamp: string }[]
  >([
    {
      role: 'assistant',
      text: `Hi Nick! I'm your Percfect Post AI Assistant. Ask me to write viral captions, generate hashtag strategies, analyze platform algorithms, or rewrite your post copy for maximum engagement across X, Instagram, LinkedIn, and TikTok.`,
      timestamp: 'Just now',
    },
  ]);

  if (!isOpen) return null;

  const quickPrompts = [
    {
      label: '🚀 Write Viral Hook',
      prompt: `Write 3 high-converting viral hooks for my social media post about: "${
        currentDescription || selectedMediaName || 'creator content'
      }"`,
    },
    {
      label: '💡 Daily Post Idea Today',
      prompt: `Suggest an engaging, viral post concept for today with a compelling caption, hooks, and hashtags tailored for multi-platform reach.`,
    },
    {
      label: '🆘 Help! I am Stuck on Setup',
      prompt: `I'm setting up my social templates, API keys, and watermark logo. Can you guide me step-by-step on how everything connects so my workflow runs smoothly on its own?`,
    },
    {
      label: '📈 Best Post Times',
      prompt:
        'What are the current optimal posting times and algorithmic engagement triggers for Twitter/X, Instagram, and LinkedIn?',
    },
    {
      label: '🏷️ Trending Hashtag Cluster',
      prompt: `Give me 15 targeted, non-shadowbanned hashtags for a visual post in the tech & creator niche, separated into broad, niche, and community categories.`,
    },
    {
      label: '👔 LinkedIn Thought Leadership',
      prompt: `Turn this caption into an insightful, authentic LinkedIn post with strong readability and a question at the end: "${
        currentDescription || 'Sharing our latest project update and visual asset.'
      }"`,
    },
  ];

  const handleSend = async (customText?: string) => {
    const textToSend = customText || promptInput;
    if (!textToSend.trim() || isLoading) return;

    const userMsg = {
      role: 'user' as const,
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setChatHistory((prev) => [...prev, userMsg]);
    setPromptInput('');
    setIsLoading(true);

    try {
      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [
            ...chatHistory.map((m) => ({
              role: m.role === 'assistant' ? 'model' : 'user',
              text: m.text,
            })),
            { role: 'user', text: textToSend },
          ],
          role: 'strategist',
          useHighThinking: subscription.plan === 'pro',
          provider: 'gemini',
        }),
      });

      if (!res.ok) {
        throw new Error('Failed to get AI response');
      }

      const data = await res.json();
      const reply = data.reply || 'Here is your AI recommendation!';

      setChatHistory((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: reply,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } catch (err: any) {
      setChatHistory((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: `Error contacting AI service: ${err.message || 'Please try again.'}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-3 sm:p-6 animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-600 via-purple-600 to-pink-500 flex items-center justify-center text-white shadow-md">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-sm text-white flex items-center gap-2">
                Ask AI Assistant
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  Google Gemini 3.5
                </span>
              </h3>
              <p className="text-[11px] text-slate-400">
                Cross-platform algorithm strategist, viral hooks & copy rewriter
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Quick Suggestion Chips */}
        <div className="px-4 py-2.5 bg-slate-950/40 border-b border-slate-800/80 flex items-center gap-1.5 overflow-x-auto no-scrollbar">
          {quickPrompts.map((item, idx) => (
            <button
              key={idx}
              onClick={() => handleSend(item.prompt)}
              disabled={isLoading}
              className="px-2.5 py-1 rounded-full bg-slate-800/80 hover:bg-indigo-600/30 text-slate-300 hover:text-indigo-200 border border-slate-700/60 text-[11px] font-medium whitespace-nowrap transition flex items-center gap-1 shrink-0"
            >
              <span>{item.label}</span>
            </button>
          ))}
        </div>

        {/* Chat Message Feed */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 no-scrollbar max-h-[420px]">
          {chatHistory.map((msg, i) => (
            <div
              key={i}
              className={`flex flex-col ${
                msg.role === 'user' ? 'items-end' : 'items-start'
              }`}
            >
              <div
                className={`max-w-[85%] rounded-2xl p-3 text-xs leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-indigo-600 text-white font-medium rounded-tr-sm'
                    : 'bg-slate-800/90 border border-slate-700/70 text-slate-200 rounded-tl-sm'
                }`}
              >
                <div className="whitespace-pre-wrap">{msg.text}</div>

                {msg.role === 'assistant' && i > 0 && (
                  <div className="mt-2.5 pt-2 border-t border-slate-700/60 flex items-center justify-between text-[10px] text-slate-400">
                    <span>{msg.timestamp}</span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleCopy(msg.text, i)}
                        className="hover:text-white flex items-center gap-1 transition"
                      >
                        {copiedIndex === i ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                        <span>{copiedIndex === i ? 'Copied' : 'Copy'}</span>
                      </button>

                      {onApplyTextToDescription && (
                        <button
                          onClick={() => {
                            onApplyTextToDescription(msg.text);
                            onClose();
                          }}
                          className="text-indigo-400 hover:text-indigo-300 font-semibold flex items-center gap-1 transition"
                        >
                          <span>Insert to Description</span>
                          <ArrowRight className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="flex items-center gap-2 text-xs text-indigo-300 bg-indigo-950/40 border border-indigo-800/40 rounded-xl p-3 w-fit">
              <Zap className="w-3.5 h-3.5 animate-spin text-indigo-400" />
              <span>Thinking and formulating strategy...</span>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div className="p-3 border-t border-slate-800 bg-slate-950 flex items-center gap-2">
          <input
            type="text"
            value={promptInput}
            onChange={(e) => setPromptInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSend();
            }}
            placeholder="Ask AI for hooks, rewrite tips, hashtag clusters, or platform strategy..."
            className="flex-1 bg-slate-900 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
          <button
            onClick={() => handleSend()}
            disabled={!promptInput.trim() || isLoading}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition flex items-center gap-1.5 disabled:opacity-50"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Send</span>
          </button>
        </div>
      </div>
    </div>
  );
};
