import { NextRequest, NextResponse } from 'next/server';

export const VALID_GROUP_BY = ['tenant', 'affiliate', 'channel', 'payment_rail', 'date'] as const;
export const VALID_TIME_RANGE = ['today', 'yesterday', 'last_7_days', 'last_30_days', 'current_month'] as const;
export const VALID_PAYMENT_METHOD = ['qris', 'dodo_mor', 'all'] as const;
export const VALID_CHANNEL = ['ctwa', 'web', 'studio', 'all'] as const;
export const VALID_STATUS = ['completed', 'paid', 'pending', 'settled', 'all'] as const;

export type GroupByOption = (typeof VALID_GROUP_BY)[number];
export type TimeRangeOption = (typeof VALID_TIME_RANGE)[number];
export type PaymentMethodOption = (typeof VALID_PAYMENT_METHOD)[number];
export type ChannelOption = (typeof VALID_CHANNEL)[number];
export type StatusOption = (typeof VALID_STATUS)[number];
export type BoonPilotQuerySource = 'gemini' | 'heuristic_fallback';

export interface BoonPilotQueryOutput {
  groupBy: GroupByOption;
  timeRange: TimeRangeOption;
  paymentMethod: PaymentMethodOption;
  channel: ChannelOption;
  status: StatusOption;
  summaryText: string;
  source: BoonPilotQuerySource;
}

const MAX_QUERY_LENGTH = 250;

const SYSTEM_PROMPT = `Kamu adalah BoonPilot Analytics Parser. Tugasmu menerjemahkan pertanyaan bahasa alami pengguna mengenai operasional dan keuangan toko menjadi filter analitik terstruktur dalam format JSON. Ekstrak parameter:
- groupBy: salah satu dari ('tenant', 'affiliate', 'channel', 'payment_rail', 'date')
- timeRange: salah satu dari ('today', 'yesterday', 'last_7_days', 'last_30_days', 'current_month')
- paymentMethod: salah satu dari ('qris', 'dodo_mor', 'all')
- channel: salah satu dari ('ctwa', 'web', 'studio', 'all')
- status: salah satu dari ('completed', 'pending', 'all')
- summaryText: ringkasan 1-2 kalimat singkat dalam bahasa Indonesia.
HANYA kembalikan valid JSON tanpa markdown formatting atau backticks (\`\`\`json).`;

function isValidEnum<T extends string>(val: unknown, allowed: readonly T[]): val is T {
  return typeof val === 'string' && (allowed as readonly string[]).includes(val);
}

function validateAndSanitizeOutput(
  raw: Record<string, unknown>,
  source: BoonPilotQuerySource,
  fallbackBase: Omit<BoonPilotQueryOutput, 'source'>
): BoonPilotQueryOutput {
  const groupBy: GroupByOption = isValidEnum(raw.groupBy, VALID_GROUP_BY)
    ? raw.groupBy
    : fallbackBase.groupBy;

  const timeRange: TimeRangeOption = isValidEnum(raw.timeRange, VALID_TIME_RANGE)
    ? raw.timeRange
    : fallbackBase.timeRange;

  const paymentMethod: PaymentMethodOption = isValidEnum(raw.paymentMethod, VALID_PAYMENT_METHOD)
    ? raw.paymentMethod
    : fallbackBase.paymentMethod;

  const channel: ChannelOption = isValidEnum(raw.channel, VALID_CHANNEL)
    ? raw.channel
    : fallbackBase.channel;

  const status: StatusOption = isValidEnum(raw.status, VALID_STATUS)
    ? raw.status
    : fallbackBase.status;

  let summaryText =
    typeof raw.summaryText === 'string' && raw.summaryText.trim().length > 0
      ? raw.summaryText.replace(/<[^>]*>/g, '').trim().slice(0, 300)
      : fallbackBase.summaryText;

  return {
    groupBy,
    timeRange,
    paymentMethod,
    channel,
    status,
    summaryText,
    source,
  };
}

