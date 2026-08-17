from abc import ABC, abstractmethod

class DigitalDeliveryAdapter(ABC):
    @abstractmethod
    async def generate_access_payload(self, delivery_payload: str) -> dict:
        pass

class GoogleDriveDeliveryAdapter(DigitalDeliveryAdapter):
    async def generate_access_payload(self, delivery_payload: str) -> dict:
        return {
            "delivery_type": "google_drive",
            "url": delivery_payload,
            "instructions": "Akses folder/file Google Drive dan simpan salinan ke Drive pribadi Anda."
        }

class S3DeliveryAdapter(DigitalDeliveryAdapter):
    async def generate_access_payload(self, delivery_payload: str) -> dict:
        return {
            "delivery_type": "s3_direct",
            "url": delivery_payload,
            "instructions": "Download file langsung melalui tautan aman berikut."
        }

class DigitalDeliveryService:
    _adapters = {
        "google_drive": GoogleDriveDeliveryAdapter(),
        "s3": S3DeliveryAdapter()
    }

    @classmethod
    async def fulfill(cls, adapter_name: str, payload: str) -> dict:
        adapter = cls._adapters.get(adapter_name, GoogleDriveDeliveryAdapter())
        return await adapter.generate_access_payload(payload)