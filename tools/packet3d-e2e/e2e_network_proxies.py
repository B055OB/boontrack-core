#!/usr/bin/env python3
"""tools/packet3d-e2e/e2e_network_proxies.py
Packet 3D Step 3 (Terminal 5 / Account 5):
Real In-Network Infrastructure for Two-Service E2E & Fault Injection Testing.

Hosts 3 strictly local loopback servers (ZERO external or production egress):
  1. 127.0.0.1:18080 — Supabase-compatible PostgREST Gateway -> Docker PostgREST (127.0.0.1:13000)
  2. 127.0.0.2:18090 — Real TCP/HTTP In-Network Fault Proxy -> Core FastAPI (127.0.0.1:18000)
                       Supports PASS_THROUGH, TIMEOUT_AFTER_CORE_ACCEPT, HTTP_503,
                       and TCP_RESET_AFTER_CORE_ACCEPT (genuine SO_LINGER TCP RST).
  3. 127.0.0.1:18095 — Deterministic Local Xendit Sandbox-Contract Harness
                       (EXPLICITLY labeled LOCAL_SANDBOX_CONTRACT_HARNESS; live Xendit
                       Sandbox is marked BLOCKED when non-prod credentials are unavailable).
"""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import struct
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from aiohttp import web

POSTGREST_UPSTREAM = "http://127.0.0.1:13000"
CORE_UPSTREAM = "http://127.0.0.1:18000"

FAULT_STATE: Dict[str, Any] = {
    "mode": "PASS_THROUGH",
    "delay_seconds": 12.5,
    "logs": [],
}

XENDIT_AUDIT: Dict[str, Any] = {
    "harness_mode": "LOCAL_SANDBOX_CONTRACT_HARNESS",
    "qr_codes_calls": [],
    "v2_invoices_calls": [],
    "get_invoices_calls": [],
    "expected_secret_key": "xnd_development_p3d_e2e_local_contract_key",
}


def crc16_ccitt_hex(payload: str) -> str:
    crc = 0xFFFF
    for ch in payload.encode("utf-8"):
        crc ^= ch << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def build_valid_emvco_dynamic_qris(external_id: str, amount: int) -> str:
    """Constructs a syntactically valid EMVCo Dynamic QRIS payload (Tag 01=12, 5802ID, CRC16)."""
    amt_str = str(int(amount))
    ref_clean = "".join(c for c in external_id if c.isalnum())[:20] or "ORDER001"
    # Merchant Account Info (Tag 26) — Xendit Sandbox-Contract Merchant (NOT platform DANA!)
    mai_inner = "0014ID.CO.XENDIT.SANDBOX01159360081100000010303UMI"
    tag26 = f"26{len(mai_inner):02d}{mai_inner}"
    tag54 = f"54{len(amt_str):02d}{amt_str}"
    add_inner = f"05{len(ref_clean):02d}{ref_clean}"
    tag62 = f"62{len(add_inner):02d}{add_inner}"
    body = (
        "000201"
        "010212"
        f"{tag26}"
        "52045812"
        "5303360"
        f"{tag54}"
        "5802ID"
        "5911ONLINEBOOST"
        "6007JAKARTA"
        "610512190"
        f"{tag62}"
        "6304"
    )
    return body + crc16_ccitt_hex(body)


# =============================================================================
# 1. PostgREST Supabase-Compatible Gateway (127.0.0.1:18080)
# =============================================================================

async def postgrest_proxy_handler(request: web.Request) -> web.Response:
    path = request.path
    if path.startswith("/rest/v1"):
        upstream_path = path[len("/rest/v1"):] or "/"
    else:
        upstream_path = path

    qs = f"?{request.query_string}" if request.query_string else ""
    target_url = f"{POSTGREST_UPSTREAM}{upstream_path}{qs}"

    fwd_headers: Dict[str, str] = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "content-length", "transfer-encoding", "connection", "accept-encoding"):
            continue
        fwd_headers[k] = v

    body = await request.read()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=fwd_headers,
            content=body,
        )

    out_headers: Dict[str, str] = {}
    for k, v in resp.headers.items():
        lk = k.lower()
        if lk in ("transfer-encoding", "connection", "content-encoding", "content-length"):
            continue
        out_headers[k] = v

    return web.Response(
        status=resp.status_code,
        body=resp.content,
        headers=out_headers,
    )


