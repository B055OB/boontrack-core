'use client';

import React, { useState, useEffect, useMemo } from 'react';
import {
  Sparkles,
  Check,
  LayoutTemplate,
  ArrowRight,
  TrendingUp,
  Eye,
  MessageSquare,
  Receipt,
  Wallet,
  Newspaper,
  ShoppingBag,
  Layers,
  Filter,
} from 'lucide-react';
import { ProductItem } from '@/lib/product-catalog';
import { getStorefrontUrl } from '@/lib/utils/storefrontUrl';
import { getSupabase } from '@/lib/supabaseClient';
import StoreBioLinkWidget from '@/app/[tenant]/dashboard/components/StoreBioLinkWidget';
import AiSessionQuotaMeter from '@/app/[tenant]/dashboard/components/AiSessionQuotaMeter';
import BoonPilotQueryBar, { BoonPilotFilters } from '@/components/BoonPilotQueryBar';
import { isValidPaidStatus, extractOrderAmount } from '@/lib/finance-engine';
import { formatCurrency } from '@/lib/i18n';

interface DashboardOverviewTabProps {
  tenantSlug: string;
  displayName: string;
  storeDisplayName?: string;
  storeBio?: string;
  storeLogoUrl?: string;
  storeQrisUrl?: string;
  waStatus: string;
  connectedPhone?: string | null;
  products: ProductItem[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  transactions: any[];
  totalOmzet: number;
  isTeamScale?: boolean;
  isAdsPerformance?: boolean;
  isSoloOrTrial?: boolean;
  isCheckoutLite?: boolean;
  isTrialActive?: boolean;
  tierLabel?: string;
  trialDaysLeft?: number | null;
  storeCategory?: string;
  chatConversationsCount?: number;
  onOpenStoreSettings: () => void;
  onOpenNewProduct: () => void;
  onApplyPitch?: (patch: Partial<ProductItem>) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onNavigateTab: (tab: any) => void;
  onSavedFeedback?: (msg: string) => void;
  customDomain?: string | null;
}

export default function DashboardOverviewTab({
  tenantSlug,
  displayName,
  storeDisplayName,
  storeBio,
  storeLogoUrl,
  storeQrisUrl,
  waStatus,
  connectedPhone,
  products = [],
  transactions = [],
  totalOmzet = 0,
  isTeamScale = false,
  isAdsPerformance = false,
  isSoloOrTrial = false,
  isCheckoutLite = false,
  isTrialActive = false,
  tierLabel,
  trialDaysLeft,
  storeCategory,
  chatConversationsCount,
  onOpenStoreSettings,
  onOpenNewProduct,
  onApplyPitch,
  onNavigateTab,
  onSavedFeedback,
  customDomain,
}: DashboardOverviewTabProps) {
  const [hasCopiedUrl, setHasCopiedUrl] = useState(false);
  const [activeTemplate, setActiveTemplate] = useState<'default' | 'microsite' | 'personal'>('default');
  const [isUpdatingTemplate, setIsUpdatingTemplate] = useState(false);

  const activeStoreName = storeDisplayName || displayName;
  const storePublicUrl = getStorefrontUrl(tenantSlug, customDomain);

  // Time of day greeting
  const timeGreeting = useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 11) return 'Pagi';
    if (hour < 15) return 'Siang';
    if (hour < 18) return 'Sore';
    return 'Malam';
  }, []);

  const [hasCompletedSetup, setHasCompletedSetup] = useState<boolean>(false);

  // Fetch active storefront template & persistent onboarding status from Supabase / localStorage
  useEffect(() => {
    let isMounted = true;

    // 1. Initial check from localStorage (instant, zero flicker)
    try {
      if (typeof window !== 'undefined') {
        const cached = localStorage.getItem(`boontrack_${tenantSlug}_onboarding_completed`);
        if (cached === 'true') {
          setHasCompletedSetup(true);
        }
      }
    } catch {}

    async function loadTenantData() {
      try {
        const supabase = getSupabase();
        if (!supabase) return;

        const tenantRes = await supabase
          .from('tenants')
          .select('id, metadata')
          .eq('slug', tenantSlug)
          .maybeSingle();

        if (isMounted) {
          const meta = tenantRes.data?.metadata || {};
          const t =
            meta.selected_template ||
            meta.storefront_template ||
            meta.template ||
            meta.theme?.template ||
            'default';
          if (t === 'microsite' || t === 'personal') {
            setActiveTemplate(t);
          } else {
            setActiveTemplate('default');
          }

          // Evaluate persistent onboarding completion
          const isPersistedInDb = Boolean(meta.onboarding_completed || meta.has_completed_setup);
          const isCriteriaMet = Boolean(
            isPersistedInDb ||
              (products &&
                products.length > 0 &&
                ((storeQrisUrl && storeQrisUrl.trim() !== '') ||
                  waStatus === 'CONNECTED' ||
                  Boolean(connectedPhone) ||
                  (transactions && transactions.length > 0)))
          );

          if (isCriteriaMet) {
            setHasCompletedSetup(true);
            try {
              if (typeof window !== 'undefined') {
                localStorage.setItem(`boontrack_${tenantSlug}_onboarding_completed`, 'true');
              }
            } catch {}

            // Persist to Supabase if not yet marked
            if (!isPersistedInDb && tenantRes.data?.id) {
              const updatedMeta = { ...meta, onboarding_completed: true };
              await supabase
                .from('tenants')
                .update({ metadata: updatedMeta })
                .eq('id', tenantRes.data.id);
            }
          }
        }
      } catch (err) {
        console.warn('Gagal memuat konfigurasi tenant di dashboard:', err);
      }
    }
    loadTenantData();
    return () => {
      isMounted = false;
    };
  }, [tenantSlug, products, storeQrisUrl, waStatus, connectedPhone, transactions]);

  // Handle template selection
  const handleSelectTemplate = async (templateKey: 'default' | 'microsite' | 'personal') => {
    if (isUpdatingTemplate || activeTemplate === templateKey) return;
    setIsUpdatingTemplate(true);
    setActiveTemplate(templateKey);

    try {
      // 1. Direct update to Supabase tenants.metadata
      const supabase = getSupabase();
      const { data: tenantRow } = await supabase
        .from('tenants')
        .select('id, metadata')
        .eq('slug', tenantSlug)
        .maybeSingle();

      if (tenantRow?.id) {
        const updatedMeta = {
          ...(tenantRow.metadata || {}),
          selected_template: templateKey,
          storefront_template: templateKey,
          template: templateKey,
          theme: {
            ...(tenantRow.metadata?.theme || {}),
            template: templateKey,
          },
        };
        await supabase
          .from('tenants')
          .update({ metadata: updatedMeta })
          .eq('id', tenantRow.id);
      }

      // 2. Sync via settings API route
      await fetch(`/api/v1/tenants/${encodeURIComponent(tenantSlug)}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template: templateKey,
          theme: { template: templateKey },
        }),
      });

      if (onSavedFeedback) {
        const nameMap: Record<string, string> = {
          default: 'Katalog Toko (Default)',
          microsite: 'Microsite Bio-Link',
          personal: 'Personal Brand & Authority',
        };
        onSavedFeedback(`✅ Template etalase berhasil diubah ke ${nameMap[templateKey]}!`);
      }
    } catch (err) {
      console.warn('Gagal menyimpan template etalase:', err);
    } finally {
      setIsUpdatingTemplate(false);
    }
  };

  const handleCopyStoreLink = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(storePublicUrl);
      } else if (typeof document !== 'undefined') {
        const textArea = document.createElement('textarea');
        textArea.value = storePublicUrl;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      setHasCopiedUrl(true);
      if (onSavedFeedback) onSavedFeedback('Tautan toko berhasil disalin!');
      setTimeout(() => setHasCopiedUrl(false), 2500);
    } catch (err) {
      console.warn('Gagal menyalin tautan toko:', err);
    }
  };

  // Status indikator toko & onboarding
  const isPlatformPhone = Boolean(
    connectedPhone &&
      (connectedPhone.includes('85181830080') ||
        connectedPhone.includes('85179555449') ||
        connectedPhone.includes('85139555449'))
  );
  const isWaConnected = (waStatus === 'CONNECTED' || Boolean(connectedPhone)) && !isPlatformPhone;
  const isProductAdded = products.length > 0;

  // ── REACTIVE AI FILTER STATE & MEMOIZED DATASET FILTERING ──
  const [activeAiFilter, setActiveAiFilter] = useState<BoonPilotFilters | null>(null);

  const isAiFilterActive = Boolean(
    activeAiFilter &&
      (activeAiFilter.summaryText ||
        activeAiFilter.timeRange !== 'last_7_days' ||
        activeAiFilter.paymentMethod !== 'all' ||
        activeAiFilter.channel !== 'all' ||
        activeAiFilter.status !== 'all' ||
        activeAiFilter.groupBy !== 'date')
  );

  // Helper to resolve payment method category from transaction record
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const resolveOrderPaymentMethod = (t: any): 'qris' | 'dodo_mor' => {
    const rawMethod = String(
      t.payment_method || t.payment_rail || t.method || t.gateway || ''
    ).toLowerCase();
    if (
      rawMethod.includes('dodo') ||
      rawMethod.includes('mor') ||
      rawMethod.includes('stripe') ||
      rawMethod.includes('card') ||
      rawMethod.includes('cc')
    ) {
      return 'dodo_mor';
    }
    return 'qris';
  };

  // Helper to resolve channel category from transaction record
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const resolveOrderChannel = (t: any): 'ctwa' | 'web' | 'studio' => {
    const rawChannel = String(
      t.channel || t.source_channel || t.utm_source || t.order_source || t.source || ''
    ).toLowerCase();
    if (rawChannel.includes('studio') || rawChannel.includes('internal')) {
      return 'studio';
    }
    if (
      rawChannel.includes('web') ||
      rawChannel.includes('storefront') ||
      rawChannel.includes('catalog') ||
      rawChannel.includes('bio')
    ) {
      return 'web';
    }
    return 'ctwa';
  };

  // Helper to check if order status is pending
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const isOrderPending = (t: any): boolean => {
    const rawStatus = String(t.payment_status || t.status || '').toLowerCase();
    return (
      rawStatus === 'pending' ||
      rawStatus === 'unpaid' ||
      rawStatus === 'waiting' ||
      rawStatus === 'awaiting_payment'
    );
  };

  // Memoized filteredOrders bound to activeAiFilter
  const filteredOrders = useMemo(() => {
    if (!transactions || transactions.length === 0) return [];

    const now = Date.now();
    const startOfToday = new Date();
    startOfToday.setHours(0, 0, 0, 0);

    const startOfCurrentMonth = new Date();
    startOfCurrentMonth.setDate(1);
    startOfCurrentMonth.setHours(0, 0, 0, 0);

    const timeRange = activeAiFilter?.timeRange || 'last_7_days';
    const paymentMethod = activeAiFilter?.paymentMethod || 'all';
    const channel = activeAiFilter?.channel || 'all';
    const status = activeAiFilter?.status || 'all';

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return transactions.filter((t: any) => {
      // 1. Time Range filter
      const rawDate = t.created_at || t.date || t.updated_at;
      const tTime = rawDate ? new Date(rawDate).getTime() : NaN;
      if (!isNaN(tTime)) {
        if (timeRange === 'today') {
          const twentyFourHoursAgo = now - 24 * 60 * 60 * 1000;
          if (tTime < Math.min(startOfToday.getTime(), twentyFourHoursAgo)) return false;
        } else if (timeRange === 'yesterday') {
          const fortyEightHoursAgo = now - 48 * 60 * 60 * 1000;
          const twentyFourHoursAgo = now - 24 * 60 * 60 * 1000;
          if (tTime < fortyEightHoursAgo || tTime > twentyFourHoursAgo) return false;
        } else if (timeRange === 'last_7_days') {
          if (tTime < now - 7 * 24 * 60 * 60 * 1000) return false;
        } else if (timeRange === 'last_30_days') {
          if (tTime < now - 30 * 24 * 60 * 60 * 1000) return false;
        } else if (timeRange === 'current_month') {
          if (tTime < startOfCurrentMonth.getTime()) return false;
        }
      }

      // 2. Payment Method filter
      if (paymentMethod !== 'all') {
        const orderPayMethod = resolveOrderPaymentMethod(t);
        if (orderPayMethod !== paymentMethod) return false;
      }

      // 3. Channel filter
      if (channel !== 'all') {
        const orderChannel = resolveOrderChannel(t);
        if (orderChannel !== channel) return false;
      }

      // 4. Status filter
      if (status !== 'all') {
        const rawStatus = t.payment_status || t.status;
        if (status === 'pending') {
          if (!isOrderPending(t)) return false;
        } else if (status === 'completed' || status === 'paid' || status === 'settled') {
          if (!isValidPaidStatus(rawStatus)) return false;
        }
      }

      return true;
    });
  }, [transactions, activeAiFilter]);

  const [realVisits, setRealVisits] = useState<number | null>(null);
  const [realChatSessions, setRealChatSessions] = useState<number | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function loadAnalyticsSummary() {
      if (!tenantSlug) return;
      try {
        const res = await fetch(
          `/api/v1/tenants/${encodeURIComponent(tenantSlug)}/analytics/summary`,
          {
            cache: 'no-store',
          }
        );
        if (res.ok) {
          const json = await res.json();
          if (json.success && isMounted) {
            setRealVisits(typeof json.visits === 'number' ? json.visits : 0);
            setRealChatSessions(typeof json.chat_sessions === 'number' ? json.chat_sessions : 0);
          }
        }
      } catch (err) {
        console.warn('Gagal memuat ringkasan analitik:', err);
      }
    }
    loadAnalyticsSummary();
    return () => {
      isMounted = false;
    };
  }, [tenantSlug]);

  const totalVisits = realVisits !== null ? realVisits : 0;

  // ── DYNAMIC 4 QUICK METRIC CARDS BOUND TO filteredOrders ──

  // 1. Omzet Toko: SUM nilai order yang cocok dengan filter
  const filteredOmzet = useMemo(() => {
    if (!transactions || transactions.length === 0) {
      if (isAiFilterActive && activeAiFilter?.status === 'pending') return 0;
      return totalOmzet > 0 && !isAiFilterActive ? totalOmzet : 0;
    }

    if (activeAiFilter?.status === 'pending') {
      return filteredOrders.reduce((sum: number, t: any) => sum + extractOrderAmount(t), 0);
    }

    const matchingPaid = filteredOrders.filter((t: any) =>
      isValidPaidStatus(t.payment_status || t.status)
    );
    const calculated = matchingPaid.reduce(
      (sum: number, t: any) => sum + extractOrderAmount(t),
      0
    );

    if (calculated > 0) return calculated;
    return !isAiFilterActive && totalOmzet > 0 ? totalOmzet : 0;
  }, [filteredOrders, transactions, totalOmzet, isAiFilterActive, activeAiFilter]);

  // 2. Pesanan Baru: COUNT order closing yang cocok dengan filter
  const filteredClosingOrdersCount = useMemo(() => {
    if (!filteredOrders || filteredOrders.length === 0) return 0;
    if (activeAiFilter?.status === 'pending') {
      return 0;
    }
    const paidOrders = filteredOrders.filter((t: any) =>
      isValidPaidStatus(t.payment_status || t.status)
    );
    return paidOrders.length > 0 ? paidOrders.length : filteredOrders.length;
  }, [filteredOrders, activeAiFilter]);

  // 3. QRIS Pending: COUNT order QRIS berstatus pending dalam populasi terfilter
  const filteredPendingQrisCount = useMemo(() => {
    if (!filteredOrders || filteredOrders.length === 0) return 0;
    return filteredOrders.filter((t: any) => {
      return isOrderPending(t) && resolveOrderPaymentMethod(t) === 'qris';
    }).length;
  }, [filteredOrders]);

  // 4. Trafik Interaksi: Total interaksi sesuai filter
  const baseChatInteractions = useMemo(() => {
    if (realChatSessions !== null) return realChatSessions;
    if (chatConversationsCount !== undefined && chatConversationsCount !== null) {
      return chatConversationsCount;
    }
    return 0;
  }, [realChatSessions, chatConversationsCount]);

  const filteredInteractionsCount = useMemo(() => {
    if (!isAiFilterActive) return baseChatInteractions;
    if (filteredOrders.length > 0 && transactions.length > 0) {
      const ratio = filteredOrders.length / Math.max(transactions.length, 1);
      return Math.max(filteredOrders.length, Math.round(baseChatInteractions * ratio));
    }
    if (activeAiFilter?.channel && activeAiFilter.channel !== 'all' && activeAiFilter.channel !== 'ctwa') {
      return filteredOrders.length;
    }
    if (activeAiFilter?.timeRange === 'today') {
      return Math.ceil(baseChatInteractions / 7);
    }
    return baseChatInteractions;
  }, [isAiFilterActive, filteredOrders, transactions, baseChatInteractions, activeAiFilter]);

  // ── GROUPED ANALYTICS BREAKDOWN ROWS FOR REACTIVE TABLE ──
  const groupedAnalyticsRows = useMemo(() => {
    const groupBy = activeAiFilter?.groupBy || 'date';
    const map = new Map<
      string,
      { key: string; label: string; orderCount: number; paidAmount: number; pendingCount: number }
    >();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    filteredOrders.forEach((t: any) => {
      let groupKey = 'Lainnya';
      let groupLabel = 'Lainnya';

      if (groupBy === 'affiliate') {
        groupKey = String(t.affiliate_code || t.affiliate_id || t.referral_code || 'direct_organic');
        groupLabel =
          groupKey === 'direct_organic' ? 'Organik / Langsung (Tanpa Afiliasi)' : `Afiliasi: ${groupKey}`;
      } else if (groupBy === 'channel') {
        const ch = resolveOrderChannel(t);
        groupKey = ch;
        groupLabel =
          ch === 'ctwa'
            ? 'Chat-to-WhatsApp (CTWA)'
            : ch === 'web'
            ? 'Web Storefront'
            : 'BoonTrack Studio';
      } else if (groupBy === 'payment_rail') {
        const pm = resolveOrderPaymentMethod(t);
        groupKey = pm;
        groupLabel = pm === 'qris' ? 'QRIS Otomatis' : 'Dodo MoR Gateway';
      } else if (groupBy === 'tenant') {
        groupKey = tenantSlug;
        groupLabel = activeStoreName;
      } else {
        const rawDate = t.created_at || t.date || t.updated_at;
        const d = rawDate ? new Date(rawDate) : null;
        if (d && !isNaN(d.getTime())) {
          groupKey = d.toISOString().slice(0, 10);
          groupLabel = d.toLocaleDateString('id-ID', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
          });
        } else {
          groupKey = 'hari-ini';
          groupLabel = 'Periode Berjalan';
        }
      }

      const existing = map.get(groupKey) || {
        key: groupKey,
        label: groupLabel,
        orderCount: 0,
        paidAmount: 0,
        pendingCount: 0,
      };

      existing.orderCount += 1;
      if (isOrderPending(t)) {
        existing.pendingCount += 1;
      }
      if (isValidPaidStatus(t.payment_status || t.status) || activeAiFilter?.status === 'pending') {
        existing.paidAmount += extractOrderAmount(t);
      }

      map.set(groupKey, existing);
    });

    return Array.from(map.values()).slice(0, 8);
  }, [filteredOrders, activeAiFilter, tenantSlug, activeStoreName]);

  const handleOpenBoonPilotOnboarding = () => {
    const onboardingPrompt =
      'Halo BoonPilot, saya baru buka toko. Tolong bantu dan tuntun saya langkah demi langkah dari awal buka toko sampai live di BoonTrack Shop!';
    const onboardingGuideMessage = `Halo! Saya **BoonPilot AI**, co-pilot resmi toko Anda di BoonTrack Shop. 🚀

Saya siap menuntun Anda dari langkah awal hingga toko live dan siap closing order otomatis 24/7. Berikut adalah **8 Langkah Praktis Onboarding Toko** yang perlu Anda lengkapi:

### 1. 🏪 Isi Profil Toko
Lengkapi identitas toko Anda di tab **Pengaturan Toko**: nama toko, unggah logo resmi, dan tentukan kategori bisnis Anda agar etalase tampil profesional dan terpercaya di mata calon pelanggan.

### 2. 💳 Isi Pembayaran & QRIS (BoonTrack Reader)
Unggah barcode QRIS toko Anda. **BoonTrack Reader** bertugas mendeteksi mutasi transfer dan pembayaran QRIS pelanggan secara **otomatis realtime**, sehingga Anda tidak perlu lagi repot cek manual mutasi m-banking satu per satu!

### 3. 📍 Isi Alamat Usaha / Domisili Toko
Tentukan lokasi domisili atau alamat operasional usaha Anda. *(Bagi penyedia produk digital, e-course, atau jasa konsultasi online, bagian ini menjadi domisili resmi toko tanpa perlu setting kurir fisik)*.

### 4. 📦 Isi Titik Gudang & Penjemputan *(Khusus Toko Fisik & F&B)*
Jika Anda menjual barang fisik atau kuliner, masukkan alamat titik jemput gudang/dapur agar integrasi kurir instan dan multi-ekspedisi (JNE, J&T, SiCepat, dll.) dapat menghitung estimasi ongkir otomatis.

### 5. 🛍️ Upload Produk Pertama
Tambahkan minimal 1 produk, katalog jasa, atau aset digital di menu **Produk**. Berikan foto menarik, harga normal & promo, serta deskripsi singkat yang menggugah selera belanja.

### 6. 🧠 Setup Bot via "Setup Terpadu"
Klik tombol **Setup Terpadu** di tab Otomasi/BoonPilot untuk **menyambungkan otak AI toko**. Di sini AI akan mempelajari playbook penjualan, aturan diskon, dan knowledge toko Anda agar siap membalas chat seperti CS profesional.

### 7. 📲 Konek WhatsApp Toko
Buka tab **WhatsApp**, scan barcode QR dengan WhatsApp bisnis Anda untuk aktivasi CS bot otomatis 24/7 dalam melayani chat pembeli dan menerbitkan QRIS dinamis.

### 8. 🔔 Notifikasi Real-time Telegram Toko
Langkah pamungkas! Sambungkan bot Telegram **@boonshop_bot** agar notifikasi pesanan baru & bukti transfer QRIS lunas berdering seketika di HP Anda (instant push, bebas delay dibandingkan email).

---
💡 **Mau mulai dari langkah mana dulu?** Anda bisa langsung tanyakan ke saya jika ada bagian yang ingin dipandu secara spesifik!`;

    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('open-boonpilot', {
          detail: {
            prompt: onboardingPrompt,
            initialAssistantMessage: onboardingGuideMessage,
          },
        })
      );
    }
  };

  const handleSelectBusinessCategoryOnboarding = (catTitle: string, catDesc: string) => {
    const onboardingPrompt = `Halo BoonPilot, saya menjalankan bisnis ${catTitle} (${catDesc}). Tolong bantu dan tuntun saya setup toko dan produk saya langkah demi langkah sampai live di BoonTrack Shop!`;
    const onboardingGuideMessage = `Halo! Saya **BoonPilot AI**, co-pilot resmi toko Anda di BoonTrack Shop. 🚀

Senang sekali bisa mendampingi setup bisnis **${catTitle}** Anda! Untuk model bisnis ini, kita akan siapkan:
1. 🏪 **Profil Toko & Kontak WhatsApp**: Agar calon pembeli atau klien langsung terhubung dengan CS Anda.
2. 📦 **Katalog Produk & Penawaran**: Menambahkan produk / paket ${catTitle} dengan foto menarik dan harga promo.
3. 💳 **Metode Pembayaran (BoonTrack Reader / QRIS)**: Otomasi deteksi bukti pembayaran 24/7 tanpa perlu cek rekening manual.
4. 🎨 **Halaman Penawaran (Landing Page)**: Buat halaman penawaran yang meyakinkan pembeli dalam hitungan menit.

Kira-kira kita mulai dari mana dulu? Apakah Anda sudah menyiapkan nama produk atau foto katalognya?`;

    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('open-boonpilot', {
          detail: {
            prompt: onboardingPrompt,
            initialAssistantMessage: onboardingGuideMessage,
          },
        })
      );
    }
  };

  const handleOpenSalesStrategy = () => {
    const prompt = `Halo BoonPilot, tolong berikan analisis dan saran strategi penjualan terbaik untuk toko saya (${activeStoreName}). Bantu rancang formula penawaran produk, promo menarik, dan copywriting closing yang efektif.`;
    const initialAssistantMessage = `Halo! Saya **BoonPilot AI Sales Strategist**. 🎯

Saya siap membantu merancang strategi penjualan dan copywriting terbaik untuk toko **${activeStoreName}**.

Beberapa fokus strategi yang bisa kita optimalkan:
1. 🎁 **Formula Penawaran & Bundling Promo**: Buat paket bundling produk agar nilai rata-rata keranjang belanja pelanggan (AOV) meningkat.
2. ✍️ **Copywriting Pesan Otomatis WhatsApp**: Rancang template pesan sapaan dan follow-up bot yang persuasif untuk memicu closing instan.
3. ⚡ **Penetapan Harga & Flash Promo**: Strategi diskon dinamis yang menjaga margin keuntungan tetap sehat.
4. 🎯 **Penargetan Segmen Pelanggan**: Trik menaikkan repeat order dari pelanggan lama.

Bagian mana yang ingin kita prioritaskan dan rancang bersama sekarang?`;

    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('open-boonpilot', {
          detail: {
            prompt,
            initialAssistantMessage,
          },
        })
      );
    }
  };

  const handleOpenPerformanceEvaluation = () => {
    const prompt = `Halo BoonPilot, tolong lakukan evaluasi dan analisa performa bisnis toko saya (${activeStoreName}). Berikan insight mengenai arus omzet, tren konversi pesanan, dan saran perbaikan funnel penjualan.`;
    const initialAssistantMessage = `Halo! Saya **BoonPilot Business Intelligence**. 📊

Mari kita bedah dan evaluasi performa bisnis toko **${activeStoreName}**:

1. 📈 **Evaluasi Omzet & Tren Transaksi**: Analisa riwayat penjualan, rata-rata nilai order, dan pergerakan tren 7 hari terakhir.
2. 🔄 **Efisiensi Konversi Chat ke Order**: Evaluasi efektivitas interaksi WhatsApp bot dan rasio calon pembeli yang menyelesaikan checkout QRIS.
3. 💡 **Rekomendasi Optimasi Funnel**: Langkah taktis perbaikan halaman produk, CTA etalase, dan retensi pelanggan untuk mendongkrak omzet toko.

Silakan sebutkan metrik atau target penjualan yang ingin kita analisa lebih lanjut!`;

    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('open-boonpilot', {
          detail: {
            prompt,
            initialAssistantMessage,
          },
        })
      );
    }
  };

  const handleOpenMenuTour = () => {
    const prompt =
      'Halo BoonPilot, saya ingin panduan Tur Singkat untuk mengenal fungsi menu-menu penting di BoonTrack.';
    const initialAssistantMessage = `🎉 **Selamat Datang di Tur Interaktif 10 Menu Utama BoonTrack!** 🧭

Berikut adalah peta 10 menu & ekosistem utama toko Anda:

1. 📊 **Dashboard (Overview)**: Monitoring performa trafik etalase, sesi chat, dan transaksi harian secara realtime.
2. 📦 **Produk & Jasa**: Manajemen katalog fisik, modul digital, layanan jasa, varian, dan stok otomatis.
3. 🚚 **Pengiriman & Kurir**: Integrasi agregator kurir lincah dan setup titik gudang/dapur penjemputan (ongkir akurat otomatis).
4. 🎨 **Tampilan & Tema**: 3 opsi gaya etalase depan (Katalog Standar, Microsite Bio-link ala Linktree modern, dan Personal Brand).
5. 🧠 **AI Knowledge & Bot**: Pusat latihan otak bot toko (FAQ, SOP retur, knowledge produk, gaya bicara CS).
6. 💬 **WhatsApp & Broadcast**: Dual-gateway WhatsApp (Direct Gateway vs Official Meta Centang Biru) serta Telegram Sales Bot di grup jualan.
7. 📥 **Smart Chatbox**: Fitur balas pesan keroyokan oleh tim CS dan otomasi penembakan sinyal purchase event ke media iklan.
8. 🎯 **Ads Tracking Pro**: Pelacak presisi multi-channel (Facebook CAPI, TikTok Pixel, Google Ads) lengkap dengan opsi dipandu step-by-step.
9. 💰 **Laporan Keuangan**: Rekap pembukuan otomatis yang eksklusif mencatat transaksi berstatus PAID (lunas).
10. 📝 **Daftar Pesanan Toko**: Mekanisme mutasi instan QRIS (otomatis berstatus PAID dalam 5-15 detik) vs penanganan status UNPAID beserta pesan follow-up otomatis.

---
💡 **Tahukah Anda?**
Di luar sana, jika Anda berlangganan terpisah untuk tools website katalog, WhatsApp broadcast, AI CS bot, kurir otomatis, dan multi-channel ads tracking, biayanya bisa mencapai **Rp 1,5 jt – Rp 3 jt per bulan**! Di BoonTrack, seluruh senjata penjualan ini sudah **menyatu sempurna dalam 1 ekosistem** terpadu. 🚀

👇 **Silakan pilih menu yang ingin Anda pelajari detailnya:**`;

    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('open-boonpilot', {
          detail: {
            prompt,
            initialAssistantMessage,
          },
        })
      );
    }
  };

  return (
    <div className="flex-1 p-4 sm:p-6 md:p-8 max-w-7xl mx-auto w-full space-y-6 sm:space-y-8 animate-in fade-in duration-200">
      {/* ── 1. ABOVE-THE-FOLD: KARTU METRIK CEPAT TOKO (REACTIVE STORE METRICS) ── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl sm:text-2xl font-black text-slate-900 dark:text-white tracking-tight">
              {activeStoreName}
            </h1>
            <span className="text-[10px] font-black uppercase tracking-wider text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-950/60 px-2.5 py-0.5 rounded-full border border-purple-200/60 dark:border-purple-800/70">
              {tierLabel || 'Live Dashboard'}
            </span>
            {isAiFilterActive && (
              <span className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-wider text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950/60 px-2.5 py-0.5 rounded-full border border-indigo-200 dark:border-indigo-800">
                <Filter className="w-2.5 h-2.5" />
                Filter AI Aktif
              </span>
            )}
          </div>
          <div className="text-xs text-slate-600 dark:text-slate-400 font-semibold hidden sm:flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>Realtime Store Engine</span>
          </div>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          {/* Card 1: Omzet Toko */}
          <div className="bg-white dark:bg-slate-900/90 p-4 sm:p-5 rounded-2xl border border-slate-200 dark:border-slate-800/80 shadow-xs hover:border-purple-400 dark:hover:border-purple-600 transition-all">
            <div className="flex items-center justify-between text-slate-600 dark:text-slate-400 text-xs font-semibold mb-2">
              <span>{activeAiFilter?.status === 'pending' ? 'Nilai Order Pending' : 'Omzet Toko'}</span>
              <div className="w-7 h-7 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                <Wallet className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-lg sm:text-2xl text-slate-900 dark:text-white font-black tracking-tight">
              {formatCurrency(filteredOmzet)}
            </div>
            <div className="text-[11px] text-emerald-600 dark:text-emerald-400 font-bold mt-1 flex items-center gap-1">
              <span>
                {isAiFilterActive
                  ? `Filter: ${filteredOrders.length} transaksi cocok`
                  : '↑ 100% Masuk Rekening'}
              </span>
            </div>
          </div>

          {/* Card 2: Pesanan Baru */}
          <div className="bg-white dark:bg-slate-900/90 p-4 sm:p-5 rounded-2xl border border-slate-200 dark:border-slate-800/80 shadow-xs hover:border-purple-400 dark:hover:border-purple-600 transition-all">
            <div className="flex items-center justify-between text-slate-600 dark:text-slate-400 text-xs font-semibold mb-2">
              <span>Pesanan Baru</span>
              <div className="w-7 h-7 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                <ShoppingBag className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-lg sm:text-2xl text-slate-900 dark:text-white font-black tracking-tight">
              {filteredClosingOrdersCount.toLocaleString('id-ID')}
            </div>
            <div className="text-[11px] text-slate-600 dark:text-slate-400 font-semibold mt-1">
              {filteredClosingOrdersCount > 0
                ? 'Pesanan closing sesuai filter'
                : isAiFilterActive
                ? '0 order closing pada filter ini'
                : 'Menunggu pesanan pertama'}
            </div>
          </div>

          {/* Card 3: QRIS Pending */}
          <div className="bg-white dark:bg-slate-900/90 p-4 sm:p-5 rounded-2xl border border-slate-200 dark:border-slate-800/80 shadow-xs hover:border-purple-400 dark:hover:border-purple-600 transition-all">
            <div className="flex items-center justify-between text-slate-600 dark:text-slate-400 text-xs font-semibold mb-2">
              <span>QRIS Pending</span>
              <div className="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 flex items-center justify-center">
                <Receipt className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-lg sm:text-2xl text-slate-900 dark:text-white font-black tracking-tight">
              {filteredPendingQrisCount.toLocaleString('id-ID')}
            </div>
            <div className="text-[11px] text-amber-600 dark:text-amber-400 font-bold mt-1">
              {filteredPendingQrisCount > 0 ? 'Menanti konfirmasi bayar' : 'Semua QRIS lunas'}
            </div>
          </div>

          {/* Card 4: Trafik Interaksi */}
          <div className="bg-white dark:bg-slate-900/90 p-4 sm:p-5 rounded-2xl border border-slate-200 dark:border-slate-800/80 shadow-xs hover:border-purple-400 dark:hover:border-purple-600 transition-all">
            <div className="flex items-center justify-between text-slate-600 dark:text-slate-400 text-xs font-semibold mb-2">
              <span>Trafik Interaksi</span>
              <div className="w-7 h-7 rounded-lg bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 flex items-center justify-center">
                <MessageSquare className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-lg sm:text-2xl text-slate-900 dark:text-white font-black tracking-tight">
              {filteredInteractionsCount.toLocaleString('id-ID')}
            </div>
            <div className="text-[11px] text-purple-600 dark:text-purple-400 font-bold mt-1">
              {filteredInteractionsCount > 0 ? 'Sesi interaksi terkonversi' : 'Siap sambungkan bot'}
            </div>
          </div>
        </div>
      </section>

      {/* ── 2. CONVERSATIONAL ANALYTICS QUERY BAR (GEMINI FLASH) ── */}
      <BoonPilotQueryBar
        tenantSlug={tenantSlug}
        onFilterChange={(newFilters) => setActiveAiFilter(newFilters)}
      />

      {/* ── 2B. REACTIVE ANALYTICS MATRIX TABLE (WHEN AI FILTER ACTIVE OR TRANSACTIONS PRESENT) ── */}
      {(isAiFilterActive || groupedAnalyticsRows.length > 0) && (
        <section className="bg-white dark:bg-slate-900/90 rounded-2xl border border-slate-200 dark:border-slate-800/80 shadow-xs p-4 sm:p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-purple-600 dark:text-purple-400" />
              <h3 className="text-xs sm:text-sm font-black text-slate-900 dark:text-white tracking-tight">
                Matriks Analitik Terkelompok ({(activeAiFilter?.groupBy || 'date').toUpperCase()})
              </h3>
            </div>
            <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
              <span className="px-2.5 py-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 font-semibold">
                Rentang: {activeAiFilter?.timeRange || 'last_7_days'}
              </span>
              <span className="px-2.5 py-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 font-semibold">
                Metode: {activeAiFilter?.paymentMethod || 'all'}
              </span>
              <span className="px-2.5 py-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 font-semibold">
                Channel: {activeAiFilter?.channel || 'all'}
              </span>
            </div>
          </div>

          {groupedAnalyticsRows.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 font-semibold">
                    <th className="py-2 pr-4">Dimensi ({activeAiFilter?.groupBy || 'date'})</th>
                    <th className="py-2 px-4 text-right">Jumlah Transaksi</th>
                    <th className="py-2 px-4 text-right">QRIS Pending</th>
                    <th className="py-2 pl-4 text-right">Total Nilai (Omzet)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/70 dark:divide-slate-800/70">
                  {groupedAnalyticsRows.map((row) => (
                    <tr key={row.key} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40 transition">
                      <td className="py-2.5 pr-4 font-bold text-slate-900 dark:text-white">
                        {row.label}
                      </td>
                      <td className="py-2.5 px-4 text-right font-black text-slate-900 dark:text-white">
                        {row.orderCount.toLocaleString('id-ID')}
                      </td>
                      <td className="py-2.5 px-4 text-right font-bold text-amber-600 dark:text-amber-400">
                        {row.pendingCount.toLocaleString('id-ID')}
                      </td>
                      <td className="py-2.5 pl-4 text-right font-black text-emerald-600 dark:text-emerald-400">
                        {formatCurrency(row.paidAmount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-slate-600 dark:text-slate-400 font-semibold">
              Tidak ada transaksi yang cocok dengan kombinasi filter saat ini.
            </div>
          )}
        </section>
      )}

      {/* ── VISUAL AI SESSION QUOTA METER (P0 SAAS MONETISASI) ── */}
      <AiSessionQuotaMeter tenantSlug={tenantSlug} tierName={tierLabel} isTeamScale={isTeamScale} />

      {/* WIDGET PENGELOLAAN TAUTAN BIO RESMI TOKO */}
      <StoreBioLinkWidget tenantSlug={tenantSlug} customDomain={customDomain} />

      {/* ── BAGIAN B: RINGKASAN ANALITIK (REACTIVE SUMMARY) ── */}
      <section className="space-y-3 sm:space-y-4">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <h3 className="text-base sm:text-lg font-black text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              <span>Ringkasan Performa ({activeAiFilter?.timeRange === 'today' ? 'Hari Ini' : activeAiFilter?.timeRange === 'current_month' ? 'Bulan Berjalan' : '7 Hari Terakhir'})</span>
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold">
              Pantau arus kunjungan etalase, pesan WhatsApp otomatis, dan sesi pembayaran pelanggan.
            </p>
          </div>
          <span className="text-[11px] font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 px-3 py-1 rounded-xl hidden sm:inline-block">
            Auto-Sync 24 Jam
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Pengunjung Etalase */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-3 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-600 dark:text-slate-400 font-semibold">
                Pengunjung Etalase
              </span>
              <div className="w-8 h-8 rounded-xl bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                <Eye className="w-4 h-4" />
              </div>
            </div>
            <div>
              <div className="text-2xl text-slate-900 dark:text-white font-black tracking-tight">
                {totalVisits.toLocaleString('id-ID')}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] font-bold">
                {totalVisits > 0 ? (
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                    Trafik kunjungan aktif
                  </span>
                ) : (
                  <span className="text-slate-600 dark:text-slate-400 font-semibold">
                    0 Kunjungan tercatat
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Card 2: Chat Masuk WA Bot */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-3 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-600 dark:text-slate-400 font-semibold">
                Chat Masuk WA Bot
              </span>
              <div className="w-8 h-8 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                <MessageSquare className="w-4 h-4" />
              </div>
            </div>
            <div>
              <div className="text-2xl text-slate-900 dark:text-white font-black tracking-tight">
                {filteredInteractionsCount.toLocaleString('id-ID')}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] font-bold">
                {filteredInteractionsCount > 0 ? (
                  <span className="text-emerald-600 dark:text-emerald-400">
                    ● Online &amp; Aktif • {filteredInteractionsCount.toLocaleString('id-ID')} Sesi Terlayani
                  </span>
                ) : (
                  <span className="text-slate-600 dark:text-slate-400 font-semibold">
                    0 Sesi Terlayani
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Card 3: Pesanan / Invoice QRIS */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-3 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-600 dark:text-slate-400 font-semibold">
                Pesanan / Invoice QRIS
              </span>
              <div className="w-8 h-8 rounded-xl bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 flex items-center justify-center">
                <Receipt className="w-4 h-4" />
              </div>
            </div>
            <div>
              <div className="text-2xl text-slate-900 dark:text-white font-black tracking-tight">
                {filteredClosingOrdersCount.toLocaleString('id-ID')}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] font-semibold text-slate-600 dark:text-slate-400">
                <span>
                  {filteredClosingOrdersCount > 0
                    ? `${filteredClosingOrdersCount.toLocaleString('id-ID')} Pesanan Terfilter`
                    : 'Menunggu pesanan'}
                </span>
              </div>
            </div>
          </div>

          {/* Card 4: Estimasi Transaksi */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-3 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-600 dark:text-slate-400 font-semibold">
                Estimasi Nilai Masuk
              </span>
              <div className="w-8 h-8 rounded-xl bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 flex items-center justify-center">
                <Wallet className="w-4 h-4" />
              </div>
            </div>
            <div>
              <div className="text-xl sm:text-2xl text-slate-900 dark:text-white font-black tracking-tight">
                {formatCurrency(filteredOmzet)}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <span>100% Masuk Rekening</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── BAGIAN C: MODUL TAMPILAN & MICROSITE TERINTEGRASI ── */}
      <section
        id="template-module-section"
        className="bg-white dark:bg-slate-900/70 rounded-3xl border border-slate-200 dark:border-slate-800/60 p-6 sm:p-7 shadow-xs space-y-6"
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-5">
          <div className="space-y-1">
            <span className="text-[10px] font-black uppercase tracking-wider text-purple-600 dark:text-purple-300 bg-purple-50 dark:bg-purple-950/60 px-2.5 py-0.5 rounded-full">
              Pusat Desain Etalase
            </span>
            <h3 className="text-lg sm:text-xl font-black text-slate-900 dark:text-white tracking-tight">
              Tampilan Toko &amp; Microsite Terintegrasi
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold">
              Pilih template etalase yang paling sesuai dengan model bisnis Anda. Perubahan langsung aktif seketika.
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={onOpenStoreSettings}
              className="px-3.5 py-2 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200/80 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 font-bold text-xs rounded-xl transition cursor-pointer"
            >
              Atur Profil &amp; Logo
            </button>
            <button
              type="button"
              onClick={() => onNavigateTab('themes')}
              className="px-3.5 py-2 bg-slate-100 dark:bg-slate-800 hover:bg-purple-50 dark:hover:bg-purple-950/50 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 font-bold text-xs rounded-xl transition cursor-pointer"
            >
              Atur Tema Visual
            </button>
          </div>
        </div>

        {/* 3 Template Selection Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {/* Option 1: Default Catalog */}
          <div
            onClick={() => handleSelectTemplate('default')}
            className={`p-5 rounded-3xl border transition-all cursor-pointer flex flex-col justify-between space-y-4 group ${
              activeTemplate === 'default'
                ? 'border-blue-600 dark:border-blue-500 bg-blue-50/20 dark:bg-slate-900/90 shadow-md ring-4 ring-blue-500/10'
                : 'bg-white dark:bg-slate-900/90 border-slate-200 dark:border-slate-800/80 hover:border-slate-300 dark:hover:border-slate-700 shadow-xs'
            }`}
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="w-10 h-10 rounded-2xl bg-blue-100 dark:bg-blue-950/70 text-blue-700 dark:text-blue-300 flex items-center justify-center font-bold">
                  <ShoppingBag className="w-5 h-5" />
                </div>
                {activeTemplate === 'default' && (
                  <span className="px-2.5 py-0.5 bg-blue-600 text-white font-bold text-[10px] rounded-full flex items-center gap-1 shadow-xs">
                    <Check className="w-3 h-3" />
                    <span>Aktif</span>
                  </span>
                )}
              </div>
              <div>
                <h4 className="font-black text-slate-900 dark:text-white text-sm">
                  Katalog Toko (Default)
                </h4>
                <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold mt-1 leading-relaxed">
                  Tata letak e-commerce grid modern lengkap dengan tombol tambah keranjang, estimasi ongkir, dan checkout QRIS terintegrasi.
                </p>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs font-bold text-blue-600 dark:text-blue-400">
              <span>
                {activeTemplate === 'default' ? 'Sedang Digunakan' : 'Gunakan Template Ini'}
              </span>
              <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </div>

          {/* Option 2: Microsite Bio-Link */}
          <div
            onClick={() => handleSelectTemplate('microsite')}
            className={`p-5 rounded-3xl border transition-all cursor-pointer flex flex-col justify-between space-y-4 group ${
              activeTemplate === 'microsite'
                ? 'border-purple-600 dark:border-purple-500 bg-purple-50/20 dark:bg-slate-900/90 shadow-md ring-4 ring-purple-500/10'
                : 'bg-white dark:bg-slate-900/90 border-slate-200 dark:border-slate-800/80 hover:border-slate-300 dark:hover:border-slate-700 shadow-xs'
            }`}
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="w-10 h-10 rounded-2xl bg-purple-100 dark:bg-purple-950/70 text-purple-700 dark:text-purple-300 flex items-center justify-center font-bold">
                  <LayoutTemplate className="w-5 h-5" />
                </div>
                {activeTemplate === 'microsite' && (
                  <span className="px-2.5 py-0.5 bg-purple-600 text-white font-bold text-[10px] rounded-full flex items-center gap-1 shadow-xs">
                    <Check className="w-3 h-3" />
                    <span>Aktif</span>
                  </span>
                )}
              </div>
              <div>
                <h4 className="font-black text-slate-900 dark:text-white text-sm">
                  Microsite Bio-Link
                </h4>
                <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold mt-1 leading-relaxed">
                  Tampilan bio ringkas ala Linktree khusus konversi media sosial. Fokus pada avatar, bio singkat, dan deretan tombol CTA rounded vertikal.
                </p>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs font-bold text-purple-600 dark:text-purple-400">
              <span>
                {activeTemplate === 'microsite' ? 'Sedang Digunakan' : 'Gunakan Template Ini'}
              </span>
              <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </div>

          {/* Option 3: Personal Authority */}
          <div
            onClick={() => handleSelectTemplate('personal')}
            className={`p-5 rounded-3xl border transition-all cursor-pointer flex flex-col justify-between space-y-4 group ${
              activeTemplate === 'personal'
                ? 'border-indigo-600 dark:border-indigo-500 bg-indigo-50/20 dark:bg-slate-900/90 shadow-md ring-4 ring-indigo-500/10'
                : 'bg-white dark:bg-slate-900/90 border-slate-200 dark:border-slate-800/80 hover:border-slate-300 dark:hover:border-slate-700 shadow-xs'
            }`}
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="w-10 h-10 rounded-2xl bg-indigo-100 dark:bg-indigo-950/70 text-indigo-700 dark:text-indigo-300 flex items-center justify-center font-bold">
                  <Sparkles className="w-5 h-5" />
                </div>
                {activeTemplate === 'personal' && (
                  <span className="px-2.5 py-0.5 bg-indigo-600 text-white font-bold text-[10px] rounded-full flex items-center gap-1 shadow-xs">
                    <Check className="w-3 h-3" />
                    <span>Aktif</span>
                  </span>
                )}
              </div>
              <div>
                <h4 className="font-black text-slate-900 dark:text-white text-sm">
                  Personal Brand &amp; Authority
                </h4>
                <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold mt-1 leading-relaxed">
                  Desain landing page personal mentor &amp; profesional untuk membangun kredibilitas tinggi, sesi konsultasi, dan portofolio keahlian.
                </p>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs font-bold text-indigo-600 dark:text-indigo-400">
              <span>
                {activeTemplate === 'personal' ? 'Sedang Digunakan' : 'Gunakan Template Ini'}
              </span>
              <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </div>
        </div>
      </section>

      {/* ── BAGIAN D: KABAR & UPDATE TERBARU BOONTRACK (NEWS & UPDATES FEED) ── */}
      <section className="space-y-3 sm:space-y-4">
        <div className="space-y-0.5">
          <h3 className="text-base sm:text-lg font-black text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
            <Newspaper className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
            <span>Kabar &amp; Update Terbaru BoonTrack</span>
          </h3>
          <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold">
            Fitur terbaru dan tips praktis untuk meningkatkan konversi etalase toko Anda.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* News 1 (Fitur Baru: Bot Telegram Real-Time) */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-2.5 flex flex-col justify-between hover:shadow-md transition-shadow group">
            <div className="space-y-2">
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 inline-flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Fitur Baru
              </span>
              <h4 className="font-black text-slate-900 dark:text-white text-sm leading-snug">
                Notifikasi Bot Telegram Real-Time: Pesanan &amp; Pembayaran Masuk Instan
              </h4>
              <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold leading-relaxed">
                Kini dashboard toko Anda terhubung langsung dengan Telegram. Dapatkan notifikasi instan langsung ke HP untuk setiap pesanan baru masuk, konfirmasi pembayaran lunas (PAID / CAPI dispatched), bukti transfer, hingga status koneksi bot WhatsApp tanpa takut terlewat.
              </p>
            </div>
            <button
              type="button"
              onClick={() => onNavigateTab('telegram_alerts')}
              className="pt-2 text-[11px] font-bold text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 flex items-center gap-1 group/btn cursor-pointer transition text-left"
            >
              <span>Hubungkan Telegram -&gt;</span>
            </button>
          </div>

          {/* News 2 (Pembayaran: Dynamic QRIS V2) */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-2.5 flex flex-col justify-between hover:shadow-md transition-shadow">
            <div className="space-y-2">
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                Pembayaran
              </span>
              <h4 className="font-black text-slate-900 dark:text-white text-sm leading-snug">
                Dynamic QRIS V2: Otomatisasi Masuk Rekening Bebas MDR
              </h4>
              <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold leading-relaxed">
                Setiap pembayaran checkout kini diverifikasi otomatis oleh bot dan dana langsung diteruskan ke rekening utama tanpa potongan transaksi.
              </p>
            </div>
            <div className="pt-2 text-[11px] font-bold text-slate-600 dark:text-slate-400">
              Telah aktif di toko Anda
            </div>
          </div>

          {/* News 3 (Desain: Template Bio-Link) */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-2.5 flex flex-col justify-between hover:shadow-md transition-shadow">
            <div className="space-y-2">
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-purple-50 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                Desain
              </span>
              <h4 className="font-black text-slate-900 dark:text-white text-sm leading-snug">
                Template Bio-Link Baru: Super Cepat &amp; Mobile-First
              </h4>
              <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold leading-relaxed">
                Tampilan microsite kini dioptimalkan khusus untuk pengunjung dari TikTok dan Instagram dengan waktu muat di bawah 1 detik.
              </p>
            </div>
            <div
              onClick={() => onNavigateTab('themes')}
              className="pt-2 text-[11px] font-bold text-purple-600 dark:text-purple-400 hover:text-purple-700 cursor-pointer flex items-center gap-1"
            >
              <span>Coba di tab Tampilan Toko</span>
            </div>
          </div>

          {/* News 4 (Tips Penjualan: WhatsApp CTA) */}
          <div className="bg-white dark:bg-slate-900/90 p-5 rounded-3xl border border-slate-200 dark:border-slate-800/80 shadow-xs space-y-2.5 flex flex-col justify-between hover:shadow-md transition-shadow">
            <div className="space-y-2">
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                Tips Penjualan
              </span>
              <h4 className="font-black text-slate-900 dark:text-white text-sm leading-snug">
                Optimasi Tombol WhatsApp untuk Meningkatkan Closing
              </h4>
              <p className="text-xs text-slate-600 dark:text-slate-400 font-semibold leading-relaxed">
                Gunakan format sapaan otomatis di tombol etalase agar calon pembeli merasa dilayani secara personal sejak ketukan pertama.
              </p>
            </div>
            <div
              onClick={() => onNavigateTab('whatsapp')}
              className="pt-2 text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:text-blue-700 cursor-pointer flex items-center gap-1"
            >
              <span>Pelajari Panduan Bot</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
