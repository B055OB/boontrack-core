"""app/services/shipping/factory.py
Shipping Adapter Factory & Multi-Courier Rate Aggregator.
Resolves and instantiates appropriate ShippingAdapter based on TenantRuntimeContext metadata (shipping_config).
"""

from typing import Optional, Dict, Any, Union, List
from app.schemas.context import TenantRuntimeContext
from app.services.shipping.base import (
    ShippingAdapter,
    RateRequest,
    RateOption,
)
from app.services.shipping.biteship import BiteshipAdapter


class ShippingAdapterFactory:
    """Factory resolver & rate aggregator untuk adapter pengiriman / logistik multi-tenant."""

    @classmethod
    def resolve(
        cls,
        context_or_config: Union[TenantRuntimeContext, Dict[str, Any], None] = None,
        provider_override: Optional[str] = None,
    ) -> ShippingAdapter:
        """
        Menentukan adapter pengiriman:
        1. Menggunakan provider_override jika disediakan ('biteship').
        2. Membaca context.metadata.shipping_config jika context_or_config adalah TenantRuntimeContext.
        3. Membaca dict config langsung jika context_or_config adalah dict.
        4. Default ke BiteshipAdapter.
        """
        config: Dict[str, Any] = {}

        if isinstance(context_or_config, TenantRuntimeContext):
            meta = getattr(context_or_config, "metadata", {}) or {}
            config = meta.get("shipping_config") or {}
        elif isinstance(context_or_config, dict):
            config = context_or_config.get("shipping_config") or context_or_config

        provider = str(provider_override or config.get("provider") or config.get("aggregator") or "biteship").strip().lower()
        api_key = config.get("api_key")

        if provider in ("biteship", "default"):
            return BiteshipAdapter(api_key=api_key)

        # Default fallback ke Biteship
        return BiteshipAdapter(api_key=api_key)

    @classmethod
    async def aggregate_rates(
        cls,
        context_or_config: Union[TenantRuntimeContext, Dict[str, Any], None],
        request: RateRequest,
    ) -> List[RateOption]:
        """
        Menghitung dan mengagregasikan seluruh opsi tarif kurir berdasarkan konfigurasi tenant:
        - Memfilter kurir yang diizinkan (allowed_couriers)
        - Menambahkan markup tarif jika diatur di shipping_config
        - Mengurutkan opsi dari tarif terendah ke tertinggi
        """
        config: Dict[str, Any] = {}
        if isinstance(context_or_config, TenantRuntimeContext):
            meta = getattr(context_or_config, "metadata", {}) or {}
            config = meta.get("shipping_config") or {}
        elif isinstance(context_or_config, dict):
            config = context_or_config.get("shipping_config") or context_or_config

        adapter = cls.resolve(context_or_config)
        raw_options = await adapter.calculate_rates(request)

        # 1. Filter kurir yang diaktifkan oleh tenant
        enabled_couriers = config.get("enabled_couriers") or config.get("allowed_couriers")
        if enabled_couriers and isinstance(enabled_couriers, list):
            allowed_set = {c.lower().strip() for c in enabled_couriers}
            raw_options = [o for o in raw_options if o.courier_code.lower() in allowed_set]

        # 2. Terapkan markup tarif (flat atau percentage) jika ada
        markup_flat = int(config.get("markup_flat") or 0)
        markup_pct = float(config.get("markup_percentage") or 0.0)

        processed_options: List[RateOption] = []
        for opt in raw_options:
            final_rate = opt.rate
            if markup_pct > 0:
                final_rate += int(final_rate * (markup_pct / 100.0))
            if markup_flat > 0:
                final_rate += markup_flat

            processed_options.append(RateOption(
                courier_name=opt.courier_name,
                courier_code=opt.courier_code,
                service_name=opt.service_name,
                service_type=opt.service_type,
                rate=final_rate,
                etd=opt.etd,
                description=opt.description,
                is_cod=opt.is_cod,
            ))

        # 3. Urutkan berdasarkan harga termurah
        processed_options.sort(key=lambda x: x.rate)
        return processed_options
