# 📄 ADR-002: LLM Provider Abstraction & AI Gateway

* **Status:** ACCEPTED
* **Date:** 2026-08-01
* **Deciders:** Founder, CTO (Virtual)
* **Technical Context:** app/intelligence/ & CTO Decision #089–#094

---

## 🏛️ Context & Problem Statement
Integrasi langsung (*hardcoded*) ke SDK vendor AI tertentu (seperti Google Gemini atau OpenAI) membuat kodingan terikat erat (*tight coupling*) pada satu penyedia. Jika vendor mengubah kebijakan API, terjadi *breaking changes* pada SDK, atau layanan mengalami *downtime*, *Core Engine* sistem akan ikut terganggu atau terhenti (*crash*).

Selain itu, modul AI sering kali berubah menjadi *junk folder* (folder penampungan berantakan) jika mencampurkan logika bisnis, penulisan prompt, dan SDK vendor di satu tempat yang sama.

---

## 🎯 Decision
Kami menerapkan **LLM Provider Abstraction** dan **AI Gateway Pattern** yang terisolasi penuh di bawah namespace `app/intelligence/`.

### Prinsip Utama (Sesuai CTO Decision #089 - #094):
1. **AI Vendor Independence (#089):** *Core Engine* tidak boleh mengenal vendor AI tertentu. AI Provider adalah *replaceable implementation* (komponen yang dapat diganti kapan saja).
2. **AI ≠ LLM Structure (#090):** Memisahkan area *intelligence* berdasarkan domainnya (LLM, Prompts, Embedding, Reranker, Classifier) agar arsitektur tidak membengkak di satu folder.
3. **Prompt as Source Code (#091):** Prompt dilarang ditulis *hardcoded* di dalam kode Python. Semua prompt disimpan terpisah sebagai file `.md` berversi (contoh: `prompts/interview/v1.md`).
4. **Stateless Provider (#092):** Provider tidak boleh menyimpan *state* atau histori percakapan. Histori dikelola penuh oleh *Conversation Engine*.
5. **Canonical Response (#093):** Seluruh provider wajib mengembalikan format objek standar **`LLMResponse`** (`text`, `finish_reason`, `latency_ms`, `token_usage`, `provider`, `model`).
6. **AI Gateway (#094):** Seluruh pemanggilan AI wajib melewati pintu tunggal `AIGateway` yang menangani *retry, timeout, fallback, telemetry,* dan *mocking*.

### Arsitektur AI Layer:
```text
Conversation Engine
       │
       ▼
   AI Gateway ───────► Prompt Loader & Telemetry
       │
 Provider Factory
       │
 ┌─────┼──────────┬──────────┐
 ▼     ▼          ▼          ▼
Mock  Gemini   OpenAI     Ollama
