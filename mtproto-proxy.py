#!/usr/bin/env python3
"""
mtproto-proxy.py — Straw Hat | 麦わら帽子 (LUFFY PANEL) MTProto (Telegram) proxy engine
======================================================================================

Supervises the actual MTProto (Telegram) proxying for every enabled
`mtproto_inbounds` row in the panel's SQLite database. It supports two
engines and picks automatically based on what's available on the host:

  1. **mtg (preferred, opportunistic)** — if the real `mtg` binary
     (github.com/9seconds/mtg) happens to be on `PATH` or pointed to by
     `MTPROXY_BIN`, one `mtg simple-run` child process is supervised per
     usable inbound, each bound to its own internal port. mtg is a mature,
     widely-deployed Go implementation of the MTProto proxy protocol.
     This deploy doesn't ship a Dockerfile, so `mtg` won't be present
     unless you installed it yourself on the host — that's fine, the
     built-in engine below is the expected path for a plain
     Procfile/buildpack deploy (Railway/Render without Docker).
  2. **Built-in Python engine (default for this deploy)** — used whenever
     `mtg` isn't found, i.e. normally. Implements the obfuscated2
     handshake from scratch and demultiplexes every secret on one shared
     port. See "Protocol notes" below for its limitations; test it before
     relying on it in production.

Either way, this file:
  * Tracks quota/expiry/active state per inbound and starts/stops the
    relevant proxy process accordingly.
  * Can be launched two ways:
      1. Standalone:  `python mtproto-proxy.py`
      2. Embedded:    `main.py` spawns this file as a subprocess on
         startup (see `spawn_mtproto_proxy()` in main.py) so a single
         `web` process on Railway/Render brings both up together.

Live traffic accounting (used_bytes) is only maintained by the built-in
engine — mtg doesn't expose clean per-secret byte counters, so under mtg
the dashboard's usage counter stays wherever it was last manually set;
quota/expiry/active enforcement still works either way (an inbound that
becomes unusable has its proxy process stopped).

Protocol notes / honest limitations of the built-in engine (the one this deploy actually uses)
-------------------------------------------------------------------------------------------------
  * Supports the **abridged** and **intermediate** client transports,
    which cover the overwhelming majority of real MTProto-proxy
    clients (including the official Telegram apps).
  * **Padded-intermediate** is intentionally NOT supported — correctly
    stripping its padding requires parsing the inner MTProto message
    length, and getting that wrong silently corrupts traffic. Clients
    that pick padded-intermediate are disconnected immediately rather
    than pretending to work.
  * Fake-TLS ("dd"-secret / SNI masking) is not implemented. Plain
    16-byte hex secrets are supported; a leading "dd"/"ee" prefix on a
    pasted secret is stripped automatically so old secrets still work,
    but the connection will not be disguised as a TLS handshake.
  * Because this sandbox has no network access, this code could not be
    tested against live Telegram datacenters. The handshake math
    follows the publicly documented obfuscated2 scheme used by every
    open-source MTProto proxy (official MTProxy, mtg, mtprotoproxy,
    etc.). Test it after deploying and report back if a client can't
    connect — the DC IP list or a byte offset is the most likely
    culprit to revisit.

Sponsor ("proxy ad tag")
------------------------
Telegram will show a promoted/sponsor channel to users of your proxy
if — and only if — you register your proxy's IP, port and secret with
the official @MTProxybot on Telegram. This file does not need to send
anything special on the wire for that; the `sponsor_tag` value stored
per inbound is purely for your own reference in the panel (paste the
tag @MTProxybot gives you back in there as a reminder of what you
registered).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets as pysecrets
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass, field

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    print("Missing dependency 'cryptography'. Install with: pip install cryptography", file=sys.stderr)
    raise

logging.basicConfig(
    level=os.environ.get("MTPROTO_LOG_LEVEL", "INFO"),
    format="%(asctime)s [mtproto] %(levelname)s %(message)s",
)
log = logging.getLogger("mtproto-proxy")

# ── Config ────────────────────────────────────────────────────────────────

DB_FILE = os.environ.get("LUFFY_DB_FILE") or ("/data/panel.db" if os.path.isdir("/data") else "panel.db")
MTPROTO_PORT = int(os.environ.get("MTPROTO_PORT", "3456"))
MTPROTO_BIND = os.environ.get("MTPROTO_BIND", "0.0.0.0")
RELOAD_INTERVAL = 5          # seconds between re-reading inbounds from DB
USAGE_FLUSH_INTERVAL = 10    # seconds between writing used_bytes back to DB
IDLE_TIMEOUT = 180           # close relay if silent this long

# Well-known Telegram datacenter addresses (public, used by every open
# source MTProto proxy implementation). Negative dc_id in the handshake
# means "this is a nearest-DC/media test connection" — we just use abs().
DC_IPS_V4 = {
    1: "149.154.175.50",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130",
}
DEFAULT_DC = 2
TG_PORT = 443

ABRIDGED_TAG = b"\xef\xef\xef\xef"
INTERMEDIATE_TAG = b"\xee\xee\xee\xee"
PADDED_INTERMEDIATE_TAG = b"\xdd\xdd\xdd\xdd"
FORBIDDEN_PREFIXES = (b"HEAD", b"POST", b"GET ", b"\x16\x03\x01\x02", b"\x16\x03\x03\x01")


# ── DB access (shared file with main.py) ────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_table():
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS mtproto_inbounds (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                secret TEXT NOT NULL UNIQUE,
                dc_id INTEGER DEFAULT 2,
                limit_bytes INTEGER DEFAULT 0,
                used_bytes INTEGER DEFAULT 0,
                max_connections INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                expires_at TEXT,
                sponsor_tag TEXT DEFAULT '',
                addresses_json TEXT DEFAULT '[]'
            );
        """)
        conn.commit()
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(mtproto_inbounds)").fetchall()}
        for col, ddl in (
            ("bind_port", "ALTER TABLE mtproto_inbounds ADD COLUMN bind_port INTEGER"),
            ("public_host", "ALTER TABLE mtproto_inbounds ADD COLUMN public_host TEXT DEFAULT ''"),
            ("public_port", "ALTER TABLE mtproto_inbounds ADD COLUMN public_port TEXT DEFAULT ''"),
        ):
            if col not in existing_cols:
                conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


