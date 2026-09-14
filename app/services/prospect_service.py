"""app/services/prospect_service.py
Service layer for managing control_plane.tenant_prospects data intake and retrieval.
"""

import uuid
import logging
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from app.core.config import settings
from app.schemas.tenant_prospect_schema import (
    TenantOnboardIntakeRequest,
    TenantProspectItem,
)

logger = logging.getLogger("PROSPECT_SERVICE")


def get_db_connection():
    """Returns a direct psycopg2 database connection."""
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


class ProspectService:
    def create_prospect(self, payload: TenantOnboardIntakeRequest) -> Dict[str, Any]:
        """Inserts a new prospect into control_plane.tenant_prospects with status 'PROSPECT_PILOT_REQUESTED'."""
        prospect_id = str(uuid.uuid4())
        feature_flags = payload.build_feature_flags()
        channels_config = payload.channels.model_dump()
        hardware_config = payload.hardware.model_dump()
        status = "PROSPECT_PILOT_REQUESTED"

        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO control_plane.tenant_prospects (
                        id, brand_name, industry, pic_name, whatsapp,
                        pain_points, desired_outcome,
                        channels_config, hardware_config, feature_flags,
                        status, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, NOW()
                    )
                    RETURNING id, brand_name, industry, pic_name, whatsapp,
                              pain_points, desired_outcome,
                              channels_config, hardware_config, feature_flags,
                              status, created_at;
                    """,
                    (
                        prospect_id,
                        payload.brand_name.strip(),
                        payload.industry.strip(),
                        payload.pic_name.strip(),
                        payload.whatsapp.strip(),
                        payload.pain_points.strip(),
                        payload.desired_outcome.strip(),
                        Json(channels_config),
                        Json(hardware_config),
                        Json(feature_flags),
                        status,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                if not row:
                    raise RuntimeError("Failed to insert and return tenant prospect.")
                
                # Format response dict
                res = dict(row)
                res["id"] = str(res["id"])
                return res
        except Exception as e:
            conn.rollback()
            logger.error(f"[ProspectService] Failed to create prospect: {e}", exc_info=True)
            raise
        finally:
            conn.close()

    def list_prospects(self, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieves all tenant prospects ordered by created_at DESC."""
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, brand_name, industry, pic_name, whatsapp,
                           pain_points, desired_outcome,
                           channels_config, hardware_config, feature_flags,
                           status, created_at
                    FROM control_plane.tenant_prospects
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s;
                    """,
                    (limit, offset),
                )
                rows = cur.fetchall() or []
                results = []
                for r in rows:
                    item = dict(r)
                    item["id"] = str(item["id"])
                    results.append(item)
                return results
        except Exception as e:
            logger.error(f"[ProspectService] Failed to list prospects: {e}", exc_info=True)
            raise
        finally:
            conn.close()

    def update_status(self, prospect_id: str, new_status: str) -> Optional[Dict[str, Any]]:
        """Updates prospect status (e.g. FOLLOWED_UP, PILOT_APPROVED, ARCHIVED)."""
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE control_plane.tenant_prospects
                    SET status = %s
                    WHERE id = %s
                    RETURNING id, brand_name, industry, pic_name, whatsapp, status, created_at;
                    """,
                    (new_status.strip(), prospect_id),
                )
                row = cur.fetchone()
                conn.commit()
                if row:
                    item = dict(row)
                    item["id"] = str(item["id"])
                    return item
                return None
        except Exception as e:
            conn.rollback()
            logger.error(f"[ProspectService] Failed to update status: {e}", exc_info=True)
            raise
        finally:
            conn.close()


prospect_service = ProspectService()
