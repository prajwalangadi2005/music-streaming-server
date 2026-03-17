# ─────────────────────────────────────────────────────────────
#  server/qos_monitor.py  —  Step 4: QoS Metrics Collection
#
#  Tracks per-client:
#    - Latency (RTT per chunk)
#    - Throughput (KB/s)
#    - Buffer underruns
#    - Packet retransmits
#  Exports results to CSV and prints live dashboard
# ─────────────────────────────────────────────────────────────

import csv
import os
import sys
import time
import threading
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)


class QoSMonitor:
    def __init__(self, client_id: int, song_title: str = "Unknown"):
        self.client_id   = client_id
        self.song_title  = song_title
        self.start_time  = time.time()
        self.lock        = threading.Lock()

        # Per-chunk metrics
        self.latencies      = []   # RTT per chunk in seconds
        self.chunk_sizes    = []   # bytes per chunk
        self.timestamps     = []   # send time of each chunk

        # Session counters
        self.total_chunks   = 0
        self.total_bytes    = 0
        self.retransmits    = 0
        self.underruns      = 0
        self.chunks_lost    = 0

    # ── Record events ─────────────────────────────────────────

    def record_chunk(self, seq_num: int, chunk_size: int,
                     send_time: float, ack_time: float):
        """Record one chunk's delivery metrics."""
        rtt = ack_time - send_time
        with self.lock:
            self.latencies.append(rtt)
            self.chunk_sizes.append(chunk_size)
            self.timestamps.append(send_time)
            self.total_chunks += 1
            self.total_bytes  += chunk_size

    def record_retransmit(self):
        with self.lock:
            self.retransmits += 1

    def record_underrun(self):
        with self.lock:
            self.underruns += 1

    # ── Computed metrics ──────────────────────────────────────

    def avg_latency_ms(self) -> float:
        with self.lock:
            if not self.latencies:
                return 0.0
            return round(sum(self.latencies) / len(self.latencies) * 1000, 2)

    def max_latency_ms(self) -> float:
        with self.lock:
            if not self.latencies:
                return 0.0
            return round(max(self.latencies) * 1000, 2)

    def throughput_kbps(self) -> float:
        elapsed = time.time() - self.start_time
        with self.lock:
            if elapsed <= 0:
                return 0.0
            return round((self.total_bytes / 1024) / elapsed, 2)

    def elapsed_sec(self) -> float:
        return round(time.time() - self.start_time, 2)

    def summary(self) -> dict:
        return {
            "client_id"       : self.client_id,
            "song"            : self.song_title,
            "total_chunks"    : self.total_chunks,
            "total_kb"        : round(self.total_bytes / 1024, 1),
            "avg_latency_ms"  : self.avg_latency_ms(),
            "max_latency_ms"  : self.max_latency_ms(),
            "throughput_kbps" : self.throughput_kbps(),
            "retransmits"     : self.retransmits,
            "underruns"       : self.underruns,
            "duration_sec"    : self.elapsed_sec(),
        }

    def print_summary(self):
        s = self.summary()
        print(f"\n{'='*50}")
        print(f"  QoS REPORT — Client #{self.client_id}")
        print(f"{'='*50}")
        print(f"  Song           : {s['song']}")
        print(f"  Duration       : {s['duration_sec']} sec")
        print(f"  Total Data     : {s['total_kb']} KB  ({s['total_chunks']} chunks)")
        print(f"  Throughput     : {s['throughput_kbps']} KB/s")
        print(f"  Avg Latency    : {s['avg_latency_ms']} ms")
        print(f"  Max Latency    : {s['max_latency_ms']} ms")
        print(f"  Retransmits    : {s['retransmits']}")
        print(f"  Buffer Underruns: {s['underruns']}")
        print(f"{'='*50}\n")

    # ── CSV Export ────────────────────────────────────────────

    def export_csv(self, output_dir: str = None):
        """
        Export per-chunk metrics to CSV file.
        Creates: qos_client<id>_<timestamp>.csv
        """
        if output_dir is None:
            output_dir = ROOT_DIR

        os.makedirs(output_dir, exist_ok=True)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(output_dir, f"qos_client{self.client_id}_{ts}.csv")

        with self.lock:
            latencies  = list(self.latencies)
            chunk_sizes = list(self.chunk_sizes)
            timestamps  = list(self.timestamps)

        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["seq_num", "send_time", "chunk_size_bytes",
                             "latency_ms", "throughput_kbps_instant"])
            running_bytes = 0
            for i, (lat, size, ts_val) in enumerate(
                    zip(latencies, chunk_sizes, timestamps)):
                running_bytes += size
                elapsed = ts_val - timestamps[0] if timestamps else 0
                instant_tput = round((running_bytes / 1024) / elapsed, 2) \
                               if elapsed > 0 else 0
                writer.writerow([
                    i,
                    round(ts_val, 4),
                    size,
                    round(lat * 1000, 2),
                    instant_tput
                ])

        print(f"[QoS] CSV exported → {filename}")
        return filename


# ── Global registry of active monitors ───────────────────────
_monitors      = {}
_monitors_lock = threading.Lock()


def create_monitor(client_id: int, song_title: str = "Unknown") -> QoSMonitor:
    monitor = QoSMonitor(client_id, song_title)
    with _monitors_lock:
        _monitors[client_id] = monitor
    return monitor


def get_monitor(client_id: int):
    with _monitors_lock:
        return _monitors.get(client_id)


def remove_monitor(client_id: int):
    with _monitors_lock:
        _monitors.pop(client_id, None)


def print_all_summaries():
    with _monitors_lock:
        monitors = list(_monitors.values())
    for m in monitors:
        m.print_summary()
