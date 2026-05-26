"""SQLite-backed storage for the relay. Stores only ciphertext."""
import hashlib
import secrets
import sqlite3
import string
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOM_PEER_CAP = 2
MESSAGE_TTL = timedelta(days=7)
INVITE_TTL = timedelta(minutes=10)
INVITE_CODE_ALPHABET = string.ascii_letters + string.digits  # base62
INVITE_CODE_LEN = 8
INVITE_CODE_MAX_TRIES = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS peers (
    room_id TEXT NOT NULL,
    pubkey TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (room_id, pubkey)
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    from_pubkey TEXT NOT NULL,
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_room_created ON messages(room_id, created_at, id);
CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None
        )
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def create_room(self, token: str) -> str:
        room_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO rooms (id, token_hash, created_at) VALUES (?,?,?)",
            (room_id, _hash_token(token), _utcnow()),
        )
        return room_id

    def authenticate(self, room_id: str, token: str) -> bool:
        row = self.conn.execute(
            "SELECT token_hash FROM rooms WHERE id=?", (room_id,)
        ).fetchone()
        return bool(row) and row[0] == _hash_token(token)

    def register_peer(self, room_id: str, pubkey: str) -> str | None:
        existing = [
            r[0]
            for r in self.conn.execute(
                "SELECT pubkey FROM peers WHERE room_id=?", (room_id,)
            ).fetchall()
        ]
        if pubkey in existing:
            return None
        if len(existing) >= ROOM_PEER_CAP:
            return "room is full"
        self.conn.execute(
            "INSERT INTO peers (room_id, pubkey, joined_at) VALUES (?,?,?)",
            (room_id, pubkey, _utcnow()),
        )
        return None

    def list_peers(self, room_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT pubkey, joined_at FROM peers WHERE room_id=? ORDER BY joined_at",
            (room_id,),
        ).fetchall()
        return [{"pubkey": r[0], "joined_at": r[1]} for r in rows]

    def insert_message(
        self, room_id: str, from_pubkey: str, nonce: bytes, ciphertext: bytes
    ) -> tuple[str, str]:
        mid = uuid.uuid4().hex
        ts = _utcnow()
        self.conn.execute(
            "INSERT INTO messages (id, room_id, from_pubkey, nonce, ciphertext, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (mid, room_id, from_pubkey, nonce, ciphertext, ts),
        )
        return mid, ts

    def list_messages(self, room_id: str, since: str | None) -> list[dict]:
        if since:
            rows = self.conn.execute(
                "SELECT id, from_pubkey, nonce, ciphertext, created_at FROM messages "
                "WHERE room_id=? AND created_at > ? ORDER BY created_at, id",
                (room_id, since),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, from_pubkey, nonce, ciphertext, created_at FROM messages "
                "WHERE room_id=? ORDER BY created_at, id",
                (room_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "from_pubkey": r[1],
                "nonce": r[2],
                "ciphertext": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def sweep_expired(self) -> int:
        cutoff = (datetime.now(timezone.utc) - MESSAGE_TTL).isoformat()
        cur = self.conn.execute(
            "DELETE FROM messages WHERE created_at < ?", (cutoff,)
        )
        return cur.rowcount

    def put_invite(self, payload: str) -> str:
        for _ in range(INVITE_CODE_MAX_TRIES):
            code = "".join(
                secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LEN)
            )
            try:
                self.conn.execute(
                    "INSERT INTO invites (code, payload, created_at) VALUES (?,?,?)",
                    (code, payload, _utcnow()),
                )
                return code
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("could not allocate unique invite code")

    def claim_invite(self, code: str) -> str | None:
        cutoff = (datetime.now(timezone.utc) - INVITE_TTL).isoformat()
        self.conn.execute("DELETE FROM invites WHERE created_at < ?", (cutoff,))
        row = self.conn.execute(
            "SELECT payload FROM invites WHERE code=?", (code,)
        ).fetchone()
        if not row:
            return None
        self.conn.execute("DELETE FROM invites WHERE code=?", (code,))
        return row[0]
