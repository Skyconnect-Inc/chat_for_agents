import pytest

from chatagents import crypto


def test_roundtrip():
    a_pub, a_priv = crypto.new_keypair()
    b_pub, b_priv = crypto.new_keypair()
    nonce, ct = crypto.encrypt(b"hello", b_pub, a_priv)
    assert crypto.decrypt(ct, nonce, a_pub, b_priv) == b"hello"


def test_tamper_detection():
    a_pub, a_priv = crypto.new_keypair()
    b_pub, b_priv = crypto.new_keypair()
    nonce, ct = crypto.encrypt(b"secret", b_pub, a_priv)
    tampered = ct[:-1] + bytes([ct[-1] ^ 0x01])
    with pytest.raises(Exception):
        crypto.decrypt(tampered, nonce, a_pub, b_priv)


def test_wrong_recipient_fails():
    a_pub, a_priv = crypto.new_keypair()
    b_pub, _ = crypto.new_keypair()
    _, c_priv = crypto.new_keypair()
    nonce, ct = crypto.encrypt(b"secret", b_pub, a_priv)
    with pytest.raises(Exception):
        crypto.decrypt(ct, nonce, a_pub, c_priv)
