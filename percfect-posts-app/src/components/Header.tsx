import React, { useState, useRef, useEffect } from 'react';
import {
  Crown,
  Sparkles,
  ChevronDown,
  Layers,
  Image as ImageIcon,
  Film,
  Sliders,
  Send,
  BarChart3,
  Bot,
  Chrome,
  Check,
  Home,
} from 'lucide-react';
import { UserSubscription } from '../types.ts';
import { PerfectPostsLogo } from './PerfectPostsLogo.tsx';

export type ActiveTab =
  | 'media'
  | 'compose'
  | 'studio'
  | 'video'
  | 'templates'
  | 'ai'
  | 'history'
  | 'extension';

interface HeaderProps {
  subscription: UserSubscription;
  activeTab: ActiveTab;
  onChangeTab: (tab: ActiveTab) => void;
  onOpenUpgrade: () => void;
}

const SITE_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Studio', href: '/percfectstudios' },
  { label: 'Library', href: '/studios/library' },
  { label: 'Settings (your socials)', href: '/settings#social' },
];

const PAGE_TITLES: Record<ActiveTab, { title: string; subtitle?: string }> = {
  media: { title: 'Media Center', subtitle: 'Photo & Video Workspace' },
  studio: { title: 'Watermark Studio', subtitle: 'Brand Stamps & Protection' },
  video: { title: 'Video Studio', subtitle: '9:16 Trim, Stitch & Freeze-Frames' },
  templates: { title: 'Accounts & Templates', subtitle: 'Platform Credentials & Presets' },
  compose: { title: 'Multi-Network Composer', subtitle: 'Cross-Platform Drafts' },
  history: { title: 'Analytics & Logs', subtitle: 'Live Stats & Viral Reach' },
  ai: { title: 'AI Brains & Engines', subtitle: 'Gemini, Grok & Custom Keys' },
  extension: { title: 'Chrome Extension', subtitle: 'Web Clipper Companion' },
};

