from fastapi import APIRouter, Query, Request
import logging

try:
    from app.services.supabase_client import supabase
except ImportError:
    try:
        from app.core.database import supabase
    except ImportError:
        supabase = None

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])
logger = logging.getLogger(__name__)

@router.get("/track_click")
@router.post("/track_click")
async def track_click(channel: str = Query("direct"), request: Request = None):
    """
    Endpoint untuk mencatat klik/view dari landing page boontrack.com/<channel>
    ke tabel click_logs di Supabase.
    """
    try:
        clean_channel = channel.lower().strip()
        data = {
            "channel": clean_channel,
            "utm_source": clean_channel,
            "source": "web_landing_page"
        }
        
        if supabase:
            # Insert baris data baru ke tabel click_logs
            supabase.table("click_logs").insert(data).execute()
            
        logger.info(f"[TRACK CLICK SUCCESS] Channel: {clean_channel}")
        return {
            "status": "success",
            "message": f"Click tracked for channel: {clean_channel}"
        }
    except Exception as e:
        logger.error(f"[TRACK CLICK ERROR] {e}")
        return {
            "status": "error",
            "message": str(e)
        }