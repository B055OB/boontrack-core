from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.digital_asset import DigitalAsset, Delivery, KnowledgeMapping, ARSStatus

class DigitalAssetRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_asset(self, asset: DigitalAsset) -> DigitalAsset:
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def get_by_slug(self, slug: str) -> Optional[DigitalAsset]:
        return self.db.query(DigitalAsset).filter(DigitalAsset.slug == slug).first()

    def get_by_intent(self, intent_code: str, status: ARSStatus = ARSStatus.PUBLISHED) -> List[DigitalAsset]:
        return self.db.query(DigitalAsset).filter(
            DigitalAsset.intent_code == intent_code,
            DigitalAsset.status == status
        ).all()

    def add_delivery(self, delivery: Delivery) -> Delivery:
        self.db.add(delivery)
        self.db.commit()
        self.db.refresh(delivery)
        return delivery

    def add_knowledge_mapping(self, mapping: KnowledgeMapping) -> KnowledgeMapping:
        self.db.add(mapping)
        self.db.commit()
        self.db.refresh(mapping)
        return mapping
