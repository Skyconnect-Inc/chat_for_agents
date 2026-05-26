"""Long-term keypair persistence and home-directory resolution."""
import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import crypto

IDENTITY_FILE = "identity.json"


@dataclass(frozen=True)
class Identity:
    pubkey: bytes
    privkey: bytes


def home_dir() -> Path:
    p = Path(os.environ.get("CHATAGENTS_HOME") or (Path.home() / ".chatagents"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_or_create(h: Path | None = None) -> Identity:
    h = h or home_dir()
    f = h / IDENTITY_FILE
    if f.exists():
        data = json.loads(f.read_text())
        return Identity(
            pubkey=base64.b64decode(data["pubkey"]),
            privkey=base64.b64decode(data["privkey"]),
        )
    pub, priv = crypto.new_keypair()
    data = {
        "pubkey": base64.b64encode(pub).decode(),
        "privkey": base64.b64encode(priv).decode(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    f.write_text(json.dumps(data, indent=2))
    os.chmod(f, 0o600)
    return Identity(pubkey=pub, privkey=priv)


def fingerprint(pubkey: bytes) -> str:
    return hashlib.sha256(pubkey).hexdigest()[:12]
