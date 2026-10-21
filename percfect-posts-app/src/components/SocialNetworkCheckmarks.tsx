import React from 'react';
import { Check, Plus } from 'lucide-react';
import { SocialPlatform } from '../types.ts';

export interface PlatformVisualInfo {
  id: SocialPlatform;
  name: string;
  shortLabel: string;
  badgeBg: string;
  textColor: string;
  borderColor: string;
  accentColor: string;
}

export const PLATFORM_VISUALS: Record<SocialPlatform, PlatformVisualInfo> = {
  twitter: {
    id: 'twitter',
    name: 'X (Twitter)',
    shortLabel: '𝕏',
    badgeBg: 'bg-black text-white',
    textColor: 'text-white',
    borderColor: 'border-slate-700',
    accentColor: '#ffffff',
  },
  instagram: {
    id: 'instagram',
    name: 'Instagram',
    shortLabel: 'IG',
    badgeBg: 'bg-gradient-to-tr from-[#f09433] via-[#dc2743] to-[#bc1888] text-white',
    textColor: 'text-white',
    borderColor: 'border-rose-500/50',
    accentColor: '#E1306C',
  },
  linkedin: {
    id: 'linkedin',
    name: 'LinkedIn',
    shortLabel: 'LI',
    badgeBg: 'bg-[#0A66C2] text-white',
    textColor: 'text-white',
    borderColor: 'border-blue-400/50',
    accentColor: '#0A66C2',
  },
  tiktok: {
    id: 'tiktok',
    name: 'TikTok',
    shortLabel: 'TT',
    badgeBg: 'bg-black text-[#00f2fe]',
    textColor: 'text-[#00f2fe]',
    borderColor: 'border-[#ff0050]/60',
    accentColor: '#00f2fe',
  },
  youtube: {
    id: 'youtube',
    name: 'YouTube',
    shortLabel: 'YT',
    badgeBg: 'bg-[#FF0000] text-white',
    textColor: 'text-white',
    borderColor: 'border-red-400/60',
    accentColor: '#FF0000',
  },
  pinterest: {
    id: 'pinterest',
    name: 'Pinterest',
    shortLabel: 'PIN',
    badgeBg: 'bg-[#BD081C] text-white',
    textColor: 'text-white',
    borderColor: 'border-red-600/60',
    accentColor: '#BD081C',
  },
  facebook: {
    id: 'facebook',
    name: 'Facebook',
    shortLabel: 'FB',
    badgeBg: 'bg-[#1877F2] text-white',
    textColor: 'text-white',
    borderColor: 'border-blue-500/50',
    accentColor: '#1877F2',
  },
  threads: {
    id: 'threads',
    name: 'Threads',
    shortLabel: 'TH',
    badgeBg: 'bg-zinc-900 text-white',
    textColor: 'text-white',
    borderColor: 'border-zinc-600',
    accentColor: '#ffffff',
  },
  bluesky: {
    id: 'bluesky',
    name: 'Bluesky',
    shortLabel: 'BSKY',
    badgeBg: 'bg-[#0285FF] text-white',
    textColor: 'text-white',
    borderColor: 'border-sky-400/60',
    accentColor: '#0285FF',
  },
  patreon: {
    id: 'patreon',
    name: 'Patreon',
    shortLabel: 'PAT',
    badgeBg: 'bg-[#FF424D] text-white',
    textColor: 'text-white',
    borderColor: 'border-red-400/60',
    accentColor: '#FF424D',
  },
  discord: {
    id: 'discord',
    name: 'Discord',
    shortLabel: 'DISC',
    badgeBg: 'bg-[#5865F2] text-white',
    textColor: 'text-white',
    borderColor: 'border-indigo-400/60',
    accentColor: '#5865F2',
  },
  substack: {
    id: 'substack',
    name: 'Substack',
    shortLabel: 'SUB',
    badgeBg: 'bg-[#FF6719] text-white',
    textColor: 'text-white',
    borderColor: 'border-orange-400/60',
    accentColor: '#FF6719',
  },
  reddit: {
    id: 'reddit',
    name: 'Reddit',
    shortLabel: 'RD',
    badgeBg: 'bg-[#FF4500] text-white',
    textColor: 'text-white',
    borderColor: 'border-orange-500/60',
    accentColor: '#FF4500',
  },
  medium: {
    id: 'medium',
    name: 'Medium',
    shortLabel: 'MED',
    badgeBg: 'bg-[#00AB6C] text-white',
    textColor: 'text-white',
    borderColor: 'border-emerald-400/60',
    accentColor: '#00AB6C',
  },
  mastodon: {
    id: 'mastodon',
    name: 'Mastodon',
    shortLabel: 'MAST',
    badgeBg: 'bg-[#6364FF] text-white',
    textColor: 'text-white',
    borderColor: 'border-purple-400/60',
    accentColor: '#6364FF',
  },
};

export const getPlatformVisual = (
  platformId: string,
  customPlatforms?: { id: string; name: string; brandColor?: string; shortLabel?: string }[]
): PlatformVisualInfo => {
  if (PLATFORM_VISUALS[platformId]) {
    return PLATFORM_VISUALS[platformId];
  }

  const custom = customPlatforms?.find((p) => p.id === platformId);
  const brandColor = custom?.brandColor || '#6366f1';
  const name = custom?.name || platformId.charAt(0).toUpperCase() + platformId.slice(1);
  const shortLabel = custom?.shortLabel || platformId.slice(0, 3).toUpperCase();

  return {
    id: platformId,
    name,
    shortLabel,
    badgeBg: `text-white`,
    textColor: 'text-white',
    borderColor: 'border-white/30',
    accentColor: brandColor,
  };
};

