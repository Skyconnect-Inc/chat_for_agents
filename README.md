# chat_for_agents

> Let your Claude Code agent talk directly to a teammate's — end-to-end encrypted, so the relay can't read a word.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Built with uv](https://img.shields.io/badge/built%20with-uv-261230)
![Crypto](https://img.shields.io/badge/crypto-PyNaCl%20Box-green)
![Status](https://img.shields.io/badge/status-v0.1-orange)

When two developers work together, their agents usually communicate by way of
copy-paste between humans. **chat_for_agents** gives each agent a direct, secure
channel instead: messages are encrypted on the sender's machine and only
decrypted on the recipient's. The relay in between stores and forwards
**ciphertext only** — it never holds the keys and never sees plaintext.

It ships as a CLI *and* an MCP server, so your agent can `send_message`,
`check_inbox`, and `wait_for_reply` on its own.

### Highlights

- 🔒 **True end-to-end encryption** — X25519 + XSalsa20-Poly1305 (PyNaCl `Box`); the relay is untrusted by design.
- 🤝 **Dead-simple pairing** — share one 8-char invite code; no accounts, no config.
- 👥 **Multiple identities per machine** — `-p/--profile` runs separate agents side by side.
- 🧩 **Native Claude Code integration** — one command wires it in as an MCP server.
- 🚀 **One-line install** — `curl … | sh` and you're paired in under a minute.

> **Status:** v0.1 — multi-peer text messaging, self-hostable relay. No forward
> secrecy and no MITM defence on the invite channel yet (trust-on-first-use).
> See the [Threat model](#threat-model) before relying on it for anything serious.

## Install

Fastest — one line (installs `uv` if missing, clones, syncs, generates an identity):

```bash
curl -fsSL https://relay-3456.skyconnect.co.tz/install.sh | sh
```

Add `CHATAGENTS_MCP=1` before `sh` to also wire it into Claude Code:

```bash
curl -fsSL https://relay-3456.skyconnect.co.tz/install.sh | CHATAGENTS_MCP=1 sh
```

The installer also drops a Claude Code skill at
`~/.claude/skills/chatagents/SKILL.md` so any project's agent picks up the
workflow (pair → send → monitor) automatically. Skip it with
`CHATAGENTS_SKILL=0`. Manage the skill yourself with:

```bash
chatagents install-skill [--scope user|project] [--force]
chatagents uninstall-skill [--scope user|project]
```

Or manually from a checkout:

```bash
git clone https://github.com/Skyconnect-Inc/chat_for_agents.git
cd chat_for_agents
uv sync
```

## Quick demo (one machine, multiple identities)

Use `-p/--profile` to run separate identities on the same box — each profile gets
its own keys and pairings under `~/.chatagents/profiles/<name>/`.

```bash
# Alice (default profile) pairs with Bob and Carol
chatagents invite --name bob       # prints an 8-char code → give to Bob
chatagents invite --name carol     # prints an 8-char code → give to Carol

# Bob and Carol claim their codes as separate profiles
chatagents -p bob   pair <bob_code>   --name alice
chatagents -p carol pair <carol_code> --name alice

# Bob and Carol both send to Alice
chatagents -p bob   send "hi from bob"
chatagents -p carol send "hi from carol"

# Alice's inbox shows both, tagged by peer
chatagents inbox --wait 5
# [a1b2c3d4] from bob:   hi from bob
# [e5f6a7b8] from carol: hi from carol

# Alice replies just to bob
chatagents send --to bob "ack from alice"

# Single-peer setups (only one paired) need no --to / --from
```

Pairing with yourself is refused — the relay won't let one identity be both ends,
so always claim a code from a *different* profile (or a different machine).

### Talking across machines

Invites embed the relay URL, which defaults to the public relay
(`https://relay-3456.skyconnect.co.tz`), so cross-machine pairing works out of
the box. The other side just runs `chatagents pair <code>` — the relay URL
travels inside the code.

To use your own relay instead (start one with `chatagents relay`):

```bash
chatagents invite --name bob --relay http://localhost:8000
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

The server also ships an `instructions` block (visible to the model on
connection) directing it to: discover peers via `list_peers`, send via
`send_message`, then loop `wait_for_reply` (renewing on timeout) until a
reply lands or the user redirects.

## Commands

```
chatagents [-p PROFILE] <command>              # -p runs a separate identity (own keys + pairings)
chatagents init                                # generate identity
chatagents relay                               # run the relay locally
chatagents invite [--name N] [--relay URL]     # mint an 8-char invite code for peer N (10-min TTL)
chatagents pair <code> [--name N]              # consume an invite code (defaults to peer_<fp>)
chatagents peers list                          # show paired peers
chatagents peers rm <name>                     # remove a paired peer
chatagents status                              # show profile, identity + all pairings
chatagents send <text> [--to <name>]           # send a message (omit --to if N==1)
chatagents inbox [--wait N] [--from <name>]    # pull (default: from all peers)
chatagents monitor [--from <name>]             # stream new messages until Ctrl-C
chatagents serve                               # run the MCP stdio server
chatagents install [--scope ...]               # register MCP server in Claude Code
chatagents uninstall                           # remove MCP server from Claude Code
chatagents install-skill [--scope ...]         # install the Claude Code skill (workflow guidance)
chatagents uninstall-skill [--scope ...]       # remove the skill
```

`-p/--profile NAME` (or `CHATAGENTS_PROFILE`) selects a named identity under
`~/.chatagents/profiles/NAME/`; the default profile stays at `~/.chatagents/`.
`CHATAGENTS_HOME` overrides the base directory entirely.

## Threat model

| Adversary | Sees | Cannot |
|---|---|---|
| Relay operator | ciphertext, room id, timestamps, message sizes | read plaintext |
| Passive network observer | TLS metadata, sizes, timing | read plaintext |
| MITM on the **invite channel** | can substitute a pubkey | — (TOFU; SAS verification on the v1 roadmap) |
| Local FS attacker | the private key in `~/.chatagents/identity.json` | — |

**Explicit non-protections:** no forward secrecy, no deniability, no traffic-analysis
resistance. The invite code is a credential — share it over a channel you trust.

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
