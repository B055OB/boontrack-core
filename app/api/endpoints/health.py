import uuid
import asyncio
from datetime import datetime
from aiohttp import web
from psycopg2.extras import RealDictCursor
from app.core.database import get_db_connection

async def health_check_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "healthy", "message": "BoonTrack Core is awake!"}, status=200)

async def tracker_handler(request: web.Request) -> web.Response:
    try:
        source = request.match_info.get('source', 'direct')
        utm_source = request.query.get('utm_source', source)
        utm_medium = request.query.get('utm_medium', 'organic')
        utm_campaign = request.query.get('utm_campaign', 'general')
        utm_content = request.query.get('utm_content', '')
        utm_term = request.query.get('utm_term', '')
        
        ip = request.headers.get('CF-Connecting-IP') or request.remote
        user_agent = request.headers.get('User-Agent', '')
        
        click_id = f"CLK-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:6]}"

        def _log_click():
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO click_logs 
                    (click_id, source, utm_source, utm_medium, utm_campaign, utm_content, utm_term, event_name, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'click_link', %s, %s)
                """, (click_id, source, utm_source, utm_medium, utm_campaign, utm_content, utm_term, ip, user_agent))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as ce:
                print(f"[Tracker DB Error] {ce}", flush=True)

        asyncio.create_task(asyncio.to_thread(_log_click))

        target_bot_url = f"https://t.me/boontrackbot?start={click_id}"
        return web.HTTPFound(location=target_bot_url)

    except Exception as e:
        print(f"[Tracker Error] {e}", flush=True)
        return web.HTTPFound(location="https://t.me/boontrackbot")

async def funnel_report_handler(request: web.Request) -> web.Response:
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT 
                LOWER(c.source) as channel,
                COUNT(DISTINCT c.click_id) as total_klik,
                COUNT(DISTINCT CASE WHEN c.telegram_user_id IS NOT NULL THEN c.telegram_user_id END) as masuk_telegram,
                COUNT(DISTINCT CASE WHEN a.event = 'resume_generated' THEN a.user_id END) as selesai_cv,
                COUNT(DISTINCT CASE WHEN p.status = 'PAID' THEN p.telegram_id END) as purchase
            FROM click_logs c
            LEFT JOIN analytics a ON c.telegram_user_id = a.user_id
            LEFT JOIN product_orders p ON c.telegram_user_id = p.telegram_id
            GROUP BY LOWER(c.source);
        """
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return web.json_response({"status": "success", "data": rows})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)
