import os
import json
import asyncio
from datetime import datetime, timedelta
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
    
    # 1. Tabel users
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
    
    # 2. Tabel analytics
    cur.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            event VARCHAR(100),
            meta JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Tabel cv_documents
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

    # 4. Tabel user_progress
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id BIGINT PRIMARY KEY,
            last_step INT,
            data JSONB,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 5. Tabel product_orders
    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_orders (
            id SERIAL PRIMARY KEY,
            order_id VARCHAR(50) UNIQUE,
            telegram_id BIGINT,
            product_name VARCHAR(100),
            base_price INT,
            unique_code INT,
            total_amount INT UNIQUE,
            status VARCHAR(20) DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        );
    """)

    # 6. Tabel donation_sessions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS donation_sessions (
            id SERIAL PRIMARY KEY,
            donation_id VARCHAR(50) UNIQUE,
            telegram_id BIGINT,
            base_amount INT,
            unique_code INT,
            total_amount INT UNIQUE,
            status VARCHAR(20) DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        );
    """)

    # 7. Tabel click_logs (Analytics Tracking)
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

    # 8. Tabel cv_reviews
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cv_reviews (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            target_position VARCHAR(255) NOT NULL,
            cv_version INT DEFAULT 1,
            overall_score INT NOT NULL,
            quality_score INT NOT NULL,
            job_match_score INT NOT NULL,
            evidence_score INT NOT NULL,
            review_json JSONB NOT NULL,
            confidence_level VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 9. Tabel ai_usage_logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            provider VARCHAR(50) NOT NULL,
            feature VARCHAR(50) DEFAULT 'general',
            prompt_tokens INT DEFAULT 0,
            completion_tokens INT DEFAULT 0,
            total_tokens INT DEFAULT 0,
            status_code INT DEFAULT 200,
            is_error BOOLEAN DEFAULT FALSE,
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    await asyncio.to_thread(_save_dropoff_sync, user_id, step, data)

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

def _count_referrals_sync(referrer_id: str) -> int:
    try:
        conn = get_db_connection()
        cur = conn.cursor()
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

# --- Order & Donation Helpers ---

def _check_user_paid_sync(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM donation_sessions WHERE telegram_id = %s AND status = 'VERIFIED' LIMIT 1;",
            (user_id,)
        )
        res = cur.fetchone()
        cur.close()
        conn.close()
        return bool(res)
    except Exception as e:
        print(f"Check User Paid Error: {e}", flush=True)
        return False

async def check_user_paid(user_id):
    return await asyncio.to_thread(_check_user_paid_sync, user_id)

def _create_order_sync(telegram_id, product_name, base_price, unique_code, total_amount):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        order_id = f"ORD-{int(datetime.now().timestamp())}"
        expires_at = datetime.now() + timedelta(minutes=15)
        cur.execute("""
            INSERT INTO product_orders (order_id, telegram_id, product_name, base_price, unique_code, total_amount, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (total_amount) DO UPDATE SET
                telegram_id = EXCLUDED.telegram_id,
                product_name = EXCLUDED.product_name,
                expires_at = EXCLUDED.expires_at,
                status = 'PENDING';
        """, (order_id, telegram_id, product_name, base_price, unique_code, total_amount, expires_at))
        conn.commit()
        cur.close()
        conn.close()
        return order_id
    except Exception as e:
        print(f"Create Order Error: {e}", flush=True)
        return None

async def create_order(telegram_id, product_name, base_price, unique_code, total_amount):
    return await asyncio.to_thread(_create_order_sync, telegram_id, product_name, base_price, unique_code, total_amount)

def _match_and_complete_order_sync(amount):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM product_orders 
            WHERE total_amount = %s AND expires_at > CURRENT_TIMESTAMP
            LIMIT 1;
        """, (amount,))
        order = cur.fetchone()
        if order and order.get("status") == "PENDING":
            cur.execute("UPDATE product_orders SET status = 'PAID' WHERE id = %s;", (order["id"],))
            conn.commit()
        cur.close()
        conn.close()
        return order
    except Exception as e:
        print(f"Match Order Error: {e}", flush=True)
        return None

async def match_and_complete_order(amount):
    return await asyncio.to_thread(_match_and_complete_order_sync, amount)

def _create_donation_session_sync(telegram_id, base_amount, unique_code, total_amount):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        donation_id = f"DON-{int(datetime.now().timestamp())}"
        expires_at = datetime.now() + timedelta(minutes=15)
        cur.execute("""
            INSERT INTO donation_sessions (donation_id, telegram_id, base_amount, unique_code, total_amount, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (total_amount) DO UPDATE SET
                telegram_id = EXCLUDED.telegram_id,
                base_amount = EXCLUDED.base_amount,
                expires_at = EXCLUDED.expires_at,
                status = 'PENDING';
        """, (donation_id, telegram_id, base_amount, unique_code, total_amount, expires_at))
        conn.commit()
        cur.close()
        conn.close()
        return donation_id
    except Exception as e:
        print(f"Create Donation Error: {e}", flush=True)
        return None

async def create_donation_session(telegram_id, base_amount, unique_code, total_amount):
    return await asyncio.to_thread(_create_donation_session_sync, telegram_id, base_amount, unique_code, total_amount)

def _match_and_complete_donation_sync(amount):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM donation_sessions 
            WHERE total_amount = %s AND status = 'PENDING'
            ORDER BY created_at DESC 
            LIMIT 1;
        """, (amount,))
        donation = cur.fetchone()
        if donation:
            cur.execute("UPDATE donation_sessions SET status = 'VERIFIED' WHERE id = %s;", (donation["id"],))
            conn.commit()
        cur.close()
        conn.close()
        return donation
    except Exception as e:
        print(f"Match Donation Error: {e}", flush=True)
        return None

async def match_and_complete_donation(amount):
    return await asyncio.to_thread(_match_and_complete_donation_sync, amount)
