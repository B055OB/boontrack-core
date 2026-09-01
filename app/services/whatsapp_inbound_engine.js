import makeWASocket, { useMultiFileAuthState, DisconnectReason, delay } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import axios from 'axios';

const tenantSessions = new Map();
const FASTAPI_INTERNAL_URL = process.env.FASTAPI_INTERNAL_URL || 'http://127.0.0.1:8000';

export async function initGrowthSession(tenantSlug, onQRCallback) {
  const authDir = `./sessions/${tenantSlug}`;
  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  const sock = makeWASocket({
    auth: state,
    printQRInTerminal: false,
    browser: ['BoonTrack Inbound', 'Chrome', '1.0.0'],
    syncFullHistory: false
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      const qrDataUrl = await QRCode.toDataURL(qr);
      onQRCallback({ qr_raw: qr, qr_image: qrDataUrl });
    }

    if (connection === 'close') {
      const isLoggedOut = lastDisconnect?.error?.output?.statusCode === DisconnectReason.loggedOut;
      if (!isLoggedOut) {
        initGrowthSession(tenantSlug, onQRCallback);
      } else {
        tenantSessions.delete(tenantSlug);
      }
    }
  });

  // Listener Khusus Pesan Inbound
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;

    for (const msg of messages) {
      if (msg.key.fromMe) continue; // Abaikan pesan dari bot sendiri

      const senderJid = msg.key.remoteJid;
      const incomingText = msg.message?.conversation || msg.message?.extendedTextMessage?.text || '';

      if (!incomingText) continue;

      // 1. Kirim Presence 'composing' (Mengetik)
      await sock.sendPresenceUpdate('composing', senderJid);
      await delay(2000 + Math.random() * 1500); // Human-like delay 2-3.5 detik

      try {
        // 2. Oper ke FastAPI Core untuk diproses AI Knowledge / Router Katalog
        const res = await axios.post(`${FASTAPI_INTERNAL_URL}/api/v1/whatsapp/inbound-process`, {
          tenant_slug: tenantSlug,
          sender_phone: senderJid.replace('@s.whatsapp.net', ''),
          message_body: incomingText
        });

        const replyText = res.data?.reply_text;
        if (replyText) {
          await sock.sendMessage(senderJid, { text: replyText });
        }
      } catch (err) {
        console.error(`Gagal memproses auto-reply inbound tenant [${tenantSlug}]:`, err.message);
      } finally {
        await sock.sendPresenceUpdate('paused', senderJid);
      }
    }
  });

  tenantSessions.set(tenantSlug, sock);
  return sock;
}