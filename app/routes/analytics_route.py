from flask import Blueprint, request, jsonify
import logging
import threading

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
logger = logging.getLogger(__name__)

def _async_insert_click(data):
    """
    Fungsi eksekusi di latar belakang agar server tidak hang/timeout.
    """
    try:
        try:
            from app.services.supabase_client import supabase
        except ImportError:
            from app.core.database import supabase
            
        if supabase:
            supabase.table("click_logs").insert(data).execute()
            logger.info(f"[DB INSERT SUCCESS] Channel: {data.get('channel')}")
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
    
    # Jalankan insert database di background thread (Non-blocking)
    threading.Thread(target=_async_insert_click, args=(data,), daemon=True).start()
    
    # Langsung kembalikan respon instan tanpa menunggu DB
    return jsonify({
        "status": "success",
        "message": f"Click tracked for channel: {channel}"
    }), 200