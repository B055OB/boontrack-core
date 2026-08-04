--
-- PostgreSQL database dump
--

\restrict BOLh6NcvZ1Wpx8uqHLk6oz3lS8AgpKlxYkA1DlsP8CofbZFjb2aDykfwByhpKwT

-- Dumped from database version 15.18
-- Dumped by pg_dump version 15.18

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: user_cv_data; Type: TABLE; Schema: public; Owner: boontrack_user
--

CREATE TABLE public.user_cv_data (
    telegram_id bigint NOT NULL,
    nama character varying,
    email character varying,
    phone_number character varying,
    domisili character varying,
    linkedin_url character varying,
    posisi character varying,
    pendidikan text,
    pengalaman text,
    pencapaian text,
    skill text,
    updated_at timestamp without time zone
);


ALTER TABLE public.user_cv_data OWNER TO boontrack_user;

--
-- Name: user_cv_data_telegram_id_seq; Type: SEQUENCE; Schema: public; Owner: boontrack_user
--

CREATE SEQUENCE public.user_cv_data_telegram_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.user_cv_data_telegram_id_seq OWNER TO boontrack_user;

--
-- Name: user_cv_data_telegram_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: boontrack_user
--

ALTER SEQUENCE public.user_cv_data_telegram_id_seq OWNED BY public.user_cv_data.telegram_id;


--
-- Name: user_cv_data telegram_id; Type: DEFAULT; Schema: public; Owner: boontrack_user
--

ALTER TABLE ONLY public.user_cv_data ALTER COLUMN telegram_id SET DEFAULT nextval('public.user_cv_data_telegram_id_seq'::regclass);


--
-- Data for Name: user_cv_data; Type: TABLE DATA; Schema: public; Owner: boontrack_user
--

COPY public.user_cv_data (telegram_id, nama, email, phone_number, domisili, linkedin_url, posisi, pendidikan, pengalaman, pencapaian, skill, updated_at) FROM stdin;
6075596043	Sujianti	sujianti777@gmail.com	087718181814	Bandung	,	Istri Aldi	Universitas Trisakti S1 Akuntansi	Bos Kosmetik	.	Microsoft Office\nMemasak\nJago Jualan	2026-08-04 04:01:23.276174
\.


--
-- Name: user_cv_data_telegram_id_seq; Type: SEQUENCE SET; Schema: public; Owner: boontrack_user
--

SELECT pg_catalog.setval('public.user_cv_data_telegram_id_seq', 1, false);


--
-- Name: user_cv_data user_cv_data_pkey; Type: CONSTRAINT; Schema: public; Owner: boontrack_user
--

ALTER TABLE ONLY public.user_cv_data
    ADD CONSTRAINT user_cv_data_pkey PRIMARY KEY (telegram_id);


--
-- Name: ix_user_cv_data_telegram_id; Type: INDEX; Schema: public; Owner: boontrack_user
--

CREATE INDEX ix_user_cv_data_telegram_id ON public.user_cv_data USING btree (telegram_id);


--
-- PostgreSQL database dump complete
--

\unrestrict BOLh6NcvZ1Wpx8uqHLk6oz3lS8AgpKlxYkA1DlsP8CofbZFjb2aDykfwByhpKwT

