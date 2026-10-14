-- Migration 026: Add provider column to conversations table for Strict Channel Binding (Zero Guessing)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS provider VARCHAR(50);
CREATE INDEX IF NOT EXISTS idx_conversations_channel_conn ON conversations (channel_connection_id);
