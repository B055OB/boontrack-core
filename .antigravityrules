# BOONTRACK CORE ARCHITECTURE GOVERNANCE RULES

1. BARREL EXPORT RESTRICTION:
   - Dilarang membuat barrel export sapu jagat (`components/index.ts` atau `lib/index.ts`) yang mengekspor modul berat bersama komponen inti.
   - Gunakan direct atomic imports ke path spesifik.

2. ZERO HARDCODED DOMAINS:
   - Helper URL builder wajib mengutamakan `tenant.custom_domain` jika ada, sebelum fallback ke `shop.boontrack.com/{slug}`.

3. PACKAGE / SHARED EXPORTS:
   - Ekspor tipe dan utility wajib bersih dari runtime side-effects agar tidak memicu Temporal Dead Zone (TDZ) pada consumer repo (inbox).