def build_postgrest_gateway_app() -> web.Application:
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", postgrest_proxy_handler)
    return app


# =============================================================================
# 2. Local Xendit Sandbox-Contract Server (127.0.0.1:18095)
# =============================================================================

async def xendit_create_qr_code(request: web.Request) -> web.Response:
    auth_hdr = request.headers.get("Authorization", "")
    expected_basic = "Basic " + base64.b64encode(
        f"{XENDIT_AUDIT['expected_secret_key']}:".encode("utf-8")
    ).decode("utf-8")
    auth_valid = auth_hdr == expected_basic

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    external_id = str(payload.get("external_id") or payload.get("reference_id") or f"QR-{uuid.uuid4().hex[:8]}")
    amount = int(payload.get("amount") or 0)
    qr_id = f"qr_p3d_contract_{uuid.uuid4().hex[:10]}"
    qr_string = build_valid_emvco_dynamic_qris(external_id, amount)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "endpoint": "/qr_codes",
        "external_id": external_id,
        "amount": amount,
        "type": payload.get("type"),
        "currency": payload.get("currency"),
        "qr_id": qr_id,
        "auth_valid": auth_valid,
        "remote": request.remote,
        "user_agent": request.headers.get("User-Agent", ""),
    }
    XENDIT_AUDIT["qr_codes_calls"].append(entry)

    if not auth_valid:
        return web.json_response(
            {"error_code": "API_VALIDATION_ERROR", "message": "Invalid Basic Auth secret key"},
            status=401,
        )

    return web.json_response(
        {
            "id": qr_id,
            "reference_id": external_id,
            "external_id": external_id,
            "type": "DYNAMIC",
            "currency": "IDR",
            "amount": amount,
            "status": "ACTIVE",
            "qr_string": qr_string,
            "expires_at": expires_at,
            "created": datetime.now(timezone.utc).isoformat(),
        },
        status=200,
    )


async def xendit_create_invoice(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    XENDIT_AUDIT["v2_invoices_calls"].append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "endpoint": "/v2/invoices",
            "external_id": payload.get("external_id"),
            "amount": payload.get("amount"),
            "user_agent": request.headers.get("User-Agent", ""),
        }
    )
    return web.json_response(
        {
            "id": f"inv_dup_{uuid.uuid4().hex[:8]}",
            "external_id": payload.get("external_id"),
            "amount": payload.get("amount"),
            "status": "PENDING",
            "invoice_url": f"http://127.0.0.1:18095/web/{payload.get('external_id')}",
        },
        status=200,
    )


async def xendit_get_invoices(request: web.Request) -> web.Response:
    ext_id = request.query.get("external_id", "")
    XENDIT_AUDIT["get_invoices_calls"].append({"ts": datetime.now(timezone.utc).isoformat(), "external_id": ext_id})
    matched = [c for c in XENDIT_AUDIT["qr_codes_calls"] if c.get("external_id") == ext_id]
    if not matched:
        return web.json_response([], status=200)
    return web.json_response(
        [{"id": matched[-1]["qr_id"], "external_id": ext_id, "status": "PENDING", "amount": matched[-1]["amount"]}],
        status=200,
    )


async def xendit_audit_get(request: web.Request) -> web.Response:
    return web.json_response(XENDIT_AUDIT, status=200)


async def xendit_audit_reset(request: web.Request) -> web.Response:
    XENDIT_AUDIT["qr_codes_calls"].clear()
    XENDIT_AUDIT["v2_invoices_calls"].clear()
    XENDIT_AUDIT["get_invoices_calls"].clear()
    return web.json_response({"reset": True}, status=200)


def build_xendit_contract_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/qr_codes", xendit_create_qr_code)
    app.router.add_post("/v2/invoices", xendit_create_invoice)
    app.router.add_get("/v2/invoices", xendit_get_invoices)
    app.router.add_get("/__xendit__/audit", xendit_audit_get)
    app.router.add_post("/__xendit__/reset", xendit_audit_reset)
    return app


