import os, psycopg2, re
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

# 1. Baca definisi constraint chk_conversations_bot_mode dari PostgreSQL
cur.execute("""
    SELECT pg_get_constraintdef(oid) 
    FROM pg_constraint 
    WHERE conname = 'chk_conversations_bot_mode';
""")
c_row = cur.fetchone()
c_def = c_row[0] if c_row else ""
print("Definisi constraint chk_conversations_bot_mode:\n", c_def)

# 2. Baca nilai bot_mode yang sudah tersimpan di database
cur.execute("SELECT DISTINCT bot_mode FROM conversations WHERE bot_mode IS NOT NULL;")
existing_modes = [r[0] for r in cur.fetchall()]
print("Nilai bot_mode eksis:", existing_modes)

# 3. Ekstrak nilai sah dari constraint (misal: 'AI', 'HUMAN', dll)
allowed = re.findall(r"'([A-Za-z0-9_]+)'", c_def)
print("Nilai sah dari constraint:", allowed)

# Tentukan nilai aktif (bukan HUMAN / MANUAL)
active_mode = None
for candidate in ['AI', 'AI_ACTIVE', 'AUTO', 'BOT']:
    if candidate in allowed or candidate in existing_modes:
        active_mode = candidate
        break
if not active_mode and allowed:
    non_human = [m for m in allowed if 'HUMAN' not in m.upper() and 'MANUAL' not in m.upper()]
    if non_human:
        active_mode = non_human[0]

print("-> Mode bot aktif terpilih:", active_mode)

# 4. Update tabel conversations tanpa terkena pelanggaran constraint
if active_mode:
    cur.execute(f"""
        UPDATE conversations 
        SET bot_paused = false, 
            bot_mode = '{active_mode}', 
            is_paused = false, 
            current_state = 'BOT_ACTIVE',
            paused_until = NULL 
        WHERE bot_paused = true OR is_paused = true OR bot_mode != '{active_mode}';
    """)
else:
    cur.execute("""
        UPDATE conversations 
        SET bot_paused = false, 
            is_paused = false, 
            current_state = 'BOT_ACTIVE',
            paused_until = NULL 
        WHERE bot_paused = true OR is_paused = true;
    """)
print(f"-> Sukses update conversations: {cur.rowcount} baris diaktifkan.")

# 5. Update tabel chat_sessions
cur.execute("""
    UPDATE chat_sessions 
    SET is_paused = false, 
        current_state = 'BOT_ACTIVE', 
        paused_until = NULL 
    WHERE is_paused = true OR paused_until > NOW();
""")
print(f"-> Sukses update chat_sessions: {cur.rowcount} baris diaktifkan.")

conn.commit()
print("=== SEMUA SESI BERHASIL DIAKTIFKAN KEMBALI KE BOT AI ===")
conn.close()