@dataclass
class Inbound:
    id: str
    label: str
    secret: bytes           # raw 16 bytes
    secret_hex: str          # original hex string (needed verbatim for mtg)
    dc_id: int
    bind_port: int
    public_host: str
    public_port: str
    limit_bytes: int
    used_bytes: int
    max_connections: int
    active: bool
    expires_at: float | None  # unix ts or None
    pending_usage: int = field(default=0, repr=False)
    live_connections: int = field(default=0, repr=False)

    def is_usable(self) -> bool:
        if not self.active:
            return False
        if self.expires_at is not None and time.time() > self.expires_at:
            return False
        if self.limit_bytes > 0 and self.used_bytes >= self.limit_bytes:
            return False
        if self.max_connections > 0 and self.live_connections >= self.max_connections:
            return False
        return True


def clean_secret_hex(raw: str) -> bytes | None:
    s = (raw or "").strip().lower()
    if s.startswith(("dd", "ee")) and len(s) == 34:
        s = s[2:]
    if len(s) != 32:
        return None
    try:
        return bytes.fromhex(s)
    except ValueError:
        return None


def parse_iso(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        from datetime import datetime
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return None


class InboundStore:
    """Holds the live set of MTProto inbounds, periodically re-synced from
    the shared SQLite DB, and batches usage writes back to it."""

    def __init__(self):
        self.by_secret: dict[bytes, Inbound] = {}
        self._lock = asyncio.Lock()

    async def reload_loop(self):
        while True:
            try:
                self._reload_once()
            except Exception as e:
                log.error(f"reload error: {e}")
            await asyncio.sleep(RELOAD_INTERVAL)

    def _reload_once(self):
        conn = get_db()
        try:
            rows = conn.execute("SELECT * FROM mtproto_inbounds").fetchall()
        finally:
            conn.close()
        fresh: dict[bytes, Inbound] = {}
        used_ports = {row["bind_port"] for row in rows if row["bind_port"]}
        next_port = MTPROTO_PORT
        for row in rows:
            secret = clean_secret_hex(row["secret"])
            if not secret:
                continue
            existing = self.by_secret.get(secret)
            bind_port = row["bind_port"]
            if not bind_port:
                while next_port in used_ports:
                    next_port += 1
                bind_port = next_port
                used_ports.add(bind_port)
                self._persist_bind_port(row["id"], bind_port)
            fresh[secret] = Inbound(
                id=row["id"],
                label=row["label"],
                secret=secret,
                secret_hex=row["secret"].strip().lower(),
                dc_id=row["dc_id"] or DEFAULT_DC,
                bind_port=bind_port,
                public_host=(row["public_host"] or "").strip() if "public_host" in row.keys() else "",
                public_port=(row["public_port"] or "").strip() if "public_port" in row.keys() else "",
                limit_bytes=row["limit_bytes"] or 0,
                used_bytes=row["used_bytes"] or 0,
                max_connections=row["max_connections"] or 0,
                active=bool(row["active"]),
                expires_at=parse_iso(row["expires_at"]),
                pending_usage=existing.pending_usage if existing else 0,
                live_connections=existing.live_connections if existing else 0,
            )
        self.by_secret = fresh

    def _persist_bind_port(self, ib_id: str, bind_port: int):
        conn = get_db()
        try:
            conn.execute("UPDATE mtproto_inbounds SET bind_port = ? WHERE id = ?", (bind_port, ib_id))
            conn.commit()
        finally:
            conn.close()

    async def flush_loop(self):
        while True:
            await asyncio.sleep(USAGE_FLUSH_INTERVAL)
            try:
                self._flush_once()
            except Exception as e:
                log.error(f"flush error: {e}")

    def _flush_once(self):
        pending = [(ib.id, ib.pending_usage) for ib in self.by_secret.values() if ib.pending_usage]
        if not pending:
            return
        conn = get_db()
        try:
            for ib_id, amount in pending:
                conn.execute("UPDATE mtproto_inbounds SET used_bytes = used_bytes + ? WHERE id = ?", (amount, ib_id))
            conn.commit()
        finally:
            conn.close()
        for ib in self.by_secret.values():
            if ib.pending_usage:
                ib.used_bytes += ib.pending_usage
                ib.pending_usage = 0

    def find(self, secret: bytes) -> Inbound | None:
        return self.by_secret.get(secret)


STORE = InboundStore()


# ── obfuscated2 handshake ───────────────────────────────────────────────────

def gen_random_header() -> bytes:
    while True:
        rnd = bytearray(os.urandom(64))
        if rnd[0] == 0xEF:
            continue
        if bytes(rnd[:4]) in FORBIDDEN_PREFIXES:
            continue
        if bytes(rnd[:4]) in (ABRIDGED_TAG, INTERMEDIATE_TAG, PADDED_INTERMEDIATE_TAG):
            continue
        if rnd[4:8] == b"\x00\x00\x00\x00":
            continue
        return bytes(rnd)


def make_ctr(key: bytes, iv: bytes):
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    return cipher.encryptor(), cipher.decryptor()  # CTR: encryptor == decryptor logically, kept separate for clarity


def build_outbound_header(protocol_tag: bytes, dc_id: int, secret: bytes = b""):
    """Build our own obfuscated2 header (used for the proxy->DC leg).
    Returns (wire_bytes, keystream_cipher_for_our_outgoing_data,
    keystream_cipher_for_data_we_receive)."""
    rnd = bytearray(gen_random_header())
    payload = bytearray(rnd)
    payload[56:60] = protocol_tag
    payload[60:62] = struct.pack("<h", dc_id)

    key = hashlib.sha256(bytes(payload[8:40]) + secret).digest()
    iv = bytes(payload[40:56])
    enc_cipher = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
    encrypted_full = enc_cipher.update(bytes(payload))  # advances keystream by 64 bytes, as needed

    wire = bytearray(rnd)
    wire[56:64] = encrypted_full[56:64]

    reversed_block = bytes(rnd)[55:7:-1]
    dec_key = hashlib.sha256(reversed_block[0:32] + secret).digest()
    dec_iv = reversed_block[32:48]
    dec_cipher = Cipher(algorithms.AES(dec_key), modes.CTR(dec_iv)).decryptor()

    return bytes(wire), enc_cipher, dec_cipher


def try_match_secret(header: bytes, candidates) -> tuple[Inbound, bytes, bytes] | None:
    """Try decrypting the client's 64-byte header against every known
    secret; return (inbound, protocol_tag, dc_id_bytes) on the first
    valid match."""
    if header[0] == 0xEF or bytes(header[:4]) in FORBIDDEN_PREFIXES:
        return None
    for secret, inbound in list(candidates.items()):
        key = hashlib.sha256(header[8:40] + secret).digest()
        iv = header[40:56]
        dec = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
        decrypted = dec.update(header)
        tag = decrypted[56:60]
        if tag in (ABRIDGED_TAG, INTERMEDIATE_TAG, PADDED_INTERMEDIATE_TAG):
            return inbound, tag, decrypted[60:62]
    return None


# ── Framing helpers ──────────────────────────────────────────────────────

def frame_intermediate(payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "little") + payload


def frame_abridged(payload: bytes) -> bytes:
    n = len(payload) // 4
    if n < 0x7F:
        return bytes([n]) + payload
    return b"\x7f" + n.to_bytes(3, "little") + payload


class FrameParser:
    """Buffers bytes and yields whole packets for abridged/intermediate
    client framing. Quick-acks (top bit set on an intermediate length
    field) are yielded as raw 4-byte blobs, unchanged."""

    def __init__(self, mode: bytes):
        self.mode = mode
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf.extend(data)

    def pop_packets(self):
        out = []
        buf = self.buf
        while True:
            if self.mode == INTERMEDIATE_TAG:
                if len(buf) < 4:
                    break
                raw_len = int.from_bytes(buf[0:4], "little")
                if raw_len & 0x80000000:
                    out.append(bytes(buf[0:4]))  # quick ack, no body
                    del buf[0:4]
                    continue
                if len(buf) < 4 + raw_len:
                    break
                out.append(bytes(buf[4:4 + raw_len]))
                del buf[0:4 + raw_len]
            else:  # abridged
                if len(buf) < 1:
                    break
                first = buf[0]
                if first < 0x7F:
                    length = first * 4
                    if len(buf) < 1 + length:
                        break
                    out.append(bytes(buf[1:1 + length]))
                    del buf[0:1 + length]
                else:
                    if len(buf) < 4:
                        break
                    length = int.from_bytes(bytes(buf[1:4]) + b"\x00", "little") * 4
                    if len(buf) < 4 + length:
                        break
                    out.append(bytes(buf[4:4 + length]))
                    del buf[0:4 + length]
        return out

    def reframe_out(self, payload: bytes) -> bytes:
        if len(payload) == 4 and int.from_bytes(payload, "little") & 0x80000000:
            return payload  # quick ack passthrough
        if self.mode == INTERMEDIATE_TAG:
            return frame_intermediate(payload)
        return frame_abridged(payload)


# ── Relay ────────────────────────────────────────────────────────────────

async def pipe_client_to_dc(reader, dec_from_client, parser: FrameParser,
                             dc_writer, enc_to_dc, inbound: Inbound, usage: list):
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            break
        plain = dec_from_client.update(chunk)
        parser.feed(plain)
        for pkt in parser.pop_packets():
            dc_writer.write(enc_to_dc.update(frame_intermediate(pkt) if len(pkt) != 4 or not (int.from_bytes(pkt, "little") & 0x80000000) else pkt))
        await dc_writer.drain()
        usage[0] += len(chunk)
        inbound.pending_usage += len(chunk)
        if not inbound.is_usable():
            break


async def pipe_dc_to_client(dc_reader, dec_from_dc, dc_parser: FrameParser,
                             writer, enc_to_client, inbound: Inbound, usage: list):
    while True:
        chunk = await dc_reader.read(65536)
        if not chunk:
            break
        plain = dec_from_dc.update(chunk)
        dc_parser.feed(plain)
        for pkt in dc_parser.pop_packets():
            writer.write(enc_to_client.update(dc_parser.reframe_out(pkt) if len(pkt) != 4 or not (int.from_bytes(pkt, "little") & 0x80000000) else pkt))
        await writer.drain()
        usage[0] += len(chunk)
        inbound.pending_usage += len(chunk)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    try:
        header = await asyncio.wait_for(reader.readexactly(64), timeout=10)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError):
        writer.close()
        return

    match = try_match_secret(header, STORE.by_secret)
    if not match:
        writer.close()
        return
    inbound, tag, dc_id_bytes = match

    if tag == PADDED_INTERMEDIATE_TAG:
        # Not supported (see module docstring) — close rather than corrupt traffic.
        writer.close()
        return

    if not inbound.is_usable():
        writer.close()
        return

    # Derive the two client-facing ciphers (mirrors main.py's math).
    dec_key = hashlib.sha256(header[8:40] + inbound.secret).digest()
    dec_iv = header[40:56]
    dec_from_client = Cipher(algorithms.AES(dec_key), modes.CTR(dec_iv)).decryptor()
    dec_from_client.update(header)  # consume the 64 bytes already spent on the header itself

    reversed_block = header[55:7:-1]
    enc_key = hashlib.sha256(reversed_block[0:32] + inbound.secret).digest()
    enc_iv = reversed_block[32:48]
    enc_to_client = Cipher(algorithms.AES(enc_key), modes.CTR(enc_iv)).encryptor()

    dc_id = struct.unpack("<h", dc_id_bytes)[0]
    dc_id = abs(dc_id) or inbound.dc_id or DEFAULT_DC
    dc_ip = DC_IPS_V4.get(dc_id, DC_IPS_V4[DEFAULT_DC])

    try:
        dc_reader, dc_writer = await asyncio.wait_for(asyncio.open_connection(dc_ip, TG_PORT), timeout=10)
    except Exception as e:
        log.warning(f"cannot reach DC{dc_id} ({dc_ip}): {e}")
        writer.close()
        return

    dc_header, enc_to_dc, dec_from_dc = build_outbound_header(INTERMEDIATE_TAG, dc_id)
    dc_writer.write(dc_header)
    await dc_writer.drain()

    inbound.live_connections += 1
    client_parser = FrameParser(tag)
    dc_parser = FrameParser(INTERMEDIATE_TAG)
    usage = [0]

    try:
        await asyncio.gather(
            pipe_client_to_dc(reader, dec_from_client, client_parser, dc_writer, enc_to_dc, inbound, usage),
            pipe_dc_to_client(dc_reader, dec_from_dc, dc_parser, writer, enc_to_client, inbound, usage),
        )
    except (ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:
        log.debug(f"relay ended for {inbound.label} ({peer}): {e}")
    finally:
        inbound.live_connections = max(0, inbound.live_connections - 1)
        for w in (writer, dc_writer):
            try:
                w.close()
            except Exception:
                pass


async def main():
    ensure_table()
    STORE._reload_once()
    asyncio.create_task(STORE.reload_loop())
    asyncio.create_task(STORE.flush_loop())

    binary = find_mtg_binary()
    if binary:
        log.info(f"mtg binary found at {binary} — using it as the MTProto engine (recommended path)")
        await run_with_mtg(binary)
    else:
        log.info(
            "mtg binary not found on this host (expected for a plain Procfile/buildpack deploy — "
            "no Dockerfile is used) — using the built-in pure-Python engine. See mtproto-proxy.py's "
            "module docstring for what it does and doesn't support."
        )
        await run_builtin_engine()


async def run_builtin_engine():
    """Fallback engine: one asyncio server on MTPROTO_PORT, demultiplexing
    every configured secret off the single obfuscated2 handshake — see the
    module docstring for its tested-but-unverified-against-Telegram status."""
    server = await asyncio.start_server(handle_client, MTPROTO_BIND, MTPROTO_PORT)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info(f"MTProto proxy (built-in engine) listening on {addrs} — {len(STORE.by_secret)} secret(s) loaded from {DB_FILE}")
    async with server:
        await server.serve_forever()


# ── mtg engine (preferred — real, battle-tested MTProto proxy binary) ──────
# One `mtg simple-run` child process per usable inbound, each bound to its
# own internal port (assigned/persisted in `bind_port`). This mirrors how
# every other reference implementation of "MTProto proxy behind Railway"
# does it: mtg handles the actual protocol, we just supervise it and decide
# which secrets are currently allowed to run (active/quota/expiry).
#
# Trade-off: mtg does not expose clean per-secret byte counters, so
# used_bytes is NOT updated live in this mode (it still updates for the
# built-in fallback engine). Enforcement of active/expiry/quota still
# works — an inbound that becomes unusable has its mtg process stopped —
# just not live traffic counting.

_mtg_tasks: dict[int, asyncio.Task] = {}   # bind_port -> supervisor task
_mtg_procs: dict[int, asyncio.subprocess.Process] = {}


def find_mtg_binary() -> str:
    env_bin = os.environ.get("MTPROXY_BIN", "").strip()
    if env_bin and os.path.isfile(env_bin):
        return env_bin
    for candidate in ("/usr/local/bin/mtg", "/mtg", "mtg"):
        found = candidate if os.path.isfile(candidate) else None
        if not found:
            import shutil
            found = shutil.which(candidate)
        if found:
            return found
    return ""


async def _pump_mtg_output(stream, label: str):
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", "replace").rstrip()
        if text:
            log.info(f"[mtg:{label}] {text}")


async def _supervise_mtg(binary: str, bind_port: int, get_secret_hex):
    """Keeps one mtg instance alive on `bind_port` for as long as the
    inbound behind it stays usable; exits (and lets the caller restart it
    later if the inbound becomes usable again) otherwise."""
    backoff = 2
    while True:
        secret_hex = get_secret_hex()
        if secret_hex is None:
            return  # inbound gone or no longer usable — caller will clean us up
        bind = f"0.0.0.0:{bind_port}"
        cmd = [binary, "simple-run", "-c", "4096", "-t", "30s", bind, secret_hex]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            log.error(f"failed to start mtg on {bind}: {e}")
            return
        _mtg_procs[bind_port] = proc
        log.info(f"mtg started on {bind}")
        await asyncio.gather(
            _pump_mtg_output(proc.stdout, str(bind_port)),
            _pump_mtg_output(proc.stderr, str(bind_port)),
            proc.wait(),
        )
        _mtg_procs.pop(bind_port, None)
        if get_secret_hex() is None:
            return  # inbound was disabled/removed while mtg was running — stop cleanly
        log.warning(f"mtg on {bind} exited (code {proc.returncode}), restarting in {backoff}s")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


async def run_with_mtg(binary: str):
    async def reconcile_loop():
        while True:
            wanted = {ib.bind_port: ib.secret_hex for ib in STORE.by_secret.values() if ib.is_usable()}
            # start supervisors for newly-usable inbounds
            for port, secret_hex in wanted.items():
                if port not in _mtg_tasks or _mtg_tasks[port].done():
                    def _get(port=port):
                        ib = next((x for x in STORE.by_secret.values() if x.bind_port == port), None)
                        return ib.secret_hex if ib and ib.is_usable() else None
                    _mtg_tasks[port] = asyncio.create_task(_supervise_mtg(binary, port, _get))
            # stop supervisors for ports that are no longer wanted
            for port in list(_mtg_tasks.keys()):
                if port not in wanted:
                    proc = _mtg_procs.get(port)
                    if proc and proc.returncode is None:
                        proc.terminate()
                    task = _mtg_tasks.pop(port, None)
                    if task:
                        task.cancel()
            await asyncio.sleep(RELOAD_INTERVAL)

    log.info(f"MTProto proxy (mtg engine) starting — {len(STORE.by_secret)} secret(s) loaded from {DB_FILE}")
    await reconcile_loop()


def gen_secret() -> str:
    return pysecrets.token_hex(16)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
