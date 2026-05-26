"""MCP stdio server exposing send_message, check_inbox, wait_for_reply, list_peers."""
import base64
import time
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import identity, messaging, pairing

WAIT_CAP_SECONDS = 300

server = FastMCP("chatagents")


@server.tool()
def send_message(text: str, peer: Optional[str] = None) -> dict:
    """Send a text message to a paired developer's Claude Code agent.

    If you have exactly one paired peer, `peer` may be omitted. If you have
    multiple peers, pass `peer=<name>` to choose the recipient — use
    `list_peers` to discover the available local names.

    Messages are end-to-end encrypted, but they go to a real human-operated
    peer. Do not include secrets unless the operator confirmed.
    """
    return messaging.send_text(text, peer=peer)


@server.tool()
def check_inbox(peer: Optional[str] = None) -> dict:
    """Pull and decrypt any new messages.

    If `peer` is omitted, polls ALL paired peers and returns their messages
    together. Each message includes a `peer` field naming the local nickname
    of the sender. Non-blocking.
    """
    return {"messages": messaging.receive(peer=peer, wait=0)}


@server.tool()
def wait_for_reply(timeout_s: int = 60, peer: Optional[str] = None) -> dict:
    """Long-poll for a new message.

    If `peer` is omitted, waits for any new message from any paired peer.
    Returns {"messages": [...]} once one arrives, or {"timed_out": true}
    after timeout_s seconds (max 300).
    """
    deadline = time.monotonic() + max(1, min(timeout_s, WAIT_CAP_SECONDS))
    while time.monotonic() < deadline:
        remaining = int(deadline - time.monotonic())
        msgs = messaging.receive(peer=peer, wait=min(max(remaining, 1), 30))
        if msgs:
            return {"messages": msgs}
    return {"timed_out": True}


@server.tool()
def list_peers() -> dict:
    """List currently paired peers (local name, fingerprint, role)."""
    out = []
    for p in pairing.list_peers():
        peer_fp = (
            identity.fingerprint(base64.b64decode(p["peer_pubkey"]))
            if p.get("peer_pubkey")
            else None
        )
        out.append({"name": p["name"], "fingerprint": peer_fp, "role": p["my_role"]})
    return {"peers": out}


def run_stdio() -> None:
    server.run()
