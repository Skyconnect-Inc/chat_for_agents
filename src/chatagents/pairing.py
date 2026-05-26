"""Multi-peer pairings persistence.

One identity, many peers. Each peer is a file at ~/.chatagents/pairings/<name>.json.
"""
import base64
import json
import os
import re
from pathlib import Path
from typing import TypedDict

from . import identity

PAIRINGS_DIR = "pairings"
LEGACY_FILE = "pairing.json"
_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


class Peer(TypedDict, total=False):
    name: str
    relay: str
    room_id: str
    room_token: str
    peer_pubkey: str | None
    my_role: str
    cursor: str | None


class NoPeersError(Exception):
    pass


class AmbiguousPeerError(Exception):
    pass


class UnknownPeerError(Exception):
    pass


# ---------- storage ----------

def _dir(h: Path | None = None) -> Path:
    d = (h or identity.home_dir()) / PAIRINGS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    if not _NAME_RE.fullmatch(name):
        raise ValueError(
            f"invalid peer name {name!r} (allowed: letters, digits, ._- ; ≤64 chars)"
        )
    return name


def _peer_path(name: str, h: Path | None = None) -> Path:
    return _dir(h) / f"{_safe_name(name)}.json"


def _migrate_legacy(h: Path | None = None) -> None:
    home = h or identity.home_dir()
    legacy = home / LEGACY_FILE
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text())
    except Exception:
        legacy.unlink()
        return
    if data.get("peer_pubkey"):
        fp = identity.fingerprint(base64.b64decode(data["peer_pubkey"]))
        name = f"peer_{fp[:6]}"
    else:
        name = "default"
    data["name"] = name
    save_peer(data, h)
    legacy.unlink()


def list_peers(h: Path | None = None) -> list[Peer]:
    _migrate_legacy(h)
    out: list[Peer] = []
    for f in sorted(_dir(h).glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            continue
    return out


def load_peer(name: str, h: Path | None = None) -> Peer | None:
    _migrate_legacy(h)
    p = _peer_path(name, h)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_peer(peer: Peer, h: Path | None = None) -> None:
    if "name" not in peer:
        raise ValueError("peer must include 'name'")
    p = _peer_path(peer["name"], h)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(peer, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(p)  # atomic on POSIX


def remove_peer(name: str, h: Path | None = None) -> bool:
    p = _peer_path(name, h)
    if p.exists():
        p.unlink()
        return True
    return False


def name_exists(name: str, h: Path | None = None) -> bool:
    return _peer_path(name, h).exists()


def resolve(name: str | None, h: Path | None = None) -> Peer:
    """Look up a peer by name, or return the sole peer if name is None."""
    if name is not None:
        p = load_peer(name, h)
        if p is None:
            raise UnknownPeerError(name)
        return p
    peers = list_peers(h)
    if not peers:
        raise NoPeersError("no peers — run `chatagents pair <invite>` first")
    if len(peers) > 1:
        names = ", ".join(p["name"] for p in peers)
        raise AmbiguousPeerError(
            f"multiple peers ({names}) — specify one with --to/--from/peer="
        )
    return peers[0]
