CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SEQUENCE IF NOT EXISTS public.product_orders_id_seq;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'affiliate_status_enum') THEN CREATE TYPE public.affiliate_status_enum AS ENUM ('ACTIVE', 'SUSPENDED'); END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'commission_status_enum') THEN CREATE TYPE public.commission_status_enum AS ENUM ('PENDING', 'APPROVED', 'PAID'); END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscription_status') THEN CREATE TYPE public.subscription_status AS ENUM ('TRIAL', 'ACTIVE', 'GRACE_PERIOD', 'EXPIRED', 'PAID', 'GRANTED', 'PENDING_PAYMENT'); END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscription_tier') THEN CREATE TYPE public.subscription_tier AS ENUM ('STARTER', 'PRO_SCALE', 'ENTERPRISE', 'CHECKOUT_LITE', 'ADS_PERFORMANCE', 'SOLO', 'TEAM_SCALE'); END IF; END $$;

CREATE TABLE public.tenants (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "slug" text NOT NULL
);

CREATE TABLE public.affiliates (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "tenant_id" character varying NOT NULL,
    "name" character varying NOT NULL,
    "phone_number" character varying NOT NULL,
    "referral_code" character varying NOT NULL,
    "commission_rate" numeric DEFAULT 10.00 NOT NULL,
    "payout_bank_details" jsonb DEFAULT '{}'::jsonb,
    "status" public.affiliate_status_enum DEFAULT 'ACTIVE'::affiliate_status_enum NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    "manager_id" uuid,
    "phone" character varying,
    "bank_name" character varying,
    "bank_account_number" character varying,
    "bank_account_holder" character varying,
    "is_bank_verified" boolean DEFAULT false,
    "experience_level" character varying DEFAULT 'BEGINNER'::character varying,
    "promotion_strategy_notes" text,
    "social_media_links" jsonb DEFAULT '{}'::jsonb,
    "portfolio_url" text,
    "screening_status" character varying DEFAULT 'PENDING'::character varying,
    "rejection_reason" text,
    "agreed_to_rules" boolean DEFAULT false,
    "reviewed_by" uuid,
    "reviewed_at" timestamp with time zone,
    "email" character varying,
    "role" character varying DEFAULT 'affiliate'::character varying NOT NULL,
    "parent_am_id" uuid,
    "region" character varying DEFAULT 'ID-NATIONAL'::character varying,
    "metadata" jsonb DEFAULT '{}'::jsonb,
    "balance" numeric DEFAULT 0,
    "total_withdrawn" numeric DEFAULT 0
);

CREATE TABLE public.orders (
    "id" text NOT NULL,
    "tenant_id" character varying(100),
    "status" text NOT NULL,
    "tenant_slug" text,
    "product_id" text,
    "product_title" text,
    "gross_amount" numeric,
    "customer_name" text,
    "customer_phone" text,
    "customer_email" text,
    "affiliate_code" text,
    "manager_id" uuid,
    "utm_source" text,
    "utm_medium" text,
    "utm_campaign" text,
    "utm_content" text,
    "utm_term" text,
    "fbclid" text,
    "ttclid" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "correlation_id" text,
    "paid_at" timestamp with time zone,
    "order_status" character varying(32) DEFAULT 'PENDING'::character varying,
    "mutation_id" character varying(128),
    "trace_id" character varying(64),
    "payment_status" character varying(32) DEFAULT 'PENDING'::character varying,
    "qr_code_url" text,
    "email_sent" boolean DEFAULT false,
    "email_sent_at" timestamp with time zone,
    "briefing_url" text,
    "customer_briefing" jsonb,
    "payment_proof_url" text,
    "metadata" jsonb DEFAULT '{}'::jsonb,
    "download_url" text,
    "fulfillment_metadata" jsonb DEFAULT '{}'::jsonb,
    "order_number" text,
    "reseller_attribution_id" uuid,
    "reseller_id" uuid,
    "reseller_code" text,
    "quantity" integer DEFAULT 1,
    "contact_id" uuid,
    "notified_at" timestamp with time zone,
    "is_archived" boolean DEFAULT false,
    "reseller_user_id" uuid,
    "reseller_code_snapshot" character varying(50),
    "reseller_commission_amount" numeric(12,2) DEFAULT 0,
    "attribution_type" character varying(20),
    "affiliate_id" uuid
);

