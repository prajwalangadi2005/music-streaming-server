
#  client/audio_player.py  —  Step 3: Audio Playback
#
#  Pulls chunks from BufferManager and plays them using pygame.
#  Runs in its own thread so it doesn't block the command loop.
#
#  Approach:
#    - Collect ALL chunks into a BytesIO object first
#    - Once EOF received, play the complete audio
#    - This avoids pygame limitations with streaming partial MP3s


import threading
import time
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Try to import pygame 
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class AudioPlayer:
    def __init__(self, buffer_manager):
        self.buffer_manager = buffer_manager
        self.playing        = False
        self.stopped        = False
        self.play_thread    = None

        if PYGAME_AVAILABLE:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
            print("[Audio] pygame.mixer initialized")
        else:
            print("[Audio] pygame not found — audio will be saved to output.mp3 instead")
            print("[Audio] Install with:  pip install pygame")

    def start(self, file_extension: str = ".mp3"):
        """Start the playback thread."""
        self.stopped     = False
        self.file_ext    = file_extension
        self.play_thread = threading.Thread(
            target=self._playback_loop,
            daemon=True,
            name="AudioPlayer"
        )
        self.play_thread.start()

    def _playback_loop(self):
        """
        Main playback loop:
          1. Wait for pre-buffer to fill
          2. Collect all chunks into memory
          3. Play audio when EOF received
        """
        # Wait until enough chunks are buffered
        self.buffer_manager.wait_for_prebuffer()

        if self.stopped:
            return

        print("[Audio] Collecting audio chunks...")
        audio_data = io.BytesIO()
        chunks_played = 0

        # Drain buffer until EOF
        while not self.stopped:
            result = self.buffer_manager.pop(timeout=5.0)
            if result is None:
                break   # EOF or timeout
            seq_num, data = result
            audio_data.write(data)
            chunks_played += 1

            # Print progress every 50 chunks
            if chunks_played % 50 == 0:
                print(f"[Audio] Buffered {chunks_played} chunks "
                      f"({audio_data.tell()//1024} KB)...")

        if self.stopped:
            print("[Audio] Playback stopped by user")
            return

        # All chunks received — play the audio
        total_kb = audio_data.tell() // 1024
        print(f"[Audio] All chunks received ({total_kb} KB) — starting playback...")

        audio_data.seek(0)

        if PYGAME_AVAILABLE:
            self._play_with_pygame(audio_data)
        else:
            self._save_to_file(audio_data)

    def _play_with_pygame(self, audio_data: io.BytesIO):
        """Play audio using pygame.mixer."""
        try:
            self.playing = True
            pygame.mixer.music.load(audio_data)
            pygame.mixer.music.play()
            print("[Audio] ▶  Playing... (pygame)")

            # Wait until playback finishes
            while pygame.mixer.music.get_busy() and not self.stopped:
                time.sleep(0.5)

            print("[Audio] ■  Playback complete")
        except Exception as e:
            print(f"[Audio] pygame error: {e}")
            print("[Audio] Saving to output.mp3 instead...")
            audio_data.seek(0)
            self._save_to_file(audio_data)
        finally:
            self.playing = False

    def _save_to_file(self, audio_data: io.BytesIO):
        """Fallback: save received audio to file."""
        output_file = "received_audio.mp3"
        with open(output_file, "wb") as f:
            f.write(audio_data.read())
        size_kb = os.path.getsize(output_file) // 1024
        print(f"[Audio] Saved to '{output_file}' ({size_kb} KB)")
        print(f"[Audio] Open the file to listen to the song!")

    def stop(self):
        """Stop playback."""
        self.stopped = True
        if PYGAME_AVAILABLE and self.playing:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.playing = False
        print("[Audio] Stopped")

    def pause(self):
        if PYGAME_AVAILABLE and self.playing:
            pygame.mixer.music.pause()
            print("[Audio] Paused")

    def resume(self):
        if PYGAME_AVAILABLE and self.playing:
            pygame.mixer.music.unpause()
            print("[Audio] Resumed")
