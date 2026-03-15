#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  client/buffer_manager.py  —  Step 3: Audio Buffer
#
#  Manages a thread-safe queue of audio chunks.
#  Producer: network receiver thread pushes chunks in
#  Consumer: audio player thread pulls chunks out
#
#  Features:
#    - Pre-buffering: waits for N chunks before playback starts
#    - Underrun detection: signals server when buffer is low
#    - Thread-safe using threading.Lock + threading.Event
# ─────────────────────────────────────────────────────────────

import threading
import time
import ssl
import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import PRE_BUFFER_COUNT, MSG_ENCODING, MSG_END


class BufferManager:
    def __init__(self, conn: ssl.SSLSocket, max_size: int = 50):
        self.conn          = conn          # socket — for sending ACK / BUFFER_LOW
        self.max_size      = max_size      # max chunks to hold in buffer
        self.buffer        = deque()       # the actual chunk queue
        self.lock          = threading.Lock()
        self.not_empty     = threading.Event()  # signals when buffer has data
        self.pre_buffered  = threading.Event()  # signals pre-buffer complete
        self.finished      = False         # True when EOF received
        self.stopped       = False         # True when user stops

        # Stats
        self.total_chunks  = 0
        self.underruns     = 0

    # ── Producer side (called by network thread) ──────────────

    def push(self, seq_num: int, data: bytes):
        """Add a chunk to the buffer and send ACK to server."""
        with self.lock:
            self.buffer.append((seq_num, data))
            self.total_chunks += 1

        # Signal that buffer now has data
        self.not_empty.set()

        # Signal pre-buffer complete once we have enough chunks
        if self.total_chunks >= PRE_BUFFER_COUNT:
            self.pre_buffered.set()

        # Send ACK back to server with timestamp
        self._send_ack(seq_num)

        # Check if buffer is running low — warn server
        fill_pct = self.fill_percent()
        if fill_pct < 30 and self.total_chunks > PRE_BUFFER_COUNT:
            self._send_buffer_low(fill_pct)

    def set_finished(self):
        """Called when EOF marker is received."""
        self.finished = True
        self.pre_buffered.set()   # unblock player even if pre-buffer not full
        self.not_empty.set()

    # ── Consumer side (called by audio player thread) ─────────

    def pop(self, timeout: float = 2.0):
        """
        Get next chunk from buffer.
        Blocks until data is available or timeout.
        Returns (seq_num, data) or None on timeout/stop.
        """
        deadline = time.time() + timeout
        while not self.stopped:
            with self.lock:
                if self.buffer:
                    chunk = self.buffer.popleft()
                    if not self.buffer:
                        self.not_empty.clear()
                    return chunk

            # Buffer empty
            if self.finished:
                return None   # EOF and nothing left

            # Underrun — buffer ran dry during playback
            self.underruns += 1
            print(f"[Buffer] UNDERRUN #{self.underruns} — waiting for data...")

            # Wait for new data
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self.not_empty.wait(timeout=remaining)

        return None

    def wait_for_prebuffer(self):
        """Block until enough chunks are buffered to start playback."""
        print(f"[Buffer] Pre-buffering {PRE_BUFFER_COUNT} chunks...")
        self.pre_buffered.wait()
        print(f"[Buffer] Pre-buffer ready — starting playback")

    def stop(self):
        """Signal buffer to stop — unblocks any waiting threads."""
        self.stopped = True
        self.not_empty.set()
        self.pre_buffered.set()

    def clear(self):
        """Drain the buffer (used on STOP/SEEK)."""
        with self.lock:
            self.buffer.clear()
        self.not_empty.clear()

    # ── Stats ─────────────────────────────────────────────────

    def fill_percent(self) -> int:
        """Return buffer fullness as 0-100%."""
        with self.lock:
            size = len(self.buffer)
        return min(int((size / self.max_size) * 100), 100)

    def size(self) -> int:
        with self.lock:
            return len(self.buffer)

    # ── Socket helpers ────────────────────────────────────────

    def _send_ack(self, seq_num: int):
        """Send ACK <seq> <timestamp> to server."""
        try:
            msg = f"ACK {seq_num} {time.time()}{MSG_END}"
            self.conn.sendall(msg.encode(MSG_ENCODING))
        except (ssl.SSLError, OSError):
            pass

    def _send_buffer_low(self, fill_pct: int):
        """Notify server that buffer is running low."""
        try:
            msg = f"BUFFER_LOW {fill_pct}{MSG_END}"
            self.conn.sendall(msg.encode(MSG_ENCODING))
        except (ssl.SSLError, OSError):
            pass
