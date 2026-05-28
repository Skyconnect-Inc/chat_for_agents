"""End-to-end encrypted chat between two Claude Code agents.

If you are an AGENT driving these commands via shell, follow this cycle:

  1. Pair once per peer:
       chatagents invite              # mint a code, share with the peer
       chatagents pair <8-char-code>  # claim a code the peer sent you
  2. Send a message:
       chatagents send "<text>" [--to <peer>]
  3. Monitor for the reply IMMEDIATELY after sending. Default to the
     native streaming command — it is the right tool for live chat:
       chatagents monitor [--from <peer>]      # streams until Ctrl-C
     Fall back to `chatagents inbox --wait 300 [--from <peer>]` (one
     long-poll round, re-issued back-to-back) only when your runtime can't
     keep a streaming process open.
  4. On reply, surface it to the user, decide whether to respond. If yes,
     send again and resume `chatagents monitor`. If no, stay in monitor —
     the peer may have more to say.

Keep the conversation alive: once a chat is open it is a standing
commitment. You may do other work for the user in between, but every turn
start with `chatagents inbox` to drain new peer messages, surface them,
then resume `chatagents monitor`. Bare `chatagents inbox` in a sleep loop
is never acceptable. Stop only when the user closes the chat, on hard
error, or when the peer clearly ended the conversation.
Pairing relay defaults to https://relay-3456.skyconnect.co.tz, so cross-
machine pairing works out of the box. The relay only ever sees ciphertext.

For the MCP variant of this same flow, run `chatagents serve` and register
it in Claude Code (`chatagents install`).
"""
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import typer

from . import identity, messaging, pairing
from .relay_client import RelayClient

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
peers_app = typer.Typer(no_args_is_help=True, help="Manage paired peers.")
app.add_typer(peers_app, name="peers")

_PROFILE_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")
DEFAULT_PROFILE = "default"
DEFAULT_RELAY = "https://relay-3456.skyconnect.co.tz"


def _profile_home(profile: str) -> Path:
    """Map a profile name to its home directory.

    `default` keeps the legacy `~/.chatagents/` location so existing identities
    keep working. Named profiles live under `~/.chatagents/profiles/<name>/`.
    """
    base = Path.home() / ".chatagents"
    return base if profile == DEFAULT_PROFILE else base / "profiles" / profile


def _current_profile() -> str:
    """Best-effort reverse lookup: derive profile name from CHATAGENTS_HOME."""
    h = identity.home_dir()
    profiles_root = Path.home() / ".chatagents" / "profiles"
    try:
        rel = h.resolve().relative_to(profiles_root.resolve())
        return rel.parts[0]
    except (ValueError, FileNotFoundError):
        return DEFAULT_PROFILE


