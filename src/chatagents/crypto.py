"""Thin wrappers around PyNaCl's authenticated public-key Box."""
from nacl.public import PrivateKey, PublicKey, Box
from nacl.utils import random as nacl_random


def new_keypair() -> tuple[bytes, bytes]:
    sk = PrivateKey.generate()
    return bytes(sk.public_key), bytes(sk)


def encrypt(plaintext: bytes, peer_pub: bytes, my_priv: bytes) -> tuple[bytes, bytes]:
    box = Box(PrivateKey(my_priv), PublicKey(peer_pub))
    nonce = nacl_random(Box.NONCE_SIZE)
    return nonce, box.encrypt(plaintext, nonce).ciphertext


def decrypt(ciphertext: bytes, nonce: bytes, peer_pub: bytes, my_priv: bytes) -> bytes:
    box = Box(PrivateKey(my_priv), PublicKey(peer_pub))
    return box.decrypt(ciphertext, nonce)
