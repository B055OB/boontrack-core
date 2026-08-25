import asyncio
from aiohttp import web
from typing import Dict, Optional
from pydantic import BaseModel, Field

from app.core.database import get_db_connection
from app.services.whatsapp_service import log_to_supabase_messages
from app.services.cv_flow_service import ai_career_chat_response
from app.services.webchat_service import WebChatService
from app.services.lead_service import LeadService
from app.services.ai_gateway import AIGateway
from app.services.brain_engine import BrainEngine
from app.repositories.session_repository import SessionRepository

WEB_SESSION_COUNTS: Dict[str, int] = {}
MAX_WEB_MESSAGES = 7

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
}

_b2b_session_repo = SessionRepository()
_b2b_ai_gateway = AIGateway()
_b2b_brain_engine = BrainEngine(session_repo=_b2b_session_repo, ai_gateway=_b2b_ai_gateway)
_b2b_lead_service = LeadService(ai_gateway=_b2b_ai_gateway)
_b2b_webchat_service = WebChatService(brain_engine=_b2b_brain_engine, lead_service=_b2b_lead_service)

async def handle_web_chat_http(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=CORS_HEADERS)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error", "message": "Invalid JSON"}, status=400, headers=CORS_HEADERS)

    session_id = str(data.get("session_id", "")).strip()
    user_msg = str(data.get("message", "")).strip()
    utm_data = data.get("utm_data") or {}
    click_id = data.get("click_id")

    if not user_msg:
        return web.json_response({"status": "error", "message": "Pesan tidak boleh kosong"}, status=400, headers=CORS_HEADERS)

    # 1. LOG PESAN USER WEBCHAT KARIR KE SUPABASE
    await log_to_supabase_messages(
        sender=f"Visitor / {session_id[:8]}",
        text=user_msg,
        tenant_id="boontrack-career",
        channel="webchat",
        user_id=session_id,
        user_name=f"Web Visitor #{session_id[:5]}"
    )

    current_count = WEB_SESSION_COUNTS.get(session_id, 0)

    if utm_data and current_count == 0:
        def _log_utm():
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO click_logs (click_id, utm_source, utm_medium, utm_campaign, utm_content, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (click_id) DO NOTHING
                """, (
                    click_id or session_id,
                    utm_data.get("utm_source", "web_direct"),
                    utm_data.get("utm_medium", "web_chat"),
                    utm_data.get("utm_campaign", "none"),
                    utm_data.get("utm_content", "none")
                ))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"[WEB CHAT UTM LOG ERROR] {e}", flush=True)

        asyncio.create_task(asyncio.to_thread(_log_utm))

    if current_count >= MAX_WEB_MESSAGES:
        return web.json_response({
            "status": "limit_reached",
            "reply": "Kamu sudah mencapai batas konsultasi awal gratis di web. Mau lanjutkan konsultasi mendalam dan review CV lengkap?",
            "cta": {
                "type": "telegram",
                "label": "🚀 Lanjutkan di Telegram",
                "url": f"https://t.me/BoonTrackBot?start={click_id or session_id}"
            }
        }, headers=CORS_HEADERS)

    try:
        web_context_prompt = (
            f"[Instruksi Khusus Web Chat: Berikan respons yang SANGAT SINGKAT, padat, dan to-the-point "
            f"(maksimal 2-3 kalimat pendek). Berikan 1 poin insight kunci tanpa bertele-tele.]\n\n"
            f"Pesan User: {user_msg}"
        )

        ai_reply = await ai_career_chat_response(
            user_query=web_context_prompt,
            user_context={"session_id": session_id, "source": "web_chat"}
        )
    except Exception as e:
        print(f"[WEB CHAT AI ERROR] {e}", flush=True)
        ai_reply = "Saya siap bantu carikan solusinya! Boleh ceritakan posisi apa yang ingin kamu lamar saat ini?"

    WEB_SESSION_COUNTS[session_id] = current_count + 1
    updated_count = WEB_SESSION_COUNTS[session_id]

    user_msg_lower = user_msg.lower()
    if "telegram" in user_msg_lower or "link" in user_msg_lower:
        ai_reply = "Kamu bisa langsung lanjut konsultasi penuh dan pembuatan CV di bot resmi kami di https://t.me/boontrackbot atau klik tombol hijau di bawah ya!"
    elif updated_count in [2, 3]:
        ai_reply += "\n\n👉 *Untuk pembahasan lebih lengkap dan panduan detailnya, silakan lanjut di Telegram ya!*"

    # 2. LOG RESPON BOT WEBCHAT KE SUPABASE
    await log_to_supabase_messages(
        sender="BoonTrack AI",
        text=ai_reply,
        tenant_id="boontrack-career",
        channel="webchat",
        user_id=session_id,
        user_name=f"Web Visitor #{session_id[:5]}"
    )

    cta_data = None
    if updated_count >= 3:
        cta_data = {
            "type": "telegram",
            "label": "🚀 Lanjutkan Konsultasi Penuh di Telegram",
            "url": f"https://t.me/BoonTrackBot?start={click_id or session_id}"
        }

    return web.json_response({
        "status": "success",
        "reply": ai_reply,
        "messages_used": updated_count,
        "messages_limit": MAX_WEB_MESSAGES,
        "cta": cta_data
    }, headers=CORS_HEADERS)

async def handle_b2b_webchat_http(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        session_id = data.get("session_id", "default_session")
        message = data.get("message", "")

        if not message:
            return web.json_response({"error": "Message cannot be empty"}, status=400)

        # 1. Log chat user holding ke Supabase
        await log_to_supabase_messages(
            sender=f"Visitor / {session_id[:8]}",
            text=message,
            tenant_id="boontrack-holding",
            channel="webchat",
            user_id=session_id,
            user_name=f"Holding Visitor #{session_id[:5]}"
        )

        result = await _b2b_webchat_service.process_business_chat(
            session_id=session_id,
            message=message
        )

        raw_reply = result.get("reply", "")
        if any(keyword in str(raw_reply).upper() for keyword in ["QUERY", "START", "FALLBACK", "GENERAL"]):
            reply = "Terima kasih atas pertanyaannya! BoonTrack Group siap membantu kebutuhan otomatisasi AI dan software kustom untuk bisnis Anda. Ada spesifikasi khusus yang ingin didiskusikan?"
        else:
            reply = raw_reply

        # 2. Log balasan AI holding ke Supabase
        await log_to_supabase_messages(
            sender="BoonTrack AI",
            text=reply,
            tenant_id="boontrack-holding",
            channel="webchat",
            user_id=session_id,
            user_name=f"Holding Visitor #{session_id[:5]}"
        )

        return web.json_response({
            "status": "success",
            "session_id": session_id,
            "reply": reply,
            "is_lead_qualified": result.get("is_lead_qualified", False)
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)
