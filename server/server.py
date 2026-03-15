#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  server/server.py  —  Step 5: Optimized + Edge Cases Fixed
#
#  Fixes added:
#    - SSL handshake timeout (prevents hanging connections)
#    - Max clients limit (prevents server overload)
#    - Graceful shutdown closes all active streams
#    - Detailed error logging per client
# ─────────────────────────────────────────────────────────────   

import socket, ssl, sys, os, threading, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, BASE_DIR)

from config import HOST, PORT, SERVER_CERT, SERVER_KEY
from client_handler import ClientHandler

MAX_CLIENTS         = 10   # reject connections beyond this
active_clients      = {}
active_clients_lock = threading.Lock()
client_counter      = 0


def create_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(
        certfile=os.path.join(ROOT_DIR, SERVER_CERT),
        keyfile =os.path.join(ROOT_DIR, SERVER_KEY)
    )
    print(f"[SSL]  TLS 1.2+ enforced  |  Cert: {SERVER_CERT}")
    return ctx


def handle_client_thread(ssl_conn, addr, client_id):
    handler = ClientHandler(ssl_conn, addr, client_id)
    with active_clients_lock:
        active_clients[client_id] = handler
        print(f"[SERVER] Client #{client_id} joined  |  Active: {len(active_clients)}")
    try:
        handler.run()
    except Exception as e:
        print(f"[ERROR] Client #{client_id} crashed: {e}")
    finally:
        with active_clients_lock:
            active_clients.pop(client_id, None)
            print(f"[SERVER] Client #{client_id} left   |  Active: {len(active_clients)}")
        try:
            ssl_conn.close()
        except Exception:
            pass


def run_server():
    global client_counter
    print("=" * 55)
    print("  MUSIC STREAMING SERVER — Step 5 (Optimized)")
    print("=" * 55)

    ssl_ctx  = create_ssl_context()
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw_sock.bind((HOST, PORT))
    raw_sock.listen(10)
    print(f"[TCP]  Bound to {HOST}:{PORT}  |  Max clients: {MAX_CLIENTS}")

    server_sock = ssl_ctx.wrap_socket(raw_sock, server_side=True)
    server_sock.settimeout(1.0)

    print(f"\n[SERVER] Ready — waiting for clients on {HOST}:{PORT}")
    print("[SERVER] Press Ctrl+C to stop\n")

    try:
        while True:
            try:
                raw_conn, addr = server_sock.accept()
            except socket.timeout:
                continue
            except ssl.SSLError as e:
                print(f"[WARN]  SSL handshake failed from {addr}: {e}")
                continue

            # ── Max clients check ─────────────────────────────
            with active_clients_lock:
                current_count = len(active_clients)

            if current_count >= MAX_CLIENTS:
                print(f"[WARN]  Max clients reached ({MAX_CLIENTS}) — rejecting {addr}")
                try:
                    raw_conn.close()
                except Exception:
                    pass
                continue

            client_counter += 1
            cid = client_counter

            t = threading.Thread(
                target=handle_client_thread,
                args=(raw_conn, addr, cid),
                daemon=True,
                name=f"Client-{cid}"
            )
            t.start()
            print(f"[THREAD] Started '{t.name}'  |  {addr[0]}:{addr[1]}")

    except KeyboardInterrupt:
        print("\n[SERVER] Ctrl+C — shutting down gracefully...")
        with active_clients_lock:
            count = len(active_clients)
            for handler in active_clients.values():
                try:
                    if handler.stream_manager:
                        handler.stream_manager.stop()
                except Exception:
                    pass
        if count:
            print(f"[SERVER] Stopped {count} active stream(s)")
        time.sleep(0.5)
    finally:
        server_sock.close()
        print("[SERVER] Socket closed. Goodbye!")


if __name__ == "__main__":
    run_server()





