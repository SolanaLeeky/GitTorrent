"""AES-256-GCM encryption for chunk data.

Encrypts chunks before distributing to peers. Peers hold ciphertext
they cannot read. The key stays on the tracker (repo secret).

Usage:
    from engine.crypto import encrypt_chunk, decrypt_chunk

    key = os.environ["ENCRYPTION_KEY"]  # 32-byte hex string
    ciphertext = encrypt_chunk(plaintext_bytes, key)
    plaintext = decrypt_chunk(ciphertext, key)

Wire format: nonce (12 bytes) || tag (16 bytes) || ciphertext
All encoded as a single bytes blob, then base64'd for dispatch.
"""

from __future__ import annotations

import os
import struct
from hashlib import sha256

# Use stdlib hmac + AES via a simple XOR-CTR fallback if cryptography not installed.
# In production, `pip install cryptography` and use the real AES-GCM.
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

NONCE_SIZE = 12
TAG_SIZE = 16
KEY_SIZE = 32  # 256 bits


def _derive_key(key_hex: str) -> bytes:
    """Derive a 32-byte key from a hex string or passphrase."""
    raw = bytes.fromhex(key_hex) if len(key_hex) == 64 else sha256(key_hex.encode()).digest()
    if len(raw) != KEY_SIZE:
        raise ValueError(f"Key must be {KEY_SIZE} bytes (got {len(raw)})")
    return raw


def encrypt_chunk(data: bytes, key_hex: str) -> bytes:
    """Encrypt data with AES-256-GCM.

    Returns: nonce || tag || ciphertext (as bytes).
    """
    key = _derive_key(key_hex)

    if _HAS_CRYPTO:
        nonce = os.urandom(NONCE_SIZE)
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, data, None)  # ct includes tag
        # AESGCM.encrypt returns ciphertext+tag appended
        return nonce + ct
    else:
        # Fallback: XOR with key-derived stream (NOT production-grade)
        # This is a placeholder so the module works without `cryptography`
        nonce = os.urandom(NONCE_SIZE)
        stream = sha256(key + nonce).digest()
        # Extend stream to cover data
        full_stream = b""
        counter = 0
        while len(full_stream) < len(data):
            full_stream += sha256(key + nonce + struct.pack(">I", counter)).digest()
            counter += 1
        ct = bytes(a ^ b for a, b in zip(data, full_stream[:len(data)]))
        tag = sha256(key + nonce + ct).digest()[:TAG_SIZE]
        return nonce + tag + ct


def decrypt_chunk(blob: bytes, key_hex: str) -> bytes:
    """Decrypt data encrypted with encrypt_chunk.

    Args:
        blob: nonce || tag || ciphertext (or nonce || ciphertext+tag for cryptography lib)
        key_hex: Same key used for encryption.

    Returns: plaintext bytes.
    Raises: ValueError on authentication failure.
    """
    key = _derive_key(key_hex)

    if _HAS_CRYPTO:
        nonce = blob[:NONCE_SIZE]
        ct_with_tag = blob[NONCE_SIZE:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct_with_tag, None)
    else:
        nonce = blob[:NONCE_SIZE]
        tag = blob[NONCE_SIZE:NONCE_SIZE + TAG_SIZE]
        ct = blob[NONCE_SIZE + TAG_SIZE:]
        # Verify tag
        expected_tag = sha256(key + nonce + ct).digest()[:TAG_SIZE]
        if tag != expected_tag:
            raise ValueError("Decryption failed: authentication tag mismatch")
        # Decrypt
        full_stream = b""
        counter = 0
        while len(full_stream) < len(ct):
            full_stream += sha256(key + nonce + struct.pack(">I", counter)).digest()
            counter += 1
        return bytes(a ^ b for a, b in zip(ct, full_stream[:len(ct)]))


def is_encryption_enabled() -> bool:
    """Check if encryption is enabled in config."""
    from engine import config
    cfg = config.load_json(config.CONFIG_FILE)
    return cfg.get("encryption_enabled", False)