function fallbackParser(query: string): BoonPilotQueryOutput {
  const q = query.toLowerCase();

  let groupBy: GroupByOption = 'date';
  let timeRange: TimeRangeOption = 'last_7_days';
  let paymentMethod: PaymentMethodOption = 'all';
  let channel: ChannelOption = 'all';
  let status: StatusOption = 'all';

  if (q.includes('afiliasi') || q.includes('affiliate') || q.includes('komisi') || q.includes('partner')) {
    groupBy = 'affiliate';
  } else if (q.includes('channel') || q.includes('saluran') || q.includes('sumber')) {
    groupBy = 'channel';
  } else if (q.includes('metode') || q.includes('payment') || q.includes('rail')) {
    groupBy = 'payment_rail';
  } else if (q.includes('tenant') || q.includes('toko') || q.includes('cabang')) {
    groupBy = 'tenant';
  }

  if (q.includes('hari ini') || q.includes('today') || q.includes('sekarang')) {
    timeRange = 'today';
  } else if (q.includes('kemarin') || q.includes('yesterday')) {
    timeRange = 'yesterday';
  } else if (q.includes('30 hari') || q.includes('sebulan') || q.includes('last 30')) {
    timeRange = 'last_30_days';
  } else if (q.includes('bulan ini') || q.includes('current month')) {
    timeRange = 'current_month';
  } else if (q.includes('minggu ini') || q.includes('7 hari') || q.includes('pekan ini') || q.includes('seminggu')) {
    timeRange = 'last_7_days';
  }

  if (q.includes('qris')) {
    paymentMethod = 'qris';
  } else if (q.includes('dodo') || q.includes('mor') || q.includes('payout') || q.includes('gateway')) {
    paymentMethod = 'dodo_mor';
  }

  if (q.includes('ctwa') || q.includes('whatsapp') || q.includes('wa') || q.includes('chat')) {
    channel = 'ctwa';
  } else if (q.includes('web') || q.includes('storefront') || q.includes('etalase') || q.includes('katalog')) {
    channel = 'web';
  } else if (q.includes('studio')) {
    channel = 'studio';
  }

  if (q.includes('pending') || q.includes('menunggu') || q.includes('belum bayar') || q.includes('unpaid')) {
    status = 'pending';
  } else if (q.includes('lunas') || q.includes('paid') || q.includes('sukses') || q.includes('completed') || q.includes('closing')) {
    status = 'completed';
  }

  const groupLabel =
    groupBy === 'affiliate'
      ? 'afiliasi'
      : groupBy === 'channel'
      ? 'channel transaksi'
      : groupBy === 'payment_rail'
      ? 'metode pembayaran'
      : groupBy === 'tenant'
      ? 'tenant'
      : 'tanggal harian';
  const rangeLabel =
    timeRange === 'today'
      ? 'hari ini (24 jam terakhir)'
      : timeRange === 'yesterday'
      ? 'kemarin'
      : timeRange === 'last_7_days'
      ? '7 hari terakhir'
      : timeRange === 'last_30_days'
      ? '30 hari terakhir'
      : 'bulan berjalan';
  const payLabel =
    paymentMethod === 'qris'
      ? 'QRIS'
      : paymentMethod === 'dodo_mor'
      ? 'Dodo MoR'
      : 'semua metode pembayaran';
  const statusLabel =
    status === 'pending'
      ? ' berstatus pending'
      : status === 'completed'
      ? ' berstatus lunas (closing)'
      : '';

  return {
    groupBy,
    timeRange,
    paymentMethod,
    channel,
    status,
    summaryText: `Menampilkan analisis transaksi ${payLabel}${statusLabel} yang dikelompokkan per ${groupLabel} selama ${rangeLabel}.`,
    source: 'heuristic_fallback',
  };
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => null);
    if (!body || typeof body.query !== 'string') {
      return NextResponse.json(
        { error: 'Parameter query (string) wajib diisi.' },
        { status: 400 }
      );
    }

    const userQuery = body.query.trim();

    if (!userQuery) {
      return NextResponse.json(
        { error: 'Parameter query tidak boleh kosong.' },
        { status: 400 }
      );
    }

    if (userQuery.length > MAX_QUERY_LENGTH) {
      return NextResponse.json(
        {
          error: `Panjang kueri melebihi batas keamanan maksimum (${MAX_QUERY_LENGTH} karakter).`,
          maxAllowedLength: MAX_QUERY_LENGTH,
        },
        { status: 400 }
      );
    }

    const heuristicResult = fallbackParser(userQuery);
    const apiKey = process.env.GEMINI_API_KEY || process.env.GEMINI_API_KEY_STUDIO || '';

    if (!apiKey) {
      return NextResponse.json(heuristicResult);
    }

    // Call Gemini 2.0 Flash REST endpoint with strict timeout (< 400ms target, 1800ms hard abort)
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1800);

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          contents: [
            {
              role: 'user',
              parts: [{ text: `${SYSTEM_PROMPT}\n\nPertanyaan pengguna: "${userQuery}"` }],
            },
          ],
          generationConfig: {
            temperature: 0.1,
            maxOutputTokens: 256,
            responseMimeType: 'application/json',
          },
        }),
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        const data = await response.json();
        const rawJsonText = data?.candidates?.[0]?.content?.parts?.[0]?.text;
        if (rawJsonText) {
          const parsed = JSON.parse(rawJsonText);
          if (parsed && typeof parsed === 'object') {
            const validated = validateAndSanitizeOutput(parsed, 'gemini', heuristicResult);
            return NextResponse.json(validated);
          }
        }
      }
    } catch {
      // Fall back gracefully to deterministic heuristic parser on timeout or network error
    } finally {
      clearTimeout(timeoutId);
    }

    return NextResponse.json(heuristicResult);
  } catch (err: any) {
    return NextResponse.json(
      { error: err?.message || 'Internal server error' },
      { status: 500 }
    );
  }
}