export const Header: React.FC<HeaderProps> = ({
  subscription,
  activeTab,
  onChangeTab,
  onOpenUpgrade,
}) => {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const isFree = subscription.plan === 'free';
  const isPro = subscription.plan === 'pro';
  const isPremium = subscription.plan === 'premium' || subscription.plan === 'agency';

  const menuItems: { id: ActiveTab; label: string; icon: React.ReactNode; badge?: string }[] = [
    { id: 'media', label: 'Media Center', icon: <Layers className="w-4 h-4 text-indigo-400" /> },
    { id: 'studio', label: 'Watermark Studio', icon: <ImageIcon className="w-4 h-4 text-sky-400" /> },
    {
      id: 'video',
      label: 'Video Studio',
      icon: <Film className="w-4 h-4 text-rose-400" />,
      badge: isPremium ? 'UNLOCKED' : 'PREMIUM',
    },
    { id: 'templates', label: 'Accounts & Format Templates', icon: <Sliders className="w-4 h-4 text-emerald-400" /> },
    { id: 'compose', label: 'Social Composer', icon: <Send className="w-4 h-4 text-purple-400" /> },
    {
      id: 'history',
      label: 'Post Analytics & History',
      icon: <BarChart3 className="w-4 h-4 text-amber-400" />,
      badge: isPremium ? 'FULL' : isPro ? 'BASIC' : 'PREVIEW',
    },
    { id: 'ai', label: 'AI Brains & Guides', icon: <Bot className="w-4 h-4 text-cyan-400" /> },
    { id: 'extension', label: 'Chrome Web Clipper', icon: <Chrome className="w-4 h-4 text-teal-400" /> },
  ];

  const currentInfo = PAGE_TITLES[activeTab] || { title: 'Media Center' };

  return (
    <header data-pp-logo="1" className="border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-md sticky top-0 z-50 px-4 lg:px-8 py-3.5">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        {/* ========================================================
            LEFT CORNER:
            1. User's Crowned "P" Cyber Metallic Logo (Click opens dropdown)
            2. Current Page Title
        ======================================================== */}
        <div className="flex items-center gap-3 relative" ref={dropdownRef}>
          {/* Logo with interactive Dropdown Trigger */}
          <button
            onClick={() => setIsDropdownOpen((prev) => !prev)}
            className="group relative flex items-center gap-1.5 focus:outline-none transition-transform active:scale-95"
            title="Click to jump to any Studio or Tool"
          >
            <PerfectPostsLogo size={42} showCrownGlow={true} />
            <div className="w-5 h-5 rounded-full bg-slate-800/80 border border-slate-700 flex items-center justify-center text-slate-400 group-hover:text-white group-hover:bg-slate-700 transition">
              <ChevronDown
                className={`w-3.5 h-3.5 transition-transform duration-200 ${
                  isDropdownOpen ? 'rotate-180 text-amber-400' : ''
                }`}
              />
            </div>
          </button>

          {/* Page Title & Subtitle */}
          <div className="flex flex-col">
            <h1 className="text-lg sm:text-xl font-black text-white tracking-tight leading-none flex items-center gap-2">
              <span>{currentInfo.title}</span>
            </h1>
            {currentInfo.subtitle && (
              <span className="text-[11px] text-slate-400 font-medium hidden sm:inline-block mt-0.5">
                {currentInfo.subtitle}
              </span>
            )}
          </div>

          {/* Quick-Jump Dropdown Menu */}
          {isDropdownOpen && (
            <div className="absolute top-full left-0 mt-2.5 w-72 bg-slate-900 border border-slate-750 rounded-2xl shadow-2xl shadow-black/80 overflow-hidden py-1.5 z-50 animate-in fade-in slide-in-from-top-2 duration-150">
              <div className="px-3 py-2 border-b border-slate-800 bg-slate-950/50">
                <span className="text-[10px] font-black tracking-wider uppercase text-slate-400">
                  Navigation & Studios
                </span>
              </div>

              <div className="p-1 space-y-0.5">
                {menuItems.map((item) => {
                  const isActive = activeTab === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => {
                        onChangeTab(item.id);
                        setIsDropdownOpen(false);
                      }}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-semibold transition ${
                        isActive
                          ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                          : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                      }`}
                    >
                      <div className="flex items-center gap-2.5">
                        {item.icon}
                        <span>{item.label}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {item.badge && (
                          <span
                            className={`text-[9px] font-black px-1.5 py-0.5 rounded uppercase tracking-wider ${
                              isActive
                                ? 'bg-white/20 text-white'
                                : 'bg-slate-800 text-slate-400 border border-slate-700'
                            }`}
                          >
                            {item.badge}
                          </span>
                        )}
                        {isActive && <Check className="w-3.5 h-3.5 text-white" />}
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="px-3 py-2 border-t border-slate-800 bg-slate-950/50">
                <span className="text-[10px] font-black tracking-wider uppercase text-slate-400">
                  Percfect website
                </span>
              </div>
              <div className="p-1 space-y-0.5">
                {SITE_LINKS.map((l) => (
                  <a
                    key={l.href}
                    href={l.href}
                    className="w-full flex items-center px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 hover:bg-slate-800 hover:text-white transition"
                  >
                    {l.label}
                  </a>
                ))}
              </div>

              <div className="p-2 border-t border-slate-800 bg-slate-950/50 flex items-center justify-between text-[11px] text-slate-400">
                <span>The Percfect Post</span>
                <span className="font-bold text-amber-400 capitalize">
                  {subscription.plan} Plan
                </span>
              </div>
            </div>
          )}
        </div>

        {/* ========================================================
            RIGHT CORNER:
            "Upgrade" (if Free), "PRO" (if Pro), or "PREMIUM" (if Premium)
        ======================================================== */}
        <div className="flex items-center gap-3">
          <a
            href="/"
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 text-slate-300 hover:text-white hover:border-slate-500 text-xs font-bold transition"
          >
            <Home className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Website</span>
          </a>
          {isFree ? (
            <button
              onClick={onOpenUpgrade}
              className="group relative inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-amber-500 via-yellow-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-slate-950 font-black text-xs sm:text-sm tracking-wide shadow-lg shadow-amber-500/20 hover:shadow-amber-500/35 transition active:scale-95"
            >
              <Crown className="w-4 h-4 text-slate-950" />
              <span>Upgrade</span>
              <Sparkles className="w-3.5 h-3.5 text-slate-950/70" />
            </button>
          ) : isPro ? (
            <button
              onClick={onOpenUpgrade}
              className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-amber-500/20 to-yellow-500/15 border border-amber-500/40 hover:border-amber-400 text-amber-300 font-black text-xs tracking-wider uppercase shadow-md shadow-amber-500/10 hover:bg-amber-500/25 transition active:scale-95"
              title="You are a PRO member (5 networks, 5MP upscaling). Click to manage or upgrade to Premium."
            >
              <Crown className="w-3.5 h-3.5 text-amber-400" />
              <span>PRO</span>
            </button>
          ) : (
            <button
              onClick={onOpenUpgrade}
              className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-purple-500/25 via-indigo-500/20 to-cyan-500/25 border border-purple-500/40 hover:border-purple-400 text-purple-200 font-black text-xs tracking-wider uppercase shadow-md shadow-purple-500/15 hover:bg-purple-500/30 transition active:scale-95"
              title="You are a PREMIUM member (Unlimited networks, 10MP upscaling, full video studio, 1TB storage)."
            >
              <Crown className="w-3.5 h-3.5 text-yellow-400" />
              <span>PREMIUM</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
