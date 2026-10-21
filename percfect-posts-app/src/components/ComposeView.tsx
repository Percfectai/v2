import React, { useState } from 'react';
import {
  Send,
  Sparkles,
  Flame,
  Calendar,
  Clock,
  Check,
  Zap,
  Image as ImageIcon,
  ShieldCheck,
  Layers,
  AlertCircle,
  Copy,
  Sliders,
  ExternalLink,
} from 'lucide-react';
import {
  SocialPlatform,
  PlatformConfig,
  SocialTemplate,
  MediaItem,
  WatermarkSettings,
  UserSubscription,
  PostItem,
} from '../types.ts';
import { PhotoPostedBadges } from './SocialNetworkCheckmarks.tsx';

interface ComposeViewProps {
  platforms: PlatformConfig[];
  templates: SocialTemplate[];
  mediaList: MediaItem[];
  selectedMediaUrl: string;
  onSelectMediaUrl: (url: string) => void;
  watermarkSettings: WatermarkSettings;
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
  onOpenStudio: () => void;
  onPublishPost: (post: Omit<PostItem, 'id'>) => void;
  initialTopic?: string;
}

export const ComposeView: React.FC<ComposeViewProps> = ({
  platforms,
  templates,
  mediaList,
  selectedMediaUrl,
  onSelectMediaUrl,
  watermarkSettings,
  subscription,
  onOpenUpgrade,
  onOpenStudio,
  onPublishPost,
  initialTopic = '',
}) => {
  const [topic, setTopic] = useState(
    initialTopic ||
      'Launching our new cross-platform creator suite with automated watermarking, super-resolution upscaling, and AI-adapted copy for all social networks.'
  );
  const [tone, setTone] = useState<string>('engaging');
  const [titleStamp, setTitleStamp] = useState('MAJOR ANNOUNCEMENT');
  const [disclaimerStamp, setDisclaimerStamp] = useState(
    '© 2026 • #Sponsored #Ad'
  );
  const [selectedPlatformIds, setSelectedPlatformIds] = useState<SocialPlatform[]>([
    'twitter',
    'instagram',
    'linkedin',
    'tiktok',
  ]);
  const [activePreviewPlatform, setActivePreviewPlatform] = useState<SocialPlatform>('twitter');

  // AI generation state
  const [isGenerating, setIsGenerating] = useState(false);
  const [useHighThinking, setUseHighThinking] = useState(false);
  const [viralScore, setViralScore] = useState<number | null>(92);
  const [strategicAdvice, setStrategicAdvice] = useState<string>(
    'Post on X and LinkedIn at 9:00 AM EST for highest executive engagement, followed by Instagram at 12:30 PM.'
  );

  // Platform captions & tags dictionary
  const [platformCaptions, setPlatformCaptions] = useState<Partial<Record<SocialPlatform, string>>>({
    twitter:
      '🚨 The modern creator toolkit has permanently shifted ⚡️\n\nWhat used to take 4 hours of manual resizing and rewriting now takes 10 seconds with smart mass-posting.\n\nWatermark, upscale, and publish to all networks in 1 click:\n👇\n\n#BuildInPublic #AI #Creativity',
    instagram:
      '✨ The future of content creation isn’t about working longer hours—it’s about eliminating repetitive friction.\n\nHere is how high-output creators are scaling their reach across 6+ platforms:\n\n1. Generate 1 high-resolution master asset\n2. Auto-stamp logo & authentic copyright\n3. Adapt copy natively for each social algorithm\n4. Schedule at peak attention windows\n\n💬 Double tap and drop your biggest content bottleneck in the comments!\n\n#creatorcommunity #digitalmarketingtips #contentcreator #massposting #socialmediastrategy #branding101',
    linkedin:
      'Perspective on the rapid evolution of cross-channel distribution:\n\nIn 2026, content fragmentation across LinkedIn, X, TikTok, and Instagram creates significant operational overhead for marketing teams. \n\nTeams that leverage automated semantic adaptation and intelligent asset watermarking are winning. They spend 90% of their time on thesis formulation and 10% on distribution.\n\nHow is your organization adapting your multi-platform strategy this quarter?',
    tiktok:
      'Stop manually rewriting your captions for 5 different apps! 🤯 Here is how to mass-post with custom logo watermarks in 10 seconds. Link in bio! #fyp #techtok #creatorhacks #viral',
    youtube:
      'How to Mass Post to Every Social Network with AI in 2026 (Full Walkthrough)\n\nIn this short, we break down automated watermarking, super-resolution upscaling, and how to format captions for X, Instagram, LinkedIn, and TikTok in seconds.\n\nSubscribe for daily creator tech workflows!\n\n#Shorts #TechHacks #AItools',
    pinterest:
      'The Ultimate Cross-Platform Mass Posting Blueprint: How to scale your visual brand across all networks automatically with custom logo stamps and scheduled queues.',
    facebook:
      'Exciting milestone for digital creators! We are testing the new Mass Post Studio companion extension. What social platform is driving the most engagement for your brand right now? Let us know below!',
    threads:
      'Unpopular opinion: If you are still manually copying and pasting captions between Twitter, Instagram, and LinkedIn in 2026, you are burning 15 hours a week for nothing.',
    bluesky:
      'Open decentralized distribution is finally here. Testing 1-click cross-posting with verified media watermarks.',
  });

  const [platformTags, setPlatformTags] = useState<Partial<Record<SocialPlatform, string[]>>>({
    twitter: ['#BuildInPublic', '#AI', '#Creativity'],
    instagram: ['#creatorcommunity', '#digitalmarketingtips', '#contentcreator', '#massposting'],
    linkedin: ['#DigitalMarketing', '#Automation', '#GrowthStrategy'],
    tiktok: ['#fyp', '#techtok', '#creatorhacks'],
  });

  // Scheduling state
  const [scheduleDate, setScheduleDate] = useState('');
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishSuccess, setPublishSuccess] = useState(false);
  const [networkWarning, setNetworkWarning] = useState<string | null>(null);

  const isFree = subscription.plan === 'free';
  const isPro = subscription.plan === 'pro';
  const maxNetworksAllowed = isFree ? 2 : isPro ? 5 : 999;

  const togglePlatform = (p: SocialPlatform) => {
    setSelectedPlatformIds((prev) => {
      if (prev.includes(p)) {
        return prev.filter((x) => x !== p);
      }
      if (prev.length >= maxNetworksAllowed) {
        setNetworkWarning(
          isFree
            ? 'Free tier is limited to 2 social networks. Upgrade to Pro for 5, or Premium for unlimited!'
            : 'Pro tier is limited to 5 social networks. Upgrade to Premium for unlimited!'
        );
        setTimeout(() => setNetworkWarning(null), 5000);
        return prev;
      }
      setNetworkWarning(null);
      return [...prev, p];
    });
  };

  const handleSelectAll = () => {
    if (isFree) {
      setSelectedPlatformIds(platforms.slice(0, 2).map((p) => p.id));
      setNetworkWarning('Free tier is limited to 2 social networks.');
      setTimeout(() => setNetworkWarning(null), 4000);
    } else if (isPro) {
      setSelectedPlatformIds(platforms.slice(0, 5).map((p) => p.id));
      setNetworkWarning('Pro tier is limited to 5 social networks.');
      setTimeout(() => setNetworkWarning(null), 4000);
    } else {
      setSelectedPlatformIds(platforms.map((p) => p.id));
    }
  };

  const handleGenerateCopy = async () => {
    if (!topic.trim() || isGenerating) return;

    setIsGenerating(true);
    try {
      const res = await fetch('/api/gemini/generate-social-copy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic,
          tone,
          title: titleStamp,
          disclaimer: disclaimerStamp,
          platforms: selectedPlatformIds,
          useHighThinking,
        }),
      });

      const json = await res.json();
      if (json.data && json.data.platforms) {
        const newCaptions: Partial<Record<SocialPlatform, string>> = { ...platformCaptions };
        const newTags: Partial<Record<SocialPlatform, string[]>> = { ...platformTags };

        Object.keys(json.data.platforms).forEach((platKey) => {
          const p = platKey as SocialPlatform;
          if (json.data.platforms[p]) {
            newCaptions[p] = json.data.platforms[p].caption || '';
            newTags[p] = json.data.platforms[p].tags || [];
          }
        });

        setPlatformCaptions(newCaptions);
        setPlatformTags(newTags);
        if (json.data.viralScore) setViralScore(json.data.viralScore);
        if (json.data.strategicAdvice) setStrategicAdvice(json.data.strategicAdvice);
      }
    } catch (err) {
      console.error('Failed to generate copy:', err);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleTriggerPublish = (isScheduled: boolean) => {
    setIsPublishing(true);
    setTimeout(() => {
      setIsPublishing(false);
      setPublishSuccess(true);

      const finalCaptions = { ...platformCaptions };
      let finalBaseCaption = topic;

      if (isFree || subscription.mandatoryAttribution) {
        const attributionStr = '\n\n⚡ Streamlined with Perfect Posts - https://perfectposts.app';
        if (!finalBaseCaption.includes('Streamlined with Perfect Posts')) {
          finalBaseCaption = `${finalBaseCaption.trim()}${attributionStr}`;
        }
        selectedPlatformIds.forEach((pid) => {
          const orig = finalCaptions[pid] || finalBaseCaption;
          if (!orig.includes('Streamlined with Perfect Posts')) {
            finalCaptions[pid] = `${orig.trim()}${attributionStr}`;
          }
        });
      }

      onPublishPost({
        title: titleStamp || 'Cross-Platform Mass Post',
        baseCaption: finalBaseCaption,
        platformCaptions: finalCaptions,
        platformTags,
        platforms: selectedPlatformIds,
        mediaUrl: selectedMediaUrl,
        status: isScheduled ? 'scheduled' : 'posted',
        scheduledTime: isScheduled ? scheduleDate || new Date().toISOString() : undefined,
        postedAt: !isScheduled ? new Date().toISOString() : undefined,
        viralScore: viralScore || 90,
        stats: {
          impressions: 0,
          likes: 0,
          shares: 0,
          comments: 0,
          clicks: 0,
        },
        extensionSynced: true,
      });

      setTimeout(() => setPublishSuccess(false), 3000);
    }, 1500);
  };

  const activeConfig = platforms.find((p) => p.id === activePreviewPlatform) || platforms[0];
  const currentCaption = platformCaptions[activePreviewPlatform] || '';
  const charLimit = activeConfig.maxChars;
  const isOverLimit = currentCaption.length > charLimit;

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Send className="w-5 h-5 text-indigo-400" />
            Compose & Cross-Platform Mass Post
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Craft 1 master message, auto-adapt formatting with Gemini AI, watermark media, and broadcast across all connected social channels.
          </p>
        </div>

        {viralScore && (
          <div className="flex items-center gap-2 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800">
            <Sparkles className="w-4 h-4 text-amber-400" />
            <div className="text-xs">
              <span className="text-slate-400">Viral Hook Score: </span>
              <strong className="text-emerald-400 font-bold">{viralScore}/100</strong>
            </div>
          </div>
        )}
      </div>

      {/* Main Grid: Input & Options (6 cols) + Multi-Platform Live Preview (6 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Master Inputs & AI Parameters (6 cols) */}
        <div className="lg:col-span-6 space-y-4">
          {/* Target Platforms Pill Selector */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                Target Social Networks ({selectedPlatformIds.length}/{platforms.length})
              </span>
              <button
                onClick={handleSelectAll}
                className="text-[11px] text-indigo-400 hover:underline font-semibold"
              >
                Select All
              </button>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {platforms.map((p) => {
                const isSelected = selectedPlatformIds.includes(p.id);
                return (
                  <button
                    key={p.id}
                    onClick={() => togglePlatform(p.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 ${
                      isSelected
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'bg-slate-800/80 text-slate-400 hover:bg-slate-750 hover:text-slate-200'
                    }`}
                  >
                    <span>{p.name.split(' ')[0]}</span>
                    {isSelected && <Check className="w-3 h-3 text-white" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Master Message Composer */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-white">
                Master Topic / Content Seed:
              </label>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-slate-400">Tone:</span>
                <select
                  value={tone}
                  onChange={(e) => setTone(e.target.value)}
                  className="bg-slate-950 border border-slate-800 text-slate-200 text-xs rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
                >
                  <option value="engaging">Engaging & Punchy</option>
                  <option value="viral">Viral & Intriguing</option>
                  <option value="professional">Thought Leadership</option>
                  <option value="educational">Educational / How-To</option>
                  <option value="witty">Witty & Casual</option>
                </select>
              </div>
            </div>

            <textarea
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="What do you want to share? Describe your product launch, thought, tutorial, or news..."
              className="w-full h-28 bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none leading-relaxed"
            />

            {/* Title & Disclaimer Stamps */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">
                  Visual Title Stamp:
                </label>
                <input
                  type="text"
                  value={titleStamp}
                  onChange={(e) => setTitleStamp(e.target.value)}
                  placeholder="e.g. SPECIAL ANNOUNCEMENT"
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-300">
                  Legal / Disclaimer Stamp:
                </label>
                <input
                  type="text"
                  value={disclaimerStamp}
                  onChange={(e) => setDisclaimerStamp(e.target.value)}
                  placeholder="e.g. #Ad #Sponsored"
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            {/* High Thinking Mode & AI Trigger */}
            <div className="pt-2 border-t border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={useHighThinking}
                  onChange={(e) => {
                    if (e.target.checked && subscription.plan === 'free') {
                      onOpenUpgrade();
                      return;
                    }
                    setUseHighThinking(e.target.checked);
                  }}
                  className="w-4 h-4 rounded text-orange-500 focus:ring-0 bg-slate-800 border-slate-700"
                />
                <span className="flex items-center gap-1 font-medium">
                  <Flame className={`w-3.5 h-3.5 ${useHighThinking ? 'text-orange-400' : 'text-slate-500'}`} />
                  High Thinking Mode (Deep Reasoning)
                </span>
              </label>

              <button
                onClick={handleGenerateCopy}
                disabled={isGenerating || !topic.trim()}
                className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-md transition disabled:opacity-50"
              >
                {isGenerating ? (
                  <>
                    <Zap className="w-3.5 h-3.5 animate-spin" />
                    Generating Across All Formats...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                    AI Format & Generate Tags
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Attached Media Box */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-white flex items-center gap-2">
                <ImageIcon className="w-4 h-4 text-indigo-400" />
                Attached Asset & Stamping
              </span>
              <button
                onClick={onOpenStudio}
                className="text-[11px] text-indigo-400 hover:underline flex items-center gap-1"
              >
                <Sliders className="w-3 h-3" />
                Open Watermark Studio
              </button>
            </div>

            <div className="flex items-center gap-4 bg-slate-950 p-2.5 rounded-lg border border-slate-800">
              <div className="relative w-20 h-20 rounded-lg overflow-hidden border border-slate-700 shrink-0 bg-black">
                <img
                  src={selectedMediaUrl}
                  alt="Selected Media"
                  className="w-full h-full object-cover"
                />
                <div className="absolute top-1 left-1 bg-black/80 px-1 py-0.2 rounded text-[8px] font-mono text-indigo-300">
                  Stamped
                </div>
              </div>

              <div className="flex-1 space-y-1.5 text-xs">
                <div className="flex items-center gap-2 text-emerald-400 font-semibold text-[11px]">
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>Logo Watermark & Disclaimers Active</span>
                </div>
                <p className="text-[11px] text-slate-400">
                  Logo: {watermarkSettings.logoUrl ? 'Configured' : 'Default'} • Position: {watermarkSettings.position}
                </p>
                <div className="flex items-center gap-2 pt-0.5">
                  <button
                    onClick={() => {
                      const idx = mediaList.findIndex((m) => m.url === selectedMediaUrl);
                      const next = mediaList[(idx + 1) % mediaList.length];
                      if (next) onSelectMediaUrl(next.url);
                    }}
                    className="text-[10px] text-indigo-400 hover:underline"
                  >
                    Swap Stored Image
                  </button>
                </div>

                {/* Social Network Posted Colored Checkmarks Status */}
                {(() => {
                  const currentItem = mediaList.find(
                    (m) => m.url === selectedMediaUrl || m.watermarkedUrl === selectedMediaUrl
                  );
                  if (currentItem?.postedNetworks && currentItem.postedNetworks.length > 0) {
                    return (
                      <div className="pt-1 flex items-center gap-1.5 flex-wrap border-t border-slate-800/80 mt-1">
                        <span className="text-[10px] text-slate-400 font-medium">Previously Posted:</span>
                        <PhotoPostedBadges postedNetworks={currentItem.postedNetworks} size="xs" />
                      </div>
                    );
                  }
                  return (
                    <div className="pt-1 border-t border-slate-800/80 mt-1">
                      <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-1">
                        <Check className="w-3 h-3" /> Fresh Asset (Not posted anywhere yet)
                      </span>
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Multi-Platform Live Preview & Customizer (6 cols) */}
        <div className="lg:col-span-6 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col h-[580px]">
            {/* Platform Sub-Tabs */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
              <span className="text-xs font-bold text-white">Live Platform Preview</span>

              {/* Mini Platform Switcher */}
              <div className="flex items-center gap-1 overflow-x-auto no-scrollbar max-w-[280px]">
                {selectedPlatformIds.map((pId) => {
                  const p = platforms.find((x) => x.id === pId);
                  const isSelected = activePreviewPlatform === pId;
                  return (
                    <button
                      key={pId}
                      onClick={() => setActivePreviewPlatform(pId)}
                      className={`px-2.5 py-1 rounded-md text-[11px] font-bold capitalize transition ${
                        isSelected
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {p?.name.split(' ')[0]}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Interactive Social Preview Card */}
            <div className="flex-1 bg-slate-950 border border-slate-850 rounded-xl p-4 flex flex-col justify-between overflow-y-auto no-scrollbar shadow-inner">
              <div className="space-y-3">
                {/* Simulated Platform Post Header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <img
                      src={activeConfig.avatar || '/static/assets/brand/favicon-64.png'}
                      alt="Avatar"
                      className="w-8 h-8 rounded-full object-cover border border-slate-700"
                    />
                    <div>
                      <div className="flex items-center gap-1.5 text-xs font-bold text-white">
                        <span>{activeConfig.accountHandle || activeConfig.name}</span>
                        <span className="text-[10px] text-indigo-400">✓</span>
                      </div>
                      <span className="text-[10px] text-slate-500 font-mono">
                        Native {activeConfig.name} Format
                      </span>
                    </div>
                  </div>

                  <span
                    className={`text-[10px] font-mono px-2 py-0.5 rounded ${
                      isOverLimit
                        ? 'bg-rose-500/20 text-rose-300 font-bold border border-rose-500/40'
                        : 'text-slate-400 bg-slate-900'
                    }`}
                  >
                    {currentCaption.length} / {charLimit} chars
                  </span>
                </div>

                {/* Editable Platform Caption */}
                <div>
                  <textarea
                    value={currentCaption}
                    onChange={(e) =>
                      setPlatformCaptions({
                        ...platformCaptions,
                        [activePreviewPlatform]: e.target.value,
                      })
                    }
                    rows={6}
                    className="w-full bg-slate-900/90 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 resize-none leading-relaxed"
                  />
                </div>

                {/* Media preview with stamped title & logo */}
                <div className="relative rounded-lg overflow-hidden border border-slate-800 aspect-video bg-black/60">
                  <img
                    src={selectedMediaUrl}
                    alt="Stamped Preview"
                    className="w-full h-full object-cover"
                  />
                  {titleStamp && (
                    <div className="absolute top-2 left-2 px-2 py-0.5 bg-slate-900/85 backdrop-blur rounded text-[10px] font-bold text-white border border-indigo-500/50">
                      {titleStamp}
                    </div>
                  )}
                  {watermarkSettings.enabled && (
                    <div className="absolute bottom-2 right-2 px-2 py-0.5 bg-slate-900/80 backdrop-blur rounded text-[9px] font-bold text-indigo-300 border border-white/10">
                      {watermarkSettings.watermarkText || 'PercfectAI'}
                    </div>
                  )}
                  {disclaimerStamp && (
                    <div className="absolute inset-x-0 bottom-0 py-0.5 bg-black/80 text-[8px] text-center text-slate-400">
                      {disclaimerStamp}
                    </div>
                  )}
                </div>
              </div>

              {/* Strategic Advice Callout */}
              {strategicAdvice && (
                <div className="mt-3 p-2.5 rounded-lg bg-indigo-950/40 border border-indigo-800/40 text-[11px] text-indigo-200">
                  <strong className="text-amber-300">AI Distribution Tip: </strong>
                  {strategicAdvice}
                </div>
              )}
            </div>

            {/* Mass Dispatch & Schedule Controls */}
            <div className="mt-4 pt-3 border-t border-slate-800 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
              {/* Date / Schedule picker */}
              <div className="flex items-center gap-1.5 bg-slate-950 px-2.5 py-1.5 rounded-lg border border-slate-800 text-xs text-slate-300">
                <Calendar className="w-3.5 h-3.5 text-slate-400" />
                <input
                  type="datetime-local"
                  value={scheduleDate}
                  onChange={(e) => setScheduleDate(e.target.value)}
                  className="bg-transparent text-slate-300 text-xs focus:outline-none cursor-pointer"
                />
              </div>

              <div className="flex items-center gap-2">
                {scheduleDate ? (
                  <button
                    onClick={() => handleTriggerPublish(true)}
                    disabled={isPublishing}
                    className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs flex items-center gap-1.5 shadow transition"
                  >
                    <Clock className="w-3.5 h-3.5" />
                    Schedule ({selectedPlatformIds.length})
                  </button>
                ) : (
                  <button
                    onClick={() => handleTriggerPublish(false)}
                    disabled={isPublishing}
                    className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center gap-2 shadow-lg shadow-indigo-600/30 transition"
                  >
                    {isPublishing ? (
                      <>
                        <Zap className="w-3.5 h-3.5 animate-spin" />
                        Mass Posting to {selectedPlatformIds.length} Networks...
                      </>
                    ) : publishSuccess ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-emerald-300" />
                        Published to All Networks!
                      </>
                    ) : (
                      <>
                        <Send className="w-3.5 h-3.5" />
                        Mass Post Now ({selectedPlatformIds.length} Networks)
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