CREATE TABLE public.product_orders (
    "id" integer DEFAULT nextval('product_orders_id_seq'::regclass) NOT NULL,
    "order_id" character varying,
    "telegram_id" bigint,
    "product_name" character varying,
    "base_price" integer,
    "unique_code" integer,
    "total_amount" integer,
    "status" character varying DEFAULT 'PENDING'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "expires_at" timestamp without time zone,
    "attribution_id" uuid,
    "payment_method" character varying DEFAULT 'DIRECT'::character varying,
    "fulfillment_status" character varying DEFAULT 'UNFULFILLED'::character varying,
    "cod_settlement_status" character varying DEFAULT 'NONE'::character varying,
    "courier_tracking_id" character varying,
    "courier_code" character varying,
    "shipping_cost" numeric DEFAULT 0,
    "courier_service_name" character varying,
    "shipping_address" text,
    "destination_postal_code" character varying,
    "weight_gram" integer DEFAULT 1000,
    "tenant_id" character varying(100),
    "affiliate_id" uuid
);

CREATE TABLE public.delivery_orders (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "tenant_id" character varying NOT NULL,
    "order_id" character varying NOT NULL,
    "provider" character varying NOT NULL,
    "booking_id" character varying,
    "tracking_number" character varying,
    "service_type" character varying NOT NULL,
    "is_cod" boolean DEFAULT false,
    "cod_amount" numeric DEFAULT 0,
    "shipping_cost" numeric DEFAULT 0,
    "status" character varying DEFAULT 'DRAFT'::character varying,
    "origin_payload" jsonb DEFAULT '{}'::jsonb,
    "destination_payload" jsonb DEFAULT '{}'::jsonb,
    "settlement_proof_url" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "affiliate_id" uuid
);

