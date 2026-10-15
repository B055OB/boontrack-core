-- ==============================================================================================
-- Migration 030: Harden RLS on all remaining tenant-scoped tables
-- ==============================================================================================
-- Enforces FORCE ROW LEVEL SECURITY and dual-resolution tenant isolation policies
-- across all 23 remaining tenant tables, closing any zero-policy loopholes.
-- ==============================================================================================

-- Table: activation_codes
ALTER TABLE public."activation_codes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."activation_codes" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_activation_codes" ON public."activation_codes";
CREATE POLICY "auth_tenant_activation_codes" ON public."activation_codes"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_activation_codes" ON public."activation_codes";
CREATE POLICY "service_role_all_activation_codes" ON public."activation_codes"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: commission_ledger
ALTER TABLE public."commission_ledger" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."commission_ledger" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_commission_ledger" ON public."commission_ledger";
CREATE POLICY "auth_tenant_commission_ledger" ON public."commission_ledger"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_commission_ledger" ON public."commission_ledger";
CREATE POLICY "service_role_all_commission_ledger" ON public."commission_ledger"
AS PERMISSIVE FOR ALL TO service_role
USING (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: contact_channel_identities
ALTER TABLE public."contact_channel_identities" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."contact_channel_identities" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_contact_channel_identities" ON public."contact_channel_identities";
CREATE POLICY "auth_tenant_contact_channel_identities" ON public."contact_channel_identities"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_contact_channel_identities" ON public."contact_channel_identities";
CREATE POLICY "service_role_all_contact_channel_identities" ON public."contact_channel_identities"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: contact_notes
ALTER TABLE public."contact_notes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."contact_notes" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_contact_notes" ON public."contact_notes";
CREATE POLICY "auth_tenant_contact_notes" ON public."contact_notes"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_contact_notes" ON public."contact_notes";
CREATE POLICY "service_role_all_contact_notes" ON public."contact_notes"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: contacts
ALTER TABLE public."contacts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."contacts" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_contacts" ON public."contacts";
CREATE POLICY "auth_tenant_contacts" ON public."contacts"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ) OR (
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ) OR (
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_contacts" ON public."contacts";
CREATE POLICY "service_role_all_contacts" ON public."contacts"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ) OR (
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ) OR (
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: document_jobs
ALTER TABLE public."document_jobs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."document_jobs" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_document_jobs" ON public."document_jobs";
CREATE POLICY "auth_tenant_document_jobs" ON public."document_jobs"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ))
WITH CHECK ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ));
DROP POLICY IF EXISTS "service_role_all_document_jobs" ON public."document_jobs";
CREATE POLICY "service_role_all_document_jobs" ON public."document_jobs"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: inbox_idempotency_keys
ALTER TABLE public."inbox_idempotency_keys" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."inbox_idempotency_keys" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_inbox_idempotency_keys" ON public."inbox_idempotency_keys";
CREATE POLICY "auth_tenant_inbox_idempotency_keys" ON public."inbox_idempotency_keys"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ))
WITH CHECK ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ));
DROP POLICY IF EXISTS "service_role_all_inbox_idempotency_keys" ON public."inbox_idempotency_keys";
CREATE POLICY "service_role_all_inbox_idempotency_keys" ON public."inbox_idempotency_keys"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: lifecycle_events
ALTER TABLE public."lifecycle_events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."lifecycle_events" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_lifecycle_events" ON public."lifecycle_events";
CREATE POLICY "auth_tenant_lifecycle_events" ON public."lifecycle_events"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_lifecycle_events" ON public."lifecycle_events";
CREATE POLICY "service_role_all_lifecycle_events" ON public."lifecycle_events"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: lifecycle_templates
ALTER TABLE public."lifecycle_templates" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."lifecycle_templates" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_lifecycle_templates" ON public."lifecycle_templates";
CREATE POLICY "auth_tenant_lifecycle_templates" ON public."lifecycle_templates"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_lifecycle_templates" ON public."lifecycle_templates";
CREATE POLICY "service_role_all_lifecycle_templates" ON public."lifecycle_templates"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: merchant_devices
ALTER TABLE public."merchant_devices" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."merchant_devices" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_merchant_devices" ON public."merchant_devices";
CREATE POLICY "auth_tenant_merchant_devices" ON public."merchant_devices"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_merchant_devices" ON public."merchant_devices";
CREATE POLICY "service_role_all_merchant_devices" ON public."merchant_devices"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: shop_commission_ledger
ALTER TABLE public."shop_commission_ledger" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."shop_commission_ledger" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_shop_commission_ledger" ON public."shop_commission_ledger";
CREATE POLICY "auth_tenant_shop_commission_ledger" ON public."shop_commission_ledger"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_shop_commission_ledger" ON public."shop_commission_ledger";
CREATE POLICY "service_role_all_shop_commission_ledger" ON public."shop_commission_ledger"
AS PERMISSIVE FOR ALL TO service_role
USING (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: shop_reseller_settings
ALTER TABLE public."shop_reseller_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."shop_reseller_settings" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_shop_reseller_settings" ON public."shop_reseller_settings";
CREATE POLICY "auth_tenant_shop_reseller_settings" ON public."shop_reseller_settings"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_shop_reseller_settings" ON public."shop_reseller_settings";
CREATE POLICY "service_role_all_shop_reseller_settings" ON public."shop_reseller_settings"
AS PERMISSIVE FOR ALL TO service_role
USING (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: shop_wa_instances
ALTER TABLE public."shop_wa_instances" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."shop_wa_instances" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_shop_wa_instances" ON public."shop_wa_instances";
CREATE POLICY "auth_tenant_shop_wa_instances" ON public."shop_wa_instances"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_shop_wa_instances" ON public."shop_wa_instances";
CREATE POLICY "service_role_all_shop_wa_instances" ON public."shop_wa_instances"
AS PERMISSIVE FOR ALL TO service_role
USING (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: studio_job_credit_reservations
ALTER TABLE public."studio_job_credit_reservations" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."studio_job_credit_reservations" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_studio_job_credit_reservations" ON public."studio_job_credit_reservations";
CREATE POLICY "auth_tenant_studio_job_credit_reservations" ON public."studio_job_credit_reservations"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_studio_job_credit_reservations" ON public."studio_job_credit_reservations";
CREATE POLICY "service_role_all_studio_job_credit_reservations" ON public."studio_job_credit_reservations"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: subscriptions
ALTER TABLE public."subscriptions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."subscriptions" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_subscriptions" ON public."subscriptions";
CREATE POLICY "auth_tenant_subscriptions" ON public."subscriptions"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_subscriptions" ON public."subscriptions";
CREATE POLICY "service_role_all_subscriptions" ON public."subscriptions"
AS PERMISSIVE FOR ALL TO service_role
USING (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: tags
ALTER TABLE public."tags" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."tags" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_tags" ON public."tags";
CREATE POLICY "auth_tenant_tags" ON public."tags"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_tags" ON public."tags";
CREATE POLICY "service_role_all_tags" ON public."tags"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: telegram_bots
ALTER TABLE public."telegram_bots" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."telegram_bots" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_telegram_bots" ON public."telegram_bots";
CREATE POLICY "auth_tenant_telegram_bots" ON public."telegram_bots"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_telegram_bots" ON public."telegram_bots";
CREATE POLICY "service_role_all_telegram_bots" ON public."telegram_bots"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: tenant_members
ALTER TABLE public."tenant_members" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."tenant_members" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_tenant_members" ON public."tenant_members";
CREATE POLICY "auth_tenant_tenant_members" ON public."tenant_members"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_tenant_members" ON public."tenant_members";
CREATE POLICY "service_role_all_tenant_members" ON public."tenant_members"
AS PERMISSIVE FOR ALL TO service_role
USING (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: tenant_waba_configs
ALTER TABLE public."tenant_waba_configs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."tenant_waba_configs" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_tenant_waba_configs" ON public."tenant_waba_configs";
CREATE POLICY "auth_tenant_tenant_waba_configs" ON public."tenant_waba_configs"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ))
WITH CHECK ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ));
DROP POLICY IF EXISTS "service_role_all_tenant_waba_configs" ON public."tenant_waba_configs";
CREATE POLICY "service_role_all_tenant_waba_configs" ON public."tenant_waba_configs"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: tenant_whatsapp_channels
ALTER TABLE public."tenant_whatsapp_channels" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."tenant_whatsapp_channels" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_tenant_whatsapp_channels" ON public."tenant_whatsapp_channels";
CREATE POLICY "auth_tenant_tenant_whatsapp_channels" ON public."tenant_whatsapp_channels"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ))
WITH CHECK ((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            ));
DROP POLICY IF EXISTS "service_role_all_tenant_whatsapp_channels" ON public."tenant_whatsapp_channels";
CREATE POLICY "service_role_all_tenant_whatsapp_channels" ON public."tenant_whatsapp_channels"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE (SELECT id FROM public.tenants WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    END
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: tenants_config
ALTER TABLE public."tenants_config" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."tenants_config" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_tenants_config" ON public."tenants_config";
CREATE POLICY "auth_tenant_tenants_config" ON public."tenants_config"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ))
WITH CHECK ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ));
DROP POLICY IF EXISTS "service_role_all_tenants_config" ON public."tenants_config";
CREATE POLICY "service_role_all_tenants_config" ON public."tenants_config"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: tool_audit_logs
ALTER TABLE public."tool_audit_logs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."tool_audit_logs" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_tool_audit_logs" ON public."tool_audit_logs";
CREATE POLICY "auth_tenant_tool_audit_logs" ON public."tool_audit_logs"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ))
WITH CHECK ((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            ));
DROP POLICY IF EXISTS "service_role_all_tool_audit_logs" ON public."tool_audit_logs";
CREATE POLICY "service_role_all_tool_audit_logs" ON public."tool_audit_logs"
AS PERMISSIVE FOR ALL TO service_role
USING (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_id = (
                    SELECT slug FROM public.tenants 
                    WHERE id = (
                        CASE 
                            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                            THEN current_setting('app.current_tenant_id', true)::uuid
                            ELSE NULL
                        END
                    )
                )
                OR tenant_id = (
                    SELECT id::text FROM public.tenants 
                    WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);

-- Table: tracking_sessions
ALTER TABLE public."tracking_sessions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."tracking_sessions" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_tenant_tracking_sessions" ON public."tracking_sessions";
CREATE POLICY "auth_tenant_tracking_sessions" ON public."tracking_sessions"
AS PERMISSIVE FOR ALL TO authenticated
USING ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ))
WITH CHECK ((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        ));
DROP POLICY IF EXISTS "service_role_all_tracking_sessions" ON public."tracking_sessions";
CREATE POLICY "service_role_all_tracking_sessions" ON public."tracking_sessions"
AS PERMISSIVE FOR ALL TO service_role
USING (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL)
WITH CHECK (((
            tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = (
                SELECT slug FROM public.tenants 
                WHERE id = (
                    CASE 
                        WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        THEN current_setting('app.current_tenant_id', true)::uuid
                        ELSE NULL
                    END
                )
            )
        )) OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL);
