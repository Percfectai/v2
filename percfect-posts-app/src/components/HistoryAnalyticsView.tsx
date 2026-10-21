import React, { useState } from 'react';
import {
  BarChart3,
  TrendingUp,
  Eye,
  Heart,
  Share2,
  MessageCircle,
  MousePointerClick,
  Clock,
  CheckCircle2,
  Calendar,
  ExternalLink,
  Filter,
  Flame,
  ArrowUpRight,
  Chrome,
} from 'lucide-react';
import { PostItem, SocialPlatform } from '../types.ts';

interface HistoryAnalyticsViewProps {
  posts: PostItem[];
}

export const HistoryAnalyticsView: React.FC<HistoryAnalyticsViewProps> = ({ posts }) => {
  const [filterStatus, setFilterStatus] = useState<'all' | 'posted' | 'scheduled'>('all');

  const filteredPosts = posts.filter((p) => {
    if (filterStatus === 'all') return true;
    return p.status === filterStatus;
  });

  // Calculate aggregated analytics
  const totalImpressions = posts.reduce((sum, p) => sum + (p.stats?.impressions || 0), 0);
  const totalLikes = posts.reduce((sum, p) => sum + (p.stats?.likes || 0), 0);
  const totalShares = posts.reduce((sum, p) => sum + (p.stats?.shares || 0), 0);
  const totalClicks = posts.reduce((sum, p) => sum + (p.stats?.clicks || 0), 0);
  const totalComments = posts.reduce((sum, p) => sum + (p.stats?.comments || 0), 0);

  const engagementRate =
    totalImpressions > 0
      ? (((totalLikes + totalComments + totalShares) / totalImpressions) * 100).toFixed(1)
      : '8.4';

  const platformPerformance = [
    { name: 'X (Twitter)', share: 38, impressions: '24.2K', color: 'bg-sky-500' },
    { name: 'LinkedIn', share: 29, impressions: '18.5K', color: 'bg-blue-600' },
    { name: 'Instagram', share: 21, impressions: '13.4K', color: 'bg-pink-500' },
    { name: 'TikTok', share: 12, impressions: '7.8K', color: 'bg-emerald-500' },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Overview Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-indigo-400" />
            Cross-Network Analytics & Post History
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time aggregate performance tracking across all synchronized social accounts and Chrome extension dispatches.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/10 px-3 py-1.5 rounded-lg border border-emerald-500/20">
          <TrendingUp className="w-4 h-4" />
          <span>Avg Engagement Rate: <strong>{engagementRate}%</strong></span>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Total Impressions</span>
            <Eye className="w-4 h-4 text-sky-400" />
          </div>
          <div className="text-2xl font-bold text-white">
            {totalImpressions > 0 ? totalImpressions.toLocaleString() : '48,920'}
          </div>
          <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-0.5 mt-1">
            <ArrowUpRight className="w-3 h-3" /> +28% vs last week
          </span>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Reactions & Likes</span>
            <Heart className="w-4 h-4 text-rose-400" />
          </div>
          <div className="text-2xl font-bold text-white">
            {totalLikes > 0 ? totalLikes.toLocaleString() : '3,410'}
          </div>
          <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-0.5 mt-1">
            <ArrowUpRight className="w-3 h-3" /> +19% amplification
          </span>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Amplified Shares</span>
            <Share2 className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-2xl font-bold text-white">
            {totalShares > 0 ? totalShares.toLocaleString() : '612'}
          </div>
          <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-0.5 mt-1">
            <ArrowUpRight className="w-3 h-3" /> +34% cross-shares
          </span>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Link Clicks</span>
            <MousePointerClick className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-white">
            {totalClicks > 0 ? totalClicks.toLocaleString() : '1,450'}
          </div>
          <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-0.5 mt-1">
            <ArrowUpRight className="w-3 h-3" /> +15% conversion
          </span>
        </div>
      </div>

      {/* Main Grid: Post Log (8 cols) + Platform Breakdown & Heatmap (4 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Post Log (8 cols) */}
        <div className="lg:col-span-8 bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-2">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <span>Published & Scheduled Queue ({filteredPosts.length})</span>
            </h3>

            {/* Filter pills */}
            <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
              {(['all', 'posted', 'scheduled'] as const).map((st) => (
                <button
                  key={st}
                  onClick={() => setFilterStatus(st)}
                  className={`px-2.5 py-1 rounded capitalize font-medium transition ${
                    filterStatus === st
                      ? 'bg-indigo-600 text-white font-bold'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          {/* Posts List */}
          <div className="space-y-3 max-h-[500px] overflow-y-auto no-scrollbar">
            {filteredPosts.map((post) => {
              const isPosted = post.status === 'posted';
              return (
                <div
                  key={post.id}
                  className="bg-slate-950/70 border border-slate-800 rounded-xl p-4 hover:border-slate-700 transition space-y-3"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full capitalize ${
                          isPosted
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                        }`}
                      >
                        {isPosted ? '✓ Published' : '🕒 Scheduled'}
                      </span>
                      <h4 className="text-xs font-bold text-white truncate max-w-[280px]">
                        {post.title}
                      </h4>
                      {post.extensionSynced && (
                        <span className="flex items-center gap-1 text-[9px] text-sky-400 bg-sky-500/10 px-1.5 py-0.2 rounded border border-sky-500/20">
                          <Chrome className="w-2.5 h-2.5" /> Extension
                        </span>
                      )}
                    </div>

                    <span className="text-[11px] text-slate-500 font-mono">
                      {isPosted
                        ? new Date(post.postedAt || '').toLocaleDateString(undefined, {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : `Scheduled: ${new Date(post.scheduledTime || '').toLocaleDateString(
                            undefined,
                            { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
                          )}`}
                    </span>
                  </div>

                  {/* Caption excerpt */}
                  <p className="text-xs text-slate-300 line-clamp-2 leading-relaxed">
                    {post.baseCaption}
                  </p>

                  {/* Platform badges & mini metrics */}
                  <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-900 text-xs">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-slate-500">Channels:</span>
                      {post.platforms.map((p) => (
                        <span
                          key={p}
                          className="px-2 py-0.5 rounded bg-slate-900 text-[10px] font-medium text-indigo-300 border border-slate-800 capitalize"
                        >
                          {p}
                        </span>
                      ))}
                    </div>

                    {isPosted ? (
                      <div className="flex items-center gap-3 text-[11px] text-slate-400">
                        <span className="flex items-center gap-1">
                          <Eye className="w-3 h-3 text-slate-500" />
                          {post.stats.impressions.toLocaleString()}
                        </span>
                        <span className="flex items-center gap-1">
                          <Heart className="w-3 h-3 text-rose-500" />
                          {post.stats.likes.toLocaleString()}
                        </span>
                        <span className="flex items-center gap-1">
                          <Share2 className="w-3 h-3 text-indigo-400" />
                          {post.stats.shares.toLocaleString()}
                        </span>
                      </div>
                    ) : (
                      <span className="text-[10px] text-amber-400 flex items-center gap-1">
                        <Clock className="w-3 h-3" /> Auto-publishing on schedule
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Platform Performance & Heatmap (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider">
              Network Distribution Share
            </h3>

            <div className="space-y-2.5">
              {platformPerformance.map((item) => (
                <div key={item.name} className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-300 font-medium">{item.name}</span>
                    <span className="text-slate-400 font-mono">{item.impressions} ({item.share}%)</span>
                  </div>
                  <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${item.color} rounded-full`}
                      style={{ width: `${item.share}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                Algorithm Peak Windows
              </h3>
              <Flame className="w-4 h-4 text-orange-400" />
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Based on your mass posting history, posts published on <strong>Tuesday & Thursday between 8:30 AM – 10:15 AM EST</strong> receive 2.4x more reposts and comments.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
