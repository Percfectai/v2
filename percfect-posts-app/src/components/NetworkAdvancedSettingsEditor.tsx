import React from 'react';
import {
  Sliders,
  Shield,
  Eye,
  MessageSquare,
  Sparkles,
  Lock,
  Globe,
  Users,
  Film,
  Image as ImageIcon,
  Flame,
  Clock,
  DollarSign,
  AlertTriangle,
} from 'lucide-react';
import { PlatformConfig, SocialTemplate, NetworkAdvancedSettings } from '../types.ts';

interface NetworkAdvancedSettingsEditorProps {
  platform: PlatformConfig;
  template: SocialTemplate;
  onUpdateSettings: (newSettings: NetworkAdvancedSettings) => void;
}

export const NetworkAdvancedSettingsEditor: React.FC<NetworkAdvancedSettingsEditorProps> = ({
  platform,
  template,
  onUpdateSettings,
}) => {
  const settings: NetworkAdvancedSettings = template.advancedSettings || {};

  const updateSetting = (key: keyof NetworkAdvancedSettings, value: any) => {
    onUpdateSettings({
      ...settings,
      [key]: value,
    });
  };

  const isInstagram = platform.id === 'instagram';
  const isTwitter = platform.id === 'twitter';
  const isFacebook = platform.id === 'facebook';
  const isLinkedIn = platform.id === 'linkedin';
  const isYouTube = platform.id === 'youtube';
  const isTikTok = platform.id === 'tiktok';
  const isPinterest = platform.id === 'pinterest';
  const isPatreon = platform.id === 'patreon' || platform.name.toLowerCase().includes('patreon');

  return (
    <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4 space-y-4">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800/80">
        <div className="flex items-center gap-2">
          <Sliders className="w-4 h-4 text-indigo-400" />
          <h4 className="text-xs font-bold text-white uppercase tracking-wider">
            {platform.name} Specific Advanced Settings & Audience Rules
          </h4>
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
          Network Native
        </span>
      </div>

      {/* 1. INSTAGRAM SETTINGS */}
      {isInstagram && (
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1.5">
              Default Content Format Preference:
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { id: 'post', label: 'Feed Post', desc: 'Square 1:1 or 4:5', icon: ImageIcon },
                { id: 'reel', label: 'Reel', desc: 'Vertical 9:16 video', icon: Film },
                { id: 'story', label: 'Story', desc: '24h Ephemeral', icon: Sparkles },
                { id: 'carousel', label: 'Carousel', desc: 'Multi-slide album', icon: Sliders },
              ].map((fmt) => {
                const isCurrent = (settings.instagramFormat || 'reel') === fmt.id;
                const Icon = fmt.icon;
                return (
                  <button
                    key={fmt.id}
                    type="button"
                    onClick={() => updateSetting('instagramFormat', fmt.id)}
                    className={`p-2.5 rounded-xl border text-left transition ${
                      isCurrent
                        ? 'bg-gradient-to-br from-purple-900/30 to-pink-900/30 border-pink-500 text-white ring-1 ring-pink-500/30'
                        : 'bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center gap-1.5 font-bold text-xs">
                      <Icon className="w-3.5 h-3.5 text-pink-400" />
                      <span>{fmt.label}</span>
                    </div>
                    <div className="text-[10px] text-slate-500 mt-0.5">{fmt.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
            <label className="flex items-center gap-2 p-2.5 rounded-lg bg-slate-900 border border-slate-800 cursor-pointer text-xs text-slate-300">
              <input
                type="checkbox"
                checked={settings.instagramShareToFeed !== false}
                onChange={(e) => updateSetting('instagramShareToFeed', e.target.checked)}
                className="w-4 h-4 rounded text-pink-600 bg-slate-800 border-slate-700"
              />
              <span>Share Reel to Main Feed Grid</span>
            </label>

            <label className="flex items-center gap-2 p-2.5 rounded-lg bg-slate-900 border border-slate-800 cursor-pointer text-xs text-slate-300">
              <input
                type="checkbox"
                checked={Boolean(settings.instagramHideLikes)}
                onChange={(e) => updateSetting('instagramHideLikes', e.target.checked)}
                className="w-4 h-4 rounded text-pink-600 bg-slate-800 border-slate-700"
              />
              <span>Hide Like & View Counts</span>
            </label>

            <label className="flex items-center gap-2 p-2.5 rounded-lg bg-slate-900 border border-slate-800 cursor-pointer text-xs text-slate-300">
              <input
                type="checkbox"
                checked={settings.instagramAllowComments !== false}
                onChange={(e) => updateSetting('instagramAllowComments', e.target.checked)}
                className="w-4 h-4 rounded text-pink-600 bg-slate-800 border-slate-700"
              />
              <span>Allow Comments</span>
            </label>
          </div>
        </div>
      )}

      {/* 2. TWITTER / X SETTINGS */}
      {isTwitter && (
        <div className="space-y-3">
          {/* Mature / Sensitive Audience Toggle */}
          <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 flex items-start justify-between gap-4">
            <div className="space-y-0.5">
              <div className="flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span className="text-xs font-bold text-white">
                  Mature / Sensitive Audience Content Flag
                </span>
                <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 font-semibold">
                  18+
                </span>
              </div>
              <p className="text-[11px] text-slate-400">
                Mark posted media as containing adult or sensitive material. Twitter will apply an age-gate blur over media previews.
              </p>
            </div>

            <label className="relative inline-flex items-center cursor-pointer shrink-0">
              <input
                type="checkbox"
                checked={Boolean(settings.twitterMatureAudience)}
                onChange={(e) => updateSetting('twitterMatureAudience', e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-10 h-5 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-amber-500"></div>
            </label>
          </div>

          {/* Reply Restrictions */}
          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1.5">
              Who Can Reply to This Post:
            </label>
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: 'everyone', label: 'Everyone', desc: 'Default open replies' },
                { id: 'following', label: 'People You Follow', desc: 'Reduces bot spam' },
                { id: 'mentioned', label: 'Only Mentioned', desc: 'Restricted conversation' },
              ].map((opt) => {
                const isCurrent = (settings.twitterReplyRestriction || 'everyone') === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => updateSetting('twitterReplyRestriction', opt.id)}
                    className={`p-2 rounded-lg border text-left transition ${
                      isCurrent
                        ? 'bg-sky-950/40 border-sky-500 text-white'
                        : 'bg-slate-900 border-slate-800 text-slate-400'
                    }`}
                  >
                    <div className="font-semibold text-xs">{opt.label}</div>
                    <div className="text-[10px] text-slate-500">{opt.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 3. FACEBOOK SETTINGS */}
      {isFacebook && (
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1.5">
              Audience Privacy Level:
            </label>
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: 'public', label: 'Public', desc: 'Anyone on or off Facebook', icon: Globe },
                { id: 'friends', label: 'Friends Only', desc: 'Only your personal friends', icon: Users },
                { id: 'only_me', label: 'Only Me (Private)', desc: 'Private personal archive', icon: Lock },
              ].map((opt) => {
                const isCurrent = (settings.facebookAudience || 'public') === opt.id;
                const Icon = opt.icon;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => updateSetting('facebookAudience', opt.id)}
                    className={`p-2.5 rounded-lg border text-left transition ${
                      isCurrent
                        ? 'bg-blue-950/50 border-blue-500 text-white ring-1 ring-blue-500/30'
                        : 'bg-slate-900 border-slate-800 text-slate-400'
                    }`}
                  >
                    <div className="flex items-center gap-1.5 font-semibold text-xs">
                      <Icon className="w-3.5 h-3.5 text-blue-400" />
                      <span>{opt.label}</span>
                    </div>
                    <div className="text-[10px] text-slate-500 mt-0.5">{opt.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1.5">
              Publishing Destination:
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { id: 'page', label: 'Business / Creator Page' },
                { id: 'timeline', label: 'Personal Timeline' },
                { id: 'group', label: 'Facebook Group' },
                { id: 'story', label: 'Facebook Story' },
              ].map((dest) => {
                const isCurrent = (settings.facebookTarget || 'page') === dest.id;
                return (
                  <button
                    key={dest.id}
                    type="button"
                    onClick={() => updateSetting('facebookTarget', dest.id)}
                    className={`p-2 rounded-lg border text-center text-xs font-medium transition ${
                      isCurrent
                        ? 'bg-blue-600/20 border-blue-500 text-white'
                        : 'bg-slate-900 border-slate-800 text-slate-400'
                    }`}
                  >
                    {dest.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 4. PATREON SETTINGS */}
      {isPatreon && (
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1.5">
              Patron Tier Access Level:
            </label>
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: 'all_patrons', label: 'All Active Patrons ($1+)', desc: 'Unlocks for all paid supporters' },
                { id: 'vip_tiers', label: 'VIP Supporters Only ($5+)', desc: 'Higher tiers & sponsors only' },
                { id: 'public', label: 'Public Free Preview', desc: 'Free teaser for everyone' },
              ].map((tier) => {
                const isCurrent = (settings.patreonTierAccess || 'all_patrons') === tier.id;
                return (
                  <button
                    key={tier.id}
                    type="button"
                    onClick={() => updateSetting('patreonTierAccess', tier.id)}
                    className={`p-2.5 rounded-lg border text-left transition ${
                      isCurrent
                        ? 'bg-red-950/40 border-red-500 text-white ring-1 ring-red-500/30'
                        : 'bg-slate-900 border-slate-800 text-slate-400'
                    }`}
                  >
                    <div className="font-semibold text-xs text-red-300">{tier.label}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">{tier.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-slate-300">
                <Clock className="w-4 h-4 text-amber-400" />
                <span>Publish 24h Early Access to Patrons</span>
              </div>
              <input
                type="checkbox"
                checked={settings.patreonEarlyAccessHours === 24}
                onChange={(e) => updateSetting('patreonEarlyAccessHours', e.target.checked ? 24 : 0)}
                className="w-4 h-4 rounded text-red-600 bg-slate-800 border-slate-700"
              />
            </div>

            <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-slate-300">
                <DollarSign className="w-4 h-4 text-emerald-400" />
                <span>Charge Patrons for this Post (Paid Post)</span>
              </div>
              <input
                type="checkbox"
                checked={Boolean(settings.patreonIsPaidPost)}
                onChange={(e) => updateSetting('patreonIsPaidPost', e.target.checked)}
                className="w-4 h-4 rounded text-red-600 bg-slate-800 border-slate-700"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-slate-300 block mb-1">
              Non-Patron Locked Teaser Message:
            </label>
            <input
              type="text"
              value={
                settings.patreonTeaserText ||
                '🔒 This post is exclusively for active patrons. Become a supporter to unlock full 4K access!'
              }
              onChange={(e) => updateSetting('patreonTeaserText', e.target.value)}
              className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-red-500"
            />
          </div>
        </div>
      )}

      {/* 5. LINKEDIN SETTINGS */}
      {isLinkedIn && (
        <div className="space-y-3">
          <label className="text-xs font-medium text-slate-300 block mb-1">
            Audience Visibility:
          </label>
          <div className="grid grid-cols-2 gap-2">
            {[
              { id: 'public', label: 'Public (Anyone on LinkedIn)', icon: Globe },
              { id: 'connections', label: '1st-Degree Connections Only', icon: Users },
            ].map((opt) => {
              const isCurrent = (settings.linkedinVisibility || 'public') === opt.id;
              const Icon = opt.icon;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => updateSetting('linkedinVisibility', opt.id)}
                  className={`p-2.5 rounded-lg border text-left transition ${
                    isCurrent
                      ? 'bg-blue-950/40 border-blue-500 text-white'
                      : 'bg-slate-900 border-slate-800 text-slate-400'
                  }`}
                >
                  <div className="flex items-center gap-1.5 text-xs font-semibold">
                    <Icon className="w-3.5 h-3.5 text-blue-400" />
                    <span>{opt.label}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 6. YOUTUBE SETTINGS */}
      {isYouTube && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">
                Format:
              </label>
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  type="button"
                  onClick={() => updateSetting('youtubeFormat', 'video')}
                  className={`p-2 rounded border text-xs font-semibold ${
                    (settings.youtubeFormat || 'video') === 'video'
                      ? 'bg-red-950/50 border-red-500 text-white'
                      : 'bg-slate-900 border-slate-800 text-slate-400'
                  }`}
                >
                  Standard Video
                </button>
                <button
                  type="button"
                  onClick={() => updateSetting('youtubeFormat', 'short')}
                  className={`p-2 rounded border text-xs font-semibold ${
                    settings.youtubeFormat === 'short'
                      ? 'bg-red-950/50 border-red-500 text-white'
                      : 'bg-slate-900 border-slate-800 text-slate-400'
                  }`}
                >
                  YouTube Short
                </button>
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">
                Default Privacy:
              </label>
              <select
                value={settings.youtubePrivacy || 'public'}
                onChange={(e) => updateSetting('youtubePrivacy', e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white"
              >
                <option value="public">Public</option>
                <option value="unlisted">Unlisted</option>
                <option value="private">Private</option>
              </select>
            </div>
          </div>

          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(settings.youtubeMadeForKids)}
              onChange={(e) => updateSetting('youtubeMadeForKids', e.target.checked)}
              className="w-4 h-4 rounded text-red-600 bg-slate-800 border-slate-700"
            />
            <span>Made for Kids (COPPA child-directed compliance)</span>
          </label>
        </div>
      )}

      {/* 7. TIKTOK SETTINGS */}
      {isTikTok && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-300">Audience:</span>
            <select
              value={settings.tiktokPrivacy || 'public'}
              onChange={(e) => updateSetting('tiktokPrivacy', e.target.value)}
              className="bg-slate-900 border border-slate-800 rounded px-2.5 py-1 text-xs text-white"
            >
              <option value="public">Public to Everyone</option>
              <option value="friends">Mutual Friends Only</option>
              <option value="private">Private (Only Me)</option>
            </select>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <label className="flex items-center gap-2 p-2 rounded bg-slate-900 border border-slate-800 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={settings.tiktokAllowDuet !== false}
                onChange={(e) => updateSetting('tiktokAllowDuet', e.target.checked)}
                className="w-3.5 h-3.5 text-cyan-500 rounded bg-slate-800 border-slate-700"
              />
              <span>Allow Duet</span>
            </label>

            <label className="flex items-center gap-2 p-2 rounded bg-slate-900 border border-slate-800 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={settings.tiktokAllowStitch !== false}
                onChange={(e) => updateSetting('tiktokAllowStitch', e.target.checked)}
                className="w-3.5 h-3.5 text-cyan-500 rounded bg-slate-800 border-slate-700"
              />
              <span>Allow Stitch</span>
            </label>

            <label className="flex items-center gap-2 p-2 rounded bg-slate-900 border border-slate-800 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(settings.tiktokCommercialContent)}
                onChange={(e) => updateSetting('tiktokCommercialContent', e.target.checked)}
                className="w-3.5 h-3.5 text-cyan-500 rounded bg-slate-800 border-slate-700"
              />
              <span>Commercial Ad</span>
            </label>
          </div>
        </div>
      )}

      {/* 8. GENERIC / CUSTOM NETWORK SETTINGS (Substack, Discord, Reddit, etc.) */}
      {!isInstagram && !isTwitter && !isFacebook && !isPatreon && !isLinkedIn && !isYouTube && !isTikTok && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">
                Audience Privacy Level:
              </label>
              <select
                value={settings.customPrivacy || 'public'}
                onChange={(e) => updateSetting('customPrivacy', e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white"
              >
                <option value="public">🌐 Public (All viewers / web)</option>
                <option value="followers">👥 Followers / Channel Members Only</option>
                <option value="private">🔒 Private Draft / Archive</option>
              </select>
            </div>

            <div>
              <label className="text-xs font-medium text-slate-300 block mb-1">
                Target Subreddit / Channel / Category:
              </label>
              <input
                type="text"
                value={settings.customChannelOrSubreddit || ''}
                onChange={(e) => updateSetting('customChannelOrSubreddit', e.target.value)}
                placeholder="e.g. #announcements, r/technology, or General"
                className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
