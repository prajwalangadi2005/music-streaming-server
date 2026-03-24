#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  server/stream_manager.py  —  Fixed: retransmit works correctly
# ─────────────────────────────────────────────────────────────

import struct, time, threading, ssl, os, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, BASE_DIR)

from config import (CHUNK_SIZE, CHUNK_SIZE_MIN, CHUNK_SIZE_MAX,
                    ACK_TIMEOUT, MSG_ENCODING, MSG_END)
from qos_monitor import create_monitor, remove_monitor

HEADER_FORMAT  = "!II"
HEADER_SIZE    = struct.calcsize(HEADER_FORMAT)
SEQ_EOF        = 0xFFFFFFFF
MAX_RETRANSMIT = 5


class StreamManager:
    def __init__(self, conn, client_id):
        self.conn        = conn
        self.client_id   = client_id
        self.tag         = f"[Stream #{client_id}]"
        self.chunk_size  = CHUNK_SIZE
        self.paused      = False
        self.stopped     = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.monitor     = None

    def send_chunk(self, seq_num, data):
        try:
            header = struct.pack(HEADER_FORMAT, seq_num, len(data))
            self.conn.sendall(header + data)
            return True
        except (ssl.SSLError, OSError, BrokenPipeError) as e:
            print(f"{self.tag} Send error: {e}")
            return False

    def send_eof(self):
        try:
            self.conn.sendall(struct.pack(HEADER_FORMAT, SEQ_EOF, 0))
            print(f"{self.tag} EOF sent")
        except (ssl.SSLError, OSError):
            pass

    def recv_ack(self):
        """
        Wait for ACK with SHORT timeout.
        Returns seq_num or -1 on timeout.
        """
        # Use short timeout so retransmit happens quickly
        self.conn.settimeout(2.0)
        buffer = b""
        try:
            while True:
                byte = self.conn.recv(1)
                if not byte:
                    return (-1, 0)
                if byte == b"\n":
                    break
                buffer += byte
                if len(buffer) > 256:
                    return (-1, 0)

            line  = buffer.decode(MSG_ENCODING, errors="ignore").strip()
            parts = line.split()

            if parts and parts[0].upper() == "ACK" and len(parts) >= 2:
                try:
                    return (int(parts[1]),
                            float(parts[2]) if len(parts) > 2 else time.time())
                except ValueError:
                    return (-1, 0)

            if line.upper().startswith("BUFFER_LOW"):
                new_size = min(int(self.chunk_size * 1.25), CHUNK_SIZE_MAX)
                self.chunk_size = new_size
                if self.monitor:
                    self.monitor.record_underrun()
                return (-5, 0)

            return (-1, 0)

        except (ssl.SSLError, OSError):
            # Timeout — will trigger retransmit
            return (-1, 0)
        finally:
            self.conn.settimeout(None)

    def adapt_on_rtt(self, rtt):
        if rtt > 0.5:
            new_size = max(int(self.chunk_size * 0.75), CHUNK_SIZE_MIN)
            if new_size != self.chunk_size:
                print(f"{self.tag} High RTT {rtt:.2f}s → "
                      f"chunk {self.chunk_size}→{new_size}")
                self.chunk_size = new_size

    def stream_file(self, filepath):
        if not os.path.exists(filepath):
            print(f"{self.tag} File not found: {filepath}")
            return {}

        song_title   = os.path.splitext(os.path.basename(filepath))[0]
        self.monitor = create_monitor(self.client_id, song_title)
        file_size    = os.path.getsize(filepath)
        seq_num      = 0
        stream_ok    = True

        print(f"{self.tag} Streaming: {song_title} ({file_size//1024} KB)")

        try:
            with open(filepath, "rb") as f:
                while not self.stopped:

                    if self.paused:
                        self.pause_event.wait()
                        if self.stopped:
                            break

                    data = f.read(self.chunk_size)
                    if not data:
                        break

                    # ── Send with retransmit ──────────────────
                    delivered = False
                    for attempt in range(MAX_RETRANSMIT):
                        if self.stopped:
                            break

                        if not self.send_chunk(seq_num, data):
                            stream_ok = False
                            break

                        send_time       = time.time()
                        ack_seq, ack_ts = self.recv_ack()

                        if ack_seq == seq_num:
                            # ✅ ACK received correctly
                            ack_time = time.time()
                            self.monitor.record_chunk(
                                seq_num, len(data), send_time, ack_time)
                            self.adapt_on_rtt(ack_time - send_time)
                            delivered = True
                            break

                        elif ack_seq == -1:
                            # Timeout — retransmit same chunk
                            self.monitor.record_retransmit()
                            print(f"{self.tag} Timeout seq={seq_num} "
                                  f"— retransmitting {attempt+1}/{MAX_RETRANSMIT}")
                            # Small delay before retry
                            time.sleep(0.1)
                            continue

                        elif ack_seq == -3:
                            print(f"{self.tag} Connection lost")
                            stream_ok = False
                            self.stopped = True
                            break

                        else:
                            # Wrong ACK or BUFFER_LOW — retry
                            continue

                    if not delivered:
                        print(f"{self.tag} Moving past seq={seq_num} "
                              f"after {MAX_RETRANSMIT} attempts")

                    if not stream_ok or self.stopped:
                        break

                    seq_num    += 1
                    time.sleep(0.001)

        except Exception as e:
            print(f"{self.tag} Stream error: {e}")
        finally:
            if not self.stopped:
                self.send_eof()
            self.monitor.print_summary()
            self.monitor.export_csv()
            remove_monitor(self.client_id)

        return self.monitor.summary()

    def pause(self):
        self.paused = True
        self.pause_event.clear()

    def resume(self):
        self.paused = False
        self.pause_event.set()

    def stop(self):
        self.stopped = True
        self.pause_event.set()