CREATE TABLE public.attributions (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "tenant_id" character varying NOT NULL,
    "session_id" character varying NOT NULL,
    "affiliate_id" uuid,
    "utm_source" character varying,
    "utm_medium" character varying,
    "utm_campaign" character varying,
    "utm_content" character varying,
    "utm_term" character varying,
    "fbclid" text,
    "ttclid" text,
    "ip_hash" character varying NOT NULL,
    "user_agent" text,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE public.attribution_sessions (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "tenant_id" character varying NOT NULL,
    "affiliate_id" uuid,
    "order_id" character varying,
    "referral_code" character varying,
    "fbclid" character varying,
    "user_agent" text,
    "ip_hash" character varying NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.shop_subscriptions (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "tenant_slug" character varying,
    "plan_tier" character varying,
    "amount" numeric,
    "status" public.subscription_status DEFAULT 'TRIAL'::subscription_status,
    "xendit_invoice_id" character varying,
    "xendit_external_id" character varying,
    "current_period_start" timestamp with time zone,
    "current_period_end" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT (now() AT TIME ZONE 'Asia/Jakarta'::text),
    "updated_at" timestamp with time zone DEFAULT (now() AT TIME ZONE 'Asia/Jakarta'::text),
    "tenant_id" character varying(100) NOT NULL,
    "tier" public.subscription_tier DEFAULT 'STARTER'::subscription_tier NOT NULL,
    "duration_months" integer DEFAULT 1 NOT NULL,
    "starts_at" timestamp with time zone DEFAULT (now() AT TIME ZONE 'Asia/Jakarta'::text) NOT NULL,
    "current_period_starts_at" timestamp with time zone DEFAULT (now() AT TIME ZONE 'Asia/Jakarta'::text) NOT NULL,
    "current_period_ends_at" timestamp with time zone NOT NULL,
    "expires_at" timestamp with time zone NOT NULL,
    "invoice_id" text,
    "amount_paid" numeric DEFAULT 0,
    "metadata" jsonb DEFAULT '{}'::jsonb,
    "grant_type" text,
    "affiliate_id" uuid
);

CREATE TABLE public.shop_commission_ledger (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "subscription_id" uuid,
    "tenant_slug" character varying NOT NULL,
    "gross_amount" numeric NOT NULL,
    "affiliate_id" uuid,
    "affiliate_amount" numeric NOT NULL,
    "am_id" uuid,
    "am_amount" numeric NOT NULL,
    "platform_net_amount" numeric NOT NULL,
    "disbursement_status" character varying DEFAULT 'PENDING'::character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "tenant_id" character varying(100),
    "status" character varying(64) DEFAULT 'COMPLETED'::character varying
);

CREATE TABLE public.affiliate_commissions (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "tenant_id" character varying NOT NULL,
    "affiliate_id" uuid NOT NULL,
    "order_id" character varying NOT NULL,
    "order_amount" numeric DEFAULT 0 NOT NULL,
    "amount" numeric DEFAULT 0 NOT NULL,
    "status" public.commission_status_enum DEFAULT 'PENDING'::commission_status_enum NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "paid_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT now(),
    "product_type" character varying DEFAULT 'SHOP'::character varying
);

-- Constraints
ALTER TABLE public.affiliate_commissions ADD CONSTRAINT "affiliate_commissions_pkey" PRIMARY KEY (id);
ALTER TABLE public.affiliates ADD CONSTRAINT "affiliates_pkey" PRIMARY KEY (id);
ALTER TABLE public.attribution_sessions ADD CONSTRAINT "attribution_sessions_pkey" PRIMARY KEY (id);
ALTER TABLE public.attributions ADD CONSTRAINT "attributions_pkey" PRIMARY KEY (id);
ALTER TABLE public.delivery_orders ADD CONSTRAINT "delivery_orders_pkey" PRIMARY KEY (id);
ALTER TABLE public.orders ADD CONSTRAINT "orders_pkey" PRIMARY KEY (id);
ALTER TABLE public.product_orders ADD CONSTRAINT "product_orders_pkey" PRIMARY KEY (id);
ALTER TABLE public.shop_commission_ledger ADD CONSTRAINT "shop_commission_ledger_pkey" PRIMARY KEY (id);
ALTER TABLE public.shop_subscriptions ADD CONSTRAINT "shop_subscriptions_pkey" PRIMARY KEY (id);
ALTER TABLE public.tenants ADD CONSTRAINT "tenants_pkey" PRIMARY KEY (id);
ALTER TABLE public.affiliate_commissions ADD CONSTRAINT "uq_tenant_order_commission" UNIQUE (tenant_id, order_id);
ALTER TABLE public.affiliates ADD CONSTRAINT "uq_affiliates_tenant_id_id" UNIQUE (tenant_id, id);
ALTER TABLE public.affiliates ADD CONSTRAINT "uq_tenant_referral_code" UNIQUE (tenant_id, referral_code);
ALTER TABLE public.tenants ADD CONSTRAINT "tenants_slug_key" UNIQUE (slug);
ALTER TABLE public.affiliate_commissions ADD CONSTRAINT "affiliate_commissions_affiliate_id_fkey" FOREIGN KEY (affiliate_id) REFERENCES affiliates(id) ON DELETE CASCADE;
ALTER TABLE public.attribution_sessions ADD CONSTRAINT "fk_attribution_sessions_affiliate_composite" FOREIGN KEY (tenant_id, affiliate_id) REFERENCES affiliates(tenant_id, id);
ALTER TABLE public.attributions ADD CONSTRAINT "fk_attributions_affiliate_composite" FOREIGN KEY (tenant_id, affiliate_id) REFERENCES affiliates(tenant_id, id);
ALTER TABLE public.delivery_orders ADD CONSTRAINT "fk_delivery_orders_affiliate_composite" FOREIGN KEY (tenant_id, affiliate_id) REFERENCES affiliates(tenant_id, id);
ALTER TABLE public.orders ADD CONSTRAINT "fk_orders_affiliate_composite" FOREIGN KEY (tenant_id, affiliate_id) REFERENCES affiliates(tenant_id, id);
ALTER TABLE public.orders ADD CONSTRAINT "fk_orders_manager_composite" FOREIGN KEY (tenant_id, manager_id) REFERENCES affiliates(tenant_id, id);
ALTER TABLE public.product_orders ADD CONSTRAINT "fk_product_orders_affiliate_composite" FOREIGN KEY (tenant_id, affiliate_id) REFERENCES affiliates(tenant_id, id);
ALTER TABLE public.shop_commission_ledger ADD CONSTRAINT "fk_shop_commission_ledger_affiliate_composite" FOREIGN KEY (tenant_id, affiliate_id) REFERENCES affiliates(tenant_id, id);
ALTER TABLE public.shop_subscriptions ADD CONSTRAINT "fk_shop_subscriptions_affiliate_composite" FOREIGN KEY (tenant_id, affiliate_id) REFERENCES affiliates(tenant_id, id);