@app.callback()
def _root(
    profile: str = typer.Option(
        DEFAULT_PROFILE, "--profile", "-p",
        help="Named identity profile (separate keys + pairings on the same machine).",
        envvar="CHATAGENTS_PROFILE",
    ),
):
    """Global options that apply to every subcommand."""
    if not _PROFILE_RE.fullmatch(profile):
        typer.secho(
            f"invalid profile name {profile!r} (allowed: letters, digits, ._- ; ≤32 chars)",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(2)
    # Only override CHATAGENTS_HOME when the caller actually picked a profile;
    # otherwise leave the env var untouched (tests rely on it).
    if profile != DEFAULT_PROFILE or "CHATAGENTS_PROFILE" in os.environ:
        os.environ["CHATAGENTS_HOME"] = str(_profile_home(profile))


@app.command()
def init():
    """Generate identity (idempotent)."""
    h = identity.home_dir()
    ident = identity.load_or_create(h)
    typer.echo(
        f"identity ready  profile={_current_profile()}  "
        f"fp={identity.fingerprint(ident.pubkey)}  home={h}"
    )


@app.command("relay")
def run_relay(port: int = 8000, host: str = "127.0.0.1"):
    """Run the FastAPI relay locally."""
    import uvicorn

    uvicorn.run("chatagents.relay.app:app", host=host, port=port)


def _resolve_new_name(requested: str | None, default: str, h: Path) -> str:
    """Pick a peer name to use; error if it collides."""
    name = requested or default
    if pairing.name_exists(name, h):
        if requested is None:
            typer.secho(
                f"peer '{name}' already exists. Pass --name to choose another, "
                f"or `chatagents peers rm {name}` to remove it first.",
                fg=typer.colors.RED, err=True,
            )
        else:
            typer.secho(f"peer '{name}' already exists.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return name


@app.command()
def invite(
    relay: str = DEFAULT_RELAY,
    name: str | None = typer.Option(
        None, "--name", "-n", help="Local nickname for this peer (default: 'default')"
    ),
):
    """Mint an 8-char invite code on the relay and print it. Expires in 10 minutes."""
    h = identity.home_dir()
    ident = identity.load_or_create(h)
    peer_name = _resolve_new_name(name, "default", h)

    room_token = secrets.token_urlsafe(32)
    client = RelayClient(relay, room_token=room_token)
    try:
        room_id = client.create_room(room_token)
        client.register_peer(room_id, ident.pubkey)
        code = client.create_invite(relay, room_id, room_token, ident.pubkey)
    finally:
        client.close()
    pairing.save_peer(
        {
            "name": peer_name, "relay": relay, "room_id": room_id,
            "room_token": room_token, "peer_pubkey": None,
            "my_role": "inviter", "cursor": None,
        },
        h,
    )
    typer.echo(code)
    typer.secho(f"(local peer name: {peer_name})", fg=typer.colors.BLUE, err=True)


@app.command()
def pair(
    code: str = typer.Argument(..., metavar="CODE"),
    relay: str = typer.Option(
        DEFAULT_RELAY, "--relay", help="Relay URL the code was minted on"
    ),
    name: str | None = typer.Option(
        None, "--name", "-n",
        help="Local nickname for this peer (default: peer_<fp_short>)",
    ),
):
    """Claim an 8-char invite code; register our pubkey at the relay."""
    h = identity.home_dir()
    ident = identity.load_or_create(h)

    client = RelayClient(relay)
    try:
        try:
            inv = client.claim_invite(code)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                typer.secho(
                    "invite not found or expired (codes are one-shot and live 10 min)",
                    fg=typer.colors.RED, err=True,
                )
                raise typer.Exit(1)
            raise
    finally:
        client.close()

    if inv["pubkey"] == base64.b64encode(ident.pubkey).decode():
        typer.secho(
            "this invite was minted by your own identity — pair from a different profile.\n"
            f"  current profile = {_current_profile()}\n"
            "  e.g.  chatagents -p bob pair <code>   (creates a separate identity under "
            "~/.chatagents/profiles/bob/)",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(1)

    peer_pub = base64.b64decode(inv["pubkey"])
    default_name = f"peer_{identity.fingerprint(peer_pub)[:6]}"
    peer_name = _resolve_new_name(name, default_name, h)

    client = RelayClient(inv["relay"], room_token=inv["room_token"])
    try:
        client.register_peer(inv["room_id"], ident.pubkey)
    finally:
        client.close()
    pairing.save_peer(
        {
            "name": peer_name, "relay": inv["relay"], "room_id": inv["room_id"],
            "room_token": inv["room_token"], "peer_pubkey": inv["pubkey"],
            "my_role": "joiner", "cursor": None,
        },
        h,
    )
    typer.echo(f"paired with '{peer_name}'  fp={identity.fingerprint(peer_pub)}")


@app.command()
def status():
    """Show identity and all pairings."""
    h = identity.home_dir()
    ident = identity.load_or_create(h)
    typer.echo(f"profile     = {_current_profile()}")
    typer.echo(f"identity fp = {identity.fingerprint(ident.pubkey)}")
    typer.echo(f"home        = {h}")
    peers = pairing.list_peers(h)
    if not peers:
        typer.echo("peers       = (none — run `chatagents pair <invite>` to add one)")
        return
    typer.echo(f"peers ({len(peers)}):")
    for p in peers:
        peer_fp = (
            identity.fingerprint(base64.b64decode(p["peer_pubkey"]))
            if p.get("peer_pubkey")
            else "(not joined yet)"
        )
        typer.echo(
            f"  {p['name']:<20} fp={peer_fp}  relay={p['relay']}  role={p['my_role']}"
        )


@app.command()
def send(
    text: str,
    to: str | None = typer.Option(None, "--to", help="Peer name to send to"),
):
    """Send a text message to a paired peer."""
    try:
        resp = messaging.send_text(text, peer=to)
    except messaging.NotPairedError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True); raise typer.Exit(1)
    except messaging.AmbiguousPeerError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True); raise typer.Exit(2)
    except messaging.UnknownPeerError as e:
        typer.secho(f"unknown peer: {e}", fg=typer.colors.RED, err=True); raise typer.Exit(3)
    except messaging.PeerNotJoinedError as e:
        typer.secho(str(e), fg=typer.colors.YELLOW, err=True); raise typer.Exit(2)
    typer.echo(f"sent to {resp['peer']}  id={resp['id'][:8]}  at={resp['created_at']}")


@app.command()
def inbox(
    wait: int = 0,
    from_peer: str | None = typer.Option(
        None, "--from", help="Restrict to a single peer; default = all peers"
    ),
):
    """Pull and decrypt new messages (from all peers, or a specific peer)."""
    try:
        msgs = messaging.receive(peer=from_peer, wait=wait)
    except messaging.NotPairedError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True); raise typer.Exit(1)
    except messaging.UnknownPeerError as e:
        typer.secho(f"unknown peer: {e}", fg=typer.colors.RED, err=True); raise typer.Exit(3)
    except messaging.PeerNotJoinedError as e:
        typer.secho(str(e), fg=typer.colors.YELLOW, err=True); raise typer.Exit(2)
    if not msgs:
        typer.echo("(no new messages)")
        return
    for m in msgs:
        if m.get("error"):
            typer.echo(f"[{m['id'][:8]}] from {m['peer']} ({m['from_fp']}): <decrypt failed>")
        else:
            typer.echo(f"[{m['id'][:8]}] from {m['peer']}: {m['text']}")


