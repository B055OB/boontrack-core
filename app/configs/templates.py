"""app/configs/templates.py
Commerce Template Abstraction & Vertical Configurations.

Supports generic multi-vertical commerce operations:
- DIGITAL_PRODUCTS: Digital goods, software licenses, downloads, e-books.
- FASHION: Apparel, clothing, accessories with physical shipping & size charts.
- BEAUTY: Cosmetics, skincare, personal care with physical delivery.
- FNB: Food & beverage, cloud kitchen, catering with on-demand delivery.
- SERVICES: Professional services, consultations, memberships, appointments.

All verticals are dynamically handled via JSON parameter configs without engine logic duplication.
"""

from enum import Enum
from typing import Dict, Any, Optional, List
import copy


class CommerceVertical(str, Enum):
    DIGITAL_PRODUCTS = "DIGITAL_PRODUCTS"
    FASHION = "FASHION"
    BEAUTY = "BEAUTY"
    FNB = "FNB"
    SERVICES = "SERVICES"


COMMERCE_TEMPLATE: Dict[str, Any] = {
    "template_id": "COMMERCE_TEMPLATE",
    "version": "1.0.0",
    "description": "Generic multi-vertical commerce template for retail, digital products, F&B, and services",
    "supported_verticals": [
        CommerceVertical.DIGITAL_PRODUCTS.value,
        CommerceVertical.FASHION.value,
        CommerceVertical.BEAUTY.value,
        CommerceVertical.FNB.value,
        CommerceVertical.SERVICES.value,
    ],
    "default_vertical": CommerceVertical.DIGITAL_PRODUCTS.value,
    "vertical_configs": {
        CommerceVertical.DIGITAL_PRODUCTS.value: {
            "name": "Digital Products & Downloads",
            "delivery_adapter": "google_drive",
            "requires_shipping": False,
            "fulfillment_type": "INSTANT_DOWNLOAD",
            "menu_keywords": {
                "katalog": "CATALOG",
                "beli": "ORDER",
                "unduh": "DOWNLOAD",
                "bantuan": "HELP",
            },
            "default_pricing_mode": "flat",
            "system_prompt_addon": "Kamu melayani penjualan produk digital (e-book, template, software license) dengan pengiriman link instan.",
        },
        CommerceVertical.FASHION.value: {
            "name": "Fashion & Apparel",
            "delivery_adapter": "courier",
            "requires_shipping": True,
            "fulfillment_type": "PHYSICAL_DELIVERY",
            "menu_keywords": {
                "katalog": "CATALOG",
                "ukuran": "SIZE_CHART",
                "beli": "ORDER",
                "ongkir": "SHIPPING_CHECK",
            },
            "default_pricing_mode": "variable",
            "system_prompt_addon": "Kamu melayani penjualan busana dan aksesoris fashion, membantu rekomendasi ukuran, serta penghitungan estimasi pengiriman kurir.",
        },
        CommerceVertical.BEAUTY.value: {
            "name": "Beauty & Personal Care",
            "delivery_adapter": "courier",
            "requires_shipping": True,
            "fulfillment_type": "PHYSICAL_DELIVERY",
            "menu_keywords": {
                "katalog": "CATALOG",
                "konsultasi": "CONSULTATION",
                "beli": "ORDER",
                "tips": "BEAUTY_TIPS",
            },
            "default_pricing_mode": "variable",
            "system_prompt_addon": "Kamu adalah beauty advisor terpercaya yang membantu pelanggan memilih skincare dan kosmetik yang tepat.",
        },
        CommerceVertical.FNB.value: {
            "name": "Food & Beverage",
            "delivery_adapter": "instant_delivery",
            "requires_shipping": True,
            "fulfillment_type": "ON_DEMAND",
            "menu_keywords": {
                "menu": "CATALOG",
                "pesan": "ORDER",
                "promo": "PROMO",
                "status": "ORDER_STATUS",
            },
            "default_pricing_mode": "flat",
            "system_prompt_addon": "Kamu melayani pemesanan makanan dan minuman, memberikan rekomendasi menu favorit, serta mencatat catatan khusus pesanan.",
        },
        CommerceVertical.SERVICES.value: {
            "name": "Professional & Booking Services",
            "delivery_adapter": "calendar_booking",
            "requires_shipping": False,
            "fulfillment_type": "APPOINTMENT",
            "menu_keywords": {
                "jadwal": "SCHEDULE",
                "booking": "ORDER",
                "layanan": "CATALOG",
                "admin": "ESCALATE",
            },
            "default_pricing_mode": "custom",
            "system_prompt_addon": "Kamu melayani penjadwalan konsultasi dan reservasi layanan profesional, memastikan ketersediaan waktu dan konfirmasi pembayaran.",
        },
    },
    "features": {
        "dynamic_qris": True,
        "xendit_settlement": True,
        "whatsapp_notifications": True,
        "meta_capi_tracking": True,
        "multi_turnstile": False,
    },
}

# Alias for backward compatibility & migration transition
RETAIL_D2C_TEMPLATE: Dict[str, Any] = COMMERCE_TEMPLATE


def get_commerce_template(
    vertical: str = CommerceVertical.DIGITAL_PRODUCTS.value,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generates a dynamic commerce configuration tailored to the selected vertical.
    
    Operates without duplication of engine logic by injecting vertical-specific parameters
    into the generic COMMERCE_TEMPLATE blueprint.
    """
    normalized_vert = vertical.upper().strip() if vertical else CommerceVertical.DIGITAL_PRODUCTS.value
    if normalized_vert not in COMMERCE_TEMPLATE["vertical_configs"]:
        normalized_vert = CommerceVertical.DIGITAL_PRODUCTS.value

    config = copy.deepcopy(COMMERCE_TEMPLATE)
    active_vert_config = config["vertical_configs"][normalized_vert]

    result = {
        "template_id": "COMMERCE_TEMPLATE",
        "vertical": normalized_vert,
        "name": active_vert_config["name"],
        "delivery_adapter": active_vert_config["delivery_adapter"],
        "requires_shipping": active_vert_config["requires_shipping"],
        "fulfillment_type": active_vert_config["fulfillment_type"],
        "menu_keywords": active_vert_config["menu_keywords"],
        "default_pricing_mode": active_vert_config["default_pricing_mode"],
        "system_prompt_addon": active_vert_config["system_prompt_addon"],
        "features": copy.deepcopy(config["features"]),
    }

    if overrides:
        result.update(overrides)

    return result
