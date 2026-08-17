import enum
from decimal import Decimal
from sqlalchemy import Boolean, Enum, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TenantScopedBaseMixin


class LicenseStatus(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"
    OFFICIAL = "OFFICIAL"
    RESELLER = "RESELLER"
    FLAGGED = "FLAGGED"


class ProductType(str, enum.Enum):
    DIGITAL_FILE = "DIGITAL_FILE"
    ACCESS_KEY = "ACCESS_KEY"
    URL_LINK = "URL_LINK"
    SUBSCRIPTION = "SUBSCRIPTION"


class Product(Base, TenantScopedBaseMixin):
    __tablename__ = "products"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    product_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType, name="product_type_enum"), default=ProductType.DIGITAL_FILE, nullable=False
    )
    license_status: Mapped[LicenseStatus] = mapped_column(
        Enum(LicenseStatus, name="license_status_enum"), default=LicenseStatus.UNVERIFIED, nullable=False
    )
    asset_reference: Mapped[str] = mapped_column(Text, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)