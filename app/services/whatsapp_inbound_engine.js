import makeWASocket, { useMultiFileAuthState, DisconnectReason, delay, Browsers } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import axios from 'axios';

const tenantSessions = new Map();
const FASTAPI_INTERNAL_URL = process.env.FASTAPI_INTERNAL_URL || 'http://127.0.0.1:8000';

/**
 * Ekstraksi teks pesan secara lengkap dari berbagai format payload Baileys WhatsApp.
 */
export function extractMessageText(msg) {
  if (!msg || !msg.message) return '';
  const m = msg.message;

  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    m.buttonsResponseMessage?.selectedButtonId ||
    m.buttonsResponseMessage?.selectedDisplayText ||
    m.templateButtonReplyMessage?.selectedId ||
    m.listResponseMessage?.singleSelectReply?.selectedRowId ||
    m.ephemeralMessage?.message?.conversation ||
    m.ephemeralMessage?.message?.extendedTextMessage?.text ||
    m.ephemeralMessage?.message?.imageMessage?.caption ||
    m.viewOnceMessage?.message?.conversation ||
    m.viewOnceMessage?.message?.extendedTextMessage?.text ||
    m.viewOnceMessage?.message?.imageMessage?.caption ||
    m.viewOnceMessageV2?.message?.conversation ||
    m.viewOnceMessageV2?.message?.extendedTextMessage?.text ||
    ''
  ).trim();
}

/**
 * Registrasi listener messages.upsert pada socket Baileys dengan filtering & auto-reply AI pipeline.
 */
export function registerInboundMessageListener(sock, tenantSlug) {
  const resolvedTenant = String(tenantSlug || 'onlineboost').trim().toLowerCase();

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    // 1. Izinkan event dengan tipe 'notify' (inbound chat masuk dari WhatsApp)
    if (type !== 'notify' && type !== 'append') {
      return;
    }

    for (const msg of messages) {
      if (!msg || !msg.message) continue;

      // 2. Pastikan hanya mengabaikan pesan dari bot sendiri (fromMe)
      if (msg.key?.fromMe === true) {
        continue;
      }

      // 3. Format JID Pengirim & Filter Group / Broadcast
      const senderJid = msg.key?.remoteJid;
      if (!senderJid) continue;

      if (
        senderJid === 'status@broadcast' ||
        senderJid.endsWith('@broadcast') ||
        senderJid.endsWith('@g.us')
      ) {
        // Abaikan broadcast status WA Story dan grup agar auto-reply hanya ke chat personal
        continue;
      }

      // 4. Ekstraksi teks pesan secara lengkap
      const incomingText = extractMessageText(msg);
      if (!incomingText) {
        console.log(`[BAILEYS INBOUND] Pesan non-teks diterima dari ${senderJid} (dilewati).`);
        continue;
      }

      const senderPhone = senderJid.replace('@s.whatsapp.net', '').replace(/[^0-9]/g, '');

      // Log Terminal Detail Poin 3: Saat pesan masuk diterima
      console.log(`\n========================================================`);
      console.log(`[BAILEYS INBOUND] 📩 Pesan Masuk Diterima`);
      console.log(`  • Pengirim (JID) : ${senderJid} (HP: ${senderPhone})`);
      console.log(`  • Tenant ID      : ${resolvedTenant}`);
      console.log(`  • Isi Teks       : "${incomingText}"`);
      console.log(`========================================================`);

      // Indikator status mengetik (Human-like presence)
      try {
        await sock.sendPresenceUpdate('composing', senderJid);
      } catch (_) {}

      try {
        // Log Terminal Detail Poin 3: Proses pengambilan jawaban dari AI/Rules
        console.log(`[BAILEYS AI PIPELINE] Mengarahkan pesan ke backend AI Knowledge (/api/v1/whatsapp/inbound-process)...`);
        
        const res = await axios.post(
          `${FASTAPI_INTERNAL_URL}/api/v1/whatsapp/inbound-process`,
          {
            tenant_slug: resolvedTenant,
            sender_phone: senderPhone,
            message_body: incomingText,
          },
          { timeout: 35000 }
        );

        const replyText = res.data?.reply_text;
        console.log(`[BAILEYS AI PIPELINE] Jawaban diterima dari backend: ${replyText ? `"${replyText.substring(0, 80)}..."` : '(KOSONG)'}`);

        // Log Terminal Detail Poin 3: Saat fungsi pengiriman balasan (sock.sendMessage) dipanggil
        if (replyText) {
          console.log(`[BAILEYS DISPATCH] Mengirim balasan via sock.sendMessage ke ${senderJid}...`);
          const sendResult = await sock.sendMessage(senderJid, { text: replyText });
          console.log(`[BAILEYS DISPATCH SUCCESS] ✅ Balasan berhasil terkirim ke ${senderJid} (Msg ID: ${sendResult?.key?.id || 'OK'})`);
        } else {
          console.warn(`[BAILEYS DISPATCH WARN] Backend tidak mengembalikan reply_text untuk tenant [${resolvedTenant}]`);
        }
      } catch (err) {
        console.error(`[BAILEYS ERROR] ❌ Gagal memproses auto-reply tenant [${resolvedTenant}] ke ${senderJid}:`, err.response?.data || err.message);
      } finally {
        try {
          await sock.sendPresenceUpdate('paused', senderJid);
        } catch (_) {}
      }
    }
  });
}

