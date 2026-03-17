
import socket, ssl, json, struct, threading, io, time, sys, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, BASE_DIR)

from config import HOST, PORT, SERVER_CERT, MSG_ENCODING, MSG_END

HEADER_FORMAT = "!II"
HEADER_SIZE   = struct.calcsize(HEADER_FORMAT)
SEQ_EOF       = 0xFFFFFFFF

# Use absolute path for cert
CERT_PATH = os.path.join(ROOT_DIR, SERVER_CERT)

try:
    import pygame
    PYGAME_OK = True
except ImportError:
    PYGAME_OK = False


def create_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(cafile=CERT_PATH)
    ctx.check_hostname = False
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

def send_ack(sock, seq_num):
    try:
        sock.sendall(f"ACK {seq_num} {time.time()}{MSG_END}".encode(MSG_ENCODING))
    except OSError:
        pass

def receive_and_play(sock, song_title):
    audio_buf = io.BytesIO()
    chunks    = 0
    print(f"\n[Stream] Receiving '{song_title}'...")
    print(f"[Stream] Please wait...\n")

    while True:
        try:
            header = recv_exact(sock, HEADER_SIZE)
        except ConnectionError:
            print("[Stream] Connection lost.")
            return
        seq_num, data_len = struct.unpack(HEADER_FORMAT, header)
        if seq_num == SEQ_EOF:
            total_kb = audio_buf.tell() // 1024
            print(f"\n[Stream] Complete! {chunks} chunks, {total_kb} KB received.")
            break
        if data_len > 0:
            try:
                data = recv_exact(sock, data_len)
            except ConnectionError:
                return
            audio_buf.write(data)
            chunks += 1
            send_ack(sock, seq_num)
            if chunks % 100 == 0:
                print(f"[Stream] {chunks} chunks ({audio_buf.tell()//1024} KB)...")

    audio_buf.seek(0)
    if not PYGAME_OK:
        _save_audio(audio_buf, song_title)
        return

    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
        pygame.mixer.music.load(audio_buf)
        pygame.mixer.music.play()
        print(f"[Audio] ▶  Playing '{song_title}'")
        print(f"[Audio] Press Enter to stop...\n")

        stop_event = threading.Event()

        def wait_enter():
            try:
                input()
            except Exception:
                pass
            stop_event.set()

        def watch_pygame():
            while pygame.mixer.music.get_busy():
                if stop_event.is_set():
                    return
                time.sleep(0.3)
            stop_event.set()

        t1 = threading.Thread(target=wait_enter,   daemon=True)
        t2 = threading.Thread(target=watch_pygame, daemon=True)
        t1.start()
        t2.start()
        stop_event.wait()
        pygame.mixer.music.stop()
        print("\n[Audio] ■  Stopped.\n")

    except Exception as e:
        print(f"[Audio] Error: {e}")
        audio_buf.seek(0)
        _save_audio(audio_buf, song_title)

def _save_audio(audio_buf, title="audio"):
    audio_buf.seek(0)
    out = "received_audio.mp3"
    with open(out, "wb") as f:
        f.write(audio_buf.read())
    print(f"[Audio] Saved to '{out}' — open to listen!\n")

def pretty_response(raw):
    try:
        data = json.loads(raw)
        cmd  = data.get("command", "")
        if data.get("status") == "ERROR":
            print(f"\n  [!] {data.get('message', raw)}")
        elif cmd == "WELCOME":
            print(f"\n  [OK] {data.get('message')}")
        elif cmd == "SONGS":
            songs = data.get("songs", [])
            if not songs:
                print(f"\n  [i] No songs found. Add .mp3/.wav to songs/ folder.")
            else:
                print(f"\n  {'ID':<5} {'Title':<40} {'Size':>8}")
                print(f"  {'-'*5} {'-'*40} {'-'*8}")
                for s in songs:
                    print(f"  {s['id']:<5} {s['title']:<40} {str(s['size_kb'])+' KB':>8}")
                print()
        elif cmd == "PLAYING":
            print(f"\n  [PLAY] {data.get('message')}")
        elif cmd == "BYE":
            print(f"  [OK] {data.get('message')}")
        else:
            print(f"  Server: {raw}")
        return cmd
    except json.JSONDecodeError:
        print(f"  Server: {raw}")
        return ""

def print_help():
    print("""
  Commands:
    list          - Show available songs
    play <id>     - Stream a song  (e.g. play 1)
    quit          - Disconnect
    help          - Show this help
    """)

def run_client():
    print("=" * 55)
    print("  MUSIC STREAMING CLIENT — Step 3")
    print("=" * 55)

    ssl_ctx  = create_ssl_context()
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ssl_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=HOST)

    try:
        print(f"[TCP]  Connecting to {HOST}:{PORT} ...")
        ssl_sock.connect((HOST, PORT))
        print(f"[SSL]  {ssl_sock.version()}  |  {ssl_sock.cipher()[0]}\n")

        welcome = recv_line(ssl_sock)
        if welcome:
            pretty_response(welcome)
        print_help()

        while True:
            try:
                user_input = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                send_cmd(ssl_sock, "QUIT")
                break

            if not user_input:
                continue
            cmd_upper = user_input.upper().split()[0]
            if cmd_upper == "HELP":
                print_help()
                continue

            send_cmd(ssl_sock, user_input)
            response = recv_line(ssl_sock)
            if response is None:
                print("[CLIENT] Server disconnected.")
                break

            returned_cmd = pretty_response(response)

            if returned_cmd == "PLAYING":
                try:
                    title = json.loads(response).get("song", {}).get("title", "Unknown")
                except Exception:
                    title = "Unknown"
                receive_and_play(ssl_sock, title)

            if cmd_upper == "QUIT":
                break

    except ConnectionRefusedError:
        print(f"[ERROR] Cannot connect — is server running on {HOST}:{PORT}?")
        print(f"[HINT]  Run:  python server/server.py  (in a separate terminal)")
    except ssl.SSLError as e:
        print(f"[ERROR] SSL: {e}")
    finally:
        ssl_sock.close()
        print("[CLIENT] Disconnected.")

if __name__ == "__main__":
    run_client()
