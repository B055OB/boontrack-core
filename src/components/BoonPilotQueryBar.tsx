'use client';

import React, { useState, useTransition, useCallback } from 'react';
import {
  Sparkles,
  Search,
  X,
  SlidersHorizontal,
  RotateCcw,
  Cpu,
  AlertCircle,
} from 'lucide-react';

export interface BoonPilotFilters {
  groupBy: 'tenant' | 'affiliate' | 'channel' | 'payment_rail' | 'date';
  timeRange: 'today' | 'yesterday' | 'last_7_days' | 'last_30_days' | 'current_month';
  paymentMethod: 'qris' | 'dodo_mor' | 'all';
  channel: 'ctwa' | 'web' | 'studio' | 'all';
  status: 'all' | 'completed' | 'paid' | 'pending' | 'settled';
  summaryText?: string;
  sourceQuery?: string;
  source?: 'gemini' | 'heuristic_fallback' | 'preset' | 'manual';
}

export interface BoonPilotQueryBarProps {
  tenantSlug: string;
  onFilterChange?: (filters: BoonPilotFilters) => void;
  className?: string;
}

const MAX_QUERY_LENGTH = 250;

const DEFAULT_FILTERS: BoonPilotFilters = {
  groupBy: 'date',
  timeRange: 'last_7_days',
  paymentMethod: 'all',
  channel: 'all',
  status: 'all',
  summaryText: '',
  sourceQuery: '',
  source: undefined,
};

