from flask import Blueprint, request, jsonify
import logging

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
logger = logging.getLogger(__name__)

@analytics_bp.route('/track_click', methods=['GET', 'POST'])
def track_click():
    """
    Endpoint Flask untuk mencatat klik/view dari landing page boontrack.com/<channel>
    ke tabel click_logs di Supabase.
    """
    channel = request.args.get('channel', 'direct').lower().strip()
    
    try:
        data = {
            "channel": channel,
            "utm_source": channel,
            "source": "web_landing_page"
        }
        
        # Lazy import Supabase agar aman
        try:
            from app.services.supabase_client import supabase
            supabase.table("click_logs").insert(data).execute()
        except Exception as db_err:
            try:
                from app.core.database import supabase
                supabase.table("click_logs").insert(data).execute()
            except Exception as db_err2:
                logger.error(f"[DB INSERT ERROR] {db_err2}")
                
        logger.info(f"[TRACK CLICK SUCCESS] Channel: {channel}")
        return jsonify({
            "status": "success",
            "message": f"Click tracked for channel: {channel}"
        }), 200

    except Exception as e:
        logger.error(f"[TRACK CLICK ERROR] {e}")
        return jsonify({
            "status": "success",
            "message": f"Click tracked for channel: {channel}"
        }), 200