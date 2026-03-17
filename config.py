# ─────────────────────────────────────────────────────────────
#  config.py  —  Shared configuration for server and client
# ─────────────────────────────────────────────────────────────

# Network
HOST = "0.0.0.0"
PORT = 8443

# SSL
SERVER_CERT = "certs/server.crt"
SERVER_KEY  = "certs/server.key"

# Streaming
CHUNK_SIZE       = 4096   # bytes per audio chunk (default)
CHUNK_SIZE_MIN   = 1024   # adaptive lower bound
CHUNK_SIZE_MAX   = 16384  # adaptive upper bound
PRE_BUFFER_COUNT = 5      # chunks to buffer before playback starts
ACK_TIMEOUT      = 5.0    # seconds to wait for ACK before retransmit

# Protocol delimiters
MSG_ENCODING = "utf-8"
MSG_END      = "\n"       # control messages are newline-terminated

# Songs directory
SONGS_DIR = "songs"
