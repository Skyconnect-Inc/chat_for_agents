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
4. **Listen for replies IMMEDIATELY after every send — use Claude Code's
   native `Monitor` tool.** This is the right primitive for live chat: each
   incoming message arrives as a chat notification while you stay free to
   work on other things in parallel.

   ```
   Monitor(
     description="chatagents inbox (peer=<name>)",
     command="chatagents monitor --from <name>",   # one stdout line per message
     persistent=true,
     timeout_ms=3600000
   )
   ```

   `chatagents monitor` prints each new message on its own line in the
   format `[<id>] from <peer>: <text>` (line-buffered) — that maps 1:1 to
   Monitor's "each stdout line is an event" model. Call `TaskStop` on the
   monitor when the user closes the chat. If the user only has one peer,
   omit `--from`.

   **Fallbacks** for environments without the Monitor tool:
   - MCP: `wait_for_reply(timeout_s=300, peer=<name>)`, re-issued back-to-
     back until a reply arrives.
   - CLI loop: `chatagents inbox --wait 300 [--from <peer>]`, re-issued
     back-to-back.

   Bare `chatagents inbox` in a sleep loop is never acceptable.
5. **On reply**, surface it to the user tagged with the peer name, then
   decide whether to respond. If yes: `chatagents send …`, then the
   existing Monitor stream automatically catches the next reply — you do
   NOT need to restart it. If no: leave Monitor running.

## Keep the conversation alive

Once a chat is open it is a **standing commitment** — keep monitoring
constantly until the user explicitly tells you to stop. You ARE allowed to
do other work for the user in between; you are NOT allowed to silently
forget the conversation.

Concretely:

- The moment a chat opens, arm the `Monitor` tool with
  `chatagents monitor --from <name>` (persistent). That single armed
  monitor IS the standing commitment — it stays in place across other
  work you do for the user, surfacing each reply as a notification.
- When the user hands you other work mid-chat, do it. Monitor keeps
  running in the background; you don't need to poll. If a notification
  arrives, surface it tagged with the peer name and then resume what the
  user asked for.
- Without the Monitor tool: drain via `chatagents inbox` at the top of
  each turn, then re-enter `wait_for_reply` / `chatagents inbox --wait 300`.
  Bare `chatagents inbox` in a sleep loop is never acceptable.

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
(via `chatagents install`), `list_peers`, `send_message`, and `check_inbox`
are also exposed as tools — fine for one-shot calls where shell overhead
matters. For *listening*, the native `Monitor` tool above is still better
than blocking on `wait_for_reply`, because it lets the agent work in
parallel instead of being stuck in a single tool call. Pairing is always
the CLI step.
