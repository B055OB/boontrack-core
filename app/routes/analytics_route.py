from flask import Blueprint, request, jsonify
import logging
import threading

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
logger = logging.getLogger(__name__)

def get_supabase_client():
    """
    Helper function untuk menemukan instance Supabase secara otomatis
    tanpa memicu ImportError crash.
    """
    # Try 1: dari app.services.supabase_client
    try:
        from app.services.supabase_client import supabase
        if supabase: return supabase
    except Exception:
        pass

    # Try 2: dari app.core.database (cari semua atribut yang ada)
    try:
        import app.core.database as db_mod
        for attr in ['supabase', 'supabase_client', 'client', 'db']:
            if hasattr(db_mod, attr):
                return getattr(db_mod, attr)
    except Exception:
        pass

    return None

def _async_insert_click(data):
    """
    Fungsi eksekusi di latar belakang agar server tidak hang/timeout.
    """
    try:
        client = get_supabase_client()
        if client:
            client.table("click_logs").insert(data).execute()
            logger.info(f"[DB INSERT SUCCESS] Channel: {data.get('channel')}")
        else:
            logger.error("[DB INSERT ERROR] Supabase client tidak ditemukan.")
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

@analytics_bp.route('/funnel', methods=['GET'])
def get_funnel_summary():
    """
    Endpoint untuk menyuplai ringkasan agregat per channel ke Google Sheet CFO.
    """
    try:
        supabase = get_supabase_client()
        
        if not supabase:
            return jsonify({
                "status": "error", 
                "message": "Supabase client tidak ditemukan di app.services atau app.core.database"
            }), 500

        # Ambil data dari Supabase
        response = supabase.table("click_logs").select("*").execute()
        raw_data = response.data if response.data else []
        
        # Agregasi data berdasarkan channel
        summary = {}
        for row in raw_data:
            ch = str(row.get("channel", "unknown")).lower().strip()
            if ch not in summary:
                summary[ch] = {
                    "channel": ch,
                    "total_klik": 0,
                    "masuk_telegram": 0,
                    "selesai_cv": 0,
                    "purchase": 0
                }
            
            summary[ch]["total_klik"] += 1
            if row.get("entered_telegram"): summary[ch]["masuk_telegram"] += 1
            if row.get("cv_completed"): summary[ch]["selesai_cv"] += 1
            if row.get("purchased"): summary[ch]["purchase"] += 1
            
        return jsonify(list(summary.values())), 200

    except Exception as e:
        logger.error(f"Error fetching funnel data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500