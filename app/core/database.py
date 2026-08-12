def _init_db_sync():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Tabel users dengan skema Full UTM & Referral Attributes
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            language_code VARCHAR(10),
            first_source VARCHAR(100) DEFAULT 'direct',
            latest_source VARCHAR(100) DEFAULT 'direct',
            utm_medium VARCHAR(100) DEFAULT 'none',
            utm_campaign VARCHAR(100) DEFAULT 'none',
            utm_content VARCHAR(100) DEFAULT 'none',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 2. Tabel analytics untuk event logging & tracking referral
    cur.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            event VARCHAR(100),
            meta JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Tabel dokumen CV
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cv_documents (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            version INT DEFAULT 1,
            position VARCHAR(255),
            data JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. Tabel user progress (tracking dropoff)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id BIGINT PRIMARY KEY,
            last_step INT,
            data JSONB,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 5. Tabel click_logs (Custom Analytics & Tracking Pixel)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS click_logs (
            id SERIAL PRIMARY KEY,
            click_id VARCHAR(100) UNIQUE,
            source VARCHAR(50),
            utm_source VARCHAR(50),
            utm_medium VARCHAR(50),
            utm_campaign VARCHAR(100),
            utm_content VARCHAR(100),
            utm_term VARCHAR(100),
            telegram_user_id BIGINT,
            event_name VARCHAR(50) DEFAULT 'page_view',
            ip_address VARCHAR(50),
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    conn.commit()
    cur.close()
    conn.close()