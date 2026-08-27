import time
from collections import defaultdict
from typing import Tuple

# Hanya tenant pelayanan publik/Diskominfo yang dikenakan batasan rate limit
PUBLIC_SERVICE_TENANTS = {"diskominfo", "pelayanan_publik", "layanan_warga"}


class WhatsAppRateLimiter:
    """In-memory sliding window rate limiter per nomor telepon."""
    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.history = defaultdict(list)

    def is_allowed(self, phone_number: str, tenant_id: str = "om_budi", is_button: bool = False) -> Tuple[bool, int]:
        """
        Cek batas request nomor HP.
        Tenant non-publik (seperti om_budi, career, commerce) atau klik tombol interaktif otomatis lolos (bypass).
        """
        # Bypass penuh jika bukan pelayanan publik atau berupa interaksi tombol
        if tenant_id not in PUBLIC_SERVICE_TENANTS or is_button:
            return True, 0

        now = time.time()
        timestamps = self.history[phone_number]

        # Bersihkan timestamp di luar rentang window
        self.history[phone_number] = [t for t in timestamps if now - t < self.window_seconds]

        if len(self.history[phone_number]) >= self.max_requests:
            oldest = self.history[phone_number][0]
            retry_after = int(self.window_seconds - (now - oldest))
            return False, max(retry_after, 1)

        self.history[phone_number].append(now)
        return True, 0


# Singleton instance
wa_rate_limiter = WhatsAppRateLimiter(max_requests=5, window_seconds=60)
