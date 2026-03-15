#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  server/stream_manager.py  —  Step 5: Robust streaming
#
#  Fixes added:
#    - Max retransmit attempts before giving up
#    - Handles partial send (sendall may split)
#    - SSL error recovery mid-stream
#    - Clean EOF even on error
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
MAX_RETRANSMIT = 3   # give up after this many failed attempts


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
        """Send chunk with error handling for partial sends."""
        try:
            header = struct.pack(HEADER_FORMAT, seq_num, len(data))
            self.conn.sendall(header + data)   # sendall handles partial sends
            return True
        except ssl.SSLError as e:
            print(f"{self.tag} SSL send error: {e}")
            return False
        except (OSError, BrokenPipeError) as e:
            print(f"{self.tag} Send error: {e}")
            return False

    def send_eof(self):
        """Always try to send EOF — even on error paths."""
        try:
            self.conn.sendall(struct.pack(HEADER_FORMAT, SEQ_EOF, 0))
            print(f"{self.tag} EOF sent")
        except (ssl.SSLError, OSError):
            print(f"{self.tag} Could not send EOF — client may have disconnected")

    def recv_ack(self):
        """
        Wait for ACK with timeout.
        Handles: normal ACK, BUFFER_LOW, invalid data, timeout.
        """
        self.conn.settimeout(ACK_TIMEOUT)
        buffer = b""
        try:
            while True:
                byte = self.conn.recv(1)
                if not byte:
                    return (-1, 0)
                if byte == b"\n":
                    break
                buffer += byte
                if len(buffer) > 256:   # prevent runaway buffer
                    return (-1, 0)

            line = buffer.decode(MSG_ENCODING, errors="ignore").strip()

            if not line:
                return (-1, 0)

            parts = line.split()
            if parts[0].upper() == "ACK" and len(parts) >= 2:
                try:
                    seq = int(parts[1])
                    ts  = float(parts[2]) if len(parts) > 2 else time.time()
                    return (seq, ts)
                except ValueError:
                    return (-1, 0)

            if line.upper().startswith("BUFFER_LOW"):
                new_size = min(int(self.chunk_size * 1.25), CHUNK_SIZE_MAX)
                print(f"{self.tag} BUFFER_LOW → chunk {self.chunk_size}→{new_size}")
                self.chunk_size = new_size
                if self.monitor:
                    self.monitor.record_underrun()
                return (-5, 0)

            return (-1, 0)

        except ssl.SSLError:
            return (-1, 0)   # timeout or SSL error
        except (OSError, ConnectionResetError):
            return (-3, 0)   # connection lost
        finally:
            self.conn.settimeout(None)

    def adapt_on_rtt(self, rtt):
        """Reduce chunk size when network is slow."""
        if rtt > 0.5:
            new_size = max(int(self.chunk_size * 0.75), CHUNK_SIZE_MIN)
            if new_size != self.chunk_size:
                print(f"{self.tag} High RTT {rtt:.2f}s → chunk {self.chunk_size}→{new_size}")
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

                    # ── Pause handling ────────────────────────
                    if self.paused:
                        print(f"{self.tag} Paused — waiting for RESUME...")
                        self.pause_event.wait()
                        if self.stopped:
                            break
                        print(f"{self.tag} Resumed")

                    data = f.read(self.chunk_size)
                    if not data:
                        break   # EOF — file finished

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
                            # ✅ Delivered successfully
                            ack_time = time.time()
                            self.monitor.record_chunk(
                                seq_num, len(data), send_time, ack_time)
                            self.adapt_on_rtt(ack_time - send_time)
                            delivered = True
                            break

                        elif ack_seq == -3:
                            # Connection lost
                            print(f"{self.tag} Connection lost at seq={seq_num}")
                            stream_ok = False
                            self.stopped = True
                            break

                        elif ack_seq == -1:
                            # Timeout — retransmit
                            self.monitor.record_retransmit()
                            print(f"{self.tag} Timeout seq={seq_num} "
                                  f"attempt {attempt+1}/{MAX_RETRANSMIT}")

                        elif ack_seq == -5:
                            # BUFFER_LOW — retry same chunk
                            continue

                    if not delivered and not self.stopped:
                        print(f"{self.tag} Giving up on seq={seq_num} "
                              f"after {MAX_RETRANSMIT} attempts")

                    if not stream_ok or self.stopped:
                        break

                    seq_num    += 1
                    time.sleep(0.001)

        except FileNotFoundError:
            print(f"{self.tag} File disappeared mid-stream: {filepath}")
        except Exception as e:
            print(f"{self.tag} Unexpected stream error: {e}")
        finally:
            # Always try to send EOF
            if not self.stopped:
                self.send_eof()

            # Print QoS report and export CSV
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