# =============================================================================
# 3. Real Raw-TCP In-Network Fault Proxy (127.0.0.2:18090 -> Core 127.0.0.1:18000)
# =============================================================================

async def read_http_request(reader: asyncio.StreamReader) -> Optional[Tuple[str, str, str, Dict[str, str], bytes]]:
    header_bytes = b""
    while b"\r\n\r\n" not in header_bytes:
        chunk = await reader.read(4096)
        if not chunk:
            return None
        header_bytes += chunk
        if len(header_bytes) > 1024 * 1024:
            return None

    head_part, rest = header_bytes.split(b"\r\n\r\n", 1)
    lines = head_part.decode("latin-1").split("\r\n")
    req_line = lines[0].split(" ", 2)
    if len(req_line) < 3:
        return None
    method, target, version = req_line[0], req_line[1], req_line[2]
    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    body = rest
    if headers.get("transfer-encoding", "").lower() == "chunked":
        # Decode chunked transfer encoding
        buf = body
        decoded = bytearray()
        while True:
            while b"\r\n" not in buf:
                more = await reader.read(4096)
                if not more:
                    break
                buf += more
            size_line, buf = buf.split(b"\r\n", 1)
            chunk_size = int(size_line.split(b";", 1)[0].strip(), 16)
            if chunk_size == 0:
                break
            while len(buf) < chunk_size + 2:
                more = await reader.read(4096)
                if not more:
                    break
                buf += more
            decoded.extend(buf[:chunk_size])
            buf = buf[chunk_size + 2:]
        body = bytes(decoded)
    else:
        cl = int(headers.get("content-length", "0") or "0")
        while len(body) < cl:
            more = await reader.read(cl - len(body))
            if not more:
                break
            body += more
        body = body[:cl]

    return method, target, version, headers, body


def build_http_response_bytes(status: int, reason: str, headers: Dict[str, str], body: bytes) -> bytes:
    lines = [f"HTTP/1.1 {status} {reason}"]
    out_h = dict(headers)
    out_h["Content-Length"] = str(len(body))
    out_h["Connection"] = "close"
    for k, v in out_h.items():
        lines.append(f"{k}: {v}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def send_tcp_reset(writer: asyncio.StreamWriter) -> None:
    """Forces a genuine OS-level TCP RST packet via SO_LINGER(1, 0)."""
    sock: Optional[socket.socket] = writer.get_extra_info("socket")
    if sock is not None:
        try:
            # Windows SO_LINGER uses two unsigned shorts (l_onoff, l_linger); POSIX uses two ints
            fmt = "HH" if sys.platform == "win32" else "ii"
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack(fmt, 1, 0))
        except Exception:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            except Exception:
                pass
    try:
        writer.transport.abort()
    except Exception:
        writer.close()


