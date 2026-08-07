# 📄 ADR-001: Deterministic Engine as Permanent Baseline

* **Status:** ACCEPTED
* **Date:** 2026-08-01
* **Deciders:** Founder, CTO (Virtual)
* **Technical Context:** Conversation OS v1.0 / Solution Engine

---

##  Context & Problem Statement
Pada fase awal (Alpha-1 s.d. Alpha-3), engine percakapan sangat bergantung pada panggilan LLM API secara langsung untuk merespons pesan pengguna. Hal ini menyebabkan beberapa kendala kritikal:
1. Respon lambat (high latency).
2. Potensi *silent failure* dan error credential/API Key (seperti HTTP 401 / Unauthorized).
3. Kerentanan terhadap halusinasi AI yang memberikan informasi atau link tidak valid.

Sesuai **CTO Decision #079 (Architecture Freeze)**, sistem membutuhkan baseline yang stabil, instan, dan 100% konsisten untuk menyajikan solusi materi karir.

---

## 🎯 Decision
Kami memutuskan untuk menetapkan **Deterministic Local Engine / Search-Based Engine** sebagai baseline permanen (*Core Engine*) untuk menyajikan solusi dan respons percakapan.

### Arsitektur Alur Percakapan:
```text
User Input
   │
   ▼
Deterministic Intent / Keyword Matcher
   │
   ▼
Knowledge Assets (JSON/Database)
   │
   ▼
Instant Response (<0.1s, Zero Cost, Anti-Crash)
