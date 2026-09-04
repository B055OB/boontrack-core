import makeWASocket, { useMultiFileAuthState, DisconnectReason, Browsers } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import { registerInboundMessageListener } from './whatsapp_inbound_engine.js';

const sessions = new Map();

export async function createTenantWASession(tenantSlug, onQRGenerated) {
  const resolvedTenant = String(tenantSlug || 'onlineboost').trim().toLowerCase();
  const { state, saveCreds } = await useMultiFileAuthState(`./sessions/${resolvedTenant}`);
  
  const sock = makeWASocket({
    auth: state,
    printQRInTerminal: false,
    browser: Browsers.macOS('Desktop'),
    syncFullHistory: false
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    // String token mentah resmi dari server WhatsApp
    if (qr && onQRGenerated) {
      const qrDataUrl = await QRCode.toDataURL(qr);
      onQRGenerated({
        qr_raw: qr,
        qr_image: qrDataUrl
      });
    }

    if (connection === 'open') {
      console.log(`[BAILEYS SESSION CONNECTED] Sesi aktif terhubung untuk tenant: [${resolvedTenant}]`);
    }

    if (connection === 'close') {
      const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
      console.log(`[BAILEYS SESSION CLOSED] Sesi [${resolvedTenant}] terputus. Reconnect: ${shouldReconnect}`);
      if (shouldReconnect) {
        createTenantWASession(resolvedTenant, onQRGenerated);
      } else {
        sessions.delete(resolvedTenant);
      }
    }
  });

  // Daftarkan listener messages.upsert inbound auto-reply
  registerInboundMessageListener(sock, resolvedTenant);

  sessions.set(resolvedTenant, sock);
  return sock;
}