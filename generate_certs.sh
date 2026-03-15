#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  generate_certs.sh
#  Generates a self-signed SSL certificate for the music server
#  Run once before starting the server: bash generate_certs.sh
# ─────────────────────────────────────────────────────────────

CERT_DIR="./certs"
KEY_FILE="$CERT_DIR/server.key"
CERT_FILE="$CERT_DIR/server.crt"

echo "[*] Creating certs/ directory..."
mkdir -p "$CERT_DIR"

echo "[*] Generating self-signed certificate (valid 365 days)..."
openssl req -x509 -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -days 365 \
    -nodes \
    -subj "/C=IN/ST=Karnataka/L=Bengaluru/O=MusicStreamServer/CN=localhost"

if [ $? -eq 0 ]; then
    echo ""
    echo "[✓] Certificate generated successfully!"
    echo "    Key  → $KEY_FILE"
    echo "    Cert → $CERT_FILE"
    echo ""
    echo "[*] Certificate details:"
    openssl x509 -in "$CERT_FILE" -noout -subject -dates
else
    echo "[✗] Certificate generation failed. Is openssl installed?"
    exit 1
fi
