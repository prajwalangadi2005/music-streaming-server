#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  tests/test_concurrent.py  —  Step 4: Performance Testing
#
#  Spins up N simultaneous clients, each requests song ID 1.
#  Measures: connection time, download time, throughput.
#  Saves results to concurrent_test_results.csv
#
#  Usage:
#    python tests/test_concurrent.py          (default: 3 clients)
#    python tests/test_concurrent.py 5        (5 clients)
# ─────────────────────────────────────────────────────────────

import socket
import ssl
import struct
import threading
import time
import csv
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)

from config import HOST, PORT, SERVER_CERT, MSG_ENCODING, MSG_END

HEADER_FORMAT = "!II"
HEADER_SIZE   = struct.calcsize(HEADER_FORMAT)
SEQ_EOF       = 0xFFFFFFFF
CERT_PATH     = os.path.join(ROOT_DIR, SERVER_CERT)


def create_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(cafile=CERT_PATH)
    ctx.check_hostname = True
    ctx.verify_mode    = ssl.CERT_REQUIRED
    return ctx


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Socket closed")
        data += chunk
    return data


def recv_line(sock):
    buf = b""
    while True:
        byte = sock.recv(1)
        if not byte:
            return None
        if byte == b"\n":
            return buf.decode(MSG_ENCODING).strip()
        buf += byte


def send_cmd(sock, cmd):
    sock.sendall((cmd + MSG_END).encode(MSG_ENCODING))


def run_test_client(client_num: int, song_id: int, results: list,
                    start_barrier: threading.Barrier):
    """
    Single test client — connects, requests song, measures performance.
    All clients start simultaneously using a Barrier.
    """
    result = {
        "client_num"      : client_num,
        "connect_time_ms" : 0,
        "total_chunks"    : 0,
        "total_kb"        : 0,
        "download_time_s" : 0,
        "throughput_kbps" : 0,
        "status"          : "FAIL"
    }

    ssl_ctx  = create_ssl_context()
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ssl_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=HOST)

    try:
        # Connect and measure time
        t_connect = time.time()
        ssl_sock.connect((HOST, PORT))
        result["connect_time_ms"] = round((time.time() - t_connect) * 1000, 2)

        # Read welcome
        recv_line(ssl_sock)

        # ── Wait for all clients to be ready, then start together ──
        print(f"  [Client {client_num}] Connected — waiting at barrier...")
        start_barrier.wait()
        print(f"  [Client {client_num}] GO!")

        # Send PLAY
        send_cmd(ssl_sock, f"PLAY {song_id}")
        response = recv_line(ssl_sock)
        if not response or '"PLAYING"' not in response:
            print(f"  [Client {client_num}] Bad response: {response}")
            return

        # Receive all chunks and measure
        t_start  = time.time()
        chunks   = 0
        total_bytes = 0

        while True:
            header = recv_exact(ssl_sock, HEADER_SIZE)
            seq_num, data_len = struct.unpack(HEADER_FORMAT, header)

            if seq_num == SEQ_EOF:
                break

            if data_len > 0:
                data = recv_exact(ssl_sock, data_len)
                total_bytes += len(data)
                chunks      += 1
                # Send ACK
                ssl_sock.sendall(
                    f"ACK {seq_num} {time.time()}{MSG_END}".encode(MSG_ENCODING)
                )

        elapsed = time.time() - t_start

        result["total_chunks"]    = chunks
        result["total_kb"]        = round(total_bytes / 1024, 1)
        result["download_time_s"] = round(elapsed, 2)
        result["throughput_kbps"] = round((total_bytes / 1024) / elapsed, 2) \
                                    if elapsed > 0 else 0
        result["status"]          = "OK"

        send_cmd(ssl_sock, "QUIT")
        print(f"  [Client {client_num}] Done — "
              f"{result['total_kb']} KB in {result['download_time_s']}s "
              f"({result['throughput_kbps']} KB/s)")

    except Exception as e:
        print(f"  [Client {client_num}] Error: {e}")
        result["status"] = f"ERROR: {e}"
    finally:
        ssl_sock.close()
        results.append(result)


def save_results(results: list, num_clients: int):
    """Save test results to CSV."""
    ts       = time.strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(ROOT_DIR, f"concurrent_test_{num_clients}clients_{ts}.csv")

    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"\n[Test] Results saved → {filename}")
    return filename


def print_results(results: list):
    """Print a summary table of all client results."""
    print(f"\n{'='*65}")
    print(f"  CONCURRENT TEST RESULTS — {len(results)} clients")
    print(f"{'='*65}")
    print(f"  {'Client':<8} {'Status':<8} {'KB':>8} {'Time(s)':>8} "
          f"{'KB/s':>10} {'Connect(ms)':>12}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*12}")

    ok_results = [r for r in results if r["status"] == "OK"]

    for r in sorted(results, key=lambda x: x["client_num"]):
        print(f"  {r['client_num']:<8} {r['status']:<8} "
              f"{r['total_kb']:>8} {r['download_time_s']:>8} "
              f"{r['throughput_kbps']:>10} {r['connect_time_ms']:>12}")

    if ok_results:
        avg_tput = sum(r["throughput_kbps"] for r in ok_results) / len(ok_results)
        avg_time = sum(r["download_time_s"] for r in ok_results) / len(ok_results)
        print(f"\n  Avg Throughput : {round(avg_tput, 2)} KB/s per client")
        print(f"  Avg Download   : {round(avg_time, 2)} sec")
        print(f"  Success Rate   : {len(ok_results)}/{len(results)} clients")
    print(f"{'='*65}\n")


def run_concurrent_test(num_clients: int = 3, song_id: int = 1):
    print(f"\n{'='*65}")
    print(f"  CONCURRENT CLIENT TEST — {num_clients} simultaneous clients")
    print(f"  Server: {HOST}:{PORT}  |  Song ID: {song_id}")
    print(f"{'='*65}\n")

    results = []
    threads = []

    # Barrier ensures all clients start at exactly the same time
    barrier = threading.Barrier(num_clients)

    for i in range(1, num_clients + 1):
        t = threading.Thread(
            target=run_test_client,
            args=(i, song_id, results, barrier),
            name=f"TestClient-{i}"
        )
        threads.append(t)

    print(f"[Test] Starting {num_clients} clients simultaneously...\n")
    t_total_start = time.time()

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    total_time = round(time.time() - t_total_start, 2)
    print(f"\n[Test] All clients finished in {total_time}s")

    print_results(results)
    if results:
        save_results(results, num_clients)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_concurrent_test(num_clients=n, song_id=1)