async def handle_fault_proxy_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        parsed = await asyncio.wait_for(read_http_request(reader), timeout=15.0)
        if not parsed:
            writer.close()
            return
        method, target, _version, headers, body = parsed

        # Control endpoints on fault proxy
        if target == "/__fault__/config" and method == "POST":
            cfg = json.loads(body.decode("utf-8") or "{}")
            if "mode" in cfg:
                FAULT_STATE["mode"] = str(cfg["mode"]).upper()
            if "delay_seconds" in cfg:
                FAULT_STATE["delay_seconds"] = float(cfg["delay_seconds"])
            resp_body = json.dumps({"ok": True, "mode": FAULT_STATE["mode"], "delay_seconds": FAULT_STATE["delay_seconds"]}).encode("utf-8")
            writer.write(build_http_response_bytes(200, "OK", {"Content-Type": "application/json"}, resp_body))
            await writer.drain()
            writer.close()
            return

        if target == "/__fault__/log" and method == "GET":
            resp_body = json.dumps({"mode": FAULT_STATE["mode"], "logs": FAULT_STATE["logs"]}).encode("utf-8")
            writer.write(build_http_response_bytes(200, "OK", {"Content-Type": "application/json"}, resp_body))
            await writer.drain()
            writer.close()
            return

        if target == "/__fault__/reset" and method == "POST":
            FAULT_STATE["mode"] = "PASS_THROUGH"
            FAULT_STATE["delay_seconds"] = 12.5
            FAULT_STATE["logs"].clear()
            resp_body = json.dumps({"reset": True}).encode("utf-8")
            writer.write(build_http_response_bytes(200, "OK", {"Content-Type": "application/json"}, resp_body))
            await writer.drain()
            writer.close()
            return

        mode = FAULT_STATE["mode"]
        log_entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "method": method,
            "target": target,
            "inbound_headers": {k: v for k, v in headers.items()},
            "has_hmac_headers": any(k.startswith("x-payment-internal-") for k in headers),
            "idempotency_key": headers.get("idempotency-key") or headers.get("x-idempotency-key"),
            "body_preview": body.decode("utf-8", errors="replace")[:500],
            "core_forwarded": False,
            "core_status": None,
            "core_body_preview": None,
            "fault_action": None,
        }
        FAULT_STATE["logs"].append(log_entry)

        if mode == "HTTP_503":
            log_entry["fault_action"] = "INJECTED_WIRE_HTTP_503"
            err_body = json.dumps({"error": "INJECTED_HTTP_503", "detail": "Real in-network fault proxy HTTP 503"}).encode("utf-8")
            writer.write(build_http_response_bytes(503, "Service Unavailable", {"Content-Type": "application/json"}, err_body))
            await writer.drain()
            writer.close()
            return

        # Forward to Core upstream (for PASS_THROUGH, TIMEOUT_AFTER_CORE_ACCEPT, TCP_RESET_AFTER_CORE_ACCEPT)
        fwd_headers = {
            k: v for k, v in headers.items()
            if k not in ("host", "content-length", "transfer-encoding", "connection", "accept-encoding")
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            core_resp = await client.request(
                method=method,
                url=f"{CORE_UPSTREAM}{target}",
                headers=fwd_headers,
                content=body,
            )

        log_entry["core_forwarded"] = True
        log_entry["core_status"] = core_resp.status_code
        log_entry["core_body_preview"] = core_resp.text[:500]

        if mode == "TIMEOUT_AFTER_CORE_ACCEPT":
            log_entry["fault_action"] = f"HELD_OPEN_AFTER_CORE_HTTP_{core_resp.status_code}"
            try:
                await asyncio.sleep(float(FAULT_STATE["delay_seconds"]))
            except asyncio.CancelledError:
                pass
            writer.close()
            return

        if mode == "TCP_RESET_AFTER_CORE_ACCEPT":
            log_entry["fault_action"] = f"TCP_RST_SENT_AFTER_CORE_HTTP_{core_resp.status_code}"
            send_tcp_reset(writer)
            return

        # PASS_THROUGH
        log_entry["fault_action"] = "DELIVERED_VERBATIM"
        out_headers: Dict[str, str] = {}
        for k, v in core_resp.headers.items():
            lk = k.lower()
            if lk in ("transfer-encoding", "connection", "content-encoding", "content-length"):
                continue
            out_headers[k] = v
        writer.write(
            build_http_response_bytes(
                core_resp.status_code,
                core_resp.reason_phrase or "OK",
                out_headers,
                core_resp.content,
            )
        )
        await writer.drain()
        writer.close()
    except Exception as exc:
        FAULT_STATE["logs"].append({"ts": datetime.now(timezone.utc).isoformat(), "proxy_error": str(exc)})
        try:
            writer.close()
        except Exception:
            pass


async def main() -> None:
    pg_runner = web.AppRunner(build_postgrest_gateway_app())
    await pg_runner.setup()
    pg_site = web.TCPSite(pg_runner, "127.0.0.1", 18080)
    await pg_site.start()

    xnd_runner = web.AppRunner(build_xendit_contract_app())
    await xnd_runner.setup()
    xnd_site = web.TCPSite(xnd_runner, "127.0.0.1", 18095)
    await xnd_site.start()

    fault_server = await asyncio.start_server(handle_fault_proxy_client, "127.0.0.2", 18090)

    print("[E2E_PROXIES_READY] PostgREST-GW=127.0.0.1:18080 FaultProxy=127.0.0.2:18090 XenditContract=127.0.0.1:18095", flush=True)
    async with fault_server:
        await fault_server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
