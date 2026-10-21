import React from 'react';
import {
  Send,
  Image as ImageIcon,
  Sliders,
  Bot,
  BarChart3,
  Chrome,
  Film,
  Layers,
} from 'lucide-react';

export type ActiveTab =
  | 'media'
  | 'compose'
  | 'studio'
  | 'video'
  | 'templates'
  | 'ai'
  | 'history'
  | 'extension';

interface NavigationProps {
  activeTab: ActiveTab;
  onChangeTab: (tab: ActiveTab) => void;
  scheduledCount?: number;
}

export const Navigation: React.FC<NavigationProps> = ({
  activeTab,
  onChangeTab,
  scheduledCount = 0,
}) => {
  const navItems: {
    id: ActiveTab;
    label: string;
    icon: React.ReactNode;
    badge?: string;
    badgeColor?: string;
  }[] = [
    {
      id: 'media',
      label: 'Media Center',
      icon: <Layers className="w-4 h-4" />,
      badge: 'MAIN',
      badgeColor: 'bg-indigo-500/30 text-indigo-200 border border-indigo-500/40',
    },
    {
      id: 'studio',
      label: 'Watermark Studio',
      icon: <ImageIcon className="w-4 h-4" />,
    },
    {
      id: 'video',
      label: '9:16 Video Studio',
      icon: <Film className="w-4 h-4" />,
      badge: 'PRO',
      badgeColor: 'bg-gradient-to-r from-amber-500 to-pink-500 text-slate-950 font-black',
    },
    {
      id: 'templates',
      label: 'Accounts & Templates (Settings)',
      icon: <Sliders className="w-4 h-4" />,
    },
    {
      id: 'ai',
      label: 'AI Brains & Guides',
      icon: <Bot className="w-4 h-4" />,
    },
    {
      id: 'compose',
      label: 'Multi-Tab Composer',
      icon: <Send className="w-4 h-4" />,
    },
    {
      id: 'history',
      label: 'Post Log & Analytics',
      icon: <BarChart3 className="w-4 h-4" />,
      badge: scheduledCount > 0 ? `${scheduledCount}` : undefined,
    },
    {
      id: 'extension',
      label: 'Chrome Extension',
      icon: <Chrome className="w-4 h-4" />,
    },
  ];

  return (
    <nav className="border-b border-slate-800 bg-slate-900/60 sticky top-[61px] z-30 px-4 lg:px-8">
      <div className="max-w-7xl mx-auto flex items-center gap-1 overflow-x-auto no-scrollbar py-2">
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onChangeTab(item.id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                isActive
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/25'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              {item.icon}
              <span>{item.label}</span>
              {item.badge && (
                <span
                  className={`text-[9px] px-1.5 py-0.2 rounded-full font-bold ${
                    item.badgeColor
                      ? item.badgeColor
                      : isActive
                      ? 'bg-white/20 text-white'
                      : 'bg-slate-700 text-slate-300'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
};
