"""app/schemas/payment.py
Pydantic Schemas for Dynamic QRIS & Payment Reconciliation Engine.

Provides:
- PaymentStatus: Enum ('PENDING', 'PAID', 'EXPIRED', 'FAILED')
- ReservedItem: Schema for inventory reservation items.
- PaymentOrderCreate: Request payload to create/track an order.
- PaymentOrderResponse: Standard order/payment response.
- PaymentWebhookPayload: Universal webhook payload adapter for Xendit, Midtrans, and Duitku.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class PaymentStatus(str, Enum):
    """Status lifecycle transaksi pembayaran."""
    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class ReservedItem(BaseModel):
    """Item produk yang di-hold inventarisnya selama transaksi PENDING."""
    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(..., description="ID atau SKU unik produk")
    name: Optional[str] = Field(default="Produk", description="Nama produk")
    quantity: int = Field(default=1, ge=1, description="Jumlah kuantitas yang di-hold")
    price: Optional[Decimal] = Field(default=None, description="Harga satuan produk")


class PaymentOrderCreate(BaseModel):
    """Payload pembentukan order / payment intent baru."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., description="Identifier tenant pemilik transaksi")
    order_id: str = Field(..., description="ID unik pesanan / invoice")
    amount: Decimal = Field(..., gt=0, description="Nominal total transaksi dalam Rupiah")
    expired_at: Optional[datetime] = Field(
        default=None,
        description="Waktu kedaluwarsa pembayaran (TIMESTAMPTZ)",
    )
    items_reserved: List[Union[ReservedItem, Dict[str, Any]]] = Field(
        default_factory=list,
        description="Daftar item untuk inventory tracking / hold kuota",
    )
    customer_phone: Optional[str] = Field(default=None, description="Nomor WhatsApp customer")
    customer_name: Optional[str] = Field(default=None, description="Nama pemesan")


class PaymentOrderResponse(BaseModel):
    """Response entitas order pembayaran."""
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str = Field(..., description="UUID unik payment order")
    tenant_id: str = Field(..., description="Tenant ID")
    order_id: str = Field(..., description="Order ID")
    amount: Decimal = Field(..., description="Nominal tagihan")
    payment_status: PaymentStatus = Field(
        default=PaymentStatus.PENDING,
        description="Status pembayaran (PENDING, PAID, EXPIRED, FAILED)",
    )
    expired_at: datetime = Field(..., description="Waktu kedaluwarsa transaksi")
    items_reserved: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Daftar item inventaris yang di-hold",
    )
    customer_phone: Optional[str] = Field(default=None, description="Nomor WhatsApp customer")
    paid_at: Optional[datetime] = Field(default=None, description="Timestamp waktu pembayaran diterima")
    created_at: datetime = Field(..., description="Timestamp pembuatan order")


class PaymentWebhookPayload(BaseModel):
    """Adapter serbaguna untuk callback webhook dari berbagai Payment Gateway."""
    model_config = ConfigDict(extra="ignore")

    # Identifiers
    order_id: Optional[str] = Field(None, description="ID pesanan dari merchant / Midtrans / Duitku")
    external_id: Optional[str] = Field(None, description="ID invoice unik dari Xendit")
    merchant_order_id: Optional[str] = Field(None, description="Duitku merchant order id")

    # Status fields
    status: Optional[str] = Field(None, description="Status dari Xendit / generic (PAID, SETTLED, EXPIRED)")
    transaction_status: Optional[str] = Field(None, description="Status dari Midtrans (settlement, capture, expire)")
    result_code: Optional[str] = Field(None, description="Status kode dari Duitku ('00' = sukses)")

    # Amounts
    amount: Optional[Decimal] = Field(None, description="Nominal transaksi")
    gross_amount: Optional[str] = Field(None, description="Midtrans gross amount string")

    # Verification / Signatures
    signature_key: Optional[str] = Field(None, description="Midtrans signature hash")
    callback_token: Optional[str] = Field(None, description="Xendit verification callback token")
    signature: Optional[str] = Field(None, description="Duitku signature hash")

    # Metadata
    customer_phone: Optional[str] = Field(None, description="Nomor WhatsApp pembeli")
    customer_name: Optional[str] = Field(None, description="Nama pembeli")
    payment_method: Optional[str] = Field(None, description="Metode pembayaran (QRIS, VA, E-WALLET)")

    def resolve_order_id(self) -> str:
        """Mengambil order_id yang dinormalisasi dari payload provider manapun."""
        return str(
            self.order_id
            or self.external_id
            or self.merchant_order_id
            or ""
        ).strip()

    def is_settlement_paid(self) -> bool:
        """Mengecek apakah status webhook menunjukkan transaksi berhasil/lunas."""
        raw_status = (self.status or "").upper().strip()
        midtrans_status = (self.transaction_status or "").lower().strip()
        duitku_code = str(self.result_code or "").strip()

        if raw_status in ("PAID", "SETTLED", "SUCCESS", "COMPLETED"):
            return True
        if midtrans_status in ("settlement", "capture"):
            return True
        if duitku_code == "00":
            return True
        return False
