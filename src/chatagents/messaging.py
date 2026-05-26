"""Send / receive primitives shared by the CLI and the MCP server.

`peer=None` defaults to the sole pairing for `send_text`; `receive` polls all
peers when `peer=None` so a multi-peer Claude session can drain its inbox in
one call.
"""
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor

from . import crypto, identity, pairing
from .relay_client import RelayClient


class NotPairedError(Exception):
    pass


class PeerNotJoinedError(Exception):
    pass


class UnknownPeerError(Exception):
    pass


class AmbiguousPeerError(Exception):
    pass


def _resolve_one(name: str | None) -> dict:
    try:
        return pairing.resolve(name)
    except pairing.NoPeersError as e:
        raise NotPairedError(str(e)) from e
    except pairing.AmbiguousPeerError as e:
        raise AmbiguousPeerError(str(e)) from e
    except pairing.UnknownPeerError as e:
        raise UnknownPeerError(str(e)) from e


def _client_for(p: dict) -> RelayClient:
    return RelayClient(p["relay"], room_token=p["room_token"])


def _ensure_peer_pubkey(p: dict, client: RelayClient, my_pub: bytes) -> bytes:
    if p.get("peer_pubkey"):
        return base64.b64decode(p["peer_pubkey"])
    my_pub_b64 = base64.b64encode(my_pub).decode()
    others = [
        pe["pubkey"] for pe in client.list_peers(p["room_id"])
        if pe["pubkey"] != my_pub_b64
    ]
    if not others:
        raise PeerNotJoinedError("peer has not joined the room yet")
    p["peer_pubkey"] = others[0]
    pairing.save_peer(p)
    return base64.b64decode(others[0])


def send_text(text: str, peer: str | None = None) -> dict:
    p = _resolve_one(peer)
    ident = identity.load_or_create()
    client = _client_for(p)
    try:
        peer_pub = _ensure_peer_pubkey(p, client, ident.pubkey)
        payload = json.dumps(
            {"v": 1, "kind": "text", "body": text, "ts": int(time.time())}
        ).encode()
        nonce, ct = crypto.encrypt(payload, peer_pub, ident.privkey)
        resp = client.post_message(p["room_id"], ident.pubkey, nonce, ct)
        return {"peer": p["name"], **resp}
    finally:
        client.close()


def _receive_one_peer(p: dict, wait: int, ident: identity.Identity) -> list[dict]:
    client = _client_for(p)
    try:
        peer_pub = _ensure_peer_pubkey(p, client, ident.pubkey)
        my_pub_b64 = base64.b64encode(ident.pubkey).decode()
        resp = client.get_messages(p["room_id"], since=p.get("cursor"), wait=wait)
    finally:
        client.close()

    out: list[dict] = []
    for m in resp["messages"]:
        if m["from_pubkey"] == my_pub_b64:
            continue
        try:
            pt = crypto.decrypt(
                base64.b64decode(m["ciphertext"]),
                base64.b64decode(m["nonce"]),
                peer_pub,
                ident.privkey,
            )
            payload = json.loads(pt)
            out.append({
                "id": m["id"],
                "peer": p["name"],
                "from_fp": identity.fingerprint(peer_pub),
                "text": payload.get("body", ""),
                "ts": payload.get("ts"),
                "created_at": m["created_at"],
            })
        except Exception:
            out.append({
                "id": m["id"], "peer": p["name"],
                "from_fp": "?", "error": "decrypt_failed",
            })

    if resp.get("cursor"):
        p["cursor"] = resp["cursor"]
        pairing.save_peer(p)
    return out


def receive(peer: str | None = None, wait: int = 0) -> list[dict]:
    ident = identity.load_or_create()

    if peer is not None:
        return _receive_one_peer(_resolve_one(peer), wait, ident)

    peers = pairing.list_peers()
    if not peers:
        raise NotPairedError("no peers — run `chatagents pair <invite>` first")
    if len(peers) == 1:
        return _receive_one_peer(peers[0], wait, ident)

    # Multi-peer: poll all peers in parallel (non-blocking each round) until
    # any of them has messages or the wait window elapses.
    deadline = time.monotonic() + max(0, wait)
    while True:
        with ThreadPoolExecutor(max_workers=len(peers)) as ex:
            results = list(ex.map(lambda p: _receive_one_peer(p, 0, ident), peers))
        out = [m for batch in results for m in batch]
        if out or time.monotonic() >= deadline:
            return out
        time.sleep(min(1.0, max(0.1, deadline - time.monotonic())))
