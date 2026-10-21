import React, { useState } from 'react';
import {
  X,
  Check,
  Crown,
  Zap,
  Sparkles,
  Flame,
  ShieldCheck,
  CreditCard,
  ExternalLink,
  Copy,
  Users,
  Lock,
} from 'lucide-react';
import { PlanTier, UserSubscription } from '../types.ts';

interface UpgradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  subscription: UserSubscription;
  onSelectPlan: (plan: PlanTier) => void;
}

export const UpgradeModal: React.FC<UpgradeModalProps> = ({
  isOpen,
  onClose,
  subscription,
  onSelectPlan,
}) => {
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'annual'>('annual');
  const [isProcessing, setIsProcessing] = useState<string | null>(null);
  const [copiedAffiliate, setCopiedAffiliate] = useState(false);
  const [statusNotice, setStatusNotice] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleCheckout = async (plan: PlanTier) => {
    if (plan === 'free') {
      onSelectPlan('free');
      onClose();
      return;
    }

    setIsProcessing(plan);
    try {
      const res = await fetch('/api/stripe/create-checkout-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan,
          interval: billingCycle === 'annual' ? 'year' : 'month',
        }),
      });

      const data = await res.json();

      if (data.url) {
        // Redirect directly to live Stripe Checkout page
        window.location.href = data.url;
      } else {
        // Instant activation mode
        onSelectPlan(plan);
        setStatusNotice(
          `🎉 Successfully activated ${plan === 'premium' ? 'Premium VIP' : 'Creator Pro'}! ${
            data.message || 'Ready for unlimited publishing.'
          }`
        );
        setTimeout(() => {
          setIsProcessing(null);
          onClose();
        }, 1500);
      }
    } catch (err) {
      // Fallback
      onSelectPlan(plan);
      onClose();
    } finally {
      setIsProcessing(null);
    }
  };

  const handleCopyAffiliate = () => {
    const affiliateUrl = 'https://perfectposts.app/?ref=NickPerciballi';
    navigator.clipboard.writeText(affiliateUrl);
    setCopiedAffiliate(true);
    setTimeout(() => setCopiedAffiliate(false), 2500);
  };

  const isAnnual = billingCycle === 'annual';

  const plans = [
    {
      id: 'free' as PlanTier,
      name: 'Free Plan',
      price: '$0',
      period: 'forever',
      description: 'Unlimited posting with 2 connected social channels and trademark attribution.',
      badge: 'Free Forever',
      features: [
        'Unlimited free posts & publishing',
        'Choose up to 2 social networks',
        'Mandatory "Streamlined with Perfect Posts" link & badge',
        'Standard 1 GB Media Vault Storage',
        'Standard photo download & aspect cropping',
        'Chrome extension browser companion',
      ],
      cta: 'Current Plan',
      popular: false,
    },
    {
      id: 'pro' as PlanTier,
      name: 'Creator Pro',
      price: isAnnual ? '$5.00' : '$7',
      annualTotal: '$60 billed yearly (only $5/mo)',
      period: isAnnual ? 'mo (billed $60/yr)' : 'per month',
      description: 'Ideal for creators wanting 5 networks, 5MP upscaling, and no mandatory attribution.',
      badge: 'PRO CREATOR',
      features: [
        'Unlimited free posts & publishing',
        'Select up to 5 social networks',
        'AI Upscaler up to 5 Megapixels (5MP)',
        'Remove mandatory trademark logo & description link',
        'Custom watermark logos & branding studio',
        'Standard AI photo editing & retouching',
        '100 GB High-Speed Cloud Storage',
        'Standard post log analytics',
      ],
      cta: 'Upgrade to Pro',
      popular: true,
    },
    {
      id: 'premium' as PlanTier,
      name: 'Premium VIP',
      price: isAnnual ? '$8.33' : '$12',
      annualTotal: '$100 billed yearly (only $8.33/mo)',
      period: isAnnual ? 'mo (billed $100/yr)' : 'per month',
      description: 'The ultimate powerhouse: unlimited networks, 10MP upscaling, full video studio, and 1 TB storage.',
      badge: '👑 PREMIUM VIP',
      features: [
        'Unlimited free posts & publishing',
        'Unlimited social networks (all platforms + custom)',
        'Ultra AI Upscaler up to 10 Megapixels (10MP)',
        'Full Video Studio: trimming & stitching videos together',
        'Multi-video clip reformatting (9:16 reels & TikTok)',
        'All photo & video editing features unlocked',
        'Full analytics, viral scores, headlines & ROI charts',
        'Massive 1 Terabyte (1,000 GB) Media Vault',
        'Priority high-speed processing & automated sync',
      ],
      cta: 'Upgrade to Premium',
      popular: false,
    },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl w-full max-w-4xl max-h-[92vh] overflow-y-auto shadow-2xl p-6 sm:p-8 relative">
        <button
          onClick={onClose}
          className="absolute top-5 right-5 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="text-center max-w-xl mx-auto mb-6">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gradient-to-r from-amber-500/20 to-indigo-500/20 text-amber-300 border border-amber-500/30 text-xs font-bold mb-3">
            <Crown className="w-3.5 h-3.5 text-amber-400" />
            Monetization & Creator Scaling Architecture
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            Supercharge Your Reach & Eliminate All Limits
          </h2>
          <p className="text-slate-400 text-xs sm:text-sm mt-2">
            Stripe-secured billing. Unlock unlimited social channels, 10MP photo upscaling, 9:16 Video Studio, and remove all mandatory attribution backlinks.
          </p>

          {/* Monthly vs Annual Toggle */}
          <div className="mt-5 inline-flex items-center gap-2 p-1 rounded-xl bg-slate-950 border border-slate-800 text-xs font-bold">
            <button
              type="button"
              onClick={() => setBillingCycle('monthly')}
              className={`px-3 py-1.5 rounded-lg transition ${
                billingCycle === 'monthly'
                  ? 'bg-slate-800 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Monthly Billing
            </button>
            <button
              type="button"
              onClick={() => setBillingCycle('annual')}
              className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition ${
                billingCycle === 'annual'
                  ? 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <span>Annual Billing</span>
              <span className="text-[10px] font-black px-1.5 py-0.2 rounded-full bg-amber-400 text-slate-950">
                $100/YR SPECIAL DEAL
              </span>
            </button>
          </div>
        </div>

        {statusNotice && (
          <div className="mb-6 p-3 rounded-xl bg-emerald-950/80 border border-emerald-500/50 text-emerald-200 text-xs text-center font-bold animate-in fade-in">
            {statusNotice}
          </div>
        )}

        {/* Plan Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {plans.map((p) => {
            const isCurrent = subscription.plan === p.id;
            const loading = isProcessing === p.id;

            return (
              <div
                key={p.id}
                className={`relative rounded-xl p-5 flex flex-col justify-between transition-all ${
                  p.popular
                    ? 'bg-slate-850 border-2 border-indigo-500 shadow-xl shadow-indigo-500/15'
                    : 'bg-slate-800/60 border border-slate-750'
                }`}
              >
                {p.popular ? (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-gradient-to-r from-amber-500 to-yellow-400 text-slate-950 text-[11px] font-black tracking-wide uppercase shadow">
                    MOST POPULAR
                  </div>
                ) : p.badge ? (
                  <div
                    className={`absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full text-[10px] font-black tracking-wider uppercase shadow ${
                      p.id === 'premium'
                        ? 'bg-gradient-to-r from-purple-600 via-indigo-600 to-cyan-500 text-white'
                        : 'bg-slate-700 text-slate-300 border border-slate-600'
                    }`}
                  >
                    {p.badge}
                  </div>
                ) : null}

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <h3 className="text-base font-bold text-white flex items-center gap-1.5">
                      {p.name}
                      {p.id === 'pro' && <Flame className="w-4 h-4 text-amber-400" />}
                      {p.id === 'premium' && <Crown className="w-4 h-4 text-yellow-400" />}
                    </h3>
                  </div>
                  <div className="flex items-baseline gap-1 my-2">
                    <span className="text-3xl font-extrabold text-white">{p.price}</span>
                    <span className="text-xs text-slate-400">/{p.period}</span>
                  </div>
                  {p.annualTotal && isAnnual && (
                    <div className="text-[11px] font-semibold text-emerald-400 mb-2">
                      {p.annualTotal}
                    </div>
                  )}
                  <p className="text-xs text-slate-400 mb-4 leading-relaxed">
                    {p.description}
                  </p>

                  <div className="space-y-2 mb-6">
                    {p.features.map((f, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs text-slate-300">
                        <Check className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                        <span>{f}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => handleCheckout(p.id)}
                  disabled={isCurrent || Boolean(isProcessing)}
                  className={`w-full py-2.5 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 ${
                    isCurrent
                      ? 'bg-slate-800 text-slate-400 border border-slate-700 cursor-default'
                      : p.popular
                      ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30'
                      : 'bg-slate-700 hover:bg-slate-650 text-white'
                  }`}
                >
                  {loading ? (
                    <>
                      <Zap className="w-4 h-4 animate-spin text-amber-300" /> Connecting to Stripe...
                    </>
                  ) : isCurrent ? (
                    <>
                      <Check className="w-4 h-4 text-emerald-400" /> Active Plan
                    </>
                  ) : (
                    <>
                      <CreditCard className="w-4 h-4" /> {p.cta}
                    </>
                  )}
                </button>
              </div>
            );
          })}
        </div>

        {/* Affiliate Program Callout (Monetization Driver) */}
        <div className="mt-6 p-4 rounded-xl bg-gradient-to-r from-slate-950 via-indigo-950/40 to-slate-950 border border-indigo-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2 text-xs font-bold text-amber-300">
              <Users className="w-4 h-4 text-amber-400" />
              <span>Creator Affiliate Program • 30% Recurring Monthly Commission</span>
            </div>
            <p className="text-[11px] text-slate-400">
              Refer fellow creators, agencies, or influencers. Earn $2.10 (Pro) to $3.60 (Premium) every month for each subscriber you refer!
            </p>
          </div>

          <button
            type="button"
            onClick={handleCopyAffiliate}
            className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition shadow"
          >
            {copiedAffiliate ? <Check className="w-3.5 h-3.5 text-emerald-300" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedAffiliate ? 'Affiliate Link Copied!' : 'Copy My Referral Link'}</span>
          </button>
        </div>

        {/* Footer Guarantee & Trust Badges */}
        <div className="mt-6 pt-5 border-t border-slate-800 flex flex-wrap items-center justify-between gap-4 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>14-day money-back guarantee • Stripe 256-bit encrypted checkout</span>
          </div>
          <div className="flex items-center gap-2 text-slate-500">
            <Lock className="w-3.5 h-3.5 text-slate-500" />
            <span>Cancel anytime from your account settings</span>
          </div>
        </div>
      </div>
    </div>
  );
};

