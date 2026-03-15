# 🎵 Online Music Streaming Server
**Socket Programming Mini Project — Python · TCP · SSL/TLS**

---

## Project Structure
```
music_streaming/
├── config.py                 # Shared constants (host, port, paths)
├── generate_certs.sh         # One-time SSL certificate generator
├── server/
│   └── server.py             # TCP + SSL server (Step 1)
├── client/
│   └── client.py             # TCP + SSL client (Step 1)
├── certs/                    # Auto-created by generate_certs.sh
│   ├── server.crt
│   └── server.key
└── songs/                    # Place .mp3 / .wav files here
```

---

## Step 1 — Setup & Run

### 1. Prerequisites
```bash
python3 --version    # needs 3.8+
openssl version      # needs to be installed
pip install pygame   # for audio playback (used in later steps)
```

### 2. Generate SSL Certificates (run once)
```bash
cd music_streaming/
bash generate_certs.sh
```
You should see:
```
[✓] Certificate generated successfully!
    Key  → ./certs/server.key
    Cert → ./certs/server.crt
```

### 3. Start the Server
```bash
# From music_streaming/ directory
python3 server/server.py
```
Expected output:
```
=======================================================
  MUSIC STREAMING SERVER — Step 1 (TCP + SSL)
=======================================================
[SSL] Context created — TLS 1.2+ enforced
[SSL] Certificate : certs/server.crt
[TCP] Socket created  → AF_INET / SOCK_STREAM
[TCP] Bound to        → localhost:8443
[TCP] Listening       → backlog=5
[SERVER] Ready — waiting for connections on localhost:8443
```

### 4. Run the Client (in a new terminal)
```bash
# From music_streaming/ directory
python3 client/client.py "Hello Server!"
```
Expected output:
```
[SSL] Handshake done  → TLSv1.3
[SSL] Cipher          → ('TLS_AES_256_GCM_SHA384', 'TLSv1.3', 256)
[CLIENT] Sent         → 'Hello Server!'
[CLIENT] Received     → 'SERVER: Hello localhost:XXXXX! You said: Hello Server!'
```

---

## What Step 1 Demonstrates (Rubric)

| Rubric Component | What's shown |
|---|---|
| Core Implementation | `socket()`, `bind()`, `listen()`, `accept()`, `connect()` |
| SSL/TLS | `SSLContext`, `wrap_socket()`, cert verification, TLS 1.2+ |
| Protocol Design | Client sends message → server echoes response |
| Error Handling | SSL errors, connection refused, abrupt disconnect |

---

## Next Steps
- **Step 2** — Multi-client threading + command protocol (LIST, PLAY, QUIT)
- **Step 3** — Audio chunking + ACK-based streaming
- **Step 4** — Buffer management + adaptive bitrate
- **Step 5** — QoS monitoring + performance tests