export const ALL_PLATFORMS: SocialPlatform[] = [
  'twitter',
  'instagram',
  'linkedin',
  'tiktok',
  'youtube',
  'pinterest',
  'facebook',
  'threads',
  'bluesky',
];

interface PhotoPostedBadgesProps {
  postedNetworks?: SocialPlatform[];
  size?: 'xs' | 'sm' | 'md';
  onTogglePlatform?: (platform: SocialPlatform) => void;
  interactive?: boolean;
  customPlatforms?: { id: string; name: string; brandColor?: string; shortLabel?: string }[];
}

/**
 * Compact mini-checkmarks strip rendered directly on photo cards
 */
export const PhotoPostedBadges: React.FC<PhotoPostedBadgesProps> = ({
  postedNetworks = [],
  size = 'xs',
  onTogglePlatform,
  interactive = false,
  customPlatforms,
}) => {
  if (postedNetworks.length === 0) {
    return null;
  }

  const badgeSizeClasses =
    size === 'xs'
      ? 'h-4 text-[9px] px-1 gap-0.5'
      : size === 'sm'
      ? 'h-5 text-[10px] px-1.5 gap-1'
      : 'h-6 text-xs px-2 gap-1.5';

  const checkSize = size === 'xs' ? 'w-2.5 h-2.5' : size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5';

  return (
    <div className="flex flex-wrap items-center gap-1">
      {postedNetworks.map((platform) => {
        const visual = getPlatformVisual(platform, customPlatforms);
        const hasBgClass = visual.badgeBg.startsWith('bg-');

        return (
          <span
            key={platform}
            onClick={(e) => {
              if (interactive && onTogglePlatform) {
                e.stopPropagation();
                onTogglePlatform(platform);
              }
            }}
            title={`Posted to ${visual.name}`}
            style={!hasBgClass ? { backgroundColor: visual.accentColor } : undefined}
            className={`inline-flex items-center rounded-full font-bold shadow-sm border ${visual.badgeBg} ${visual.borderColor} ${badgeSizeClasses} ${
              interactive ? 'cursor-pointer hover:opacity-80' : ''
            }`}
          >
            <Check className={`${checkSize} stroke-[3]`} />
            <span className="leading-none">{visual.shortLabel}</span>
          </span>
        );
      })}
    </div>
  );
};

interface SocialNetworkPostedTrackerProps {
  postedNetworks?: SocialPlatform[];
  onTogglePlatform: (platform: SocialPlatform) => void;
  title?: string;
  readOnly?: boolean;
  customPlatforms?: { id: string; name: string; brandColor?: string; shortLabel?: string }[];
}

/**
 * Comprehensive colored checkmark manager for media details & preview inspector
 */
export const SocialNetworkPostedTracker: React.FC<SocialNetworkPostedTrackerProps> = ({
  postedNetworks = [],
  onTogglePlatform,
  title = 'Published Across Social Networks',
  readOnly = false,
  customPlatforms,
}) => {
  const allPlatformKeys = Array.from(
    new Set([
      ...ALL_PLATFORMS,
      ...(customPlatforms ? customPlatforms.map((c) => c.id) : []),
    ])
  );
  const postedCount = postedNetworks.length;

  return (
    <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-bold text-slate-200">{title}</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full font-semibold bg-slate-800 text-indigo-300 border border-indigo-500/20">
            {postedCount} / {allPlatformKeys.length} Posted
          </span>
        </div>
        {!readOnly && (
          <span className="text-[10px] text-slate-500">Click to toggle posted status</span>
        )}
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-9 gap-1.5">
        {allPlatformKeys.map((platform) => {
          const isPosted = postedNetworks.includes(platform);
          const visual = getPlatformVisual(platform, customPlatforms);
          const hasBgClass = visual.badgeBg.startsWith('bg-');

          return (
            <button
              key={platform}
              type="button"
              disabled={readOnly}
              onClick={() => onTogglePlatform(platform)}
              title={
                isPosted
                  ? `Posted to ${visual.name} (Click to unmark)`
                  : `Not yet posted to ${visual.name} (Click to mark as posted)`
              }
              style={
                isPosted && !hasBgClass
                  ? { backgroundColor: visual.accentColor }
                  : undefined
              }
              className={`flex flex-col items-center justify-center p-2 rounded-lg border transition text-center ${
                isPosted
                  ? `${visual.badgeBg} ${visual.borderColor} shadow-sm ring-1 ring-white/10 scale-[1.02]`
                  : 'bg-slate-900/60 border-slate-800/80 text-slate-400 hover:border-slate-700 hover:text-slate-300 opacity-60 hover:opacity-90'
              } ${readOnly ? 'cursor-default' : 'cursor-pointer'}`}
            >
              <div className="flex items-center justify-center gap-1 mb-0.5">
                {isPosted ? (
                  <div className="w-4 h-4 rounded-full bg-white/20 flex items-center justify-center">
                    <Check className="w-3 h-3 text-white stroke-[3]" />
                  </div>
                ) : (
                  <div className="w-4 h-4 rounded-full border border-slate-700 flex items-center justify-center">
                    <Plus className="w-2.5 h-2.5 text-slate-500" />
                  </div>
                )}
                <span className="font-extrabold text-[11px] leading-none">{visual.shortLabel}</span>
              </div>
              <span className="text-[9px] truncate w-full font-medium">
                {isPosted ? '✓ Posted' : 'Unposted'}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
};
