import logging
import uuid
from typing import Any, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_bot_token
from app.models.catalog import Product, ProductType
from app.models.channels import ChannelStatus, TelegramBot

logger = logging.getLogger(__name__)


class DeliveryService:
    """Abstraction layer untuk eksekusi fulfillment otomatis produk digital."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute_telegram_delivery(
        self,
        tenant_id: uuid.UUID,
        telegram_chat_id: int,
        product_id: uuid.UUID,
        order_reference: str,
    ) -> Dict[str, Any]:
        # 1. Ambil detail produk digital
        prod_query = select(Product).where(
            Product.id == product_id,
            Product.tenant_id == tenant_id
        )
        product = (await self.db.execute(prod_query)).scalar_one_or_none()
        if not product:
            raise ValueError(f"Product {product_id} not found for tenant {tenant_id}")

        # 2. Ambil kredensial Bot Telegram tenant yang aktif
        bot_query = select(TelegramBot).where(
            TelegramBot.tenant_id == tenant_id,
            TelegramBot.status == ChannelStatus.ACTIVE
        )
        bot = (await self.db.execute(bot_query)).scalar_one_or_none()
        if not bot:
            raise ValueError(f"No active Telegram Bot found for tenant {tenant_id}")

        raw_token = decrypt_bot_token(bot.encrypted_token)

        logger.info(
            f"[DELIVERY] Fulfilling order {order_reference} to Chat ID {telegram_chat_id} via @{bot.bot_username}"
        )

        # 3. Fulfillment Strategy Berdasarkan Tipe Produk
        if product.product_type == ProductType.DIGITAL_FILE:
            return {
                "status": "DELIVERED",
                "method": "TELEGRAM_DOCUMENT",
                "asset_ref": product.asset_reference,
                "order_reference": order_reference,
            }
        elif product.product_type == ProductType.URL_LINK:
            return {
                "status": "DELIVERED",
                "method": "DIRECT_URL",
                "asset_ref": product.asset_reference,
                "order_reference": order_reference,
            }

        return {
            "status": "DELIVERED",
            "method": "GENERIC_KEY",
            "asset_ref": product.asset_reference,
            "order_reference": order_reference,
        }
