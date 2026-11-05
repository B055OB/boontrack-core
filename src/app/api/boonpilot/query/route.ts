import { NextRequest, NextResponse } from 'next/server';

export interface BoonPilotQueryOutput {
  groupBy: 'tenant' | 'affiliate' | 'channel' | 'payment_rail' | 'date';
  timeRange: 'today' | 'yesterday' | 'last_7_days' | 'last_30_days' | 'current_month';
  paymentMethod: 'qris' | 'dodo_mor' | 'all';
  channel: 'ctwa' | 'web' | 'studio' | 'all';
  status?: 'all' | 'paid' | 'pending' | 'settled';
  summaryText: string;
}

const SYSTEM_PROMPT = `Kamu adalah BoonPilot Analytics Parser. Tugasmu menerjemahkan pertanyaan bahasa alami pengguna mengenai operasional dan keuangan toko menjadi filter analitik terstruktur dalam format JSON. Ekstrak parameter: groupBy ('tenant', 'affiliate', 'channel', 'payment_rail', 'date'), timeRange ('today', 'yesterday', 'last_7_days', 'last_30_days', 'current_month'), paymentMethod ('qris', 'dodo_mor', 'all'), channel ('ctwa', 'web', 'studio', 'all'), dan buatkan summaryText 1-2 kalimat singkat.
HANYA kembalikan valid JSON tanpa markdown formatting atau backticks (\`\`\`json).`;

function fallbackParser(query: string): BoonPilotQueryOutput {
  const q = query.toLowerCase();

  let groupBy: BoonPilotQueryOutput['groupBy'] = 'date';
  let timeRange: BoonPilotQueryOutput['timeRange'] = 'last_7_days';
  let paymentMethod: BoonPilotQueryOutput['paymentMethod'] = 'all';
  let channel: BoonPilotQueryOutput['channel'] = 'all';
  let status: BoonPilotQueryOutput['status'] = 'all';

  if (q.includes('afiliasi') || q.includes('affiliate') || q.includes('komisi')) {
    groupBy = 'affiliate';
  } else if (q.includes('channel') || q.includes('saluran') || q.includes('sumber')) {
    groupBy = 'channel';
  } else if (q.includes('metode') || q.includes('payment') || q.includes('rail')) {
    groupBy = 'payment_rail';
  } else if (q.includes('tenant') || q.includes('toko')) {
    groupBy = 'tenant';
  }

  if (q.includes('hari ini') || q.includes('today')) {
    timeRange = 'today';
  } else if (q.includes('kemarin') || q.includes('yesterday')) {
    timeRange = 'yesterday';
  } else if (q.includes('30 hari') || q.includes('sebulan')) {
    timeRange = 'last_30_days';
  } else if (q.includes('bulan ini')) {
    timeRange = 'current_month';
  } else if (q.includes('minggu ini') || q.includes('7 hari') || q.includes('pekan ini')) {
    timeRange = 'last_7_days';
  }

  if (q.includes('qris')) {
    paymentMethod = 'qris';
  } else if (q.includes('dodo') || q.includes('mor') || q.includes('payout')) {
    paymentMethod = 'dodo_mor';
  }

  if (q.includes('ctwa') || q.includes('whatsapp') || q.includes('chat')) {
    channel = 'ctwa';
  } else if (q.includes('web') || q.includes('storefront') || q.includes('etalase')) {
    channel = 'web';
  } else if (q.includes('studio')) {
    channel = 'studio';
  }

  if (q.includes('pending') || q.includes('menunggu')) {
    status = 'pending';
  } else if (q.includes('lunas') || q.includes('paid') || q.includes('sukses')) {
    status = 'paid';
  }

  const groupLabel = groupBy === 'affiliate' ? 'afiliasi' : groupBy === 'channel' ? 'channel transaksi' : groupBy === 'payment_rail' ? 'metode bayar' : 'tanggal';
  const rangeLabel = timeRange === 'today' ? 'hari ini' : timeRange === 'yesterday' ? 'kemarin' : timeRange === 'last_7_days' ? '7 hari terakhir' : '30 hari terakhir';
  const payLabel = paymentMethod === 'qris' ? 'QRIS' : paymentMethod === 'dodo_mor' ? 'Dodo MoR' : 'semua pembayaran';

  return {
    groupBy,
    timeRange,
    paymentMethod,
    channel,
    status,
    summaryText: `Menampilkan analisis transaksi ${payLabel} yang dikelompokkan per ${groupLabel} selama ${rangeLabel}.`,
  };
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const userQuery = (body?.query || '').trim();

    if (!userQuery) {
      return NextResponse.json({ error: 'Query parameter is required' }, { status: 400 });
    }

    const apiKey = process.env.GEMINI_API_KEY || process.env.GEMINI_API_KEY_STUDIO || '';
    if (!apiKey) {
      return NextResponse.json(fallbackParser(userQuery));
    }

    // Call Gemini 2.0 Flash REST endpoint
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000); // 2s strict timeout for <400ms target

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
          return NextResponse.json({
            groupBy: parsed.groupBy || 'affiliate',
            timeRange: parsed.timeRange || 'last_7_days',
            paymentMethod: parsed.paymentMethod || 'all',
            channel: parsed.channel || 'all',
            status: parsed.status || 'all',
            summaryText: parsed.summaryText || 'Filter analitik berhasil diterapkan.',
          });
        }
      }
    } catch {
      // Fallback silently if Gemini timeout/network error occurs
    } finally {
      clearTimeout(timeoutId);
    }

    return NextResponse.json(fallbackParser(userQuery));
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Internal server error' }, { status: 500 });
  }
}