export async function initGrowthSession(tenantSlug, onQRCallback) {
  const resolvedTenant = String(tenantSlug || 'onlineboost').trim().toLowerCase();
  const authDir = `./sessions/${resolvedTenant}`;
  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  const sock = makeWASocket({
    auth: state,
    printQRInTerminal: false,
    browser: Browsers.macOS('Desktop'),
    syncFullHistory: false
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr && onQRCallback) {
      const qrDataUrl = await QRCode.toDataURL(qr);
      onQRCallback({ qr_raw: qr, qr_image: qrDataUrl });
    }

    if (connection === 'open') {
      console.log(`[BAILEYS SESSION CONNECTED] Sesi WhatsApp Baileys terhubung untuk tenant: [${resolvedTenant}]`);
    }

    if (connection === 'close') {
      const isLoggedOut = lastDisconnect?.error?.output?.statusCode === DisconnectReason.loggedOut;
      console.log(`[BAILEYS SESSION CLOSED] Sesi [${resolvedTenant}] terputus. Reconnect: ${!isLoggedOut}`);
      if (!isLoggedOut) {
        initGrowthSession(resolvedTenant, onQRCallback);
      } else {
        tenantSessions.delete(resolvedTenant);
      }
    }
  });

  // Daftarkan listener messages.upsert
  registerInboundMessageListener(sock, resolvedTenant);

  tenantSessions.set(resolvedTenant, sock);
  return sock;
}

// Handler Khusus Pairing Code via Nomor Telepon
export async function requestPairingCodeSession(tenantSlug, phoneNumber) {
  const resolvedTenant = String(tenantSlug || 'onlineboost').trim().toLowerCase();
  let sock = tenantSessions.get(resolvedTenant);
  
  if (!sock) {
    const authDir = `./sessions/${resolvedTenant}`;
    const { state, saveCreds } = await useMultiFileAuthState(authDir);

    sock = makeWASocket({
      auth: state,
      printQRInTerminal: false,
      browser: Browsers.macOS('Desktop'),
      syncFullHistory: false
    });

    sock.ev.on('creds.update', saveCreds);
    registerInboundMessageListener(sock, resolvedTenant);
    tenantSessions.set(resolvedTenant, sock);
  }

  // Bersihkan karakter non-angka
  const cleanPhone = phoneNumber.replace(/[^0-9]/g, '');

  if (!sock.authState.creds.registered) {
    await delay(2000);
    const pairingCode = await sock.requestPairingCode(cleanPhone);
    return { success: true, pairing_code: pairingCode };
  }

  return { success: false, message: 'Nomor ini sudah terdaftar pada sesi aktif.' };
}