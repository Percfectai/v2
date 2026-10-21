import React, { useState, useEffect } from 'react';
import { Header } from './components/Header.tsx';
import { Navigation, ActiveTab } from './components/Navigation.tsx';
import { MainMediaWorkspaceView } from './components/MainMediaWorkspaceView.tsx';
import { ComposeView } from './components/ComposeView.tsx';
import { MediaStudioView } from './components/MediaStudioView.tsx';
import { VideoStudioView } from './components/VideoStudioView.tsx';
import { PlatformTemplatesView } from './components/PlatformTemplatesView.tsx';
import { AIChatProviderView } from './components/AIChatProviderView.tsx';
import { HistoryAnalyticsView } from './components/HistoryAnalyticsView.tsx';
import { ChromeExtensionView } from './components/ChromeExtensionView.tsx';
import { UpgradeModal } from './components/UpgradeModal.tsx';
import {
  INITIAL_PLATFORMS,
  INITIAL_TEMPLATES,
  INITIAL_MEDIA,
  DEFAULT_WATERMARK_SETTINGS,
  INITIAL_AI_PROVIDERS,
  INITIAL_POSTS,
  INITIAL_USER_SUBSCRIPTION,
} from './data/initialData.ts';
import {
  PlatformConfig,
  SocialTemplate,
  MediaItem,
  WatermarkSettings,
  AIProviderInfo,
  AIProvider,
  PostItem,
  UserSubscription,
  PlanTier,
  SocialPlatform,
} from './types.ts';

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('media');

  // Freemium subscription state
  const [subscription, setSubscription] = useState<UserSubscription>(
    INITIAL_USER_SUBSCRIPTION
  );
  const [isUpgradeModalOpen, setIsUpgradeModalOpen] = useState(false);

  // Core app state
  const [platforms, setPlatforms] = useState<PlatformConfig[]>(INITIAL_PLATFORMS);
  const [templates, setTemplates] = useState<SocialTemplate[]>(INITIAL_TEMPLATES);
  const [mediaList, setMediaList] = useState<MediaItem[]>(INITIAL_MEDIA);
  const [activeMedia, setActiveMedia] = useState<MediaItem | null>(INITIAL_MEDIA[0]);
  const [selectedMediaUrl, setSelectedMediaUrl] = useState<string>(INITIAL_MEDIA[0].url);
  const [watermarkSettings, setWatermarkSettings] = useState<WatermarkSettings>(
    DEFAULT_WATERMARK_SETTINGS
  );
  const [aiProviders, setAiProviders] = useState<AIProviderInfo[]>(INITIAL_AI_PROVIDERS);
  const [activeAIProvider, setActiveAIProvider] = useState<AIProvider>('gemini');
  const [posts, setPosts] = useState<PostItem[]>(INITIAL_POSTS);
  const [composeTopicDraft, setComposeTopicDraft] = useState<string>('');

  // Handle plan upgrade / selection
  const handleSelectPlan = (plan: PlanTier) => {
    if (plan === 'free') {
      setSubscription({
        plan: 'free',
        postsRemaining: 99999,
        monthlyPostLimit: 99999,
        unlimitedPosts: true,
        maxNetworks: 2,
        maxUpscaleMP: 0,
        mandatoryAttribution: true,
        customWatermarkUnlocked: false,
        highThinkingUnlocked: false,
        connectedAccountsLimit: 2,
        extensionAutoSync: true,
        storageUsedBytes: 194000000,
        storageLimitBytes: 1024 * 1024 * 1024,
        storageLabel: '185 MB / 1 GB',
        videoUnlocked: false,
        videoStitchingUnlocked: false,
        aiImageEditingUnlocked: false,
        analyticsUnlocked: false,
      });
    } else if (plan === 'pro') {
      setSubscription({
        plan: 'pro',
        postsRemaining: 99999,
        monthlyPostLimit: 99999,
        unlimitedPosts: true,
        maxNetworks: 5,
        maxUpscaleMP: 5,
        mandatoryAttribution: false,
        customWatermarkUnlocked: true,
        highThinkingUnlocked: true,
        connectedAccountsLimit: 5,
        extensionAutoSync: true,
        storageUsedBytes: 194000000,
        storageLimitBytes: 100 * 1024 * 1024 * 1024,
        storageLabel: '185 MB / 100 GB',
        videoUnlocked: false,
        videoStitchingUnlocked: false,
        aiImageEditingUnlocked: true,
        analyticsUnlocked: true,
      });
    } else {
      // premium
      setSubscription({
        plan: 'premium',
        postsRemaining: 99999,
        monthlyPostLimit: 99999,
        unlimitedPosts: true,
        maxNetworks: 999,
        maxUpscaleMP: 10,
        mandatoryAttribution: false,
        customWatermarkUnlocked: true,
        highThinkingUnlocked: true,
        connectedAccountsLimit: 999,
        extensionAutoSync: true,
        storageUsedBytes: 194000000,
        storageLimitBytes: 1024 * 1024 * 1024 * 1024,
        storageLabel: '185 MB / 1 TB (Enterprise Vault)',
        videoUnlocked: true,
        videoStitchingUnlocked: true,
        aiImageEditingUnlocked: true,
        analyticsUnlocked: true,
      });
    }
  };

  // Pull the user's socials (Settings) and library from percfectai.com.
  useEffect(() => {
    const handleOf = (raw: string) => {
      const v = raw.trim().replace(/\/+$/, '');
      if (!v.startsWith('http')) return v.startsWith('@') ? v : `@${v}`;
      const last = v.split('/').pop() || v;
      return last.startsWith('@') ? last : `@${last}`;
    };
    fetch('/api/percfectposts/site-profile', { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((data) => {
        const socials: Record<string, string> = data?.socials || {};
        setPlatforms((prev) =>
          prev.map((p) => {
            const raw = socials[p.id];
            return raw ? { ...p, accountHandle: handleOf(raw), connected: true } : p;
          })
        );
      })
      .catch(() => {});

    fetch('/api/my-library', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        const now = new Date().toISOString();
        const toItem = (x: any, kind: string, type: 'image' | 'video'): MediaItem | null => {
          const url = x.url || x.primary_image_url;
          if (!url) return null;
          return {
            id: `${kind}-${x.id}`,
            name: x.name || kind,
            url,
            type,
            dimensions: { width: 1024, height: 1024 },
            size: '',
            timestamp: x.created_at || now,
            postedNetworks: [],
          };
        };
        const items = [
          ...(data.characters || []).map((x: any) => toItem(x, 'character', 'image')),
          ...(data.photos || []).map((x: any) => toItem(x, 'photo', 'image')),
          ...(data.videos || []).map((x: any) => toItem(x, 'video', 'video')),
          ...(data.backgrounds || []).map((x: any) => toItem(x, 'background', 'image')),
        ].filter(Boolean) as MediaItem[];
        if (!items.length) return;
        setMediaList(items);
        setActiveMedia(items[0]);
        setSelectedMediaUrl(items[0].url);
      })
      .catch(() => {});
  }, []);

  // Deep-link handler from Chrome Extension
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const action = params.get('action');
      const mediaUrl = params.get('mediaUrl');
      const mediaType = params.get('type') || 'image';

      if (action === 'ai-tweak' && mediaUrl) {
        const item: MediaItem = {
          id: `ext-param-${Date.now()}`,
          name: 'Clipped Web Asset',
          url: mediaUrl,
          type: 'image',
          dimensions: { width: 1200, height: 800 },
          size: '1.5 MB',
          timestamp: new Date().toISOString(),
          postedNetworks: [],
        };
        setMediaList((prev) => [item, ...prev]);
        setActiveMedia(item);
        setSelectedMediaUrl(item.url);
        setActiveTab('studio');
      } else if (action === 'video-studio') {
        setActiveTab('video');
      } else if (action === 'clip' && mediaUrl) {
        const item: MediaItem = {
          id: `ext-param-${Date.now()}`,
          name: mediaType === 'video' ? 'Clipped Web Video' : 'Clipped Web Photo',
          url: mediaUrl,
          type: mediaType === 'video' ? 'video' : 'image',
          dimensions: { width: 1920, height: 1080 },
          size: '2.0 MB',
          timestamp: new Date().toISOString(),
          postedNetworks: [],
        };
        setMediaList((prev) => [item, ...prev]);
        setActiveMedia(item);
        setSelectedMediaUrl(item.url);
        setActiveTab(mediaType === 'video' ? 'video' : 'studio');
      }
    } catch {
      // ignore
    }
  }, []);

  // Media handlers
  const handleAddMedia = (item: MediaItem) => {
    setMediaList((prev) => [item, ...prev]);
  };

  const handleUpdateMedia = (updatedItem: MediaItem) => {
    setMediaList((prev) =>
      prev.map((item) => (item.id === updatedItem.id ? updatedItem : item))
    );
    if (activeMedia?.id === updatedItem.id) {
      setActiveMedia(updatedItem);
    }
  };

  const handleDeleteMedia = (id: string) => {
    setMediaList((prev) => prev.filter((m) => m.id !== id));
    if (activeMedia?.id === id) {
      setActiveMedia(mediaList[0] || null);
    }
  };

  const handleSendToCompose = (mediaUrl: string) => {
    setSelectedMediaUrl(mediaUrl);
    setActiveTab('compose');
  };

  // Platform & Template Handlers
  const handleUpdatePlatform = (updated: PlatformConfig) => {
    setPlatforms((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
  };

  const handleUpdateTemplate = (updated: SocialTemplate) => {
    setTemplates((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
  };

  const handleCreateTemplate = (tpl: SocialTemplate) => {
    setTemplates((prev) => [...prev, tpl]);
  };

  const handleDeleteTemplate = (id: string) => {
    setTemplates((prev) => prev.filter((t) => t.id !== id));
  };

  const handleAddPlatform = (newPlatform: PlatformConfig, initialTemplate: SocialTemplate) => {
    setPlatforms((prev) => {
      if (prev.some((p) => p.id === newPlatform.id)) {
        return prev.map((p) => (p.id === newPlatform.id ? newPlatform : p));
      }
      return [...prev, newPlatform];
    });
    setTemplates((prev) => {
      if (prev.some((t) => t.id === initialTemplate.id)) {
        return prev.map((t) => (t.id === initialTemplate.id ? initialTemplate : t));
      }
      return [...prev, initialTemplate];
    });
  };

  const handleDeletePlatform = (platformId: SocialPlatform) => {
    setPlatforms((prev) => prev.filter((p) => p.id !== platformId));
    setTemplates((prev) => prev.filter((t) => t.platform !== platformId));
  };

  // AI Provider Handlers
  const handleUpdateProviderKey = (id: AIProvider, key: string) => {
    setAiProviders((prev) =>
      prev.map((p) => (p.id === id ? { ...p, apiKey: key } : p))
    );
  };

  // Publishing Handler
  const handlePublishPost = (newPostData: Omit<PostItem, 'id'>) => {
    const newPost: PostItem = {
      id: `post-${Date.now()}`,
      ...newPostData,
    };

    setPosts((prev) => [newPost, ...prev]);

    // Mark attached media as posted to these platforms (coinciding checkmarks)
    if (newPostData.mediaUrl) {
      setMediaList((prev) =>
        prev.map((item) => {
          if (
            item.url === newPostData.mediaUrl ||
            item.watermarkedUrl === newPostData.mediaUrl
          ) {
            const currentPosted = item.postedNetworks || [];
            const combined = Array.from(
              new Set([...currentPosted, ...newPostData.platforms])
            );
            return { ...item, postedNetworks: combined as SocialPlatform[] };
          }
          return item;
        })
      );
    }

    // Decrement posts remaining for free plan
    if (subscription.plan === 'free') {
      setSubscription((prev) => ({
        ...prev,
        postsRemaining: Math.max(0, prev.postsRemaining - 1),
      }));
    }

    // Switch to history tab to view performance
    setTimeout(() => {
      setActiveTab('history');
    }, 600);
  };

  // Simulated Chrome Extension capture & post
  const handleDispatchSimulatedPost = (
    title: string,
    caption: string,
    mediaUrl: string
  ) => {
    const newPost: PostItem = {
      id: `ext-${Date.now()}`,
      title,
      baseCaption: caption,
      platformCaptions: {
        twitter: caption,
        instagram: `${caption}\n\n#social #chrome #creator`,
        linkedin: caption,
        tiktok: `${caption} #fyp #viral`,
      },
      platformTags: {
        twitter: ['#social', '#extension'],
        instagram: ['#social', '#chrome', '#creator'],
        linkedin: ['#creator', '#efficiency'],
        tiktok: ['#fyp', '#viral'],
      },
      platforms: ['twitter', 'instagram', 'linkedin', 'tiktok'],
      mediaUrl,
      status: 'posted',
      postedAt: new Date().toISOString(),
      viralScore: 88,
      stats: {
        impressions: 420,
        likes: 38,
        shares: 9,
        comments: 4,
        clicks: 12,
      },
      extensionSynced: true,
    };

    setPosts((prev) => [newPost, ...prev]);

    // Mark attached media as posted
    if (mediaUrl) {
      setMediaList((prev) =>
        prev.map((item) => {
          if (item.url === mediaUrl) {
            const currentPosted = item.postedNetworks || [];
            const combined = Array.from(
              new Set([
                ...currentPosted,
                'twitter',
                'instagram',
                'linkedin',
                'tiktok',
              ])
            );
            return { ...item, postedNetworks: combined as SocialPlatform[] };
          }
          return item;
        })
      );
    }

    // All packages (Free, Pro, Premium) enjoy unlimited posts!
  };

  const handleSendAIToComposer = (text: string) => {
    setComposeTopicDraft(text);
    setActiveTab('compose');
  };

  const scheduledCount = posts.filter((p) => p.status === 'scheduled').length;
  const activeAiName =
    aiProviders.find((p) => p.id === activeAIProvider)?.name || 'Google Gemini';

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
      {/* Streamlined Clean Header: Logo on left with dropdown navigation, title of page, Upgrade/Pro/Premium on right */}
      <Header
        subscription={subscription}
        activeTab={activeTab}
        onChangeTab={setActiveTab}
        onOpenUpgrade={() => setIsUpgradeModalOpen(true)}
      />

      {/* Workspace Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8">
        {activeTab === 'media' && (
          <MainMediaWorkspaceView
            mediaList={mediaList}
            activeMedia={activeMedia}
            onSelectMedia={(m) => {
              setActiveMedia(m);
              setSelectedMediaUrl(m.url);
            }}
            onAddMedia={handleAddMedia}
            onUpdateMedia={handleUpdateMedia}
            onDeleteMedia={handleDeleteMedia}
            platforms={platforms}
            templates={templates}
            onNavigateToSettings={() => setActiveTab('templates')}
            onNavigateToVideoStudio={() => setActiveTab('video')}
            onNavigateToCompose={() => setActiveTab('compose')}
            onNavigateToExtension={() => setActiveTab('extension')}
            onNavigateToAnalytics={() => setActiveTab('history')}
            onNavigateToAI={() => setActiveTab('ai')}
            onNavigateToStudio={() => setActiveTab('studio')}
            onPublishPost={handlePublishPost}
            subscription={subscription}
            onOpenUpgrade={() => setIsUpgradeModalOpen(true)}
            aiProviders={aiProviders}
            onUpdateProviderKey={handleUpdateProviderKey}
            watermarkSettings={watermarkSettings}
            onUpdateWatermark={setWatermarkSettings}
          />
        )}

        {activeTab === 'compose' && (
          <ComposeView
            platforms={platforms}
            templates={templates}
            mediaList={mediaList}
            selectedMediaUrl={selectedMediaUrl}
            onSelectMediaUrl={setSelectedMediaUrl}
            watermarkSettings={watermarkSettings}
            subscription={subscription}
            onOpenUpgrade={() => setIsUpgradeModalOpen(true)}
            onOpenStudio={() => setActiveTab('studio')}
            onPublishPost={handlePublishPost}
            initialTopic={composeTopicDraft}
          />
        )}

        {activeTab === 'studio' && (
          <MediaStudioView
            mediaList={mediaList}
            activeMedia={activeMedia}
            onSelectMedia={(m) => {
              setActiveMedia(m);
              setSelectedMediaUrl(m.url);
            }}
            onAddMedia={handleAddMedia}
            onUpdateMedia={handleUpdateMedia}
            onDeleteMedia={handleDeleteMedia}
            watermarkSettings={watermarkSettings}
            onUpdateWatermark={setWatermarkSettings}
            onSendToCompose={handleSendToCompose}
            subscription={subscription}
            onOpenUpgrade={() => setIsUpgradeModalOpen(true)}
            onSwitchToVideoStudio={() => setActiveTab('video')}
            aiProviders={aiProviders}
            onUpdateProviderKey={handleUpdateProviderKey}
          />
        )}

        {activeTab === 'video' && (
          <VideoStudioView
            mediaList={mediaList}
            subscription={subscription}
            onOpenUpgrade={() => setIsUpgradeModalOpen(true)}
            onSendToCompose={handleSendToCompose}
            onAddMedia={handleAddMedia}
            watermarkSettings={watermarkSettings}
          />
        )}

        {activeTab === 'templates' && (
          <PlatformTemplatesView
            platforms={platforms}
            templates={templates}
            onUpdatePlatform={handleUpdatePlatform}
            onUpdateTemplate={handleUpdateTemplate}
            onCreateTemplate={handleCreateTemplate}
            onDeleteTemplate={handleDeleteTemplate}
            onAddPlatform={handleAddPlatform}
            onDeletePlatform={handleDeletePlatform}
            subscription={subscription}
            onOpenUpgrade={() => setIsUpgradeModalOpen(true)}
          />
        )}

        {activeTab === 'ai' && (
          <AIChatProviderView
            providers={aiProviders}
            activeProviderId={activeAIProvider}
            onSelectProvider={setActiveAIProvider}
            onUpdateProviderKey={handleUpdateProviderKey}
            subscription={subscription}
            onOpenUpgrade={() => setIsUpgradeModalOpen(true)}
            onSendToComposer={handleSendAIToComposer}
          />
        )}

        {activeTab === 'history' && <HistoryAnalyticsView posts={posts} />}

        {activeTab === 'extension' && (
          <ChromeExtensionView
            onDispatchSimulatedPost={handleDispatchSimulatedPost}
            availableMediaUrls={mediaList.map((m) => m.url)}
            mediaList={mediaList}
            onAddMedia={handleAddMedia}
            onUpdateMedia={handleUpdateMedia}
            onSelectMedia={(m) => {
              setActiveMedia(m);
              setSelectedMediaUrl(m.url);
            }}
            onOpenStudioWithMedia={(m) => {
              setActiveMedia(m);
              setSelectedMediaUrl(m.url);
              setActiveTab('studio');
            }}
            onOpenVideoStudioWithMedia={(m) => {
              setActiveMedia(m);
              setSelectedMediaUrl(m.url);
              setActiveTab('video');
            }}
            onOpenAIProviderKeySetup={() => {
              setActiveTab('ai');
            }}
            aiProviders={aiProviders}
          />
        )}
      </main>

      {/* Upgrade & Freemium Tier Modal */}
      <UpgradeModal
        isOpen={isUpgradeModalOpen}
        onClose={() => setIsUpgradeModalOpen(false)}
        subscription={subscription}
        onSelectPlan={handleSelectPlan}
      />
    </div>
  );
}
