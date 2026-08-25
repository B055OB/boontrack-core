"""
Re-export OmBudiService & om_budi_service dari app.tenants.om_budi.service
untuk kompatibilitas modul.
"""
from app.tenants.om_budi.service import OmBudiService, om_budi_service

__all__ = ["OmBudiService", "om_budi_service"]