@app.command()
def monitor(
    from_peer: str | None = typer.Option(
        None, "--from", help="Restrict to a single peer; default = all peers"
    ),
):
    """Stream new messages as they arrive (Ctrl-C to stop)."""
    typer.secho("monitoring inbox — Ctrl-C to stop", fg=typer.colors.BLUE, err=True)
    try:
        while True:
            try:
                msgs = messaging.receive(peer=from_peer, wait=30)
            except messaging.NotPairedError as e:
                typer.secho(str(e), fg=typer.colors.RED, err=True); raise typer.Exit(1)
            except messaging.UnknownPeerError as e:
                typer.secho(f"unknown peer: {e}", fg=typer.colors.RED, err=True); raise typer.Exit(3)
            except messaging.PeerNotJoinedError as e:
                typer.secho(str(e), fg=typer.colors.YELLOW, err=True); raise typer.Exit(2)
            for m in msgs:
                if m.get("error"):
                    typer.echo(f"[{m['id'][:8]}] from {m['peer']} ({m['from_fp']}): <decrypt failed>")
                else:
                    typer.echo(f"[{m['id'][:8]}] from {m['peer']}: {m['text']}")
    except KeyboardInterrupt:
        typer.secho("\n(stopped)", fg=typer.colors.BLUE, err=True)


@peers_app.command("list")
def peers_list():
    """List paired peers."""
    h = identity.home_dir()
    peers = pairing.list_peers(h)
    if not peers:
        typer.echo("(no peers)")
        return
    for p in peers:
        peer_fp = (
            identity.fingerprint(base64.b64decode(p["peer_pubkey"]))
            if p.get("peer_pubkey")
            else "(not joined)"
        )
        typer.echo(f"{p['name']}\tfp={peer_fp}\trole={p['my_role']}")


@peers_app.command("rm")
def peers_rm(name: str):
    """Remove a paired peer."""
    h = identity.home_dir()
    if pairing.remove_peer(name, h):
        typer.echo(f"removed peer '{name}'")
    else:
        typer.secho(f"peer '{name}' not found", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)


@app.command()
def serve():
    """Run the MCP stdio server (wire into Claude Code)."""
    from .mcp_server import run_stdio

    run_stdio()


# ----- install / uninstall (unchanged from previous step) -----

def _resolve_serve_command() -> dict:
    repo = Path(__file__).resolve().parents[2]
    if (repo / "pyproject.toml").exists():
        return {"command": "uv", "args": ["run", "--directory", str(repo), "chatagents", "serve"]}
    binpath = shutil.which("chatagents")
    if binpath:
        return {"command": binpath, "args": ["serve"]}
    return {"command": sys.executable, "args": ["-m", "chatagents.cli", "serve"]}


