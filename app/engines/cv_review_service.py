"""
Forwarder / Backward-compatibility alias for CVReviewService.
The canonical implementation resides in app.services.cv_review_service.
"""
from app.services.cv_review_service import CVReviewService, cv_review_service

__all__ = ["CVReviewService", "cv_review_service"]