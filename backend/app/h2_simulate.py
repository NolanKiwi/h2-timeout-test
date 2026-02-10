#!/usr/bin/env python3
import sys
import argparse
import time
import socket
import ssl
import h2.connection
import h2.events
import h2.config
import h2.exceptions

# --- Logger Setup ---
def log(msg):
    sys.stdout.write(f"[INFO] {time.strftime('%H:%M:%S')} {msg}\n")
    sys.stdout.flush()

def log_err(msg):
    sys.stderr.write(f"[ERR] {time.strftime('%H:%M:%S')} {msg}\n")
    sys.stderr.flush()

# --- Argument Parsing ---
parser = argparse.ArgumentParser(description="HTTP/2 Flow Control Delay Simulator")
parser.add_argument("--host", required=True, help="Domain for TLS SNI and :authority")
parser.add_argument("--ip", help="Specific IP to connect to (optional)")
parser.add_argument("--port", type=int, default=443, help="Port (default: 443)")
parser.add_argument("--path", default="/", help="Path to request")
parser.add_argument("--range", default="bytes=0-", help="Range header value")
parser.add_argument("--delay", type=float, default=0.0, help="Delay WINDOW_UPDATE in seconds")
parser.add_argument("--start-after-bytes", type=int, default=0, help="Byte threshold to start delay")
parser.add_argument("--ping-interval", type=float, default=0.0, help="PING interval (0=disabled)")

args = parser.parse_args()

HOST = args.host
IP = args.ip if args.ip else HOST # If IP is not provided, resolve HOST later
PORT = args.port
PATH = args.path
RANGE = args.range
DELAY = args.delay
START_AFTER = args.start_after_bytes
PING_INTERVAL = args.ping_interval

# --- HTTP/2 Logic ---

def main():
    log(f"Starting H2 Client against {HOST} ({IP}):{PORT}{PATH}")
    log(f"Range: {RANGE}, Delay: {DELAY}s after {START_AFTER} bytes")

    # 1. Establish TCP Connection
    try:
        sock = socket.create_connection((IP, PORT), timeout=10)
    except Exception as e:
        log_err(f"Failed to connect to {IP}:{PORT}: {e}")
        return

    # 2. Upgrade to TLS (ALPN h2)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False # We might be connecting to a direct IP
    ctx.verify_mode = ssl.CERT_NONE # For testing purposes, disable verification if IP mismatches SNI
    ctx.set_alpn_protocols(['h2'])

    try:
        sock = ctx.wrap_socket(sock, server_hostname=HOST)
    except Exception as e:
        log_err(f"TLS Handshake failed: {e}")
        return

    if sock.selected_alpn_protocol() != "h2":
        log_err("Server did not negotiate h2 ALPN")
        return

    log("TLS Handshake successful. ALPN: h2")

    # 3. Initialize H2 Connection
    config = h2.config.H2Configuration(client_side=True)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    sock.sendall(conn.data_to_send())

    # 4. Send Request Headers
    headers = [
        (':method', 'GET'),
        (':authority', HOST),
        (':scheme', 'https'),
        (':path', PATH),
        ('range', RANGE),
        ('user-agent', 'h2-timeout-test/1.0'),
    ]
    stream_id = conn.get_next_available_stream_id()
    conn.send_headers(stream_id, headers)
    sock.sendall(conn.data_to_send())
    log(f"Sent Headers on Stream {stream_id}")

    # 5. Receive Loop
    bytes_received = 0
    delay_triggered = False
    
    last_ping_time = time.time()
    
    start_time = time.time()
    
    try:
        while True:
            # PING Check
            if PING_INTERVAL > 0 and (time.time() - last_ping_time) >= PING_INTERVAL:
                conn.ping(b'12345678') # Opaque data 8 bytes
                sock.sendall(conn.data_to_send())
                log("Sent PING")
                last_ping_time = time.time()

            # Read Data
            try:
                # Non-blocking read or short timeout
                sock.settimeout(0.1) 
                data = sock.recv(65535)
                if not data:
                    log("Connection closed by server")
                    break
            except socket.timeout:
                continue # Loop back for PING check
            except Exception as e:
                log_err(f"Socket error: {e}")
                break

            # Process H2 Events
            events = conn.receive_data(data)
            
            for event in events:
                if isinstance(event, h2.events.ResponseReceived):
                    log(f"Response Received: {event.headers}")
                elif isinstance(event, h2.events.DataReceived):
                    chunk_len = len(event.data)
                    bytes_received += chunk_len
                    # log(f"Received {chunk_len} bytes. Total: {bytes_received}")
                    
                    # Acknowledge data (Window Update) logic
                    if not delay_triggered and bytes_received >= START_AFTER:
                         if DELAY > 0:
                             log(f"Threshold reached ({bytes_received} >= {START_AFTER}). Delaying WINDOW_UPDATE for {DELAY}s...")
                             time.sleep(DELAY)
                             log("Resuming... Sending accumulated WINDOW_UPDATE")
                             delay_triggered = True # Trigger only once
                    
                    conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    
                elif isinstance(event, h2.events.StreamEnded):
                    log("Stream Ended")
                    sock.sendall(conn.data_to_send())
                    conn.close_connection()
                    sock.sendall(conn.data_to_send())
                    sock.close()
                    return
                elif isinstance(event, h2.events.PingReceived):
                    log("Received PING from server")
                elif isinstance(event, h2.events.ConnectionTerminated):
                    log_err(f"Connection Terminated: {event.error_code} - {event.additional_data}")
                    return

            # Send any pending frames (e.g. WINDOW_UPDATE, PING ACK)
            data_to_send = conn.data_to_send()
            if data_to_send:
                sock.sendall(data_to_send)

    except KeyboardInterrupt:
        log("Interrupted by user")
    finally:
        sock.close()
        log(f"Finished. Total Bytes: {bytes_received}. Duration: {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    main()
