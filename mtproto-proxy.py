#!/usr/bin/env python3
"""
mtproto-proxy.py — Straw Hat | 麦わら帽子 (LUFFY PANEL) MTProto (Telegram) proxy engine
======================================================================================

Supervises the actual MTProto (Telegram) proxying for every enabled
`mtproto_inbounds` row in the panel's SQLite database. It supports two
engines and picks automatically based on what's available at runtime:

  1. **mtg (preferred, self-installing — this is what actually runs)** —
     mtg (github.com/9seconds/mtg) is a mature, widely-deployed Go
     implementation of the MTProto proxy protocol; using it instead of a
     hand-rolled reimplementation is what makes this reliable. This deploy
     has no Dockerfile, so instead of baking mtg into an image at build
     time, this file downloads the real upstream `mtg` release straight
     from GitHub the first time it's needed (Railway/Render containers
     have normal outbound internet access at runtime) and runs it from
     there — one `mtg simple-run` child process per usable inbound, each
     bound to its own internal port. If `MTPROXY_BIN` already points at an
     installed binary, or one is already on `PATH`, that's used instead
     and nothing is downloaded.
  2. **Built-in Python engine (last-resort fallback only)** — used only if
     mtg genuinely can't be obtained (no network reachability to GitHub,
     or a host architecture no mtg release covers). Implements the
     obfuscated2 handshake from scratch and is inherently less
     battle-tested — see "Protocol notes" below. If you're seeing this
     engine's log lines and connections aren't working, that's the
     expected symptom; the fix is making sure this container can actually
     reach github.com, not the panel configuration.

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

Protocol notes / honest limitations of the built-in fallback engine (only relevant if mtg couldn't be installed)
-------------------------------------------------------------------------------------------------------------------
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
    etc.). This caveat does not apply to mtg — it's an established,
    independently maintained project, which is exactly why it's now the
    default path whenever it can be downloaded.

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
import re
import secrets as pysecrets
import sqlite3
import struct
import subprocess
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

def _writable_dir(path: str) -> bool:
    """See main.py's identical helper for why this can't just be
    os.path.isdir(): that alone gives a false positive on hosts (like
    Android/Pydroid3) where /data exists but isn't actually writable."""
    if not os.path.isdir(path):
        return False
    try:
        probe = os.path.join(path, f".write_test_{os.getpid()}")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except Exception:
        return False

DB_FILE = os.environ.get("LUFFY_DB_FILE") or ("/data/panel.db" if _writable_dir("/data") else "panel.db")
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
    if not binary:
        log.info("mtg binary not found on this host — attempting to download the real upstream binary from GitHub (no Dockerfile needed for this)...")
        binary = await ensure_mtg_binary()

    if binary:
        log.info(f"using mtg at {binary} as the MTProto engine (recommended path)")
        await run_with_mtg(binary)
    else:
        log.warning(
            "could not get mtg (no network access to GitHub, or an unsupported host architecture) — "
            "falling back to the built-in pure-Python engine. See mtproto-proxy.py's module docstring "
            "for what it does and doesn't support; this is the less battle-tested path."
        )
        await run_builtin_engine()


async def run_builtin_engine():
    """Fallback engine: demultiplexes every configured secret's obfuscated2
    handshake the same way regardless of which port a connection came in
    on, but — critically — must actually have a listener open on every
    port an inbound was assigned, not just MTPROTO_PORT. Each inbound gets
    its own bind_port (443, 444, 445, ...) from main.py so it can get its
    own Railway TCP Proxy; if this engine only listened on MTPROTO_PORT,
    every inbound except the very first would have a tg://proxy link
    pointing at a port nothing is listening on — connection refused, which
    is exactly the "proxy doesn't work" symptom this was fixed for.
    Servers are opened/closed as inbounds are added/removed/reassigned,
    on the same cadence as the inbound reload loop."""
    open_servers: dict[int, asyncio.Server] = {}

    async def reconcile():
        while True:
            wanted_ports = {ib.bind_port for ib in STORE.by_secret.values()} or {MTPROTO_PORT}
            for port in wanted_ports - open_servers.keys():
                try:
                    server = await asyncio.start_server(handle_client, MTPROTO_BIND, port)
                    open_servers[port] = server
                    log.info(f"MTProto proxy (built-in engine) now listening on {MTPROTO_BIND}:{port}")
                except OSError as e:
                    log.error(f"could not bind built-in engine to port {port}: {e}")
            for port in list(open_servers.keys() - wanted_ports):
                server = open_servers.pop(port)
                server.close()
                log.info(f"MTProto proxy (built-in engine) stopped listening on {MTPROTO_BIND}:{port} (no inbound uses it anymore)")
            await asyncio.sleep(RELOAD_INTERVAL)

    log.info(f"MTProto proxy (built-in engine) starting — {len(STORE.by_secret)} secret(s) loaded from {DB_FILE}")
    await reconcile()


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


# ── Self-installing mtg (no Dockerfile needed) ─────────────────────────────
# A plain Procfile/buildpack deploy has no step that fetches mtg the way a
# Dockerfile would, but the container still has normal outbound internet
# access at runtime (Railway/Render both allow this) — so instead of
# requiring Docker, this downloads the real mtg release straight from
# GitHub the first time it's needed and runs it from there. Nothing is
# hand-rolled here: it's the actual upstream binary, just fetched at
# startup instead of at image-build time. Every failure mode (no network,
# GitHub unreachable, unexpected asset layout, binary won't execute) is
# caught and logged, and falls back to the built-in Python engine — this
# never blocks startup or crashes the app.

