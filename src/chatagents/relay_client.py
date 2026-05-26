"""Sync httpx wrapper around the relay HTTP API."""
import base64

import httpx


class RelayClient:
    def __init__(self, base_url: str, room_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.room_token = room_token
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.room_token}"} if self.room_token else {}

    def create_room(self, room_token: str) -> str:
        r = self._client.post(f"{self.base_url}/rooms", json={"room_token": room_token})
        r.raise_for_status()
        return r.json()["room_id"]

    def register_peer(self, room_id: str, pubkey: bytes) -> None:
        r = self._client.post(
            f"{self.base_url}/rooms/{room_id}/peers",
            json={"pubkey": base64.b64encode(pubkey).decode()},
            headers=self._headers(),
        )
        if r.status_code not in (200, 204):
            r.raise_for_status()

    def list_peers(self, room_id: str) -> list[dict]:
        r = self._client.get(
            f"{self.base_url}/rooms/{room_id}/peers", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()["peers"]

    def post_message(
        self, room_id: str, from_pubkey: bytes, nonce: bytes, ciphertext: bytes
    ) -> dict:
        r = self._client.post(
            f"{self.base_url}/rooms/{room_id}/messages",
            json={
                "from_pubkey": base64.b64encode(from_pubkey).decode(),
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            },
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()

    def create_invite(
        self, relay: str, room_id: str, room_token: str, pubkey: bytes
    ) -> str:
        r = self._client.post(
            f"{self.base_url}/invites",
            json={
                "relay": relay,
                "room_id": room_id,
                "room_token": room_token,
                "pubkey": base64.b64encode(pubkey).decode(),
            },
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()["code"]

    def claim_invite(self, code: str) -> dict:
        r = self._client.get(f"{self.base_url}/invites/{code}")
        r.raise_for_status()
        return r.json()

    def get_messages(
        self, room_id: str, since: str | None = None, wait: int = 0
    ) -> dict:
        params: dict = {"wait": wait}
        if since:
            params["since"] = since
        r = self._client.get(
            f"{self.base_url}/rooms/{room_id}/messages",
            params=params,
            headers=self._headers(),
            timeout=httpx.Timeout(max(wait + 10, 60), connect=5.0),
        )
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()
