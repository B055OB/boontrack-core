import makeWASocket, { useMultiFileAuthState, DisconnectReason } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';

const sessions = new Map();

export async function createTenantWASession(tenantSlug, onQRGenerated) {
  const { state, saveCreds } = await useMultiFileAuthState(`./sessions/${tenantSlug}`);
  
  const sock = makeWASocket({
    auth: state,
    printQRInTerminal: false,
    browser: ['BoonTrack Engine', 'Chrome', '1.0.0']
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    // String token mentah resmi dari server WhatsApp
    if (qr) {
      const qrDataUrl = await QRCode.toDataURL(qr);
      onQRGenerated({
        qr_raw: qr,
        qr_image: qrDataUrl
      });
    }

    if (connection === 'close') {
      const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
      if (shouldReconnect) {
        createTenantWASession(tenantSlug, onQRGenerated);
      }
    }
  });

  sessions.set(tenantSlug, sock);
  return sock;
}