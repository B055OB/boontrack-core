from flask import Blueprint, request, jsonify
import logging
import threading
import os

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
logger = logging.getLogger(__name__)

# Credentials Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://mpluzajlzpregmjwpjqr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_OXETaOPFYI_AKCrKpLEr0Q__RUHScg7") # Gunakan Publishable Key yang tadi di-copy

def get_supabase():
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as err:
        logger.error(f"[SUPABASE INIT ERROR] {err}")
        return None

def _async_insert_click(data):
    """
    Fungsi eksekusi di latar belakang agar server tidak hang/timeout.
    """
    try:
        client = get_supabase()
        if client:
            client.table("click_logs").insert(data).execute()
            logger.info(f"[DB INSERT SUCCESS] Channel: {data.get('channel')}")
        else:
            logger.error("[DB INSERT ERROR] Client Supabase gagal dibuat.")
    except Exception as err:
        logger.error(f"[DB INSERT ASYNC ERROR] {err}")

@analytics_bp.route('/track_click', methods=['GET', 'POST'])
def track_click():
    """
    Endpoint Flask super instan (0.01s response time).
    """
    channel = request.args.get('channel', 'direct').lower().strip()
    
    data = {
        "channel": channel,
        "utm_source": channel,
        "source": "web_landing_page"
    }
    
    threading.Thread(target=_async_insert_click, args=(data,), daemon=True).start()
    
    return jsonify({
        "status": "success",
        "message": f"Click tracked for channel: {channel}"
    }), 200