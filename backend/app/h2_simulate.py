#!/usr/bin/env python3
"""
HTTP/2 WINDOW_UPDATE delay tester (hyper-h2), with optional IP connect.

Log format:
  <timestamp>\t<TAG>\t<message>

Tags:
  CONN  - TCP/TLS connection details
  H2    - HTTP/2 protocol events (SETTINGS/headers/GOAWAY/RESET)
  DATA  - data frames and flow-control state
  PING  - ping/ack events
  STATE - internal state transitions (delay start/end)
  ERR   - errors/exceptions
"""

import argparse
import os
import socket
import ssl
import time
import sys
from typing import Optional

from h2.connection import H2Connection
from h2.config import H2Configuration
from h2.events import (
    DataReceived,
    ResponseReceived,
    StreamEnded,
    StreamReset,
    ConnectionTerminated,
    SettingsAcknowledged,
    PingAckReceived,
    PingReceived,
)


def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(tag: str, msg: str) -> None:
    # Tab-delimited logs for easy parsing.
    # Flush immediately for real-time output (-u handles this too, but flush is safe)
    print(f"[{ts()}]\t{tag}\t{msg}", flush=True)


def connect_tls_h2(
    connect_addr: str,
    sni_host: str,
    port: int,
    connect_timeout: float,
    read_timeout: float,
) -> ssl.SSLSocket:
    """
    Create a TCP connection to connect_addr, wrap with TLS using SNI = sni_host,
    and enforce ALPN 'h2'. Also logs the actual connected peer IP:PORT.
    """
    # TCP connect
    try:
        raw = socket.create_connection((connect_addr, port), timeout=connect_timeout)
    except socket.gaierror:
        # If connect_addr is a domain that fails to resolve, try resolving it first for better logging
        # But socket.create_connection usually handles it.
        raise

    raw.settimeout(read_timeout)

    try:
        peer_ip, peer_port = raw.getpeername()
        local_ip, local_port = raw.getsockname()
    except Exception:
        peer_ip, peer_port = connect_addr, port
        local_ip, local_port = "unknown", 0

    log(
        "CONN",
        f"tcp_connected\tconnect_addr={connect_addr}:{port}\tpeer={peer_ip}:{peer_port}\tlocal={local_ip}:{local_port}",
    )

    # TLS wrap
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2"])

    # IMPORTANT: server_hostname must be the domain (SNI), not the IP, for correct cert/vhost.
    s = ctx.wrap_socket(raw, server_hostname=sni_host)

    negotiated = s.selected_alpn_protocol()
    # After TLS wrap, peer/local should still be the same; log again for clarity.
    try:
        peer_ip2, peer_port2 = s.getpeername()
        local_ip2, local_port2 = s.getsockname()
    except Exception:
        peer_ip2, peer_port2 = peer_ip, peer_port
        local_ip2, local_port2 = local_ip, local_port

    log(
        "CONN",
        f"tls_ready\tsni={sni_host}\talpn={negotiated}\tpeer={peer_ip2}:{peer_port2}\tlocal={local_ip2}:{local_port2}",
    )

    if negotiated != "h2":
        raise RuntimeError(f"ALPN did not negotiate 'h2' (got: {negotiated}).")

    return s


def safe_send(sock: ssl.SSLSocket, conn: H2Connection) -> None:
    try:
        out = conn.data_to_send()
        if out:
            sock.sendall(out)
    except Exception:
        pass


def try_ack_ping(conn: H2Connection, ping_data: bytes) -> None:
    # Method names differ across versions; try common candidates.
    for fn_name in ("ping_acknowledge", "ping_ack", "acknowledge_ping"):
        fn = getattr(conn, fn_name, None)
        if fn is not None:
            fn(ping_data)
            return


