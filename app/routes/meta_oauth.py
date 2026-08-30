"""Endpoint POST /api/v1/auth/facebook/exchange untuk memproses payload Pop-up SDK Meta."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import httpx
import logging
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("META_EXCHANGE")
meta_exchange_router = APIRouter(prefix="/api/v1/auth/facebook", tags=["Meta OAuth Exchange"])

META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v20.0")


class TokenExchangePayload(BaseModel):
    code: str
    tenant_slug: str


@meta_exchange_router.post("/exchange", summary="Exchange Authorization Code from Meta Popup SDK")
async def exchange_meta_code(payload: TokenExchangePayload):
    async with httpx.AsyncClient(timeout=35.0) as client:
        # 1. Exchange auth code for User Access Token
        token_url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/oauth/access_token"
        params = {
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "code": payload.code,
        }
        res = await client.get(token_url, params=params)
        if res.status_code != 200:
            logger.error(f"[Meta Exchange Error] {res.text}")
            raise HTTPException(status_code=400, detail="Gagal menukar kode otorisasi Meta.")

        user_access_token = res.json().get("access_token")

        # 2. Inspect token to discover WABA ID
        debug_url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/debug_token"
        debug_params = {
            "input_token": user_access_token,
            "access_token": f"{META_APP_ID}|{META_APP_SECRET}",
        }
        debug_res = await client.get(debug_url, params=debug_params)
        waba_id = None
        phone_number_id = None
        display_phone = None

        if debug_res.status_code == 200:
            scopes = debug_res.json().get("data", {}).get("granular_scopes", [])
            for s in scopes:
                if s.get("scope") == "whatsapp_business_management":
                    targets = s.get("target_ids", [])
                    if targets:
                        waba_id = targets[0]

        # 3. Ambil Phone Number ID yang baru didaftarkan
        if waba_id:
            phones_url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{waba_id}/phone_numbers"
            phone_res = await client.get(phones_url, headers={"Authorization": f"Bearer {user_access_token}"})
            if phone_res.status_code == 200:
                p_list = phone_res.json().get("data", [])
                if p_list:
                    phone_number_id = p_list[0].get("id")
                    display_phone = p_list[0].get("display_phone_number")

        # 4. Auto-Register Phone Number ID untuk 2-way Webhook WhatsApp
        if phone_number_id:
            reg_url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{phone_number_id}/register"
            reg_body = {"messaging_product": "whatsapp", "pin": "123456"}
            await client.post(reg_url, headers={"Authorization": f"Bearer {user_access_token}"}, json=reg_body)

        # 5. Persist ke Supabase DB
        supabase = get_supabase()
        if supabase and phone_number_id:
            supabase.table("tenants").update({
                "wa_api_token": user_access_token,
                "wa_phone_number_id": phone_number_id,
                "waba_id": waba_id,
                "wa_gateway_status": "CONNECTED",
            }).eq("slug", payload.tenant_slug).execute()

        return {
            "status": "success",
            "tenant_slug": payload.tenant_slug,
            "phone_number_id": phone_number_id,
            "phone_number": display_phone,
            "waba_id": waba_id,
        }