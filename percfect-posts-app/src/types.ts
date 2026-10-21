export type SocialPlatform =
  | 'twitter'
  | 'instagram'
  | 'linkedin'
  | 'tiktok'
  | 'youtube'
  | 'pinterest'
  | 'facebook'
  | 'threads'
  | 'bluesky'
  | string;

export interface NetworkAdvancedSettings {
  // Instagram specific
  instagramFormat?: 'post' | 'reel' | 'story' | 'carousel';
  instagramShareToFeed?: boolean;
  instagramHideLikes?: boolean;
  instagramAllowComments?: boolean;

  // Twitter / X specific
  twitterMatureAudience?: boolean; // sensitive / mature audience warning
  twitterReplyRestriction?: 'everyone' | 'following' | 'mentioned';

  // Facebook specific
  facebookAudience?: 'public' | 'friends' | 'only_me';
  facebookTarget?: 'timeline' | 'page' | 'group' | 'story';

  // LinkedIn specific
  linkedinVisibility?: 'public' | 'connections';

  // YouTube specific
  youtubeFormat?: 'video' | 'short';
  youtubePrivacy?: 'public' | 'unlisted' | 'private';
  youtubeMadeForKids?: boolean;

  // TikTok specific
  tiktokPrivacy?: 'public' | 'friends' | 'private';
  tiktokAllowDuet?: boolean;
  tiktokAllowStitch?: boolean;
  tiktokCommercialContent?: boolean;

  // Pinterest specific
  pinterestPinType?: 'standard' | 'idea';
  pinterestBoard?: string;
  pinterestDestinationLink?: string;

  // Patreon / Creator Subscription specific
  patreonTierAccess?: 'public' | 'all_patrons' | 'vip_tiers';
  patreonEarlyAccessHours?: number;
  patreonIsPaidPost?: boolean;
  patreonTeaserText?: string;

  // Generic custom network settings
  customPrivacy?: 'public' | 'followers' | 'private';
  customChannelOrSubreddit?: string;
  customTag?: string;
}

export interface PlatformConfig {
  id: SocialPlatform;
  name: string;
  tagline: string;
  maxChars: number;
  bestAspectRatios: string[];
  method: 'api_key' | 'oauth' | 'extension';
  guideTitle: string;
  apiDocUrl: string;
  steps: string[];
  authKey: string;
  tokenSecret?: string;
  connected: boolean;
  accountHandle: string;
  avatar: string;
  rateLimitNote: string;
  // Custom platform fields
  isCustom?: boolean;
  brandColor?: string;
  shortLabel?: string;
}

export interface SocialTemplate {
  id: string;
  name: string;
  platform: SocialPlatform;
  titlePrefix: string;
  disclaimer: string;
  hashtagPreset: string[];
  cta: string;
  watermarkEnabled: boolean;
  autoUpscale: boolean;
  aspectRatio: '1:1' | '9:16' | '16:9' | '4:5' | 'original';
  advancedSettings?: NetworkAdvancedSettings;
}

export interface MediaItem {
  id: string;
  name: string;
  url: string;
  type: 'image' | 'video';
  dimensions: { width: number; height: number };
  size: string;
  timestamp: string;
  watermarkedUrl?: string;
  upscaled?: boolean;
  scaleFactor?: 2 | 4;
  titleStamp?: string;
  disclaimerStamp?: string;
  postedNetworks?: SocialPlatform[];
  sourcePageUrl?: string;
}

export type WatermarkPosition =
  | 'bottom-right'
  | 'bottom-left'
  | 'top-right'
  | 'top-left'
  | 'center';

export interface WatermarkSettings {
  enabled: boolean;
  type: 'logo' | 'text' | 'both';
  logoUrl: string;
  logoOpacity: number;
  logoScale: number;
  titleText: string;
  disclaimerText: string;
  watermarkText: string;
  textColor: string;
  backgroundColor: string;
  fontFamily: string;
  fontSize: number;
  position: WatermarkPosition;
  margin: number;
}

export interface PostItem {
  id: string;
  title: string;
  baseCaption: string;
  platformCaptions: Partial<Record<SocialPlatform, string>>;
  platformTags: Partial<Record<SocialPlatform, string[]>>;
  platforms: SocialPlatform[];
  mediaId?: string;
  mediaUrl?: string;
  status: 'draft' | 'scheduled' | 'publishing' | 'posted' | 'failed';
  scheduledTime?: string;
  postedAt?: string;
  viralScore?: number;
  stats: {
    impressions: number;
    likes: number;
    shares: number;
    comments: number;
    clicks: number;
  };
  liveUrls?: Partial<Record<SocialPlatform, string>>;
  extensionSynced?: boolean;
}

export type AIProvider = 'gemini' | 'openai' | 'grok' | 'anthropic' | 'groq' | 'mistral' | 'percfectai';

export interface AIProviderInfo {
  id: AIProvider;
  name: string;
  description: string;
  defaultModel: string;
  docsUrl: string;
  keyUrl: string;
  guideSteps: string[];
  pricingNote: string;
  apiKey: string;
  isConfigured: boolean;
  supportsImageGen?: boolean;
  imageGenModel?: string;
  imageApiKey?: string;
  isImageConfigured?: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'model';
  text: string;
  timestamp: string;
  modelUsed?: string;
  persona?: string;
  thinking?: boolean;
}

export type PlanTier = 'free' | 'pro' | 'premium' | 'agency';

export interface UserSubscription {
  plan: PlanTier;
  postsRemaining: number;
  monthlyPostLimit: number;
  unlimitedPosts: boolean;
  maxNetworks: number; // 2 for free, 5 for pro, 999 for premium
  maxUpscaleMP: 0 | 5 | 10; // 0 for free (locked), 5 for pro (5MP), 10 for premium (10MP)
  mandatoryAttribution: boolean; // true for free (must have trademark logo & description link)
  customWatermarkUnlocked: boolean;
  highThinkingUnlocked: boolean;
  connectedAccountsLimit: number;
  extensionAutoSync: boolean;
  storageUsedBytes: number;
  storageLimitBytes: number;
  storageLabel: string;
  videoUnlocked: boolean; // video features & trimming
  videoStitchingUnlocked: boolean; // putting videos together
  aiImageEditingUnlocked: boolean;
  analyticsUnlocked: boolean; // full analytics & viral scores
}

export type VideoFormat = 'original' | '9:16' | '16:9' | '1:1' | '4:5';

export interface VideoClip {
  id: string;
  name: string;
  url: string;
  duration: number; // in seconds
  trimStart: number;
  trimEnd: number;
  title: string;
  thumbnailUrl?: string;
}

export interface FreezeFrameItem {
  id: string;
  timestamp: number;
  capturedImageUrl: string;
  title: string;
  createdAt: string;
}

export interface AITweakOptions {
  prompt: string;
  stylePreset?: string;
  provider: AIProvider;
  intensity?: number;
}
