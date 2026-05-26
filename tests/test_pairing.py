import base64
import json

import pytest

from chatagents import pairing


def test_save_load_remove_peer(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    p = {"name": "bob", "relay": "http://x", "room_id": "r1",
         "room_token": "t1", "peer_pubkey": None,
         "my_role": "inviter", "cursor": None}
    pairing.save_peer(p)
    loaded = pairing.load_peer("bob")
    assert loaded == p
    assert pairing.name_exists("bob")
    assert pairing.remove_peer("bob") is True
    assert pairing.load_peer("bob") is None


def test_invalid_peer_name_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        pairing.save_peer({"name": "../escape", "relay": "x", "room_id": "r",
                           "room_token": "t", "peer_pubkey": None,
                           "my_role": "inviter", "cursor": None})


def test_resolve_default_single_peer(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    pairing.save_peer({"name": "solo", "relay": "x", "room_id": "r",
                       "room_token": "t", "peer_pubkey": None,
                       "my_role": "inviter", "cursor": None})
    assert pairing.resolve(None)["name"] == "solo"


def test_resolve_ambiguous(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    for n in ("a", "b"):
        pairing.save_peer({"name": n, "relay": "x", "room_id": "r",
                           "room_token": "t", "peer_pubkey": None,
                           "my_role": "inviter", "cursor": None})
    with pytest.raises(pairing.AmbiguousPeerError):
        pairing.resolve(None)


def test_resolve_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    with pytest.raises(pairing.UnknownPeerError):
        pairing.resolve("ghost")


def test_resolve_no_peers(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    with pytest.raises(pairing.NoPeersError):
        pairing.resolve(None)


def test_legacy_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    legacy = tmp_path / "pairing.json"
    peer_pub = base64.b64encode(b"\x02" * 32).decode()
    legacy.write_text(json.dumps({
        "relay": "http://x", "room_id": "abc", "room_token": "tok_xxxxxxxxxxxxxxxx",
        "peer_pubkey": peer_pub, "my_role": "joiner", "cursor": None,
    }))
    peers = pairing.list_peers()
    assert len(peers) == 1
    assert peers[0]["name"].startswith("peer_")
    assert peers[0]["peer_pubkey"] == peer_pub
    assert not legacy.exists()


def test_legacy_migration_no_peer_pubkey(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATAGENTS_HOME", str(tmp_path))
    legacy = tmp_path / "pairing.json"
    legacy.write_text(json.dumps({
        "relay": "http://x", "room_id": "abc", "room_token": "tok",
        "peer_pubkey": None, "my_role": "inviter", "cursor": None,
    }))
    peers = pairing.list_peers()
    assert len(peers) == 1
    assert peers[0]["name"] == "default"
    assert not legacy.exists()