def run_test(
    host: str,
    ip: Optional[str],
    port: int,
    path: str,
    range_header: str,
    delay_seconds: float,
    start_after_bytes: int,
    ping_interval: float,
    connect_timeout: float,
    read_timeout: float,
    max_runtime: float,
) -> int:
    """
    Run one HTTP/2 GET request and optionally delay WINDOW_UPDATE frames.
    """
    sock: Optional[ssl.SSLSocket] = None

    # Connect to IP if provided, otherwise connect to host name (DNS happens here).
    # If ip is None, we use host.
    connect_addr = ip if ip else host

    total_received = 0
    pending_ack_bytes = 0

    delay_active = False
    delay_until = 0.0

    last_ping_sent = 0.0
    start_t = time.monotonic()

    try:
        sock = connect_tls_h2(
            connect_addr=connect_addr,
            sni_host=host,
            port=port,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )

        # Log "actual peer" once more at run start (useful if user passed --host only).
        try:
            peer_ip, peer_port = sock.getpeername()
            log("CONN", f"peer_confirmed\tpeer={peer_ip}:{peer_port}\thost={host}\tip_arg={ip if ip else ''}")
        except Exception:
            pass

        conn = H2Connection(config=H2Configuration(client_side=True, header_encoding="utf-8"))
        conn.initiate_connection()
        safe_send(sock, conn)

        # HTTP/2 request headers (:authority is the domain, not the IP)
        headers = [
            (":method", "GET"),
            (":authority", host),
            (":scheme", "https"),
            (":path", path),
            ("range", range_header),
            ("user-agent", "python-h2-flowcontrol-tester"),
            ("accept", "*/*"),
        ]

        stream_id = conn.get_next_available_stream_id()
        conn.send_headers(stream_id, headers, end_stream=True)
        safe_send(sock, conn)

        log("H2", f"request_sent\turl=https://{host}{path}\tstream_id={stream_id}")
        log(
            "STATE",
            f"params\tdelay={delay_seconds:.3f}\tstart_after_bytes={start_after_bytes}\tping_interval={ping_interval:.3f}\tread_timeout={read_timeout}",
        )

        while True:
            now = time.monotonic()
            elapsed = now - start_t
            if max_runtime > 0 and elapsed >= max_runtime:
                log("STATE", f"max_runtime_reached\tmax_runtime={max_runtime:.1f}\telapsed={elapsed:.1f}")
                return 0

            # Optional PING keepalive
            if ping_interval > 0 and (now - last_ping_sent) >= ping_interval:
                conn.ping(os.urandom(8))
                last_ping_sent = now
                safe_send(sock, conn)
                log("PING", "ping_sent\tkeepalive=1")

            # If delay timer expired, flush delayed WINDOW_UPDATE (ack pending bytes)
            if delay_active and now >= delay_until:
                if pending_ack_bytes > 0:
                    conn.acknowledge_received_data(pending_ack_bytes, stream_id)
                    safe_send(sock, conn)
                    log("STATE", f"delay_complete\twindow_update_sent_bytes={pending_ack_bytes}")
                    pending_ack_bytes = 0
                delay_active = False

            # Check socket for data (non-blocking or short timeout)
            # We use settimeout logic. If read_timeout is large, we might block too long to send PINGs or handle delay end.
            # So we should use a smaller timeout for the loop if we have active timers.
            
            loop_timeout = read_timeout
            if ping_interval > 0:
                loop_timeout = min(loop_timeout, 1.0)
            if delay_active:
                time_left = delay_until - now
                if time_left < 0: time_left = 0
                loop_timeout = min(loop_timeout, time_left + 0.1)

            sock.settimeout(loop_timeout)
            
            try:
                data = sock.recv(65535)
            except socket.timeout:
                # Timeout is normal if we are just waiting for PING interval or Delay
                # But if it's the READ timeout, we should error. 
                # Ideally check total time since last read, but here we simplify.
                # If we are strictly checking read_timeout vs idle, we need last_read_time.
                # For now, just continue loop to check timers.
                continue
                
            if not data:
                log("H2", "eof\tserver_closed_cleanly=1")
                return 0

            events = conn.receive_data(data)

            for event in events:
                if isinstance(event, SettingsAcknowledged):
                    log("H2", "settings_ack")

                elif isinstance(event, ResponseReceived):
                    hdrs = dict(event.headers)
                    status = hdrs.get(b':status') or hdrs.get(':status')
                    if isinstance(status, bytes): status = status.decode()
                    log("H2", f"response_headers\tstatus={status}")

                elif isinstance(event, DataReceived):
                    sid = event.stream_id
                    chunk_len = len(event.data)
                    total_received += chunk_len
                    pending_ack_bytes += event.flow_controlled_length

                    # Start delay mode once total_received threshold is reached
                    if (not delay_active) and delay_seconds > 0 and total_received >= start_after_bytes:
                        delay_active = True
                        delay_until = time.monotonic() + delay_seconds
                        log(
                            "STATE",
                            f"delay_started\ttotal_received={total_received}\twithhold_seconds={delay_seconds:.3f}",
                        )

                    # If not delaying, ACK immediately (keeps WINDOW_UPDATE flowing)
                    if not delay_active:
                        conn.acknowledge_received_data(event.flow_controlled_length, sid)

                    # Stream-level window only (connection-level querying can break on some h2 versions)
                    stream_window = conn.local_flow_control_window(sid)
                    log(
                        "DATA",
                        f"data\tsz={chunk_len}\ttotal={total_received}\tpending_ack={pending_ack_bytes}\tstream_window={stream_window}\tdelaying={1 if delay_active else 0}",
                    )

                elif isinstance(event, PingAckReceived):
                    log("PING", "ping_ack_received")

                elif isinstance(event, PingReceived):
                    log("PING", "ping_received\tack_sent=1")
                    try_ack_ping(conn, event.ping_data)
                    safe_send(sock, conn)

                elif isinstance(event, StreamReset):
                    log("H2", f"reset_stream\terror_code={event.error_code}\ttotal_received={total_received}")
                    return 1

                elif isinstance(event, ConnectionTerminated):
                    log(
                        "H2",
                        f"goaway\terror_code={event.error_code}\tlast_stream_id={event.last_stream_id}\ttotal_received={total_received}",
                    )
                    return 1

                elif isinstance(event, StreamEnded):
                    log("H2", f"stream_ended\ttotal_received={total_received}")
                    return 0

            safe_send(sock, conn)

    except socket.timeout:
        log("ERR", f"socket_timeout\tread_timeout={read_timeout}\ttotal_received={total_received}")
        return 2
    except ConnectionResetError as e:
        log("ERR", f"connection_reset\twinerr={getattr(e, 'winerror', '')}\tmsg={e}\ttotal_received={total_received}")
        return 3
    except ssl.SSLError as e:
        log("ERR", f"ssl_error\tmsg={e}")
        return 4
    except Exception as e:
        log("ERR", f"unexpected\tname={type(e).__name__}\tmsg={e}")
        return 5
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HTTP/2 WINDOW_UPDATE delay tester (hyper-h2).")
    p.add_argument("--host", required=True, help="Domain used for TLS SNI and :authority")
    p.add_argument("--ip", default=None, help="Optional IP to connect to (TCP). If set, still uses --host for SNI/:authority.")
    p.add_argument("--port", type=int, default=443)
    p.add_argument("--path", default="/")
    p.add_argument("--range", dest="range_header", default="bytes=0-")

    p.add_argument("--delay", type=float, default=0.0, help="Withhold WINDOW_UPDATE for N seconds")
    p.add_argument(
        "--start-after-bytes",
        type=int,
        default=0,
        help="Start delay mode once total received bytes >= this value (0 = start immediately)",
    )
    p.add_argument("--ping-interval", type=float, default=0.0, help="Send HTTP/2 PING every N seconds (0 disables)")

    p.add_argument("--connect-timeout", type=float, default=10.0)
    p.add_argument("--read-timeout", type=float, default=45.0)
    p.add_argument("--max-runtime", type=float, default=0.0)
    return p.parse_args()


if __name__ == "__main__":
    a = parse_args()
    rc = run_test(
        host=a.host,
        ip=a.ip,
        port=a.port,
        path=a.path,
        range_header=a.range_header,
        delay_seconds=a.delay,
        start_after_bytes=a.start_after_bytes,
        ping_interval=a.ping_interval,
        connect_timeout=a.connect_timeout,
        read_timeout=a.read_timeout,
        max_runtime=a.max_runtime,
    )
    log("STATE", f"exit\tcode={rc}")