export default function BoonPilotQueryBar({
  tenantSlug,
  onFilterChange,
  className = '',
}: BoonPilotQueryBarProps) {
  const [queryInput, setQueryInput] = useState('');
  const [filters, setFilters] = useState<BoonPilotFilters>(DEFAULT_FILTERS);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showControlBar, setShowControlBar] = useState(false);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const applyFilters = useCallback(
    (newFilters: BoonPilotFilters) => {
      setFilters(newFilters);
      if (onFilterChange) {
        startTransition(() => {
          onFilterChange(newFilters);
        });
      }
    },
    [onFilterChange]
  );

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanQuery = queryInput.trim();
    if (!cleanQuery) return;

    if (cleanQuery.length > MAX_QUERY_LENGTH) {
      setErrorMessage(`Kueri maksimal ${MAX_QUERY_LENGTH} karakter.`);
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setActivePreset(null);

    try {
      const res = await fetch('/api/boonpilot/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: cleanQuery, tenantSlug }),
      });

      const data = await res.json();

      if (!res.ok) {
        setErrorMessage(data?.error || 'Gagal memproses kueri analitik.');
        return;
      }

      applyFilters({
        groupBy: data.groupBy || 'date',
        timeRange: data.timeRange || 'last_7_days',
        paymentMethod: data.paymentMethod || 'all',
        channel: data.channel || 'all',
        status: data.status || 'all',
        summaryText: data.summaryText || `Menampilkan hasil filter untuk: "${cleanQuery}"`,
        sourceQuery: cleanQuery,
        source: data.source === 'gemini' ? 'gemini' : 'heuristic_fallback',
      });
    } catch (err) {
      console.warn('[BoonPilotQueryBar] Query error:', err);
      setErrorMessage('Koneksi gagal saat menghubungi mesin analitik.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectPreset = (
    presetId: string,
    presetFilter: Partial<BoonPilotFilters>,
    presetSummary: string
  ) => {
    setActivePreset(presetId);
    setQueryInput('');
    setErrorMessage(null);
    applyFilters({
      ...DEFAULT_FILTERS,
      ...presetFilter,
      summaryText: presetSummary,
      sourceQuery: presetId,
      source: 'preset',
    });
  };

  const handleResetFilters = () => {
    setQueryInput('');
    setActivePreset(null);
    setErrorMessage(null);
    applyFilters(DEFAULT_FILTERS);
  };

  return (
    <div
      className={`w-full bg-white dark:bg-slate-900/90 rounded-2xl border border-slate-200 dark:border-slate-800/80 shadow-xs p-3.5 sm:p-4 space-y-3 transition-all ${className}`}
    >
      {/* ── 1. CONVERSATIONAL QUERY INPUT BAR (GOOGLE CLOUD BILLING STYLE) ── */}
      <form onSubmit={handleSearch} className="relative flex items-center gap-2">
        <div className="relative flex-1 flex items-center">
          <div className="absolute left-3.5 flex items-center gap-1.5 pointer-events-none">
            <Sparkles className="w-4 h-4 text-purple-600 dark:text-purple-400 animate-pulse" />
            <span className="hidden sm:inline-block text-[11px] font-black uppercase tracking-wider text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-950/60 px-1.5 py-0.5 rounded border border-purple-200/60 dark:border-purple-800">
              Flash Engine
            </span>
          </div>

          <input
            type="text"
            value={queryInput}
            maxLength={MAX_QUERY_LENGTH}
            onChange={(e) => {
              setQueryInput(e.target.value);
              if (errorMessage) setErrorMessage(null);
            }}
            placeholder="Tanyakan analisis toko, misal: 'Tampilkan omzet QRIS per afiliasi minggu ini'..."
            disabled={isLoading}
            className="w-full pl-10 sm:pl-36 pr-16 py-2.5 text-xs sm:text-sm bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-purple-500/40 focus:border-purple-500 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 transition"
          />

          <div className="absolute right-2.5 flex items-center gap-1">
            {queryInput.length > 180 && (
              <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">
                {queryInput.length}/{MAX_QUERY_LENGTH}
              </span>
            )}
            {queryInput && (
              <button
                type="button"
                onClick={() => {
                  setQueryInput('');
                  setErrorMessage(null);
                }}
                className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition cursor-pointer"
                title="Bersihkan input"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        <button
          type="submit"
          disabled={isLoading || !queryInput.trim()}
          className="inline-flex items-center justify-center gap-1.5 px-4 py-2.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-extrabold text-xs rounded-xl shadow-xs transition active:scale-95 disabled:opacity-50 disabled:pointer-events-none cursor-pointer shrink-0"
        >
          {isLoading ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span className="hidden sm:inline">Memproses...</span>
            </>
          ) : (
            <>
              <Search className="w-3.5 h-3.5" />
              <span>Analisis</span>
            </>
          )}
        </button>

        <button
          type="button"
          onClick={() => setShowControlBar(!showControlBar)}
          className={`p-2.5 rounded-xl border transition cursor-pointer shrink-0 ${
            showControlBar
              ? 'bg-purple-50 dark:bg-purple-950/60 border-purple-300 dark:border-purple-700 text-purple-700 dark:text-purple-300'
              : 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-200/70 dark:hover:bg-slate-700'
          }`}
          title="Buka Filter Manual"
        >
          <SlidersHorizontal className="w-4 h-4" />
        </button>
      </form>

      {errorMessage && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/70 text-rose-700 dark:text-rose-300 text-xs font-semibold">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* ── 2. INTERACTIVE PRESET CHIPS (HORIZONTAL CAROUSEL) ── */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none text-xs">
        <span className="text-[10px] font-black uppercase tracking-wider text-slate-600 dark:text-slate-400 shrink-0">
          Preset Cepat:
        </span>

        {/* Preset 1: Omzet & Komisi Afiliasi */}
        <button
          type="button"
          onClick={() =>
            handleSelectPreset(
              'preset_affiliate',
              {
                groupBy: 'affiliate',
                timeRange: 'last_7_days',
                paymentMethod: 'all',
                channel: 'all',
                status: 'all',
              },
              'Menampilkan omzet dan pembagian komisi per afiliasi dalam 7 hari terakhir.'
            )
          }
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border font-bold shrink-0 transition active:scale-95 cursor-pointer ${
            activePreset === 'preset_affiliate'
              ? 'bg-purple-600 text-white border-purple-600 shadow-xs'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 hover:border-purple-400 dark:hover:border-purple-500'
          }`}
        >
          <span>💰</span>
          <span>Omzet &amp; Komisi Afiliasi</span>
        </button>

        {/* Preset 2: Pesanan QRIS Pending */}
        <button
          type="button"
          onClick={() =>
            handleSelectPreset(
              'preset_qris_pending',
              {
                paymentMethod: 'qris',
                status: 'pending',
                timeRange: 'last_7_days',
                groupBy: 'date',
                channel: 'all',
              },
              'Menampilkan transaksi QRIS dalam status pending (menunggu verifikasi mutasi).'
            )
          }
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border font-bold shrink-0 transition active:scale-95 cursor-pointer ${
            activePreset === 'preset_qris_pending'
              ? 'bg-purple-600 text-white border-purple-600 shadow-xs'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 hover:border-purple-400 dark:hover:border-purple-500'
          }`}
        >
          <span>📦</span>
          <span>Pesanan QRIS Pending</span>
        </button>

        {/* Preset 3: Konversi Chat-to-WhatsApp */}
        <button
          type="button"
          onClick={() =>
            handleSelectPreset(
              'preset_ctwa',
              {
                channel: 'ctwa',
                groupBy: 'date',
                timeRange: 'last_7_days',
                paymentMethod: 'all',
                status: 'all',
              },
              'Menampilkan performa konversi harian dari saluran Chat-to-WhatsApp (CTWA).'
            )
          }
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border font-bold shrink-0 transition active:scale-95 cursor-pointer ${
            activePreset === 'preset_ctwa'
              ? 'bg-purple-600 text-white border-purple-600 shadow-xs'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 hover:border-purple-400 dark:hover:border-purple-500'
          }`}
        >
          <span>⚡</span>
          <span>Konversi Chat-to-WhatsApp</span>
        </button>

        {/* Preset 4: Payout & Fee MoR */}
        <button
          type="button"
          onClick={() =>
            handleSelectPreset(
              'preset_mor',
              {
                paymentMethod: 'dodo_mor',
                groupBy: 'payment_rail',
                timeRange: 'current_month',
                channel: 'all',
                status: 'all',
              },
              'Menampilkan rekonsiliasi payout dan fee Merchant of Record (MoR) bulan berjalan.'
            )
          }
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border font-bold shrink-0 transition active:scale-95 cursor-pointer ${
            activePreset === 'preset_mor'
              ? 'bg-purple-600 text-white border-purple-600 shadow-xs'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 hover:border-purple-400 dark:hover:border-purple-500'
          }`}
        >
          <span>🧾</span>
          <span>Payout &amp; Fee MoR</span>
        </button>
      </div>

      {/* ── 3. SUMMARY BANNER SAAT AI QUERY / FILTER AKTIF ── */}
      {filters.summaryText && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-gradient-to-r from-purple-50 via-indigo-50/50 to-slate-50 dark:from-purple-950/40 dark:via-indigo-950/30 dark:to-slate-900/80 border border-purple-200 dark:border-purple-800/60 rounded-xl text-xs">
          <div className="flex flex-wrap items-center gap-2 text-purple-900 dark:text-purple-200">
            <Sparkles className="w-4 h-4 text-purple-600 dark:text-purple-400 shrink-0" />
            <span className="font-semibold">{filters.summaryText}</span>

            {/* Honest Source Badge: Gemini vs Heuristic Fallback vs Preset */}
            {filters.source === 'gemini' && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-emerald-100 dark:bg-emerald-950/70 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
                <Sparkles className="w-2.5 h-2.5" />
                Gemini 2.0 Flash
              </span>
            )}
            {filters.source === 'heuristic_fallback' && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-amber-100 dark:bg-amber-950/70 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800">
                <Cpu className="w-2.5 h-2.5" />
                Heuristic Parser
              </span>
            )}
            {filters.source === 'preset' && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-purple-100 dark:bg-purple-950/70 text-purple-800 dark:text-purple-300 border border-purple-300 dark:border-purple-800">
                Preset Instan
              </span>
            )}
          </div>

          <button
            type="button"
            onClick={handleResetFilters}
            className="inline-flex items-center gap-1 text-[11px] font-bold text-purple-700 dark:text-purple-300 hover:underline shrink-0 cursor-pointer"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Reset Filter</span>
          </button>
        </div>
      )}

      {/* ── 4. CONTROL BAR KONTEKSTUAL & DYNAMIC FILTER MATRIX (COLLAPSIBLE) ── */}
      {showControlBar && (
        <div className="pt-2 border-t border-slate-200 dark:border-slate-800 grid grid-cols-2 sm:grid-cols-5 gap-2.5 text-xs">
          {/* Group By Dropdown */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wider block">
              Group By
            </label>
            <select
              value={filters.groupBy}
              onChange={(e) =>
                applyFilters({
                  ...filters,
                  groupBy: e.target.value as BoonPilotFilters['groupBy'],
                  source: 'manual',
                  summaryText: filters.summaryText || 'Filter kustom manual diterapkan.',
                })
              }
              className="w-full px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            >
              <option value="date">Tanggal (Harian)</option>
              <option value="affiliate">Afiliasi / Partner</option>
              <option value="channel">Saluran Penjualan</option>
              <option value="payment_rail">Metode Pembayaran</option>
              <option value="tenant">Tenant</option>
            </select>
          </div>

          {/* Time Range Dropdown */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wider block">
              Time Range
            </label>
            <select
              value={filters.timeRange}
              onChange={(e) =>
                applyFilters({
                  ...filters,
                  timeRange: e.target.value as BoonPilotFilters['timeRange'],
                  source: 'manual',
                  summaryText: filters.summaryText || 'Filter kustom manual diterapkan.',
                })
              }
              className="w-full px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            >
              <option value="today">Hari Ini (24 Jam)</option>
              <option value="yesterday">Kemarin</option>
              <option value="last_7_days">7 Hari Terakhir</option>
              <option value="last_30_days">30 Hari Terakhir</option>
              <option value="current_month">Bulan Ini</option>
            </select>
          </div>

          {/* Payment Method Dropdown */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wider block">
              Payment Method
            </label>
            <select
              value={filters.paymentMethod}
              onChange={(e) =>
                applyFilters({
                  ...filters,
                  paymentMethod: e.target.value as BoonPilotFilters['paymentMethod'],
                  source: 'manual',
                  summaryText: filters.summaryText || 'Filter kustom manual diterapkan.',
                })
              }
              className="w-full px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            >
              <option value="all">Semua Metode</option>
              <option value="qris">QRIS (Otomatis)</option>
              <option value="dodo_mor">Dodo MoR (Gateway)</option>
            </select>
          </div>

          {/* Channel Dropdown */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wider block">
              Channel
            </label>
            <select
              value={filters.channel}
              onChange={(e) =>
                applyFilters({
                  ...filters,
                  channel: e.target.value as BoonPilotFilters['channel'],
                  source: 'manual',
                  summaryText: filters.summaryText || 'Filter kustom manual diterapkan.',
                })
              }
              className="w-full px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            >
              <option value="all">Semua Channel</option>
              <option value="ctwa">Chat-to-WhatsApp (CTWA)</option>
              <option value="web">Web Storefront</option>
              <option value="studio">BoonTrack Studio</option>
            </select>
          </div>

          {/* Status Dropdown */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wider block">
              Status
            </label>
            <select
              value={filters.status}
              onChange={(e) =>
                applyFilters({
                  ...filters,
                  status: e.target.value as BoonPilotFilters['status'],
                  source: 'manual',
                  summaryText: filters.summaryText || 'Filter kustom manual diterapkan.',
                })
              }
              className="w-full px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            >
              <option value="all">Semua Status</option>
              <option value="completed">Lunas (Closing)</option>
              <option value="pending">Pending (Menunggu)</option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
