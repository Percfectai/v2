import React from 'react';

interface PerfectPostsLogoProps {
  size?: number; // size in px, default 40
  showCrownGlow?: boolean;
  className?: string;
  withText?: boolean;
  tagline?: string;
}

export const PerfectPostsLogo: React.FC<PerfectPostsLogoProps> = ({
  size = 40,
  showCrownGlow = true,
  className = '',
  withText = false,
  tagline,
}) => {
  return (
    <div className={`inline-flex items-center gap-3 select-none ${className}`}>
      <div
        className="relative shrink-0 flex items-center justify-center rounded-xl overflow-visible"
        style={{ width: size, height: size }}
      >
        {/* Ambient background glow matching the cyber lightning */}
        {showCrownGlow && (
          <div
            className="absolute inset-0 rounded-xl bg-gradient-to-tr from-cyan-500/30 via-amber-500/20 to-yellow-400/25 blur-md -z-10 animate-pulse"
            style={{ transform: 'scale(1.2)' }}
          />
        )}

        <svg
          viewBox="0 0 100 100"
          width={size}
          height={size}
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-full drop-shadow-[0_4px_12px_rgba(0,0,0,0.6)]"
        >
          <defs>
            {/* Crown Gold Gradients */}
            <linearGradient id="crownGold" x1="10%" y1="0%" x2="90%" y2="100%">
              <stop offset="0%" stopColor="#FFF2A3" />
              <stop offset="30%" stopColor="#F5B324" />
              <stop offset="60%" stopColor="#E2920D" />
              <stop offset="100%" stopColor="#965600" />
            </linearGradient>

            <linearGradient id="crownRim" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#B3780E" />
              <stop offset="50%" stopColor="#FED766" />
              <stop offset="100%" stopColor="#7A4500" />
            </linearGradient>

            {/* Cyber Metallic Letter P Gradients */}
            <linearGradient id="metalBevelLight" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#FFFFFF" />
              <stop offset="25%" stopColor="#B6C4D4" />
              <stop offset="55%" stopColor="#5B6A7F" />
              <stop offset="85%" stopColor="#252F3F" />
              <stop offset="100%" stopColor="#111621" />
            </linearGradient>

            <linearGradient id="metalCore" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#3B485A" />
              <stop offset="50%" stopColor="#1E2736" />
              <stop offset="100%" stopColor="#0D131C" />
            </linearGradient>

            {/* Neon Cyan Circuit Glow */}
            <linearGradient id="cyanCircuit" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#A5F3FC" />
              <stop offset="50%" stopColor="#06B6D4" />
              <stop offset="100%" stopColor="#0284C7" />
            </linearGradient>

            {/* Lightning bolt gradient */}
            <linearGradient id="lightningGlow" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#E0F2FE" />
              <stop offset="40%" stopColor="#38BDF8" />
              <stop offset="100%" stopColor="#0284C7" />
            </linearGradient>

            {/* Filter for glowing circuit traces */}
            <filter id="neonGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.5" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Background Rounded Shield / Icon Plate */}
          <rect
            x="4"
            y="4"
            width="92"
            height="92"
            rx="22"
            fill="#090D15"
            stroke="#1E293B"
            strokeWidth="2"
          />

          {/* Electric Lightning Bolt Behind Crown / P */}
          <path
            d="M 47 6 L 44 24 L 52 24 L 46 45"
            stroke="url(#lightningGlow)"
            strokeWidth="2.2"
            strokeLinecap="round"
            filter="url(#neonGlow)"
            opacity="0.9"
          />

          {/* ========================================================
              CYBERNETIC 3D LETTER "P"
          ======================================================== */}
          {/* Drop shadow of the P */}
          <path
            d="M 32 32 L 61 32 C 73 32 79 40 79 50 C 79 60 72 68 60 68 L 47 68 L 47 90 L 32 90 Z"
            fill="#020617"
            opacity="0.8"
            transform="translate(2, 3)"
          />

          {/* Outer Bevel Frame of Letter P */}
          <path
            d="M 31 31 L 62 31 C 74 31 81 40 81 50 C 81 60 74 69 61 69 L 47 69 L 47 90 L 31 90 Z"
            fill="url(#metalBevelLight)"
            stroke="#475569"
            strokeWidth="1"
          />

          {/* Inner Recessed Metal Plate */}
          <path
            d="M 35 35 L 60 35 C 69 35 75 42 75 50 C 75 58 69 65 59 65 L 44 65 L 44 86 L 35 86 Z"
            fill="url(#metalCore)"
          />

          {/* Hollow Bowl of the Letter P */}
          <path
            d="M 44 42 L 58 42 C 63 42 67 45 67 50 C 67 55 63 58 58 58 L 44 58 Z"
            fill="#090D15"
            stroke="#334155"
            strokeWidth="1.2"
          />

          {/* Cyber Circuit Traces & Dots inside the P Stem & Bowl */}
          {/* Vertical stem circuit line */}
          <line
            x1="39"
            y1="40"
            x2="39"
            y2="82"
            stroke="url(#cyanCircuit)"
            strokeWidth="1.6"
            strokeLinecap="round"
            filter="url(#neonGlow)"
          />
          {/* Stem circuit branch */}
          <path
            d="M 39 52 L 42 55 L 42 72"
            stroke="url(#cyanCircuit)"
            strokeWidth="1.2"
            fill="none"
            filter="url(#neonGlow)"
          />
          {/* Circuit nodes (dots) */}
          <circle cx="39" cy="40" r="1.8" fill="#38BDF8" />
          <circle cx="39" cy="82" r="1.8" fill="#38BDF8" />
          <circle cx="42" cy="72" r="1.4" fill="#38BDF8" />

          {/* Horizontal circuit lines in loop */}
          <path
            d="M 68 50 C 68 56 64 61 58 61"
            stroke="url(#cyanCircuit)"
            strokeWidth="1.2"
            fill="none"
            opacity="0.85"
          />

          {/* Bottom bevel claw notch */}
          <polygon
            points="31,75 36,78 31,81"
            fill="#94A3B8"
          />

          {/* ========================================================
              ROYAL ORNATE GOLDEN CROWN (Tilted atop Letter P)
          ======================================================== */}
          <g transform="translate(19, 7) rotate(-11 40 25)">
            {/* Crown Base Ring / Filigree */}
            <path
              d="M 16 28 C 28 32, 48 32, 60 28 L 62 31 C 48 36, 28 36, 14 31 Z"
              fill="url(#crownRim)"
              stroke="#543100"
              strokeWidth="0.8"
            />

            {/* Jewels on Rim */}
            <circle cx="23" cy="30.5" r="1.3" fill="#38BDF8" stroke="#164E63" strokeWidth="0.4" />
            <circle cx="32" cy="31.8" r="1.4" fill="#EF4444" stroke="#7F1D1D" strokeWidth="0.4" />
            <circle cx="42" cy="31.8" r="1.5" fill="#10B981" stroke="#064E3B" strokeWidth="0.4" />
            <circle cx="51" cy="30.5" r="1.3" fill="#38BDF8" stroke="#164E63" strokeWidth="0.4" />

            {/* Crown Peaks and Spikes */}
            <path
              d="M 15 28 
                 L 13 14 
                 L 24 23 
                 L 31 10 
                 L 38 23 
                 L 49 8 
                 L 52 24 
                 L 61 15 
                 L 59 28 
                 Z"
              fill="url(#crownGold)"
              stroke="#683C00"
              strokeWidth="1"
              strokeLinejoin="round"
            />

            {/* Golden orbs / pearls on tips of spikes */}
            <circle cx="13" cy="13" r="2.2" fill="#FED766" stroke="#9A5802" strokeWidth="0.6" />
            <circle cx="31" cy="9" r="2.4" fill="#FED766" stroke="#9A5802" strokeWidth="0.6" />
            <circle cx="49" cy="7" r="2.8" fill="#FFF2A3" stroke="#B45309" strokeWidth="0.7" />
            <circle cx="61" cy="14" r="2.2" fill="#FED766" stroke="#9A5802" strokeWidth="0.6" />

            {/* Inner Crown Carved Relief / Diamond engraving */}
            <polygon
              points="38,15 42,20 38,25 34,20"
              fill="#FDE68A"
              stroke="#B45309"
              strokeWidth="0.6"
            />
            <circle cx="38" cy="20" r="1.2" fill="#EF4444" />
          </g>
        </svg>
      </div>

      {withText && (
        <div className="flex flex-col">
          <div className="flex items-center gap-1.5">
            <span className="font-extrabold text-white tracking-tight text-base sm:text-lg">
              The Percfect Post
            </span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-black uppercase tracking-wider bg-gradient-to-r from-amber-500/20 to-yellow-500/20 text-amber-300 border border-amber-500/30">
              PRO
            </span>
          </div>
          {tagline && <span className="text-[11px] text-slate-400">{tagline}</span>}
        </div>
      )}
    </div>
  );
};
