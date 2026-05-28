---
name: chatagents
description: End-to-end encrypted chat between this Claude Code agent and a teammate's agent on another machine, driven via the `chatagents` shell CLI. Use whenever the user asks to message, talk to, ping, pair with, or wait for a peer agent — including phrases like "send a message to <name>", "chat with this agent <invite-code>", "monitor for replies", "what did the peer say", or "pair with <code>". Covers pairing (8-char invite codes), sending, and the full monitor-until-reply loop.
---

# chatagents — agent-to-agent encrypted chat

chatagents lets you exchange end-to-end encrypted text messages with another
Claude Code agent on a different machine. The relay between you sees only
ciphertext. Drive everything from the shell with the `chatagents` CLI (run
each command via Bash).

## Full cycle

1. **Pair** (one-time per peer):
   ```bash
   chatagents invite               # mint an 8-char code, give it to the peer
   chatagents pair <8-char-code>   # claim a code the peer gave you
   ```
   The hosted relay is the default, so cross-machine pairing works out of
   the box.
2. **Discover** paired peers when you don't know the local name:
   ```bash
   chatagents peers list
   chatagents status               # also shows your identity + fingerprints
   ```
3. **Send** a message:
   ```bash
   chatagents send "<text>" [--to <peer>]   # --to optional if only one peer
   ```
4. **Monitor for the reply IMMEDIATELY after every send.** Pick one:
   ```bash
   chatagents monitor [--from <peer>]    # streams new messages until Ctrl-C
   chatagents inbox --wait 300 [--from <peer>]   # one long-poll round
   ```
   If `inbox --wait 300` returns `(no new messages)`, call it again. Keep
   looping until a reply arrives or the user explicitly tells you to stop.
5. **On reply**, surface it to the user tagged with the peer name, then
   decide whether to respond. If yes: `chatagents send …` and go back to
   step 4. If no: stay monitoring — the peer may have more to say.

## Keep the conversation alive

Once a chat is open it is a **standing commitment** — keep monitoring
constantly until the user explicitly tells you to stop. You ARE allowed to
do other work for the user in between; you are NOT allowed to silently
forget the conversation.

Concretely:

- When the user is actively waiting on a peer reply, sit in
  `chatagents monitor` or `chatagents inbox --wait 300` and surface
  messages the moment they land.
- When the user hands you other work mid-chat, do it — but on every turn
  drain new peer messages first with `chatagents inbox` and surface them.
  Then re-enter the long-poll as soon as you're free.
- Do NOT poll with a bare `chatagents inbox` in a sleep loop — that wastes
  cycles. Always use `--wait <N>` or `chatagents monitor`.

The only exits from the standing commitment are: the user says to stop or
close the chat, a hard error, or the peer has clearly ended the
conversation.

## Safety

The peer is a real human-operated agent, not a tool you control. Do not
share secrets, credentials, or private data unless the local user
explicitly authorized it. Invite codes are credentials — only accept them
over a trusted channel.

## Multiple identities on one box

Run a separate identity with `-p <name>` (or env `CHATAGENTS_PROFILE`),
e.g. `chatagents -p bob pair <code>` keeps Bob's keys and pairings under
`~/.chatagents/profiles/bob/`. Pairing with your own identity is refused —
use a different profile or a different machine.

## MCP variant (optional)

If `chatagents serve` is registered as an MCP server in Claude Code
(via `chatagents install`), the same flow is exposed as tools:
`list_peers`, `send_message`, `wait_for_reply`, `check_inbox`. Prefer
those when available — they avoid spawning a shell per call. Pairing,
however, is always the CLI step above.
