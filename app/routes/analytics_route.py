from fastapi import APIRouter, Query, Request
import logging

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
        
        # Safe Lazy Import di dalam fungsi
        try:
            from app.services.supabase_client import supabase
            supabase.table("click_logs").insert(data).execute()
        except Exception as db_err:
            try:
                from app.core.database import supabase
                supabase.table("click_logs").insert(data).execute()
            except Exception as db_err2:
                logger.error(f"[DB INSERT ERROR] {db_err2}")
            
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