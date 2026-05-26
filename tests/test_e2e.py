"""End-to-end: real uvicorn relay in a thread, two clients, full handshake."""
import os
import secrets
import sqlite3
from pathlib import Path

import httpx
import pytest

from chatagents import identity, messaging, pairing
from chatagents.relay_client import RelayClient


def _as_user(home: Path) -> None:
    os.environ["CHATAGENTS_HOME"] = str(home)


def test_two_clients_exchange_and_relay_holds_only_ciphertext(relay, tmp_path):
    alice_home = tmp_path / "alice"
    bob_home = tmp_path / "bob"
    alice_home.mkdir()
    bob_home.mkdir()

    # Alice: init + invite (mints an 8-char code on the relay)
    _as_user(alice_home)
    alice = identity.load_or_create()
    room_token = secrets.token_urlsafe(32)
    c = RelayClient(relay["url"], room_token=room_token)
    room_id = c.create_room(room_token)
    c.register_peer(room_id, alice.pubkey)
    code = c.create_invite(relay["url"], room_id, room_token, alice.pubkey)
    c.close()
    assert len(code) == 8
    pairing.save_peer({
        "name": "default", "relay": relay["url"], "room_id": room_id,
        "room_token": room_token, "peer_pubkey": None,
        "my_role": "inviter", "cursor": None,
    })

    # Bob: claim the code, then register
    _as_user(bob_home)
    bob = identity.load_or_create()
    c = RelayClient(relay["url"])
    inv = c.claim_invite(code)
    c.close()
    c = RelayClient(inv["relay"], room_token=inv["room_token"])
    c.register_peer(inv["room_id"], bob.pubkey)
    c.close()
    pairing.save_peer({
        "name": "default", "relay": inv["relay"], "room_id": inv["room_id"],
        "room_token": inv["room_token"], "peer_pubkey": inv["pubkey"],
        "my_role": "joiner", "cursor": None,
    })

    # Bob -> Alice
    secret_phrase_bob = "this_is_a_distinctive_payload_from_bob"
    messaging.send_text(secret_phrase_bob)

    # Alice reads
    _as_user(alice_home)
    msgs = messaging.receive(wait=5)
    assert len(msgs) == 1
    assert msgs[0]["text"] == secret_phrase_bob
    assert msgs[0]["from_fp"] == identity.fingerprint(bob.pubkey)

    # Alice -> Bob
    secret_phrase_alice = "another_distinctive_payload_from_alice"
    messaging.send_text(secret_phrase_alice)

    # Bob reads
    _as_user(bob_home)
    msgs = messaging.receive(wait=5)
    assert len(msgs) == 1
    assert msgs[0]["text"] == secret_phrase_alice
    assert msgs[0]["from_fp"] == identity.fingerprint(alice.pubkey)

    # Relay must hold only ciphertext — neither plaintext substring appears
    rows = (
        sqlite3.connect(str(relay["home"] / "relay.sqlite"))
        .execute("SELECT ciphertext FROM messages")
        .fetchall()
    )
    assert rows, "relay did not store messages"
    for (blob,) in rows:
        assert secret_phrase_bob.encode() not in blob
        assert secret_phrase_alice.encode() not in blob


def test_invite_code_is_one_shot(relay, tmp_path):
    _as_user(tmp_path / "alice")
    (tmp_path / "alice").mkdir()
    alice = identity.load_or_create()
    room_token = secrets.token_urlsafe(32)
    c = RelayClient(relay["url"], room_token=room_token)
    room_id = c.create_room(room_token)
    c.register_peer(room_id, alice.pubkey)
    code = c.create_invite(relay["url"], room_id, room_token, alice.pubkey)
    # First claim succeeds
    inv = c.claim_invite(code)
    assert inv["room_id"] == room_id
    # Second claim 404s
    with pytest.raises(httpx.HTTPStatusError) as ei:
        c.claim_invite(code)
    assert ei.value.response.status_code == 404
    c.close()


def test_invite_requires_matching_room_token(relay, tmp_path):
    _as_user(tmp_path / "alice")
    (tmp_path / "alice").mkdir()
    alice = identity.load_or_create()
    room_token = secrets.token_urlsafe(32)
    c = RelayClient(relay["url"], room_token=room_token)
    room_id = c.create_room(room_token)
    c.register_peer(room_id, alice.pubkey)
    # Bearer = wrong token → 401
    wrong = RelayClient(relay["url"], room_token=secrets.token_urlsafe(32))
    with pytest.raises(httpx.HTTPStatusError) as ei:
        wrong.create_invite(relay["url"], room_id, room_token, alice.pubkey)
    assert ei.value.response.status_code == 401
    wrong.close()
    c.close()


def test_room_peer_cap_enforced(relay, tmp_path):
    _as_user(tmp_path / "alice")
    (tmp_path / "alice").mkdir()
    alice = identity.load_or_create()
    room_token = secrets.token_urlsafe(32)
    c = RelayClient(relay["url"], room_token=room_token)
    room_id = c.create_room(room_token)
    c.register_peer(room_id, alice.pubkey)

    # Two more peers should be rejected
    for _ in range(2):
        from chatagents import crypto as _crypto
        pub, _ = _crypto.new_keypair()
        try:
            c.register_peer(room_id, pub)
        except httpx.HTTPStatusError as e:
            assert e.response.status_code == 409
            c.close()
            return
    c.close()
    pytest.fail("expected room cap to reject the third peer")
