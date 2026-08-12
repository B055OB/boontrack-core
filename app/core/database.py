import os
import json
import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
from aiogram import types
from app.core.config import settings
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

def get_db_connection():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD
    )

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
    
    conn.commit()
    cur.close()
    conn.close()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

# --- Analytics & Tracking Helpers ---

def _track_event_sync(user_id, event, meta=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO analytics (user_id, event, meta) VALUES (%s, %s, %s)",
            (user_id, event, json.dumps(meta or {}))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Analytics DB Error: {e}")

async def track_event(user_id, event, meta=None):
    await asyncio.to_thread(_track_event_sync, user_id, event, meta)

def _save_user_sync(user: types.User, meta: dict = None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        meta = meta or {}
        first_src = meta.get("first_source", "direct")
        latest_src = meta.get("latest_source", "direct")
        medium = meta.get("utm_medium", "none")
        campaign = meta.get("utm_campaign", "none")
        content = meta.get("utm_content", "none")

        cur.execute("""
            INSERT INTO users (
                telegram_id, username, first_name, last_name, language_code, 
                first_source, latest_source, utm_medium, utm_campaign, utm_content
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                latest_source = EXCLUDED.latest_source,
                utm_medium = EXCLUDED.utm_medium,
                utm_campaign = EXCLUDED.utm_campaign,
                utm_content = EXCLUDED.utm_content;
        """, (
            user.id, user.username, user.first_name, user.last_name, user.language_code,
            first_src, latest_src, medium, campaign, content
        ))
        
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Save User DB Error: {e}")

async def save_user(user: types.User, meta: dict = None):
    await asyncio.to_thread(_save_user_sync, user, meta)

def _save_dropoff_sync(user_id, step, data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_progress (user_id, last_step, data, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                last_step = EXCLUDED.last_step,
                data = EXCLUDED.data,
                updated_at = CURRENT_TIMESTAMP;
        """, (user_id, step, json.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Dropoff DB Error: {e}")

async def save_dropoff(user_id, step, data):
    await asyncio-to_thread(_save_dropoff_sync, user_id, step, data)

def _get_user_history_sync(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT last_step, data FROM user_progress WHERE user_id = %s", (user_id,))
        progress = cur.fetchone()
        
        cur.execute("SELECT version, position, data, created_at FROM cv_documents WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        last_cv = cur.fetchone()
        
        cur.close()
        conn.close()
        return progress, last_cv
    except Exception as e:
        print(f"Get User History Error: {e}")
        return None, None

async def get_user_history(user_id):
    return await asyncio.to_thread(_get_user_history_sync, user_id)

def _save_cv_version_sync(user_id, position, data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM cv_documents WHERE user_id = %s", (user_id,))
        count = cur.fetchone()[0]
        version = count + 1
        
        cur.execute("""
            INSERT INTO cv_documents (user_id, version, position, data)
            VALUES (%s, %s, %s, %s)
        """, (user_id, version, position, json.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Save CV Version Error: {e}")

async def save_cv_version(user_id, position, data):
    await asyncio.to_thread(_save_cv_version_sync, user_id, position, data)

# --- Referral Helper Function ---

def _count_referrals_sync(referrer_id: str) -> int:
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Menghitung berapa user unik yang mendaftar via link referral milik referrer_id ini
        cur.execute("""
            SELECT COUNT(DISTINCT user_id) FROM analytics 
            WHERE event = 'start' AND (meta->>'referrer_id') = %s
        """, (str(referrer_id),))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        print(f"Count Referrals Error: {e}")
        return 0

async def count_referrals(referrer_id: str) -> int:
    return await asyncio.to_thread(_count_referrals_sync, referrer_id)