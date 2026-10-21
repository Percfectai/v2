import React, { useState, useRef, useEffect } from 'react';
import {
  Sparkles,
  Bot,
  User,
  Settings,
  Upload,
  Camera,
  Film,
  Image as ImageIcon,
  Check,
  Wand2,
  Send,
  Hash,
  Plus,
  X,
  Sliders,
  ExternalLink,
  ChevronDown,
  Layers,
  Zap,
  Info,
  RefreshCw,
  HardDrive,
  Eye,
  CheckCircle2,
  Globe,
  Share2,
  Trash2,
  Radio,
  Crown,
  Maximize2,
  Stamp,
  Download,
  Calendar,
  Clock,
  Lock,
  BarChart3,
  LayoutTemplate,
  ShieldCheck,
  KeyRound,
  Lightbulb,
  HelpCircle,
  CheckSquare,
  Square,
  ArrowRight,
  Chrome,
  CreditCard,
  Smartphone,
} from 'lucide-react';
import {
  MediaItem,
  PlatformConfig,
  SocialPlatform,
  SocialTemplate,
  UserSubscription,
  WatermarkSettings,
  AIProviderInfo,
  AIProvider,
  PostItem,
} from '../types.ts';
import {
  PLATFORM_VISUALS,
  ALL_PLATFORMS,
  PhotoPostedBadges,
  getPlatformVisual,
} from './SocialNetworkCheckmarks.tsx';
import { AskAIModal } from './AskAIModal.tsx';
import { AIPhotoTweakerModal } from './AIPhotoTweakerModal.tsx';
import { UpscalePhotoModal } from './UpscalePhotoModal.tsx';
import { APIKeyVaultModal } from './APIKeyVaultModal.tsx';

interface MainMediaWorkspaceViewProps {
  mediaList: MediaItem[];
  activeMedia: MediaItem | null;
  onSelectMedia: (item: MediaItem) => void;
  onAddMedia: (item: MediaItem) => void;
  onUpdateMedia: (item: MediaItem) => void;
  onDeleteMedia: (id: string) => void;
  platforms: PlatformConfig[];
  templates: SocialTemplate[];
  onNavigateToSettings: () => void;
  onNavigateToVideoStudio?: () => void;
  onNavigateToCompose?: () => void;
  onNavigateToExtension?: () => void;
  onNavigateToAnalytics?: () => void;
  onNavigateToAI?: () => void;
  onNavigateToStudio?: () => void;
  onPublishPost: (post: Omit<PostItem, 'id'>) => void;
  subscription: UserSubscription;
  onOpenUpgrade: () => void;
  aiProviders?: AIProviderInfo[];
  onUpdateProviderKey?: (id: AIProvider, key: string) => void;
  watermarkSettings: WatermarkSettings;
  onUpdateWatermark?: (settings: WatermarkSettings) => void;
}

