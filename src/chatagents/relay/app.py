"""FastAPI relay. Forwards ciphertext between paired peers; never decrypts."""
import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..identity import home_dir
from .storage import Storage

MAX_MESSAGE_BYTES = 64 * 1024
MAX_WAIT_SECONDS = 30

# Placeholder shipped in install.sh; replaced at serve time when the operator
# sets CHATAGENTS_REPO_URL so `curl <relay>/install.sh | sh` just works.
_INSTALL_PLACEHOLDER = "https://github.com/REPLACE_ME/chat_for_agents.git"


def _db_path():
    return home_dir() / "relay.sqlite"


def _install_script_path() -> Path:
    override = os.environ.get("CHATAGENTS_INSTALL_SH")
    if override:
        return Path(override)
    # src/chatagents/relay/app.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3] / "install.sh"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.storage = Storage(_db_path())
    yield


app = FastAPI(title="chatagents-relay", lifespan=lifespan)


def get_storage() -> Storage:
    return app.state.storage  # type: ignore[attr-defined]


def get_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    return authorization.split(None, 1)[1]


def _auth(storage: Storage, room_id: str, token: str) -> None:
    if not storage.authenticate(room_id, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token for room")


class CreateRoomReq(BaseModel):
    room_token: str = Field(min_length=16, max_length=128)


class CreateRoomResp(BaseModel):
    room_id: str


class PeerReq(BaseModel):
    pubkey: str = Field(min_length=1, max_length=128)


class MessageReq(BaseModel):
    from_pubkey: str
    nonce: str
    ciphertext: str


class MessageResp(BaseModel):
    id: str
    created_at: str


class CreateInviteReq(BaseModel):
    relay: str = Field(min_length=1, max_length=512)
    room_id: str = Field(min_length=1, max_length=64)
    room_token: str = Field(min_length=16, max_length=128)
    pubkey: str = Field(min_length=1, max_length=128)


class CreateInviteResp(BaseModel):
    code: str


class InviteResp(BaseModel):
    relay: str
    room_id: str
    room_token: str
    pubkey: str


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/install.sh")
def install_script():
    """Serve the installer so a new user can `curl <relay>/install.sh | sh`.

    If CHATAGENTS_REPO_URL is set, the placeholder repo URL is substituted so
    the served script points at the real source.
    """
    path = _install_script_path()
    try:
        body = path.read_text()
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "installer not available")
    repo_url = os.environ.get("CHATAGENTS_REPO_URL")
    if repo_url:
        body = body.replace(_INSTALL_PLACEHOLDER, repo_url)
    return Response(content=body, media_type="text/x-shellscript")


@app.post("/rooms", response_model=CreateRoomResp)
def create_room(body: CreateRoomReq, storage: Storage = Depends(get_storage)):
    return {"room_id": storage.create_room(body.room_token)}


@app.post("/invites", response_model=CreateInviteResp)
def create_invite(
    body: CreateInviteReq,
    token: str = Depends(get_token),
    storage: Storage = Depends(get_storage),
):
    if token != body.room_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "bearer token does not match room_token"
        )
    _auth(storage, body.room_id, token)
    code = storage.put_invite(body.model_dump_json())
    return {"code": code}


@app.get("/invites/{code}", response_model=InviteResp)
def get_invite(code: str, storage: Storage = Depends(get_storage)):
    payload = storage.claim_invite(code)
    if not payload:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invite not found or expired")
    return json.loads(payload)


@app.post("/rooms/{room_id}/peers", status_code=204)
def register_peer(
    room_id: str,
    body: PeerReq,
    token: str = Depends(get_token),
    storage: Storage = Depends(get_storage),
):
    _auth(storage, room_id, token)
    err = storage.register_peer(room_id, body.pubkey)
    if err:
        raise HTTPException(status.HTTP_409_CONFLICT, err)


@app.get("/rooms/{room_id}/peers")
def list_peers(
    room_id: str,
    token: str = Depends(get_token),
    storage: Storage = Depends(get_storage),
):
    _auth(storage, room_id, token)
    return {"peers": storage.list_peers(room_id)}


@app.post("/rooms/{room_id}/messages", response_model=MessageResp)
def post_message(
    room_id: str,
    body: MessageReq,
    token: str = Depends(get_token),
    storage: Storage = Depends(get_storage),
):
    _auth(storage, room_id, token)
    try:
        nonce = base64.b64decode(body.nonce)
        ct = base64.b64decode(body.ciphertext)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "nonce/ciphertext must be base64")
    if len(ct) > MAX_MESSAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"message > {MAX_MESSAGE_BYTES} bytes",
        )
    mid, ts = storage.insert_message(room_id, body.from_pubkey, nonce, ct)
    return {"id": mid, "created_at": ts}


@app.get("/rooms/{room_id}/messages")
async def get_messages(
    room_id: str,
    since: str | None = None,
    wait: int = 0,
    token: str = Depends(get_token),
    storage: Storage = Depends(get_storage),
):
    _auth(storage, room_id, token)
    wait = max(0, min(wait, MAX_WAIT_SECONDS))
    loop = asyncio.get_event_loop()
    deadline = loop.time() + wait
    while True:
        rows = storage.list_messages(room_id, since)
        if rows or wait == 0:
            break
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(0.5, remaining))
    msgs = [
        {
            "id": r["id"],
            "from_pubkey": r["from_pubkey"],
            "nonce": base64.b64encode(r["nonce"]).decode(),
            "ciphertext": base64.b64encode(r["ciphertext"]).decode(),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    cursor = msgs[-1]["created_at"] if msgs else since
    return {"messages": msgs, "cursor": cursor}
