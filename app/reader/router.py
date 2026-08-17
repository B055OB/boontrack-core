import hashlib
import uuid
from datetime import datetime, timedelta
from aiohttp import web
from sqlalchemy import select, update
from app.database.models import Tenant, ActivationCode, MerchantDevice
# Model imports menyesuaikan struktur model DB Anda

async def pair_device_handler(request: web.Request, session) -> web.Response:
    try:
        data = await request.json()
        activation_code = data.get("activation_code", "").strip()
        device_uuid = data.get("device_uuid", "").strip()
        device_name = data.get("device_name", "Android Reader")
        platform = data.get("platform", "ANDROID")
        app_version = data.get("app_version", "1.0.0")

        if not activation_code or not device_uuid:
            return web.json_response({"error": "Missing activation_code or device_uuid"}, status=400)

        # Hash SHA-256 kode aktivasi
        code_hash = hashlib.sha256(activation_code.encode()).hexdigest()

        # Cek kode aktivasi di database
        stmt = select(ActivationCode).where(
            ActivationCode.code_hash == code_hash,
            ActivationCode.status == "PENDING"
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return web.json_response({"error": "Invalid or expired activation code"}, status=401)

        # Update status kode aktivasi menjadi USED
        record.status = "USED"
        record.used_at = datetime.utcnow()

        # Daftarkan/update device
        device_id = str(uuid.uuid4())
        access_token = f"bt_at_{uuid.uuid4().hex}"
        refresh_token = f"bt_rt_{uuid.uuid4().hex}"

        new_device = MerchantDevice(
            id=device_id,
            tenant_id=record.tenant_id,
            device_uuid=device_uuid,
            device_name=device_name,
            platform=platform,
            app_version=app_version,
            is_active=True
        )
        session.add(new_device)
        await session.commit()

        return web.json_response({
            "status": "success",
            "device_id": device_id,
            "tenant_id": str(record.tenant_id),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer"
        })

    except Exception as e:
        await session.rollback()
        return web.json_response({"error": str(e)}, status=500)

async def refresh_token_handler(request: web.Request, session) -> web.Response:
    return web.json_response({"status": "success", "message": "Token refreshed"})

async def revoke_device_handler(request: web.Request, session) -> web.Response:
    return web.json_response({"status": "success", "message": "Device revoked"})