MTG_INSTALL_DIR = os.environ.get("MTG_INSTALL_DIR", "/tmp/luffy-mtg")
MTG_INSTALL_PATH = os.path.join(MTG_INSTALL_DIR, "mtg")
MTG_RELEASES_API = "https://api.github.com/repos/9seconds/mtg/releases/latest"
MTG_DOWNLOAD_TIMEOUT = 30


def _mtg_asset_url(release_json: dict) -> tuple[str, str] | None:
    """Picks the linux/amd64 asset from a GitHub release's asset list.
    Handles either a raw binary or a .tar.gz/.tgz/.zip archive containing
    one, since mtg's release layout isn't a stable, versioned API contract
    to hardcode against.

    Recent mtg releases ship several amd64 variants per platform (plain
    amd64, and CPU-feature-optimized amd64v2/amd64v3 builds) — picking an
    optimized one blindly risks "illegal instruction" on older/smaller
    Railway/Render instances that don't support those extensions. This
    always prefers the plain, most-compatible build; the run-then-verify
    check right after download is a second safety net either way."""
    import platform
    machine = platform.machine().lower()
    arch_tokens = ("amd64", "x86_64") if machine in ("x86_64", "amd64") else \
                  ("arm64", "aarch64") if machine in ("aarch64", "arm64") else (machine,)

    candidates = []
    for asset in release_json.get("assets", []):
        name = asset.get("name", "").lower()
        if "linux" in name and any(tok in name for tok in arch_tokens):
            candidates.append(asset)
    if not candidates:
        return None

    def is_plain_variant(name: str) -> bool:
        # Reject amd64v2/amd64v3/etc — only the unsuffixed arch name.
        return not re.search(r"(amd64|x86_64|arm64|aarch64)v\d", name)

    candidates.sort(key=lambda a: 0 if is_plain_variant(a.get("name", "").lower()) else 1)
    chosen = candidates[0]
    return chosen["name"], chosen["browser_download_url"]


def _mtg_download_and_install_sync() -> str:
    """Blocking implementation, run off the event loop via asyncio.to_thread.
    Returns the installed binary's path on success, or "" on any failure."""
    import urllib.request
    import urllib.error
    import tarfile
    import zipfile
    import stat
    import io

    try:
        os.makedirs(MTG_INSTALL_DIR, exist_ok=True)
        req = urllib.request.Request(MTG_RELEASES_API, headers={"User-Agent": "luffy-panel"})
        with urllib.request.urlopen(req, timeout=MTG_DOWNLOAD_TIMEOUT) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.warning(f"could not query GitHub for the latest mtg release (no network, or GitHub unreachable): {e}")
        return ""

    picked = _mtg_asset_url(release)
    if not picked:
        log.warning("mtg release found on GitHub, but no linux binary asset matched this host's architecture")
        return ""
    asset_name, url = picked
    tag = release.get("tag_name", "unknown")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "luffy-panel"})
        with urllib.request.urlopen(req, timeout=MTG_DOWNLOAD_TIMEOUT) as resp:
            data = resp.read()
    except Exception as e:
        log.warning(f"failed to download mtg {tag} asset {asset_name}: {e}")
        return ""

    try:
        lower = asset_name.lower()
        if lower.endswith((".tar.gz", ".tgz")):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                member = next((m for m in tf.getmembers() if m.isfile() and os.path.basename(m.name) == "mtg"), None)
                if not member:
                    log.warning(f"mtg {tag} archive {asset_name} didn't contain an 'mtg' binary")
                    return ""
                extracted = tf.extractfile(member)
                with open(MTG_INSTALL_PATH, "wb") as out:
                    out.write(extracted.read())
        elif lower.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                member = next((n for n in zf.namelist() if os.path.basename(n) == "mtg"), None)
                if not member:
                    log.warning(f"mtg {tag} archive {asset_name} didn't contain an 'mtg' binary")
                    return ""
                with open(MTG_INSTALL_PATH, "wb") as out:
                    out.write(zf.read(member))
        else:
            # raw binary asset
            with open(MTG_INSTALL_PATH, "wb") as out:
                out.write(data)
    except Exception as e:
        log.warning(f"failed to extract/save mtg {tag} from {asset_name}: {e}")
        return ""

    try:
        st = os.stat(MTG_INSTALL_PATH)
        os.chmod(MTG_INSTALL_PATH, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as e:
        log.warning(f"downloaded mtg but could not make it executable: {e}")
        return ""

    try:
        result = subprocess.run([MTG_INSTALL_PATH, "--version"], capture_output=True, timeout=10)
        if result.returncode not in (0, 1):  # some builds exit 1 on --version but still print it correctly
            log.warning(f"downloaded mtg {tag} did not run cleanly (exit {result.returncode}): {result.stderr[:200]!r}")
            return ""
    except Exception as e:
        log.warning(f"downloaded mtg {tag} but couldn't execute it ({e}) — likely wrong OS/architecture for this host")
        return ""

    log.info(f"downloaded and installed mtg {tag} ({asset_name}) to {MTG_INSTALL_PATH}")
    return MTG_INSTALL_PATH


async def ensure_mtg_binary() -> str:
    if os.path.isfile(MTG_INSTALL_PATH) and os.access(MTG_INSTALL_PATH, os.X_OK):
        return MTG_INSTALL_PATH
    try:
        return await asyncio.to_thread(_mtg_download_and_install_sync)
    except Exception as e:
        log.warning(f"unexpected error installing mtg, falling back to the built-in engine: {e}")
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
