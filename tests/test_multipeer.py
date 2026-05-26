"""One Alice paired with two distinct peers (Bob, Carol). Verifies routing,
cursor isolation, multi-peer inbox aggregation, and ambiguity errors."""
import os
import secrets

import pytest

from chatagents import identity, messaging, pairing
from chatagents.relay_client import RelayClient


def _as_user(home):
    os.environ["CHATAGENTS_HOME"] = str(home)


def _invite(alice_home, relay_url, name):
    """Mint a pairing on Alice's side and return the invite code + alice pubkey."""
    _as_user(alice_home)
    alice = identity.load_or_create()
    token = secrets.token_urlsafe(32)
    c = RelayClient(relay_url, room_token=token)
    room = c.create_room(token)
    c.register_peer(room, alice.pubkey)
    code = c.create_invite(relay_url, room, token, alice.pubkey)
    c.close()
    pairing.save_peer({
        "name": name, "relay": relay_url, "room_id": room,
        "room_token": token, "peer_pubkey": None,
        "my_role": "inviter", "cursor": None,
    })
    return code, alice.pubkey


def _accept(home, code, relay_url, local_name):
    """Claim invite `code` on `home`'s side."""
    _as_user(home)
    me = identity.load_or_create()
    c = RelayClient(relay_url)
    inv = c.claim_invite(code)
    c.close()
    c = RelayClient(inv["relay"], room_token=inv["room_token"])
    c.register_peer(inv["room_id"], me.pubkey)
    c.close()
    pairing.save_peer({
        "name": local_name, "relay": inv["relay"],
        "room_id": inv["room_id"], "room_token": inv["room_token"],
        "peer_pubkey": inv["pubkey"], "my_role": "joiner", "cursor": None,
    })
    return me


def test_alice_routes_to_two_distinct_peers(relay, tmp_path):
    alice_home = tmp_path / "alice"; alice_home.mkdir()
    bob_home   = tmp_path / "bob";   bob_home.mkdir()
    carol_home = tmp_path / "carol"; carol_home.mkdir()

    # Alice creates two pairings
    code_b, alice_pub = _invite(alice_home, relay["url"], "bob")
    code_c, _         = _invite(alice_home, relay["url"], "carol")

    # Bob and Carol each pair
    bob = _accept(bob_home, code_b, relay["url"], "alice")
    carol = _accept(carol_home, code_c, relay["url"], "alice")

    # Both send to Alice
    _as_user(bob_home);   messaging.send_text("hi from bob")
    _as_user(carol_home); messaging.send_text("hi from carol")

    # Alice's inbox (no peer arg) returns both, tagged by local name
    _as_user(alice_home)
    msgs = messaging.receive(wait=5)
    by_peer = {m["peer"]: m["text"] for m in msgs}
    assert by_peer == {"bob": "hi from bob", "carol": "hi from carol"}

    # Alice replies only to Bob
    messaging.send_text("ack from alice", peer="bob")

    # Bob sees the ack; Carol does not
    _as_user(bob_home)
    bob_msgs = messaging.receive(wait=5)
    assert [m["text"] for m in bob_msgs] == ["ack from alice"]

    _as_user(carol_home)
    carol_msgs = messaging.receive(wait=1)
    assert carol_msgs == []


def test_ambiguous_send_when_multiple_peers(relay, tmp_path):
    alice_home = tmp_path / "alice"; alice_home.mkdir()
    bob_home   = tmp_path / "bob";   bob_home.mkdir()
    carol_home = tmp_path / "carol"; carol_home.mkdir()
    code_b, _ = _invite(alice_home, relay["url"], "bob")
    code_c, _ = _invite(alice_home, relay["url"], "carol")
    _accept(bob_home, code_b, relay["url"], "alice")
    _accept(carol_home, code_c, relay["url"], "alice")

    _as_user(alice_home)
    with pytest.raises(messaging.AmbiguousPeerError):
        messaging.send_text("which one?")


def test_unknown_peer(relay, tmp_path):
    alice_home = tmp_path / "alice"; alice_home.mkdir()
    bob_home   = tmp_path / "bob";   bob_home.mkdir()
    code_b, _ = _invite(alice_home, relay["url"], "bob")
    _accept(bob_home, code_b, relay["url"], "alice")

    _as_user(alice_home)
    with pytest.raises(messaging.UnknownPeerError):
        messaging.send_text("hello", peer="ghost")


def test_cursor_isolation_per_peer(relay, tmp_path):
    """Reading Bob's inbox must not advance Carol's cursor (or vice versa)."""
    alice_home = tmp_path / "alice"; alice_home.mkdir()
    bob_home   = tmp_path / "bob";   bob_home.mkdir()
    carol_home = tmp_path / "carol"; carol_home.mkdir()
    code_b, _ = _invite(alice_home, relay["url"], "bob")
    code_c, _ = _invite(alice_home, relay["url"], "carol")
    _accept(bob_home, code_b, relay["url"], "alice")
    _accept(carol_home, code_c, relay["url"], "alice")

    _as_user(bob_home);   messaging.send_text("from bob")
    _as_user(carol_home); messaging.send_text("from carol")

    # Alice drains only bob's inbox
    _as_user(alice_home)
    bob_msgs = messaging.receive(peer="bob", wait=5)
    assert len(bob_msgs) == 1
    assert bob_msgs[0]["peer"] == "bob"

    # Carol's pairing cursor should be unchanged — message still pending
    carol_msgs = messaging.receive(peer="carol", wait=3)
    assert len(carol_msgs) == 1
    assert carol_msgs[0]["peer"] == "carol"
