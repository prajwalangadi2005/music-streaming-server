#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  server/client_handler.py  —  Step 5: Robust error handling
#
#  Fixes added:
#    - Invalid input validation on all commands
#    - Abrupt disconnect detection and cleanup
#    - SSL error recovery
#    - Partial failure handling mid-stream
# ─────────────────────────────────────────────────────────────

import ssl, json, threading, time, sys, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, BASE_DIR)

from config import MSG_ENCODING, MSG_END
from song_library   import get_song_catalog, get_song_by_id, get_song_path
from stream_manager import StreamManager

# Max allowed command length — prevents buffer overflow attacks
MAX_CMD_LEN = 256


class ClientHandler:
    def __init__(self, conn, addr, client_id):
        self.conn           = conn
        self.addr           = addr
        self.client_id      = client_id
        self.running        = True
        self.streaming      = False
        self.tag            = f"[Client #{client_id} | {addr[0]}:{addr[1]}]"
        self.stream_manager = None

    def send(self, message):
        try:
            self.conn.sendall((message + MSG_END).encode(MSG_ENCODING))
        except (BrokenPipeError, ssl.SSLError, OSError) as e:
            print(f"{self.tag} Send error: {e}")
            self.running = False

    def recv_line(self):
        """
        Read one command line — with fixes:
          - MAX_CMD_LEN prevents oversized input
          - Returns None on any socket/SSL error
          - Returns None on abrupt disconnect
        """
        buffer = b""
        try:
            while True:
                byte = self.conn.recv(1)
                if not byte:
                    return None   # client disconnected cleanly
                if byte == b"\n":
                    return buffer.decode(MSG_ENCODING).strip()
                buffer += byte
                # ── Fix: reject oversized commands ───────────
                if len(buffer) > MAX_CMD_LEN:
                    print(f"{self.tag} Command too long — discarding")
                    return ""
        except ssl.SSLError as e:
            print(f"{self.tag} SSL error in recv: {e}")
            return None
        except (OSError, ConnectionResetError) as e:
            print(f"{self.tag} Connection reset: {e}")
            return None
        except UnicodeDecodeError:
            print(f"{self.tag} Invalid encoding — skipping")
            return ""

    def handle_list(self):
        try:
            catalog = get_song_catalog()
            self.send(json.dumps({
                "status" : "OK",
                "command": "SONGS",
                "songs"  : catalog
            }))
            print(f"{self.tag} LIST → {len(catalog)} song(s)")
        except Exception as e:
            print(f"{self.tag} LIST error: {e}")
            self.send(json.dumps({
                "status" : "ERROR",
                "message": "Failed to retrieve song list."
            }))

    def handle_play(self, parts):
        # ── Input validation ──────────────────────────────────
        if len(parts) < 2:
            self.send(json.dumps({
                "status" : "ERROR",
                "message": "Usage: PLAY <song_id>  (e.g. PLAY 1)"
            }))
            return

        if not parts[1].isdigit():
            self.send(json.dumps({
                "status" : "ERROR",
                "message": f"Invalid song ID '{parts[1]}' — must be a number."
            }))
            return

        song_id  = int(parts[1])
        song     = get_song_by_id(song_id)
        filepath = get_song_path(song_id)

        if not song:
            self.send(json.dumps({
                "status" : "ERROR",
                "message": f"Song ID {song_id} not found. Use LIST to see available songs."
            }))
            return

        # ── File existence check ──────────────────────────────
        if not filepath or not os.path.exists(filepath):
            self.send(json.dumps({
                "status" : "ERROR",
                "message": f"Audio file missing for '{song['title']}'."
            }))
            print(f"{self.tag} File missing: {filepath}")
            return

        # Stop any existing stream cleanly
        if self.stream_manager:
            try:
                self.stream_manager.stop()
            except Exception as e:
                print(f"{self.tag} Error stopping previous stream: {e}")

        # Acknowledge
        self.send(json.dumps({
            "status" : "OK",
            "command": "PLAYING",
            "song"   : song,
            "message": f"Streaming: {song['title']}"
        }))
        print(f"{self.tag} PLAY → '{song['title']}'")

        # Stream — this blocks until done
        self.stream_manager = StreamManager(self.conn, self.client_id)
        self.streaming = True
        try:
            stats = self.stream_manager.stream_file(filepath)
            if stats:
                print(f"{self.tag} Stream complete | "
                      f"{stats.get('throughput_kbps', 0)} KB/s | "
                      f"Retransmits: {stats.get('retransmits', 0)}")
        except ssl.SSLError as e:
            print(f"{self.tag} SSL error during stream: {e}")
        except (OSError, BrokenPipeError) as e:
            print(f"{self.tag} Connection lost during stream: {e}")
        except Exception as e:
            print(f"{self.tag} Stream error: {e}")
        finally:
            self.streaming      = False
            self.stream_manager = None

    def handle_quit(self):
        if self.stream_manager:
            try:
                self.stream_manager.stop()
            except Exception:
                pass
        self.send(json.dumps({
            "status" : "OK",
            "command": "BYE",
            "message": "Goodbye!"
        }))
        print(f"{self.tag} QUIT")
        self.running = False

    def handle_unknown(self, cmd):
        self.send(json.dumps({
            "status" : "ERROR",
            "message": f"Unknown command '{cmd}'. Available: LIST, PLAY <id>, QUIT"
        }))
        print(f"{self.tag} Unknown command: '{cmd}'")

    def run(self):
        print(f"{self.tag} Session started")
        try:
            self.send(json.dumps({
                "status" : "OK",
                "command": "WELCOME",
                "message": "Welcome! Type LIST to see songs."
            }))
        except Exception as e:
            print(f"{self.tag} Failed to send welcome: {e}")
            return

        while self.running:
            if self.streaming:
                time.sleep(0.1)
                continue

            line = self.recv_line()

            # ── Abrupt disconnect ─────────────────────────────
            if line is None:
                print(f"{self.tag} Abrupt disconnect detected")
                if self.stream_manager:
                    try:
                        self.stream_manager.stop()
                    except Exception:
                        pass
                break

            if not line:
                continue

            # ── Parse and dispatch ────────────────────────────
            try:
                parts = line.strip().split()
                cmd   = parts[0].upper() if parts else ""

                if   cmd == "LIST": self.handle_list()
                elif cmd == "PLAY": self.handle_play(parts)
                elif cmd == "QUIT": self.handle_quit()
                else:               self.handle_unknown(cmd)

            except Exception as e:
                print(f"{self.tag} Command handler error: {e}")
                try:
                    self.send(json.dumps({
                        "status" : "ERROR",
                        "message": "Server error processing command."
                    }))
                except Exception:
                    break

        print(f"{self.tag} Session ended")