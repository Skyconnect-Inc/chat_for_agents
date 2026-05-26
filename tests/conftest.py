"""Shared pytest fixtures."""
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def relay(tmp_path):
    """Spin a real uvicorn-served FastAPI relay in a background thread."""
    relay_home = tmp_path / "relay"
    relay_home.mkdir()
    old = os.environ.get("CHATAGENTS_HOME")
    os.environ["CHATAGENTS_HOME"] = str(relay_home)
    port = _free_port()
    config = uvicorn.Config(
        "chatagents.relay.app:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if httpx.get(f"{url}/healthz", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("relay did not start")
    try:
        yield {"url": url, "home": relay_home}
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if old is None:
            os.environ.pop("CHATAGENTS_HOME", None)
        else:
            os.environ["CHATAGENTS_HOME"] = old