export const MainMediaWorkspaceView: React.FC<MainMediaWorkspaceViewProps> = ({
  mediaList,
  activeMedia,
  onSelectMedia,
  onAddMedia,
  onUpdateMedia,
  onDeleteMedia,
  platforms,
  templates,
  onNavigateToSettings,
  onNavigateToVideoStudio,
  onNavigateToCompose,
  onNavigateToExtension,
  onNavigateToAnalytics,
  onNavigateToAI,
  onNavigateToStudio,
  onPublishPost,
  subscription,
  onOpenUpgrade,
  aiProviders = [],
  onUpdateProviderKey,
  watermarkSettings,
  onUpdateWatermark,
}) => {
  // Center Column Filter: 'all' | 'photos' | 'videos'
  const [siteUser, setSiteUser] = useState<string>('');
  useEffect(() => {
    fetch('/api/percfectposts/site-profile', { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((d) => setSiteUser(d?.logged_in ? d.username || '' : ''))
      .catch(() => {});
  }, []);
  const [centerTab, setCenterTab] = useState<'all' | 'photos' | 'videos'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [quickFilter, setQuickFilter] = useState<'all' | 'posted' | 'unposted'>('all');

  // Modals state
  const [isAskAIOpen, setIsAskAIOpen] = useState(false);
  const [aiModalInitialPrompt, setAiModalInitialPrompt] = useState<string>('');
  const [isTweakerOpen, setIsTweakerOpen] = useState(false);
  const [showInstallAppModal, setShowInstallAppModal] = useState(false);
  const [mediaToTweak, setMediaToTweak] = useState<MediaItem | null>(null);
  const [isUpscaleOpen, setIsUpscaleOpen] = useState(false);
  const [mediaToUpscale, setMediaToUpscale] = useState<MediaItem | null>(null);
  const [isKeyVaultOpen, setIsKeyVaultOpen] = useState(false);
  const [isSchedulingOpen, setIsSchedulingOpen] = useState(false);
  const [scheduledDateTime, setScheduledDateTime] = useState<string>(() => {
    const d = new Date(Date.now() + 4 * 3600 * 1000);
    return d.toISOString().slice(0, 16);
  });
  const [watermarkNotice, setWatermarkNotice] = useState<string | null>(null);
  const [isWatermarking, setIsWatermarking] = useState(false);

  // Right Sidebar State: Tags
  const [tags, setTags] = useState<string[]>([
    'PercfectPost',
    'CreatorEconomy',
    'PercfectAI',
    'VisualArt',
  ]);
  const [newTagInput, setNewTagInput] = useState('');
  const [isSuggestingTags, setIsSuggestingTags] = useState(false);

  // Right Sidebar State: Description & Prompt box
  const [description, setDescription] = useState<string>(
    'Master your multi-platform presence with one cohesive post. Stamped, tagged, and adapted for algorithm dominance across all channels.'
  );
  const [isGeneratingCopy, setIsGeneratingCopy] = useState(false);
  const [isWandMenuOpen, setIsWandMenuOpen] = useState(false);
  const [postSuccessNotice, setPostSuccessNotice] = useState<string | null>(null);

  // Right Sidebar State: Social Media Toggle Switches
  const isFree = subscription.plan === 'free';
  const isPro = subscription.plan === 'pro';
  const isPremium = subscription.plan === 'premium' || subscription.plan === 'agency';
  const maxNetworksAllowed = isFree ? 2 : isPro ? 5 : 999;
  const [networkLimitNotice, setNetworkLimitNotice] = useState<string | null>(null);

  // Initialize with the platforms that are configured/connected respecting tier limit
  const [activeNetworkToggles, setActiveNetworkToggles] = useState<Record<SocialPlatform, boolean>>(() => {
    if (subscription.plan === 'free') {
      return {
        twitter: true,
        instagram: true,
        linkedin: false,
        tiktok: false,
        youtube: false,
        pinterest: false,
        facebook: false,
        threads: false,
        bluesky: false,
      };
    }
    return {
      twitter: true,
      instagram: true,
      linkedin: true,
      tiktok: true,
      youtube: false,
      pinterest: false,
      facebook: false,
      threads: false,
      bluesky: false,
    };
  });

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Filter media into Photos and Videos
  const photosList = mediaList.filter((m) => m.type === 'image');
  const videosList = mediaList.filter((m) => m.type === 'video');

  const filteredPhotos = photosList.filter((item) => {
    const matchesSearch = item.name.toLowerCase().includes(searchQuery.toLowerCase());
    const hasPosted = item.postedNetworks && item.postedNetworks.length > 0;
    if (quickFilter === 'posted') return matchesSearch && hasPosted;
    if (quickFilter === 'unposted') return matchesSearch && !hasPosted;
    return matchesSearch;
  });

  const filteredVideos = videosList.filter((item) => {
    const matchesSearch = item.name.toLowerCase().includes(searchQuery.toLowerCase());
    const hasPosted = item.postedNetworks && item.postedNetworks.length > 0;
    if (quickFilter === 'posted') return matchesSearch && hasPosted;
    if (quickFilter === 'unposted') return matchesSearch && !hasPosted;
    return matchesSearch;
  });

  // Selected networks array
  const selectedPlatforms = (Object.keys(activeNetworkToggles) as SocialPlatform[]).filter(
    (key) => activeNetworkToggles[key]
  );

  // Toggle network switch with package limit enforcement
  const handleToggleNetwork = (platform: SocialPlatform) => {
    const isCurrentlyActive = !!activeNetworkToggles[platform];
    if (!isCurrentlyActive) {
      const activeCount = Object.values(activeNetworkToggles).filter(Boolean).length;
      if (activeCount >= maxNetworksAllowed) {
        if (isFree) {
          setNetworkLimitNotice(
            'Free Plan allows up to 2 social networks. Upgrade to Pro for 5, or Premium for unlimited!'
          );
        } else if (isPro) {
          setNetworkLimitNotice(
            'Pro Plan allows up to 5 social networks. Upgrade to Premium for unlimited!'
          );
        }
        setTimeout(() => setNetworkLimitNotice(null), 6000);
        return;
      }
    }
    setNetworkLimitNotice(null);
    setActiveNetworkToggles((prev) => ({
      ...prev,
      [platform]: !prev[platform],
    }));
  };

  // Add custom tag
  const handleAddTag = () => {
    const clean = newTagInput.trim().replace(/^#/, '');
    if (clean && !tags.includes(clean)) {
      setTags((prev) => [...prev, clean]);
      setNewTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags((prev) => prev.filter((t) => t !== tagToRemove));
  };

  // AI Suggest Tags using Gemini
  const handleSuggestTags = async () => {
    setIsSuggestingTags(true);
    try {
      const prompt = `Suggest 6 trending, high-traffic social media hashtags for a post with this content:
Description: "${description}"
Selected Media: "${activeMedia?.name || 'High resolution photo'}"
Format: return just a JSON array of string tags without the # symbol, e.g. ["TechNews", "VisualCreator", "AIProduction"]`;

      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [{ role: 'user', text: prompt }],
          role: 'growth',
          provider: 'gemini',
        }),
      });

      if (res.ok) {
        const data = await res.json();
        const rawReply = data.reply || '';
        const match = rawReply.match(/\[(.*?)\]/s);
        if (match) {
          const parsedTags = JSON.parse(`[${match[1]}]`) as string[];
          const unique = Array.from(new Set([...tags, ...parsedTags]));
          setTags(unique.slice(0, 15));
        } else {
          setTags((prev) => [
            ...prev,
            'TrendingContent',
            'CreatorEconomy',
            'DigitalStrategy',
          ]);
        }
      }
    } catch {
      setTags((prev) => [
        ...prev,
        'ViralReach',
        'TopPost',
        'VisualCraft',
      ]);
    } finally {
      setIsSuggestingTags(false);
    }
  };

  // Open Ask AI Modal with an optional pre-filled prompt
  const openAskAIWithPrompt = (promptText: string = '') => {
    setAiModalInitialPrompt(promptText);
    setIsAskAIOpen(true);
  };

  // Magic Wand AI Action: Write from scratch or Rewrite whatever is in the prop box
  const handleWandAction = async (mode: 'write' | 'rewrite' | 'punchy' | 'linkedin' | 'cta') => {
    setIsWandMenuOpen(false);
    setIsGeneratingCopy(true);

    try {
      let prompt = '';
      if (mode === 'write') {
        prompt = `You are a master social media copywriter. Write a compelling, engaging caption from scratch for an asset named "${
          activeMedia?.name || 'Creator Visual'
        }".
Key topics & tags: ${tags.join(', ')}.
Tone: Engaging, energetic, and visually captivating. Include 1-2 tasteful emojis and a clear concluding thought.`;
      } else if (mode === 'rewrite') {
        prompt = `You are an expert social media copy doctor. Rewrite and polish this exact text from the prop box:
"${description}"
Instructions: Enhance the flow, vocabulary, rhythm, and punchiness. Keep the original intent intact while making it significantly more engaging.`;
      } else if (mode === 'punchy') {
        prompt = `Rewrite this text to be short, punchy, curiosity-inducing with a viral hook:
"${description}"`;
      } else if (mode === 'linkedin') {
        prompt = `Rewrite this text for LinkedIn thought leadership: authentic tone, clean paragraph breaks, insightful takeaway, and an engagement question at the end:
"${description}"`;
      } else if (mode === 'cta') {
        prompt = `Keep this text and append a high-converting question or call-to-action to spark comments and shares:
"${description}"`;
      }

      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [{ role: 'user', text: prompt }],
          role: 'copywriter',
          provider: 'gemini',
        }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.reply) {
          setDescription(data.reply.trim());
        }
      }
    } catch (e) {
      console.error('Wand error:', e);
    } finally {
      setIsGeneratingCopy(false);
    }
  };

  // Mass Post to selected networks
  const handleMassPost = () => {
    if (selectedPlatforms.length === 0) {
      alert('Please switch on at least one social media network on the right!');
      return;
    }

    // Mandatory attribution for free users on description
    let finalDescription = description;
    if (isFree || subscription.mandatoryAttribution) {
      const attributionStr = '\n\n⚡ Streamlined with Perfect Posts - https://perfectposts.app';
      if (!finalDescription.includes('Streamlined with Perfect Posts')) {
        finalDescription = `${finalDescription.trim()}${attributionStr}`;
      }
    }

    const platformCaptions: Partial<Record<SocialPlatform, string>> = {};
    const platformTags: Partial<Record<SocialPlatform, string[]>> = {};
    const formattedTags = tags.map((t) => (t.startsWith('#') ? t : `#${t}`));

    selectedPlatforms.forEach((p) => {
      platformCaptions[p] = finalDescription;
      platformTags[p] = formattedTags;
    });

    onPublishPost({
      title: activeMedia ? activeMedia.name : 'The Percfect Post',
      baseCaption: finalDescription,
      platformCaptions,
      platformTags,
      platforms: selectedPlatforms,
      mediaUrl: activeMedia ? (activeMedia.watermarkedUrl || activeMedia.url) : undefined,
      status: 'posted',
      postedAt: new Date().toISOString(),
      viralScore: Math.floor(Math.random() * 12) + 88,
      stats: {
        impressions: Math.floor(Math.random() * 1500) + 600,
        likes: Math.floor(Math.random() * 250) + 60,
        shares: Math.floor(Math.random() * 65) + 15,
        comments: Math.floor(Math.random() * 45) + 8,
        clicks: Math.floor(Math.random() * 120) + 25,
      },
    });

    // Update the active media's postedNetworks checkmarks!
    if (activeMedia) {
      const current = activeMedia.postedNetworks || [];
      const updated = Array.from(new Set([...current, ...selectedPlatforms]));
      const updatedItem = { ...activeMedia, postedNetworks: updated as SocialPlatform[] };
      onSelectMedia(updatedItem);
      onUpdateMedia(updatedItem);
    }

    setPostSuccessNotice(
      `Successfully published to ${selectedPlatforms.length} social networks! Checkmarks updated.`
    );
    setTimeout(() => setPostSuccessNotice(null), 4500);
  };

  // Schedule Post for Later
  const handleSchedulePost = () => {
    if (selectedPlatforms.length === 0) {
      alert('Please switch on at least one social media network on the right!');
      return;
    }

    // Mandatory attribution for free users on description
    let finalDescription = description;
    if (isFree || subscription.mandatoryAttribution) {
      const attributionStr = '\n\n⚡ Streamlined with Perfect Posts - https://perfectposts.app';
      if (!finalDescription.includes('Streamlined with Perfect Posts')) {
        finalDescription = `${finalDescription.trim()}${attributionStr}`;
      }
    }

    const platformCaptions: Partial<Record<SocialPlatform, string>> = {};
    const platformTags: Partial<Record<SocialPlatform, string[]>> = {};
    const formattedTags = tags.map((t) => (t.startsWith('#') ? t : `#${t}`));

    selectedPlatforms.forEach((p) => {
      platformCaptions[p] = finalDescription;
      platformTags[p] = formattedTags;
    });

    const scheduledTime = scheduledDateTime || new Date(Date.now() + 3600000 * 4).toISOString();

    onPublishPost({
      title: activeMedia ? activeMedia.name : 'The Percfect Post',
      baseCaption: finalDescription,
      platformCaptions,
      platformTags,
      platforms: selectedPlatforms,
      mediaUrl: activeMedia ? (activeMedia.watermarkedUrl || activeMedia.url) : undefined,
      status: 'scheduled',
      scheduledTime,
      postedAt: scheduledTime,
      viralScore: Math.floor(Math.random() * 10) + 90,
      stats: {
        impressions: 0,
        likes: 0,
        shares: 0,
        comments: 0,
        clicks: 0,
      },
    });

    setIsSchedulingOpen(false);
    setPostSuccessNotice(
      `Post scheduled for ${new Date(scheduledTime).toLocaleDateString()} at ${new Date(
        scheduledTime
      ).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} across ${
        selectedPlatforms.length
      } networks!`
    );
    setTimeout(() => setPostSuccessNotice(null), 5000);
  };

  // 1. Photo Action: Add WM or Logo (Free gets mandatory trademark stamp; Pro/Premium gets custom branding)
  const handleApplyWatermarkToPhoto = async (photo: MediaItem) => {
    setIsWatermarking(true);
    try {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.src = photo.url;

      await new Promise((resolve) => {
        img.onload = resolve;
        img.onerror = () => resolve(null);
      });

      const canvas = document.createElement('canvas');
      canvas.width = img.width || 1200;
      canvas.height = img.height || 800;
      const ctx = canvas.getContext('2d');

      if (ctx) {
        ctx.drawImage(img, 0, 0);

        const stampText = isFree
          ? '⚡ Streamlined with Perfect Posts'
          : (watermarkSettings.watermarkText || '© The Percfect Post');
        const fontSize = Math.max(20, Math.floor(canvas.width * 0.028));
        ctx.font = `bold ${fontSize}px sans-serif`;
        const textMetrics = ctx.measureText(stampText);
        const textWidth = textMetrics.width;
        const margin = Math.max(16, Math.floor(canvas.width * 0.025));

        const x = canvas.width - textWidth - margin;
        const y = canvas.height - margin;

        // Dark translucent rounded badge behind text
        ctx.fillStyle = 'rgba(0, 0, 0, 0.78)';
        ctx.beginPath();
        if (ctx.roundRect) {
          ctx.roundRect(x - 14, y - fontSize + 2, textWidth + 28, fontSize + 10, 8);
        } else {
          ctx.rect(x - 14, y - fontSize + 2, textWidth + 28, fontSize + 10);
        }
        ctx.fill();

        // Stamped Text
        ctx.fillStyle = isFree ? '#facc15' : (watermarkSettings.textColor || '#ffffff');
        ctx.fillText(stampText, x, y);

        const stampedUrl = canvas.toDataURL('image/jpeg', 0.92);
        const updated: MediaItem = {
          ...photo,
          watermarkedUrl: stampedUrl,
          titleStamp: stampText,
        };

        onUpdateMedia(updated);
        onSelectMedia(updated);
        setWatermarkNotice(
          isFree
            ? 'Mandatory Perfect Posts trademark stamp applied (Free tier)!'
            : `Watermark & Logo stamped on ${photo.name}!`
        );
        setTimeout(() => setWatermarkNotice(null), 4000);
      }
    } catch (e) {
      console.error('Watermark error:', e);
      // Fallback
      const fallbackStamp = isFree
        ? '⚡ Streamlined with Perfect Posts'
        : (watermarkSettings.watermarkText || '© The Percfect Post');
      const updated: MediaItem = {
        ...photo,
        watermarkedUrl: photo.url,
        titleStamp: fallbackStamp,
      };
      onUpdateMedia(updated);
      onSelectMedia(updated);
      setWatermarkNotice(
        isFree
          ? 'Mandatory Perfect Posts trademark applied!'
          : `Watermark applied to ${photo.name}!`
      );
      setTimeout(() => setWatermarkNotice(null), 4000);
    } finally {
      setIsWatermarking(false);
    }
  };

  // 2. Photo Action: Edit (PRO)
  const handleEditPhoto = (photo: MediaItem) => {
    if (!isPro) {
      onOpenUpgrade();
      return;
    }
    setMediaToTweak(photo);
    setIsTweakerOpen(true);
  };

  // 3. Photo Action: Upscayl (PRO)
  const handleUpscalePhoto = (photo: MediaItem) => {
    if (!isPro) {
      onOpenUpgrade();
      return;
    }
    setMediaToUpscale(photo);
    setIsUpscaleOpen(true);
  };

  // 4. Photo Action: Download (Standard)
  const handleDownloadPhoto = (photo: MediaItem) => {
    const link = document.createElement('a');
    link.href = photo.watermarkedUrl || photo.url;
    link.download = `${photo.name.replace(/\.[^/.]+$/, '')}-percfect.jpg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Bottom Right Pro Options Handlers
  const handleOpenAnalytics = () => {
    if (!isPro) {
      onOpenUpgrade();
      return;
    }
    onNavigateToAnalytics?.();
  };

  const handleOpenTemplates = () => {
    if (!isPro) {
      onOpenUpgrade();
      return;
    }
    onNavigateToSettings?.();
  };

  const handleOpenAI = () => {
    if (!isPro) {
      onOpenUpgrade();
      return;
    }
    onNavigateToAI?.();
  };

  const handleOpenKeyVault = () => {
    // Free & unlocked for everyone as requested by user
    setIsKeyVaultOpen(true);
  };

  const handleMakeWatermarkOrLogo = () => {
    if (!isPro) {
      onOpenUpgrade();
      return;
    }
    onNavigateToStudio?.();
  };

  // File Upload Handler
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const isVid = file.type.startsWith('video/');
    const newMedia: MediaItem = {
      id: `upload-${Date.now()}`,
      name: file.name,
      url: URL.createObjectURL(file),
      type: isVid ? 'video' : 'image',
      dimensions: isVid ? { width: 1920, height: 1080 } : { width: 1200, height: 800 },
      size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
      timestamp: new Date().toISOString(),
      postedNetworks: [],
    };

    onAddMedia(newMedia);
    onSelectMedia(newMedia);
  };

  return (
    <div className="space-y-4 animate-in fade-in duration-200">
      {/* 3-Column Primary Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* ========================================================
            LEFT SIDEBAR (3 cols on lg)
            - Top has User Account
            - Ask AI Button
            - Quick Vault Filters & Settings Link
        ======================================================== */}
        <div className="lg:col-span-3 space-y-4">
          {/* Quick-Access Studios & Tools (Buttons on Left Side of Page) */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-3 shadow-xl space-y-1.5">
            <div className="px-2 py-1 flex items-center justify-between border-b border-slate-800/80 mb-1">
              <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">
                Navigation & Studios
              </span>
              <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-300">
                Left Toolbar
              </span>
            </div>

            <button
              type="button"
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white shadow-md shadow-indigo-600/30 text-left"
            >
              <Layers className="w-4 h-4 text-indigo-200" />
              <span className="flex-1">Media Workspace</span>
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            </button>

            {onNavigateToStudio && (
              <button
                type="button"
                onClick={onNavigateToStudio}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
              >
                <ImageIcon className="w-4 h-4 text-sky-400" />
                <span className="flex-1">Watermark Studio</span>
                <span className="text-[9px] font-black text-slate-500 font-mono">Brand</span>
              </button>
            )}

            {onNavigateToVideoStudio && (
              <button
                type="button"
                onClick={onNavigateToVideoStudio}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
              >
                <Film className="w-4 h-4 text-pink-400" />
                <span className="flex-1">Video Studio</span>
                <span className="text-[9px] font-black px-1 py-0.2 rounded bg-pink-500/20 text-pink-300">
                  9:16
                </span>
              </button>
            )}

            {onNavigateToCompose && (
              <button
                type="button"
                onClick={onNavigateToCompose}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
              >
                <Send className="w-4 h-4 text-emerald-400" />
                <span className="flex-1">Multi-Composer</span>
              </button>
            )}

            <button
              type="button"
              onClick={onNavigateToSettings}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
            >
              <Sliders className="w-4 h-4 text-amber-400" />
              <span className="flex-1">Accounts & Custom Networks</span>
            </button>

            {onNavigateToAnalytics && (
              <button
                type="button"
                onClick={onNavigateToAnalytics}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
              >
                <BarChart3 className="w-4 h-4 text-cyan-400" />
                <span className="flex-1">Analytics & History</span>
              </button>
            )}

            {onNavigateToAI && (
              <button
                type="button"
                onClick={onNavigateToAI}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
              >
                <Bot className="w-4 h-4 text-purple-400" />
                <span className="flex-1">AI Brains & Keys</span>
              </button>
            )}

            {onNavigateToExtension && (
              <button
                type="button"
                onClick={onNavigateToExtension}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
              >
                <Chrome className="w-4 h-4 text-sky-400" />
                <span className="flex-1">Chrome Web Clipper</span>
                <span className="text-[9px] font-black px-1.5 py-0.2 rounded bg-sky-500/20 text-sky-300">
                  Ext
                </span>
              </button>
            )}

            <button
              type="button"
              onClick={() => setShowInstallAppModal(true)}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition text-left"
            >
              <Smartphone className="w-4 h-4 text-emerald-400" />
              <span className="flex-1">Install Desktop/Phone App</span>
              <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300">
                PWA
              </span>
            </button>

            <button
              type="button"
              onClick={onOpenUpgrade}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 transition text-left"
            >
              <Crown className="w-4 h-4 text-amber-400" />
              <span className="flex-1">
                {subscription.plan === 'free' ? 'Upgrade to Pro' : 'Manage Subscription'}
              </span>
              <span className="text-[9px] font-black px-1.5 py-0.2 rounded bg-amber-400 text-slate-950">
                Stripe
              </span>
            </button>
          </div>

          {/* Top Left: User Account Profile Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3.5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Connected Creator Account
              </span>
              <button
                onClick={onNavigateToSettings}
                title="Account Settings & Templates"
                className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
              >
                <Settings className="w-4 h-4" />
              </button>
            </div>

            <div className="flex items-center gap-3">
              <div className="relative">
                <img
                  src="/static/assets/brand/favicon-64.png"
                  alt=""
                  className="w-11 h-11 rounded-full object-cover ring-2 ring-indigo-500/50"
                />
                <span className="absolute bottom-0 right-0 w-3 h-3 bg-emerald-400 border-2 border-slate-900 rounded-full"></span>
              </div>

              <div className="flex-1 min-w-0">
                <h4 className="font-bold text-sm text-white truncate">{siteUser ? `@${siteUser}` : 'Not logged in'}</h4>
                <p className="text-[11px] text-slate-400 truncate">
                  {siteUser ? 'percfectai.com account' : <a href="/login?next=/percfectposts" className="text-indigo-400 hover:underline">Log in to percfectai.com</a>}
                </p>
                <div className="flex items-center gap-1.5 mt-1">
                  <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-gradient-to-r from-amber-500 to-pink-500 text-slate-950 uppercase tracking-wide">
                    {subscription.plan === 'premium'
                      ? 'Premium VIP'
                      : subscription.plan === 'pro'
                      ? 'Creator Pro'
                      : 'Free Tier'}
                  </span>
                  <span className="text-[10px] text-slate-400 font-medium">
                    {platforms.filter((p) => p.connected).length} Networks Configured
                  </span>
                </div>
              </div>
            </div>

            {/* Storage Meter */}
            <div className="bg-slate-950 p-2.5 rounded-xl border border-slate-850 space-y-1.5">
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1">
                  <HardDrive className="w-3 h-3 text-indigo-400" />
                  Media Vault Storage
                </span>
                <span className="text-white font-mono font-semibold">
                  {subscription.storageLabel}
                </span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full"
                  style={{ width: `${Math.min(100, (mediaList.length / 20) * 100)}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* Ask AI Button (High Visibility & Interactive) */}
          <button
            onClick={() => setIsAskAIOpen(true)}
            className="w-full py-3.5 px-4 rounded-2xl bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 hover:brightness-110 text-white font-extrabold text-sm shadow-xl shadow-indigo-600/30 transition transform hover:scale-[1.02] active:scale-[0.98] flex items-center justify-center gap-2.5 group"
          >
            <div className="w-6 h-6 rounded-lg bg-white/20 flex items-center justify-center text-white group-hover:rotate-12 transition">
              <Bot className="w-4 h-4" />
            </div>
            <span>Ask AI Assistant</span>
            <Sparkles className="w-4 h-4 text-amber-300 ml-auto animate-pulse" />
          </button>

          {/* Daily AI Posting Suggestions & Smooth Workflow Engine */}
          <div className="bg-gradient-to-b from-slate-900 to-indigo-950/40 border border-indigo-500/30 rounded-2xl p-3.5 space-y-2.5 shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-black text-indigo-200 flex items-center gap-1.5">
                <Lightbulb className="w-3.5 h-3.5 text-amber-400" />
                Daily AI Suggestion
              </span>
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                Today
              </span>
            </div>
            <p className="text-[11px] text-slate-300 leading-relaxed font-medium">
              "Behind-the-scenes visuals get 3.2x higher comment rates on Tuesdays. Pick a photo, add your watermark logo, and schedule for peak evening engagement."
            </p>
            <button
              onClick={() =>
                openAskAIWithPrompt(
                  'What is the best viral post concept, hook, and caption format for my brand today across X, Instagram, and LinkedIn?'
                )
              }
              className="w-full py-2 px-3 rounded-xl bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-indigo-200 text-[11px] font-bold flex items-center justify-center gap-1.5 transition"
            >
              <Sparkles className="w-3 h-3 text-amber-300" />
              <span>Generate Today's Custom Idea</span>
            </button>
          </div>

          {/* Quick Setup Checklist & "Get Unstuck" AI Assist */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-3.5 space-y-2.5 shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                Smooth Setup Guide
              </span>
              <span className="text-[10px] text-slate-400 font-mono">
                {aiProviders.some((p) => p.isConfigured) && watermarkSettings ? 'Ready' : 'In Progress'}
              </span>
            </div>
            <div className="space-y-1.5 text-[11px]">
              <div className="flex items-center justify-between text-slate-300">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  1. Templates & Accounts
                </span>
                <button
                  onClick={onNavigateToSettings}
                  className="text-indigo-400 hover:underline text-[10px]"
                >
                  Edit
                </button>
              </div>
              <div className="flex items-center justify-between text-slate-300">
                <span className="flex items-center gap-1.5">
                  {aiProviders.some((p) => p.isConfigured) ? (
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  ) : (
                    <span className="w-3 h-3 rounded-full border border-slate-600 inline-block" />
                  )}
                  2. API Keys Vault
                </span>
                <button
                  onClick={() => setIsKeyVaultOpen(true)}
                  className="text-indigo-400 hover:underline text-[10px]"
                >
                  Vault
                </button>
              </div>
              <div className="flex items-center justify-between text-slate-300">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  3. Watermark Logo & Placement
                </span>
                <button
                  onClick={onNavigateToStudio}
                  className="text-indigo-400 hover:underline text-[10px]"
                >
                  Studio
                </button>
              </div>
            </div>

            {/* Stuck Button */}
            <button
              onClick={() =>
                openAskAIWithPrompt(
                  "I'm stuck setting up my social templates, API keys, or watermark logo. Can you help me fix what's missing and get my automated posting running smoothly?"
                )
              }
              className="w-full py-2 px-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-700/70 text-[10px] font-semibold flex items-center justify-center gap-1.5 transition"
            >
              <HelpCircle className="w-3 h-3 text-pink-400" />
              <span>Stuck on anything? Ask AI to Help</span>
            </button>
          </div>

          {/* Quick Media Vault Filters */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-2.5 shadow-md">
            <h5 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center justify-between">
              <span>Vault Navigation</span>
              <span className="text-[10px] text-slate-500">{mediaList.length} items</span>
            </h5>

            <div className="space-y-1 text-xs">
              <button
                onClick={() => {
                  setCenterTab('all');
                  setQuickFilter('all');
                }}
                className={`w-full text-left px-3 py-2 rounded-xl flex items-center justify-between transition ${
                  centerTab === 'all' && quickFilter === 'all'
                    ? 'bg-indigo-600 text-white font-bold'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                <span className="flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5" />
                  All Photos & Videos
                </span>
                <span className="text-[10px] font-mono">{mediaList.length}</span>
              </button>

              <button
                onClick={() => {
                  setCenterTab('photos');
                  setQuickFilter('all');
                }}
                className={`w-full text-left px-3 py-2 rounded-xl flex items-center justify-between transition ${
                  centerTab === 'photos' && quickFilter === 'all'
                    ? 'bg-indigo-600 text-white font-bold'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                <span className="flex items-center gap-2">
                  <Camera className="w-3.5 h-3.5 text-sky-400" />
                  Photos Vault Only
                </span>
                <span className="text-[10px] font-mono">{photosList.length}</span>
              </button>

              <button
                onClick={() => {
                  setCenterTab('videos');
                  setQuickFilter('all');
                }}
                className={`w-full text-left px-3 py-2 rounded-xl flex items-center justify-between transition ${
                  centerTab === 'videos' && quickFilter === 'all'
                    ? 'bg-pink-600 text-white font-bold'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                <span className="flex items-center gap-2">
                  <Film className="w-3.5 h-3.5 text-pink-400" />
                  Videos Vault Only
                </span>
                <span className="text-[10px] font-mono">{videosList.length}</span>
              </button>

              <div className="pt-2 border-t border-slate-800 space-y-1">
                <button
                  onClick={() => setQuickFilter('unposted')}
                  className={`w-full text-left px-3 py-1.5 rounded-lg flex items-center justify-between transition text-[11px] ${
                    quickFilter === 'unposted'
                      ? 'bg-emerald-950 text-emerald-300 font-semibold border border-emerald-500/40'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>✨ Fresh (Unposted)</span>
                  <span className="font-mono">
                    {mediaList.filter((m) => !m.postedNetworks || m.postedNetworks.length === 0).length}
                  </span>
                </button>

                <button
                  onClick={() => setQuickFilter('posted')}
                  className={`w-full text-left px-3 py-1.5 rounded-lg flex items-center justify-between transition text-[11px] ${
                    quickFilter === 'posted'
                      ? 'bg-purple-950 text-purple-300 font-semibold border border-purple-500/40'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>✓ Already Posted</span>
                  <span className="font-mono">
                    {mediaList.filter((m) => m.postedNetworks && m.postedNetworks.length > 0).length}
                  </span>
                </button>
              </div>
            </div>
          </div>

          {/* Quick Shortcuts to Settings & Video Studio */}
          <div className="p-3 bg-slate-900/60 border border-slate-800/80 rounded-2xl space-y-2 text-xs">
            <button
              onClick={onNavigateToSettings}
              className="w-full py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-750 text-slate-200 font-medium flex items-center justify-between transition"
            >
              <span className="flex items-center gap-2">
                <Sliders className="w-3.5 h-3.5 text-indigo-400" />
                Templates & Settings
              </span>
              <span className="text-slate-500">&rarr;</span>
            </button>

            {onNavigateToExtension && (
              <button
                onClick={onNavigateToExtension}
                className="w-full py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-750 text-slate-200 font-medium flex items-center justify-between transition"
              >
                <span className="flex items-center gap-2">
                  <Globe className="w-3.5 h-3.5 text-sky-400" />
                  Chrome Web Clipper
                </span>
                <span className="text-slate-500">&rarr;</span>
              </button>
            )}
          </div>
        </div>

        {/* ========================================================
            MIDDLE COLUMN (5 cols on lg)
            - "The photos go down the middle"
            - "It's gonna be photos and videos two sections"
        ======================================================== */}
        <div className="lg:col-span-5 space-y-4">
          {/* Middle Header Bar: Search & Upload */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex items-center justify-between gap-3">
            <div className="flex-1 min-w-0">
              <input
                type="text"
                placeholder="Search media by title or tags..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex items-center gap-2">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept="image/*,video/*"
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-3 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center gap-1.5 shadow transition"
              >
                <Upload className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Upload</span>
              </button>
            </div>
          </div>

          {/* Section Filter Pills */}
          <div className="flex items-center gap-2 px-1">
            <button
              onClick={() => setCenterTab('all')}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition ${
                centerTab === 'all'
                  ? 'bg-slate-800 text-white border border-slate-700'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Both Sections
            </button>
            <button
              onClick={() => setCenterTab('photos')}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 ${
                centerTab === 'photos'
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Camera className="w-3.5 h-3.5" />
              <span>Photos ({photosList.length})</span>
            </button>
            <button
              onClick={() => setCenterTab('videos')}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 ${
                centerTab === 'videos'
                  ? 'bg-pink-600 text-white shadow'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Film className="w-3.5 h-3.5" />
              <span>Videos ({videosList.length})</span>
            </button>
          </div>

          {/* ==============================================
              SECTION 1: PHOTOS VAULT
          ============================================== */}
          {(centerTab === 'all' || centerTab === 'photos') && (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Camera className="w-4 h-4 text-indigo-400" />
                  <span>Photos Section</span>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">
                    {filteredPhotos.length}
                  </span>
                </h3>
                <span className="text-[10px] text-slate-400">
                  Click to select for right sidebar
                </span>
              </div>

              {filteredPhotos.length === 0 ? (
                <div className="p-8 text-center border-2 border-dashed border-slate-800 rounded-xl text-slate-500 text-xs">
                  No photos found matching your filter.
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-2 gap-3">
                  {filteredPhotos.map((photo) => {
                    const isSelected = activeMedia?.id === photo.id;
                    const hasPosted = photo.postedNetworks && photo.postedNetworks.length > 0;

                    return (
                      <div
                        key={photo.id}
                        onClick={() => onSelectMedia(photo)}
                        className={`group relative rounded-xl overflow-hidden cursor-pointer border transition-all duration-200 aspect-square bg-slate-950 ${
                          isSelected
                            ? 'border-indigo-500 ring-2 ring-indigo-500/50 shadow-lg shadow-indigo-500/20'
                            : 'border-slate-800 hover:border-slate-700'
                        }`}
                      >
                        <img
                          src={photo.watermarkedUrl || photo.url}
                          alt={photo.name}
                          className="w-full h-full object-cover transition duration-300 group-hover:scale-105"
                        />

                        {/* Top Left: Dedicated Selection Checkbox ("in the top left corner you'll have a little box to select that photo or video") */}
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectMedia(photo);
                          }}
                          className={`absolute top-2 left-2 z-10 w-6 h-6 rounded-md flex items-center justify-center transition-all duration-150 shadow-md ${
                            isSelected
                              ? 'bg-indigo-600 text-white ring-2 ring-white/60 shadow-indigo-600/40'
                              : 'bg-black/65 border border-white/40 text-transparent hover:border-white hover:text-white/40 backdrop-blur-sm'
                          }`}
                          title={isSelected ? 'Selected (Active in Right Toolbar)' : 'Click to select this photo'}
                        >
                          <Check className={`w-3.5 h-3.5 stroke-[3] ${isSelected ? 'opacity-100' : 'opacity-0 hover:opacity-100'}`} />
                        </button>

                        {/* Top Right: Social Network Posted Checkmarks ("little check with that color of the social network in top right corner") + AI Tweak */}
                        <div className="absolute top-2 right-2 z-10 flex items-center gap-1">
                          {hasPosted ? (
                            <div className="bg-black/75 backdrop-blur-md rounded-full px-1.5 py-0.5 border border-white/20 shadow-md">
                              <PhotoPostedBadges
                                postedNetworks={photo.postedNetworks}
                                size="xs"
                              />
                            </div>
                          ) : (
                            <span className="text-[8px] font-semibold px-1.5 py-0.5 rounded-full bg-black/70 text-slate-400 border border-slate-700/60 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition">
                              Unposted
                            </span>
                          )}

                          {/* AI Photo Tweak Button */}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setMediaToTweak(photo);
                              setIsTweakerOpen(true);
                            }}
                            className="p-1 rounded-md bg-purple-600/90 hover:bg-purple-500 text-white text-[10px] opacity-0 group-hover:opacity-100 transition shadow flex items-center"
                            title="Tweak photo with AI"
                          >
                            <Wand2 className="w-3 h-3" />
                          </button>
                        </div>

                        {/* Bottom Gradient Overlay */}
                        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/60 to-transparent p-2 flex items-end justify-between">
                          <div className="min-w-0 pr-1">
                            <p className="text-[11px] font-bold text-white truncate">
                              {photo.name}
                            </p>
                            <p className="text-[9px] text-slate-400">
                              {photo.dimensions.width}x{photo.dimensions.height} • {photo.size}
                            </p>
                          </div>
                          {isSelected && (
                            <span className="w-2.5 h-2.5 rounded-full bg-indigo-400 ring-4 ring-indigo-400/30 shrink-0"></span>
                          )}
                        </div>

                        {/* Interactive Buttons Under Photo When Selected */}
                        {isSelected && (
                          <div
                            onClick={(e) => e.stopPropagation()}
                            className="absolute inset-x-0 bottom-0 bg-slate-950/95 backdrop-blur-md p-1.5 border-t border-indigo-500/50 flex flex-col gap-1 z-20 animate-in fade-in"
                          >
                            <div className="flex items-center justify-between text-[10px] text-slate-300 px-1 font-bold">
                              <span className="truncate max-w-[120px]">{photo.name}</span>
                              <span className="text-indigo-400 font-mono text-[9px]">Selected</span>
                            </div>
                            <div className="grid grid-cols-4 gap-1">
                              <button
                                type="button"
                                onClick={() => handleApplyWatermarkToPhoto(photo)}
                                className="p-1 rounded bg-indigo-900/60 hover:bg-indigo-800 text-[9px] font-bold text-indigo-200 flex items-center justify-center gap-0.5 border border-indigo-500/30"
                                title="Add watermark or logo (PRO)"
                              >
                                <Stamp className="w-2.5 h-2.5" />
                                <span>WM</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => handleEditPhoto(photo)}
                                className="p-1 rounded bg-purple-900/60 hover:bg-purple-800 text-[9px] font-bold text-purple-200 flex items-center justify-center gap-0.5 border border-purple-500/30"
                                title="AI Photo Edit (PRO)"
                              >
                                <Wand2 className="w-2.5 h-2.5" />
                                <span>Edit</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => handleUpscalePhoto(photo)}
                                className="p-1 rounded bg-pink-900/60 hover:bg-pink-800 text-[9px] font-bold text-pink-200 flex items-center justify-center gap-0.5 border border-pink-500/30"
                                title="Upscayl 4K AI Super-Resolution (PRO)"
                              >
                                <Maximize2 className="w-2.5 h-2.5" />
                                <span>Upscale</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDownloadPhoto(photo)}
                                className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-[9px] font-bold text-slate-200 flex items-center justify-center gap-0.5 border border-slate-700"
                                title="Download photo"
                              >
                                <Download className="w-2.5 h-2.5" />
                                <span>Save</span>
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Dedicated Under-the-Photo Action Bar for Selected Photo */}
              {activeMedia && activeMedia.type === 'image' && (
                <div className="mt-4 p-3.5 rounded-2xl bg-slate-950 border border-indigo-500/40 shadow-xl space-y-2.5 animate-in fade-in">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <img
                        src={activeMedia.watermarkedUrl || activeMedia.url}
                        alt={activeMedia.name}
                        className="w-10 h-10 rounded-xl object-cover border border-slate-700 shrink-0"
                      />
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-xs font-black text-white truncate max-w-[160px]">
                            {activeMedia.name}
                          </span>
                          {activeMedia.upscaled && (
                            <span className="px-1.5 py-0.5 text-[9px] font-black rounded bg-pink-500/20 text-pink-300 border border-pink-500/30">
                              {activeMedia.scaleFactor || 4}X 4K
                            </span>
                          )}
                          {activeMedia.watermarkedUrl && (
                            <span className="px-1.5 py-0.5 text-[9px] font-black rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                              Watermarked
                            </span>
                          )}
                        </div>
                        <p className="text-[10px] text-slate-400">
                          {activeMedia.dimensions?.width}x{activeMedia.dimensions?.height} • {activeMedia.size}
                        </p>
                      </div>
                    </div>

                    <span className="text-[10px] text-indigo-400 font-bold px-2 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/20 shrink-0">
                      Selected Photo Actions
                    </span>
                  </div>

                  {/* The 4 requested buttons under photo: Add WM or logo, edit, Upscayl (all pro) and download */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 border-t border-slate-850">
                    <button
                      type="button"
                      onClick={() => handleApplyWatermarkToPhoto(activeMedia)}
                      disabled={isWatermarking}
                      className="py-2 px-2.5 rounded-xl bg-indigo-950/70 hover:bg-indigo-900 border border-indigo-500/40 text-indigo-200 text-xs font-bold flex items-center justify-center gap-1.5 transition shadow-sm"
                    >
                      <Stamp className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                      <span className="truncate">Add WM/Logo</span>
                      <span className="text-[9px] font-black px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 shrink-0">
                        PRO
                      </span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleEditPhoto(activeMedia)}
                      className="py-2 px-2.5 rounded-xl bg-purple-950/70 hover:bg-purple-900 border border-purple-500/40 text-purple-200 text-xs font-bold flex items-center justify-center gap-1.5 transition shadow-sm"
                    >
                      <Wand2 className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                      <span className="truncate">Edit</span>
                      <span className="text-[9px] font-black px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 shrink-0">
                        PRO
                      </span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleUpscalePhoto(activeMedia)}
                      className="py-2 px-2.5 rounded-xl bg-pink-950/70 hover:bg-pink-900 border border-pink-500/40 text-pink-200 text-xs font-bold flex items-center justify-center gap-1.5 transition shadow-sm"
                    >
                      <Maximize2 className="w-3.5 h-3.5 text-pink-400 shrink-0" />
                      <span className="truncate">Upscayl</span>
                      <span className="text-[9px] font-black px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 shrink-0">
                        PRO
                      </span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleDownloadPhoto(activeMedia)}
                      className="py-2 px-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-200 text-xs font-bold flex items-center justify-center gap-1.5 transition shadow-sm"
                    >
                      <Download className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                      <span className="truncate">Download</span>
                    </button>
                  </div>

                  {watermarkNotice && (
                    <div className="p-2 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-xs text-emerald-300 flex items-center gap-2 animate-in fade-in">
                      <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span>{watermarkNotice}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ==============================================
              SECTION 2: VIDEOS VAULT
          ============================================== */}
          {(centerTab === 'all' || centerTab === 'videos') && (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Film className="w-4 h-4 text-pink-400" />
                  <span>Videos Section</span>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">
                    {filteredVideos.length}
                  </span>
                </h3>
                {onNavigateToVideoStudio && (
                  <button
                    onClick={onNavigateToVideoStudio}
                    className="text-[11px] text-pink-400 hover:text-pink-300 font-semibold flex items-center gap-1"
                  >
                    <span>9:16 Video Studio &rarr;</span>
                  </button>
                )}
              </div>

              {filteredVideos.length === 0 ? (
                <div className="p-8 text-center border-2 border-dashed border-slate-800 rounded-xl text-slate-500 text-xs">
                  No videos found in vault. Upload one above!
                </div>
              ) : (
                <div className="space-y-3">
                  {filteredVideos.map((video) => {
                    const isSelected = activeMedia?.id === video.id;
                    const hasPosted = video.postedNetworks && video.postedNetworks.length > 0;

                    return (
                      <div
                        key={video.id}
                        onClick={() => onSelectMedia(video)}
                        className={`group relative rounded-xl overflow-hidden cursor-pointer border p-3 bg-slate-950 transition-all duration-200 ${
                          isSelected
                            ? 'border-pink-500 ring-2 ring-pink-500/50 shadow-lg shadow-pink-500/20'
                            : 'border-slate-800 hover:border-slate-700'
                        }`}
                      >
                        <div className="flex gap-3 items-center">
                          {/* Video Thumbnail / Box */}
                          <div className="relative w-28 h-20 rounded-lg overflow-hidden bg-black/60 shrink-0 flex items-center justify-center border border-slate-800">
                            <video
                              src={video.url}
                              className="w-full h-full object-cover"
                              muted
                            />
                            <div className="absolute inset-0 bg-black/30 flex items-center justify-center">
                              <Film className="w-5 h-5 text-white/80" />
                            </div>

                            {/* Top Left: Dedicated Selection Checkbox */}
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onSelectMedia(video);
                              }}
                              className={`absolute top-1.5 left-1.5 z-10 w-5 h-5 rounded flex items-center justify-center transition-all duration-150 shadow-md ${
                                isSelected
                                  ? 'bg-pink-600 text-white ring-1 ring-white/60 shadow-pink-600/40'
                                  : 'bg-black/65 border border-white/40 text-transparent hover:border-white hover:text-white/40 backdrop-blur-sm'
                              }`}
                              title={isSelected ? 'Selected (Active in Right Toolbar)' : 'Click to select this video'}
                            >
                              <Check className={`w-3 h-3 stroke-[3] ${isSelected ? 'opacity-100' : 'opacity-0 hover:opacity-100'}`} />
                            </button>

                            {/* Top Right: Social Network Posted Checkmarks */}
                            <div className="absolute top-1.5 right-1.5 z-10">
                              {hasPosted && (
                                <div className="bg-black/75 backdrop-blur-md rounded-full px-1 py-0.5 border border-white/20 shadow-md">
                                  <PhotoPostedBadges
                                    postedNetworks={video.postedNetworks}
                                    size="xs"
                                  />
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Info */}
                          <div className="flex-1 min-w-0 space-y-1">
                            <div className="flex items-center justify-between">
                              <h4 className="text-xs font-bold text-white truncate">
                                {video.name}
                              </h4>
                              {isSelected && (
                                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-pink-500/20 text-pink-300 border border-pink-500/30">
                                  Active Media
                                </span>
                              )}
                            </div>
                            <p className="text-[11px] text-slate-400">
                              {video.size} • 9:16 Vertical Ready
                            </p>

                            <div className="flex items-center gap-2 pt-1">
                              {onNavigateToVideoStudio && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onSelectMedia(video);
                                    onNavigateToVideoStudio();
                                  }}
                                  className="px-2 py-1 rounded bg-pink-900/60 hover:bg-pink-800/80 text-pink-300 text-[10px] font-bold border border-pink-700/50 transition flex items-center gap-1"
                                >
                                  <span>Reformat in Video Studio</span>
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ========================================================
            RIGHT SIDEBAR ("LITTLE SIDE ROAD ON THE RIGHT", 4 cols on lg)
            - 1. Top: TAGS
            - 2. Middle: DESCRIPTION (with Wand2 button to write/rewrite)
            - 3. Social Networks with COLORED TOGGLE SWITCHES
            - 4. Mass Post Button
        ======================================================== */}
        <div className="lg:col-span-4 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-2xl space-y-5">
            {/* Active Selected Media Header Banner */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <span className="text-xs font-extrabold text-white">Publishing Composer</span>
                <span className="text-[10px] font-bold text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
                  {selectedPlatforms.length} Networks ON
                </span>
              </div>
              {activeMedia && (
                <span className="text-[10px] text-slate-400 truncate max-w-[120px]">
                  {activeMedia.name}
                </span>
              )}
            </div>

            {/* ========================================================
                1. TOP: TAGS ("above that his tags")
            ======================================================== */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-extrabold text-white flex items-center gap-1.5">
                  <Hash className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Tags & Hashtags</span>
                </label>

                {/* AI Suggest Tags Button */}
                <button
                  onClick={handleSuggestTags}
                  disabled={isSuggestingTags}
                  className="text-[10px] font-bold text-indigo-400 hover:text-indigo-300 flex items-center gap-1 transition"
                  title="Generate trending tags with AI"
                >
                  {isSuggestingTags ? (
                    <Zap className="w-3 h-3 animate-spin" />
                  ) : (
                    <Sparkles className="w-3 h-3 text-amber-400" />
                  )}
                  <span>AI Suggest Tags</span>
                </button>
              </div>

              {/* Tag Chips Container */}
              <div className="flex flex-wrap gap-1.5 min-h-[38px] p-2 rounded-xl bg-slate-950 border border-slate-800">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-indigo-950/80 text-indigo-200 border border-indigo-500/40 text-[11px] font-semibold group"
                  >
                    <span>#{tag}</span>
                    <button
                      onClick={() => handleRemoveTag(tag)}
                      className="text-indigo-400 hover:text-rose-400 transition"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}

                {tags.length === 0 && (
                  <span className="text-[11px] text-slate-500 italic py-0.5">
                    No tags added yet. Type below or click AI Suggest.
                  </span>
                )}
              </div>

              {/* Add Custom Tag Input */}
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={newTagInput}
                  onChange={(e) => setNewTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleAddTag();
                  }}
                  placeholder="Add custom tag (e.g. CreatorEconomy)..."
                  className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
                <button
                  onClick={handleAddTag}
                  disabled={!newTagInput.trim()}
                  className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 transition"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* ========================================================
                2. MIDDLE: DESCRIPTION & WAND BUTTON
                ("above it is description above that his tags, and it will also
                have the little wand button for AI to write it for you.
                Or help you rewrite whatever you wrote already in the prop box")
            ======================================================== */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-extrabold text-white flex items-center gap-1.5">
                  <span>Description & Caption</span>
                </label>

                {/* THE WAND BUTTON FOR AI WRITE / REWRITE */}
                <div className="relative">
                  <button
                    onClick={() => setIsWandMenuOpen((prev) => !prev)}
                    disabled={isGeneratingCopy}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:brightness-110 text-white font-bold text-[11px] shadow-sm transition"
                    title="Write or rewrite caption with AI"
                  >
                    {isGeneratingCopy ? (
                      <Zap className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Wand2 className="w-3.5 h-3.5 text-amber-300" />
                    )}
                    <span>{isGeneratingCopy ? 'AI Writing...' : 'AI Magic Wand'}</span>
                    <ChevronDown className="w-3 h-3" />
                  </button>

                  {/* Wand Dropdown Menu */}
                  {isWandMenuOpen && (
                    <div className="absolute right-0 top-full mt-1.5 w-64 bg-slate-950 border border-slate-700 rounded-xl shadow-2xl p-1.5 z-40 space-y-1 animate-in fade-in zoom-in-95 duration-150">
                      <div className="px-2 py-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-800">
                        AI Copy Generator
                      </div>

                      <button
                        onClick={() => handleWandAction('write')}
                        className="w-full text-left p-2 rounded-lg hover:bg-slate-800/80 text-xs text-slate-200 hover:text-white flex items-center gap-2 transition"
                      >
                        <Sparkles className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <div>
                          <div className="font-semibold">Write Description for Me</div>
                          <div className="text-[10px] text-slate-400">
                            Creates new copy based on photo & tags
                          </div>
                        </div>
                      </button>

                      <button
                        onClick={() => handleWandAction('rewrite')}
                        className="w-full text-left p-2 rounded-lg hover:bg-slate-800/80 text-xs text-slate-200 hover:text-white flex items-center gap-2 transition"
                      >
                        <RefreshCw className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                        <div>
                          <div className="font-semibold">Rewrite Whatever I Wrote</div>
                          <div className="text-[10px] text-slate-400">
                            Enhance & polish current text in box
                          </div>
                        </div>
                      </button>

                      <button
                        onClick={() => handleWandAction('punchy')}
                        className="w-full text-left p-2 rounded-lg hover:bg-slate-800/80 text-xs text-slate-200 hover:text-white flex items-center gap-2 transition"
                      >
                        <Zap className="w-3.5 h-3.5 text-pink-400 shrink-0" />
                        <div>
                          <div className="font-semibold">Make Punchier & Viral</div>
                          <div className="text-[10px] text-slate-400">
                            Short curiosity hook for X & TikTok
                          </div>
                        </div>
                      </button>

                      <button
                        onClick={() => handleWandAction('linkedin')}
                        className="w-full text-left p-2 rounded-lg hover:bg-slate-800/80 text-xs text-slate-200 hover:text-white flex items-center gap-2 transition"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                        <div>
                          <div className="font-semibold">Make Professional (LinkedIn)</div>
                          <div className="text-[10px] text-slate-400">
                            Clean formatting & business takeaway
                          </div>
                        </div>
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Description Prompt Box */}
              <div className="relative">
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Enter caption or notes... Or click the Wand button above to let AI write or rewrite it for you!"
                  rows={4}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none leading-relaxed"
                />

                <div className="flex items-center justify-between text-[10px] text-slate-400 px-1 mt-1">
                  <span>{description.length} characters</span>
                  <span>Twitter Limit: 280</span>
                </div>

                {/* Mandatory Attribution Notice for Free Users */}
                {(isFree || subscription.mandatoryAttribution) && (
                  <div className="mt-2.5 p-2.5 rounded-xl bg-amber-950/40 border border-amber-500/30 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 text-amber-300 text-[11px] font-bold">
                        <Lock className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <span>Mandatory Attribution (Free Tier)</span>
                      </div>
                      <button
                        type="button"
                        onClick={onOpenUpgrade}
                        className="text-[9px] font-black px-2 py-0.5 rounded bg-amber-500 hover:bg-amber-400 text-slate-950 transition"
                      >
                        Remove with Pro
                      </button>
                    </div>
                    <div className="bg-slate-950/90 p-2 rounded-lg border border-slate-800 text-[11px] text-slate-300 font-mono flex items-center justify-between">
                      <span className="text-amber-300 font-semibold">⚡ Streamlined with Perfect Posts - https://perfectposts.app</span>
                      <span className="text-[9px] text-slate-400 shrink-0 ml-2">Auto-Appended</span>
                    </div>
                    <p className="text-[10px] text-slate-400 leading-tight">
                      Free tier posts must include our trademark logo & description attribution. Upgrade to Pro or Premium to remove this.
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* ========================================================
                3. BELOW DESCRIPTION: SOCIAL MEDIA TOGGLE SWITCHES
                ("There should be a spot on the right for a little toggle switches
                for that social media which is colored in the way you wanted it")
            ======================================================== */}
            <div className="space-y-2.5 pt-2 border-t border-slate-800">
              <div className="flex items-center justify-between">
                <div>
                  <label className="text-xs font-extrabold text-white block">
                    Social Networks Distribution
                  </label>
                  <span className="text-[10px] text-slate-400">
                    {isFree && `Free Plan: max 2 active (${selectedPlatforms.length}/2)`}
                    {isPro && `Pro Plan: max 5 active (${selectedPlatforms.length}/5)`}
                    {isPremium && `Premium Plan: unlimited active (${selectedPlatforms.length} active)`}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {!isPremium && (
                    <button
                      type="button"
                      onClick={onOpenUpgrade}
                      className="text-[10px] text-amber-400 hover:underline font-bold"
                    >
                      Unlock More
                    </button>
                  )}
                  <button
                    onClick={onNavigateToSettings}
                    className="text-[10px] text-indigo-400 hover:underline flex items-center gap-1 font-semibold"
                  >
                    <span>Custom Networks</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </button>
                </div>
              </div>

              {networkLimitNotice && (
                <div className="p-2.5 rounded-xl bg-rose-950/60 border border-rose-500/40 text-[11px] text-rose-200 flex items-center justify-between gap-2 animate-in fade-in">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <Lock className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                    <span className="truncate">{networkLimitNotice}</span>
                  </div>
                  <button
                    onClick={onOpenUpgrade}
                    className="px-2 py-0.5 rounded bg-rose-500 hover:bg-rose-400 text-white font-bold text-[10px] shrink-0"
                  >
                    Upgrade
                  </button>
                </div>
              )}

              {/* List of platforms with signature colored toggle switches */}
              <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
                {platforms.map((p) => {
                  const platformKey = p.id;
                  const visual = getPlatformVisual(platformKey, platforms);
                  const isToggled = activeNetworkToggles[platformKey] || false;
                  const isPostedOnCurrentMedia =
                    activeMedia?.postedNetworks?.includes(platformKey) || false;

                  return (
                    <div
                      key={platformKey}
                      className={`flex items-center justify-between p-2.5 rounded-xl border transition-all duration-150 ${
                        isToggled
                          ? 'bg-slate-950 border-slate-700 shadow-sm'
                          : 'bg-slate-950/40 border-slate-850 opacity-60'
                      }`}
                    >
                      {/* Left: Platform Icon & Name & Checkmark */}
                      <div className="flex items-center gap-2.5 min-w-0">
                        {/* Signature Platform Badge */}
                        <div
                          style={{ backgroundColor: visual.accentColor }}
                          className="w-6 h-6 rounded-lg text-white flex items-center justify-center text-[10px] font-black shrink-0 shadow-sm border border-white/20"
                        >
                          {visual.shortLabel}
                        </div>

                        <div className="min-w-0">
                          <div className="text-xs font-bold text-white flex items-center gap-1.5">
                            <span>{p.name}</span>
                            {p.isCustom && (
                              <span className="text-[9px] px-1 py-0.2 rounded bg-indigo-500/20 text-indigo-300 font-mono">
                                Custom
                              </span>
                            )}
                            {isPostedOnCurrentMedia && (
                              <span className="text-[9px] font-bold px-1 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-0.5">
                                <Check className="w-2.5 h-2.5" />
                                Posted
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] text-slate-400 truncate">
                            {p.accountHandle || 'Not linked'}
                          </div>
                        </div>
                      </div>

                      {/* Right: Signature Brand-Colored Toggle Switch */}
                      <button
                        type="button"
                        onClick={() => handleToggleNetwork(platformKey)}
                        className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none"
                        style={{
                          backgroundColor: isToggled
                            ? visual.accentColor || '#6366f1'
                            : '#334155',
                        }}
                      >
                        <span
                          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                            isToggled ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>
                  );
                })}
              </div>

              {/* Link to Settings & Templates */}
              <div className="pt-2 text-center">
                <button
                  onClick={onNavigateToSettings}
                  className="text-[11px] text-slate-400 hover:text-indigo-300 font-medium transition"
                >
                  Configure Handles, Advanced Settings & Custom Networks in Settings &rarr;
                </button>
              </div>
            </div>

            {/* Status Notice */}
            {postSuccessNotice && (
              <div className="p-3 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-xs text-emerald-300 flex items-center gap-2 animate-in fade-in">
                <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>{postSuccessNotice}</span>
              </div>
            )}

            {/* ========================================================
                4. BIG POST BUTTON
            ======================================================== */}
            <button
              onClick={handleMassPost}
              disabled={selectedPlatforms.length === 0}
              className="w-full py-4 px-5 rounded-2xl bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-700 hover:brightness-110 text-white font-black text-sm sm:text-base shadow-xl shadow-indigo-600/30 transition transform hover:scale-[1.01] active:scale-[0.99] flex items-center justify-center gap-2.5 disabled:opacity-40"
            >
              <Send className="w-5 h-5" />
              <span>Post Now to {selectedPlatforms.length} Selected Networks</span>
            </button>

            {/* ========================================================
                5. SCHEDULE BUTTON DIRECTLY UNDER POST BUTTON
            ======================================================== */}
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setIsSchedulingOpen((prev) => !prev)}
                className="w-full py-3 px-4 rounded-xl bg-slate-950 hover:bg-slate-850 border border-slate-800 hover:border-slate-700 text-slate-200 hover:text-white font-bold text-xs flex items-center justify-center gap-2 transition shadow-sm"
              >
                <Calendar className="w-4 h-4 text-indigo-400" />
                <span>Schedule Post for Later</span>
                <ChevronDown
                  className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ${
                    isSchedulingOpen ? 'rotate-180' : ''
                  }`}
                />
              </button>

              {isSchedulingOpen && (
                <div className="p-4 rounded-2xl bg-slate-950 border border-indigo-500/40 shadow-xl space-y-3 animate-in fade-in zoom-in-95">
                  <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                    <span className="text-xs font-extrabold text-white flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5 text-indigo-400" />
                      <span>Pick Schedule Time</span>
                    </span>
                    <span className="text-[10px] text-indigo-300 font-mono">
                      Auto-Queue
                    </span>
                  </div>

                  <div>
                    <label className="text-[11px] text-slate-400 block mb-1">
                      Date & Time (Local Time)
                    </label>
                    <input
                      type="datetime-local"
                      value={scheduledDateTime}
                      onChange={(e) => setScheduledDateTime(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  {/* Suggested Peak Hours */}
                  <div className="space-y-1.5">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                      Suggested Peak Engagement Times:
                    </span>
                    <div className="grid grid-cols-1 gap-1.5">
                      {[
                        { label: 'Tonight @ 7:00 PM (Peak Reach)', hoursAhead: 3 },
                        { label: 'Tomorrow @ 9:00 AM (Morning Rush)', hoursAhead: 18 },
                        { label: 'This Weekend @ 11:00 AM (High CTR)', hoursAhead: 48 },
                      ].map((preset, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => {
                            const d = new Date(Date.now() + preset.hoursAhead * 3600 * 1000);
                            setScheduledDateTime(d.toISOString().slice(0, 16));
                          }}
                          className="w-full text-left px-2.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-850 text-slate-300 text-[11px] border border-slate-800 flex items-center justify-between transition"
                        >
                          <span>{preset.label}</span>
                          <Sparkles className="w-3 h-3 text-amber-400" />
                        </button>
                      ))}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={handleSchedulePost}
                    disabled={selectedPlatforms.length === 0}
                    className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold flex items-center justify-center gap-2 shadow-lg shadow-indigo-600/25 transition disabled:opacity-40"
                  >
                    <Check className="w-3.5 h-3.5" />
                    <span>Confirm & Schedule for {selectedPlatforms.length} Networks</span>
                  </button>
                </div>
              )}
            </div>

            {/* ========================================================
                6. BOTTOM RIGHT: ANALYTICS, TEMPLATES, AI, LOCKED VAULT & WATERMARK/LOGO
                "Bottom right will have the analytics option the templates option and the AI option and perhaps a little vault button with your locked API keys for everything and then a make a watermark or logo also, all of these besides, the APIs should be pro features"
            ======================================================== */}
            <div className="mt-4 pt-3 border-t border-slate-800 space-y-2">
              <div className="flex items-center justify-between px-1">
                <span className="text-[11px] font-black text-slate-300 uppercase tracking-wider flex items-center gap-1">
                  <Sparkles className="w-3 h-3 text-indigo-400" />
                  Bottom Right Command Hub
                </span>
                <span className="text-[10px] text-slate-500 font-medium">Quick Pro Toolkit</span>
              </div>

              <div className="grid grid-cols-1 gap-2">
                {/* Option 1: Analytics (PRO) */}
                <button
                  type="button"
                  onClick={handleOpenAnalytics}
                  className="w-full text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-850 border border-slate-800/90 hover:border-slate-700 transition flex items-center justify-between group"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 group-hover:scale-105 transition">
                      <BarChart3 className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-white group-hover:text-emerald-300 transition">
                        Analytics & Performance
                      </div>
                      <div className="text-[10px] text-slate-400">
                        Impressions, CTR & viral reach metrics
                      </div>
                    </div>
                  </div>
                  <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[9px] font-black border border-amber-500/30 flex items-center gap-0.5">
                    <Crown className="w-2.5 h-2.5" />
                    PRO
                  </span>
                </button>

                {/* Option 2: Templates (PRO) */}
                <button
                  type="button"
                  onClick={handleOpenTemplates}
                  className="w-full text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-850 border border-slate-800/90 hover:border-slate-700 transition flex items-center justify-between group"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 group-hover:scale-105 transition">
                      <LayoutTemplate className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-white group-hover:text-indigo-300 transition">
                        Social Network Templates
                      </div>
                      <div className="text-[10px] text-slate-400">
                        Platform presets, handles & tag syntax
                      </div>
                    </div>
                  </div>
                  <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[9px] font-black border border-amber-500/30 flex items-center gap-0.5">
                    <Crown className="w-2.5 h-2.5" />
                    PRO
                  </span>
                </button>

                {/* Option 3: AI Option (PRO) */}
                <button
                  type="button"
                  onClick={handleOpenAI}
                  className="w-full text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-850 border border-slate-800/90 hover:border-slate-700 transition flex items-center justify-between group"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400 group-hover:scale-105 transition">
                      <Bot className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-white group-hover:text-purple-300 transition">
                        AI Brains & Strategist
                      </div>
                      <div className="text-[10px] text-slate-400">
                        Multi-model deep research & copywriting
                      </div>
                    </div>
                  </div>
                  <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[9px] font-black border border-amber-500/30 flex items-center gap-0.5">
                    <Crown className="w-2.5 h-2.5" />
                    PRO
                  </span>
                </button>

                {/* Option 4: Locked API Keys Vault (FREE / UNGATED FOR EVERYONE) */}
                <button
                  type="button"
                  onClick={handleOpenKeyVault}
                  className="w-full text-left p-2.5 rounded-xl bg-slate-950/90 hover:bg-slate-850 border border-emerald-500/30 hover:border-emerald-500/60 transition flex items-center justify-between group shadow-sm"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400 group-hover:scale-105 transition">
                      <KeyRound className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-white flex items-center gap-1.5 group-hover:text-emerald-300 transition">
                        <span>Locked API Keys Vault</span>
                        <Lock className="w-3 h-3 text-emerald-400" />
                      </div>
                      <div className="text-[10px] text-slate-400">
                        Locked local keys: Gemini, OpenAI, Claude, Grok
                      </div>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-[9px] font-extrabold border border-emerald-500/30 flex items-center gap-1">
                    <ShieldCheck className="w-2.5 h-2.5 text-emerald-400" />
                    Free Vault
                  </span>
                </button>

                {/* Option 5: Make a Watermark or Logo (PRO) */}
                <button
                  type="button"
                  onClick={handleMakeWatermarkOrLogo}
                  className="w-full text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-850 border border-slate-800/90 hover:border-slate-700 transition flex items-center justify-between group"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-pink-500/10 border border-pink-500/20 flex items-center justify-center text-pink-400 group-hover:scale-105 transition">
                      <Stamp className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-white group-hover:text-pink-300 transition">
                        Make a Watermark or Logo
                      </div>
                      <div className="text-[10px] text-slate-400">
                        Brand studio, signature stamps & PNG logos
                      </div>
                    </div>
                  </div>
                  <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[9px] font-black border border-amber-500/30 flex items-center gap-0.5">
                    <Crown className="w-2.5 h-2.5" />
                    PRO
                  </span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Interactive Ask AI Assistant Modal */}
      <AskAIModal
        isOpen={isAskAIOpen}
        onClose={() => {
          setIsAskAIOpen(false);
          setAiModalInitialPrompt('');
        }}
        initialPrompt={aiModalInitialPrompt}
        onApplyTextToDescription={(text) => setDescription(text)}
        selectedMediaName={activeMedia?.name}
        currentDescription={description}
        activeTags={tags}
        subscription={subscription}
      />

      {/* AI Photo Tweaker Modal */}
      {mediaToTweak && (
        <AIPhotoTweakerModal
          isOpen={isTweakerOpen}
          onClose={() => {
            setIsTweakerOpen(false);
            setMediaToTweak(null);
          }}
          photo={mediaToTweak}
          aiProviders={aiProviders}
          onUpdateProviderKey={onUpdateProviderKey || (() => {})}
          onSaveTweakedPhoto={(newMedia) => {
            onAddMedia(newMedia);
            onSelectMedia(newMedia);
            setIsTweakerOpen(false);
          }}
          onSendToCompose={() => {
            setIsTweakerOpen(false);
          }}
          subscription={subscription}
          onOpenUpgrade={onOpenUpgrade}
        />
      )}

      {/* Upscale 4K AI Modal */}
      <UpscalePhotoModal
        isOpen={isUpscaleOpen}
        onClose={() => {
          setIsUpscaleOpen(false);
          setMediaToUpscale(null);
        }}
        photo={mediaToUpscale}
        onSaveUpscaled={(newMedia) => {
          onUpdateMedia(newMedia);
          onSelectMedia(newMedia);
          setIsUpscaleOpen(false);
          setWatermarkNotice(`4K Ultra-HD Upscale saved to your vault!`);
          setTimeout(() => setWatermarkNotice(null), 4000);
        }}
        subscription={subscription}
        onOpenUpgrade={onOpenUpgrade}
      />

      {/* API Key Vault Modal */}
      <APIKeyVaultModal
        isOpen={isKeyVaultOpen}
        onClose={() => setIsKeyVaultOpen(false)}
        aiProviders={aiProviders}
        onUpdateProviderKey={onUpdateProviderKey || (() => {})}
      />

      {/* Standalone Native App Installation Modal (PWA) */}
      {showInstallAppModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg p-6 space-y-5 shadow-2xl relative">
            <button
              onClick={() => setShowInstallAppModal(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
            >
              <X className="w-5 h-5" />
            </button>

            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center text-white shadow-lg">
                <Smartphone className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">
                  Install "The Percfect Post" App
                </h3>
                <p className="text-xs text-slate-400">
                  Run standalone with zero browser tabs, full-screen speed, and offline capability.
                </p>
              </div>
            </div>

            <div className="space-y-3 text-xs">
              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
                <div className="flex items-center justify-between text-indigo-400 font-bold">
                  <span>💻 Google Chrome & Microsoft Edge (Desktop)</span>
                  <span className="text-[10px] bg-indigo-500/20 px-2 py-0.5 rounded text-indigo-300">1-Click</span>
                </div>
                <p className="text-slate-300 text-[11px] leading-relaxed">
                  Look in the top-right of your browser's address bar for the <strong>Install App icon (computer with down arrow)</strong>. Click it and select <strong>Install</strong>.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
                <div className="flex items-center justify-between text-sky-400 font-bold">
                  <span>📱 Apple iPhone & iPad (Safari iOS)</span>
                  <span className="text-[10px] bg-sky-500/20 px-2 py-0.5 rounded text-sky-300">iOS Native</span>
                </div>
                <p className="text-slate-300 text-[11px] leading-relaxed">
                  Tap the <strong>Share button (square with arrow up)</strong> at the bottom of Safari, scroll down, and tap <strong>"Add to Home Screen"</strong>.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
                <div className="flex items-center justify-between text-emerald-400 font-bold">
                  <span>🤖 Android (Chrome Browser)</span>
                  <span className="text-[10px] bg-emerald-500/20 px-2 py-0.5 rounded text-emerald-300">APK Style</span>
                </div>
                <p className="text-slate-300 text-[11px] leading-relaxed">
                  Tap the <strong>three dots (⋮)</strong> menu in Chrome, then tap <strong>"Install app"</strong> or <strong>"Add to Home screen"</strong>.
                </p>
              </div>
            </div>

            <div className="pt-2 flex items-center justify-between border-t border-slate-800 text-xs">
              <span className="text-slate-400 text-[11px]">
                Web Manifest & Service Worker Active
              </span>
              <button
                type="button"
                onClick={() => setShowInstallAppModal(false)}
                className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs transition"
              >
                Got It, Thanks!
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
