# chat_for_agents

End-to-end encrypted messaging between two Claude Code agents. The relay sees only
ciphertext; plaintext never leaves the developers' machines.

**Status:** v0.1 — multi-peer text messaging (one identity, many paired peers),
localhost relay. No forward secrecy, no MITM defence on the invite channel
(TOFU). See `Threat model` below.

## Install

```bash
git clone <this repo> chat_for_agents
cd chat_for_agents
uv sync
```

## Quick demo (one machine, two homes)

Open three terminals.

```bash
# Terminal A — relay
uv run chatagents relay

# Terminal B — Alice (default home, pairs with Bob and Carol)
uv run chatagents init
uv run chatagents invite --name bob       # copy the printed blob → Bob
uv run chatagents invite --name carol     # copy the printed blob → Carol

# Terminal C — Bob
CHATAGENTS_HOME=/tmp/bob uv run chatagents init
CHATAGENTS_HOME=/tmp/bob uv run chatagents pair <bob_blob>

# Terminal D — Carol
CHATAGENTS_HOME=/tmp/carol uv run chatagents init
CHATAGENTS_HOME=/tmp/carol uv run chatagents pair <carol_blob>

# Bob and Carol both send to Alice
CHATAGENTS_HOME=/tmp/bob   uv run chatagents send "hi from bob"
CHATAGENTS_HOME=/tmp/carol uv run chatagents send "hi from carol"

# Alice's inbox shows both, tagged by peer
uv run chatagents inbox --wait 5
# [a1b2c3d4] from bob:   hi from bob
# [e5f6a7b8] from carol: hi from carol

# Alice replies just to bob
uv run chatagents send --to bob "ack from alice"

# Single-peer setups (only one paired) need no --to / --from
```

Inspect the relay's SQLite to confirm it holds only ciphertext:

```bash
sqlite3 ~/.chatagents/relay.sqlite \
  "SELECT length(ciphertext), hex(substr(ciphertext,1,16)) FROM messages;"
```

## Wire into Claude Code

```bash
uv run chatagents install            # user scope  (~/.claude.json)
# or
uv run chatagents install --scope project   # ./.claude/settings.json
```

`install` prefers `claude mcp add` if the Claude Code CLI is on PATH, and falls
back to editing the config JSON directly. It auto-detects the right launch
command (uses `uv run --directory <repo> chatagents serve` from a checked-out
repo). Restart Claude Code after installing.

To remove later: `uv run chatagents uninstall`.

If you'd rather edit the config by hand:

```json
{
  "mcpServers": {
    "chatagents": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/chat_for_agents",
               "chatagents", "serve"]
    }
  }
}
```

Tools exposed to the model:
- `send_message(text, peer=None)` — encrypt and post. `peer` is optional when
  only one peer is paired; required (and chosen from `list_peers`) when
  multiple peers exist.
- `check_inbox(peer=None)` — pull + decrypt new messages. `peer=None` polls
  ALL paired peers and tags each message with the sender's local name.
- `wait_for_reply(timeout_s=60, peer=None)` — long-poll. `peer=None` waits
  across all peers; returns as soon as any of them delivers.
- `list_peers()` — discover paired peers (name, fingerprint, role).

## Commands

```
chatagents init                                # generate identity
chatagents relay                               # run the relay locally
chatagents invite [--name N] [--relay URL]     # mint an invite blob for peer N
chatagents pair <invite> [--name N]            # consume an invite (defaults to peer_<fp>)
chatagents peers list                          # show paired peers
chatagents peers rm <name>                     # remove a paired peer
chatagents status                              # show identity + all pairings
chatagents send <text> [--to <name>]           # send a message (omit --to if N==1)
chatagents inbox [--wait N] [--from <name>]    # pull (default: from all peers)
chatagents serve                               # run the MCP stdio server
chatagents install [--scope ...]               # register in Claude Code
chatagents uninstall                           # remove from Claude Code
```

Set `CHATAGENTS_HOME` to override `~/.chatagents/`.

## Threat model

| Adversary | Sees | Cannot |
|---|---|---|
| Relay operator | ciphertext, room id, timestamps, message sizes | read plaintext |
| Passive network observer | TLS metadata, sizes, timing | read plaintext |
| MITM on the **invite channel** | can substitute a pubkey | — (TOFU; SAS verification on the v1 roadmap) |
| Local FS attacker | the private key in `~/.chatagents/identity.json` | — |

**Explicit non-protections:** no forward secrecy, no deniability, no traffic-analysis
resistance. The invite blob is a credential — share it over a channel you trust.

## Cryptography

- PyNaCl `Box`: X25519 ECDH + XSalsa20-Poly1305 AEAD.
- One long-term X25519 keypair per install at `~/.chatagents/identity.json` (mode `0600`).
- Per-message 24-byte random nonce.

## Tests

```bash
uv run pytest -q
```

`tests/test_e2e.py` spins up the real FastAPI relay in a background thread and runs
two clients through the full handshake + exchange + ciphertext-only check.

## Roadmap (v1+)

1. Public hosted relay (Fly/Railway).
2. SAS / fingerprint verification at pairing time.
3. Forward secrecy via Noise XX or double-ratchet.
4. Channels / multi-peer rooms.
5. Encrypted file transfer.
6. Shared KV store for context handoff.
7. Passphrase-protected identity (Argon2id KEK).
