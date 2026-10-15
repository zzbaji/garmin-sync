"""AES-256-GCM titkosítás a nyilvános repóba kerülő fájlokhoz.
Fájlformátum: 12 bájt nonce + titkosított adat (GCM taggel)."""
import base64, hashlib, hmac, os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key(b64: str) -> bytes:
    k = base64.b64decode(b64.strip())
    if len(k) != 32:
        raise ValueError("A kulcsnak 32 bájtosnak kell lennie (openssl rand -base64 32)")
    return k


def encrypt(b64key: str, data: bytes) -> bytes:
    n = os.urandom(12)
    return n + AESGCM(_key(b64key)).encrypt(n, data, None)


def decrypt(b64key: str, blob: bytes) -> bytes:
    return AESGCM(_key(b64key)).decrypt(blob[:12], blob[12:], None)


def opaque_name(b64key: str, ident: str) -> str:
    """Kívülről értelmezhetetlen, de determinisztikus fájlnév."""
    return hmac.new(_key(b64key), ident.encode(), hashlib.sha256).hexdigest()[:20]


def write_if_changed(b64key: str, path: Path, data: bytes) -> bool:
    """Csak akkor ír, ha a tartalom változott (a véletlen nonce miatt
    különben minden futás új commitot okozna)."""
    if path.exists():
        try:
            if decrypt(b64key, path.read_bytes()) == data:
                return False
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt(b64key, data))
    return True
