# run_once_generate_certs.py
from OpenSSL import crypto
import os

os.makedirs("certs", exist_ok=True)

key = crypto.PKey()
key.generate_key(crypto.TYPE_RSA, 2048)

cert = crypto.X509()
cert.get_subject().CN = "localhost"
cert.set_serial_number(1)
cert.gmtime_adj_notBefore(0)
cert.gmtime_adj_notAfter(365 * 24 * 60 * 60)
cert.set_issuer(cert.get_subject())
cert.set_pubkey(key)
cert.sign(key, "sha256")

with open("certs/server.crt", "wb") as f:
    f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
with open("certs/server.key", "wb") as f:
    f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))

print("[✓] certs/server.crt and certs/server.key created!")