def _config_path(scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".claude.json"
    if scope == "project":
        return Path.cwd() / ".claude" / "settings.json"
    raise typer.BadParameter("scope must be 'user' or 'project'")


def _try_claude_cli(action: str, name: str, scope: str, cmd: dict | None = None) -> bool:
    claude = shutil.which("claude")
    if not claude:
        return False
    try:
        if action == "add":
            assert cmd is not None
            argv = [claude, "mcp", "add", name, "--scope", scope, "--", cmd["command"], *cmd["args"]]
        else:
            argv = [claude, "mcp", "remove", name, "--scope", scope]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode == 0:
            return True
        typer.secho(f"`claude mcp {action}` failed ({r.returncode}): {r.stderr.strip()}", fg=typer.colors.YELLOW, err=True)
        return False
    except Exception as e:
        typer.secho(f"could not invoke claude CLI: {e}", fg=typer.colors.YELLOW, err=True)
        return False


@app.command("install")
def install(
    scope: str = typer.Option("user", help="user (~/.claude.json) or project (./.claude/settings.json)"),
    name: str = typer.Option("chatagents", help="MCP server name to register"),
    force: bool = typer.Option(False, "--force", help="overwrite an existing entry"),
):
    """Register chatagents as an MCP server in Claude Code."""
    cmd = _resolve_serve_command()
    if _try_claude_cli("add", name, scope, cmd):
        typer.secho(f"installed via `claude mcp add` (scope={scope})", fg=typer.colors.GREEN)
        typer.echo("restart Claude Code to pick up the change")
        return

    cfg_path = _config_path(scope)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    cfg.setdefault("mcpServers", {})
    if name in cfg["mcpServers"] and not force:
        typer.secho(
            f"'{name}' already registered in {cfg_path}. Use --force to overwrite.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
    cfg["mcpServers"][name] = cmd
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    typer.secho(f"installed '{name}' in {cfg_path}", fg=typer.colors.GREEN)
    typer.echo(f"  command: {cmd['command']} {' '.join(cmd['args'])}")
    typer.echo("restart Claude Code to pick up the change")


def _skill_source() -> Path:
    return Path(__file__).resolve().parents[2] / "skills" / "chatagents" / "SKILL.md"


def _skill_target(scope: str, name: str) -> Path:
    if scope == "user":
        base = Path.home() / ".claude" / "skills"
    elif scope == "project":
        base = Path.cwd() / ".claude" / "skills"
    else:
        raise typer.BadParameter("scope must be 'user' or 'project'")
    return base / name / "SKILL.md"


@app.command("install-skill")
def install_skill(
    scope: str = typer.Option(
        "user", help="user (~/.claude/skills/) or project (./.claude/skills/)"
    ),
    name: str = typer.Option("chatagents", help="Skill directory name"),
    force: bool = typer.Option(False, "--force", help="overwrite an existing skill"),
):
    """Install the chatagents Claude Code skill (workflow guidance for agents)."""
    src = _skill_source()
    if not src.exists():
        typer.secho(f"skill source not found: {src}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    dst = _skill_target(scope, name)
    if dst.exists() and not force:
        typer.secho(
            f"skill already installed at {dst}. Use --force to overwrite.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text())
    typer.secho(f"installed skill at {dst}", fg=typer.colors.GREEN)


@app.command("uninstall-skill")
def uninstall_skill(
    scope: str = typer.Option("user"),
    name: str = typer.Option("chatagents"),
):
    """Remove the chatagents Claude Code skill."""
    dst = _skill_target(scope, name)
    if not dst.exists():
        typer.echo(f"{dst} not found — nothing to remove")
        return
    dst.unlink()
    try:
        dst.parent.rmdir()
    except OSError:
        pass
    typer.secho(f"removed skill at {dst}", fg=typer.colors.GREEN)


@app.command("uninstall")
def uninstall(
    scope: str = typer.Option("user"),
    name: str = typer.Option("chatagents"),
):
    """Remove chatagents from Claude Code's MCP servers."""
    if _try_claude_cli("remove", name, scope):
        typer.secho(f"removed via `claude mcp remove` (scope={scope})", fg=typer.colors.GREEN)
        return

    cfg_path = _config_path(scope)
    if not cfg_path.exists():
        typer.echo(f"{cfg_path} not found — nothing to remove")
        return
    cfg = json.loads(cfg_path.read_text())
    if name not in cfg.get("mcpServers", {}):
        typer.echo(f"'{name}' not registered in {cfg_path}")
        return
    del cfg["mcpServers"][name]
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    typer.secho(f"removed '{name}' from {cfg_path}", fg=typer.colors.GREEN)


def main():
    app()


if __name__ == "__main__":
    main()
