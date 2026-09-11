-- ============================================================================
-- Migration: Add media_url column to messages table
-- Date: 2026-09-11
-- Description: Mendukung penyimpanan URL media/gambar (Cloudflare R2) pada pesan WhatsApp.
-- ============================================================================

-- Tambahkan kolom media_url jika belum ada
ALTER TABLE public.messages
ADD COLUMN IF NOT EXISTS media_url TEXT;

-- Berikan komentar dokumentasi pada kolom
COMMENT ON COLUMN public.messages.media_url IS 'URL publik file/media tersimpan di Cloudflare R2 untuk pesan gambar/dokumen/audio.';
