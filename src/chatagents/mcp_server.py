"""MCP stdio server exposing send_message, check_inbox, wait_for_reply, list_peers."""
import base64
import time
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import identity, messaging, pairing

WAIT_CAP_SECONDS = 300

INSTRUCTIONS = """\
chatagents lets you exchange end-to-end encrypted text messages with a paired
peer — another human-operated Claude Code agent on a different machine. The
relay only sees ciphertext.

Full cycle:
  1. Pair (one-time per peer). Pairing is a shell command, NOT an MCP tool —
     run `chatagents pair <8-char-code>` via Bash with the invite the peer
     gave you, or `chatagents invite` to mint one for them.
  2. Discover: call list_peers() if you don't already know the local name.
  3. Send: send_message(text, peer=<name>). Omit `peer` when exactly one
     peer is paired.
  4. Monitor: IMMEDIATELY after every send_message, call
     wait_for_reply(timeout_s=300, peer=<name>). If it returns
     {"timed_out": true}, call it again. Keep looping until a reply arrives
     or the user explicitly tells you to stop.
  5. On reply: surface it to the user (tagged with the peer name), decide
     whether to respond. If yes, send_message and go back to step 4. If no,
     stay in wait_for_reply — the peer may have more to say.

Keep the conversation alive. Once a chat is open it is a standing
commitment — monitor constantly until the user explicitly stops it. You
ARE allowed to do other work for the user in between; you are NOT allowed
to silently forget the conversation:

  - When the user is actively waiting on a reply, stay inside
    wait_for_reply and surface messages the moment they land.
  - When the user gives you other work mid-chat, do it — but every turn
    start by draining new messages with check_inbox(), surface them, and
    resume wait_for_reply as soon as you're free.
  - Do NOT sleep-poll check_inbox in a loop; long-polling via
    wait_for_reply is what costs you nothing.

The only exits from the standing commitment: the user says to stop or
close the chat, a hard error, or the peer clearly ended the conversation.

The peer is a real person's agent, not a tool you control. Don't share
secrets, credentials, or private data unless the local user explicitly
authorized it.
"""

server = FastMCP("chatagents", instructions=INSTRUCTIONS)


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
