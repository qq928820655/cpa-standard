"""mihomo-pool 出口映射与快速分配端点测试。

不依赖真实 mihomo-pool：用本地 HTTP 服务伪装 /api/v1/hub-exits，
覆盖映射拉取、TTL 缓存、失败退空、快速分配的专属口优先与回退逻辑。
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from routers import admin as admin_router  # noqa: E402


class _PoolStub:
    """最小 mihomo-pool 面板替身：固定返回 exits，可切换故障。"""

    def __init__(self):
        self.fail = False
        self.hits = 0
        self.exits = [
            {"port": 7890, "node": "香港HKT", "group": "HUB-FIXED", "kind": "shared", "error": ""},
            {"port": 7891, "node": "轮换组", "group": "HUB-ROTATE", "kind": "shared", "error": ""},
            {"port": 17901, "node": "pro-香港-02", "group": "", "kind": "node", "error": ""},
            {"port": 17902, "node": "直连-新加坡01", "group": "", "kind": "node", "error": ""},
            {"port": 17903, "node": "直连-日本01", "group": "", "kind": "node", "error": "dial timeout"},
        ]

    def handler(self, path):
        if path == "/api/v1/hub-exits":
            self.hits += 1
            if self.fail:
                return (500, [], b'{"error":"boom"}')
            body = json.dumps({"exits": self.exits}).encode()
            return (200, [("Content-Type", "application/json")], body)
        return (404, [], b"{}")


@pytest.fixture()
def pool_stub():
    stub = _PoolStub()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            code, headers, body = stub.handler(self.path)
            self.send_response(code)
            for key, value in headers or []:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield stub, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def client(pool_stub, monkeypatch):
    from config import settings

    stub, base = pool_stub
    monkeypatch.setattr(settings, "master_key", "test-admin-key", raising=False)
    admin_router.export_config["mihomo_pool_url"] = base
    admin_router.export_config["mihomo_pool_token"] = "test-token"
    admin_router._mihomo_exits_cache["at"] = 0.0
    admin_router._mihomo_exits_cache["exits"] = []
    saved_proxy = admin_router.export_config.get("openai_plus_proxy_url")
    yield stub
    admin_router.export_config["mihomo_pool_url"] = ""
    admin_router.export_config["mihomo_pool_token"] = ""
    admin_router.export_config["openai_plus_proxy_url"] = saved_proxy
    admin_router._mihomo_exits_cache["at"] = 0.0
    admin_router._mihomo_exits_cache["exits"] = []


_AUTH = {"Authorization": "Bearer test-admin-key"}


def _admin_client():
    from main import app

    return TestClient(app)


def test_proxy_exits_lists_ports_and_nodes(client):
    with _admin_client() as http:
        resp = http.get(
            "/api/admin/openai-plus/proxy-exits",
            headers=_AUTH,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    ports = {item["port"] for item in data["exits"]}
    assert {7890, 17901, 17902} <= ports
    broken = [item for item in data["exits"] if item["error"]]
    assert broken and broken[0]["port"] == 17903


def test_proxy_exits_cached_within_ttl(client):
    stub = client
    with _admin_client() as http:
        http.get("/api/admin/openai-plus/proxy-exits", headers=_AUTH)
        http.get("/api/admin/openai-plus/proxy-exits", headers=_AUTH)
    assert stub.hits == 1


def test_proxy_exits_degrades_to_empty_on_pool_failure(client):
    stub = client
    stub.fail = True
    admin_router._mihomo_exits_cache["at"] = 0.0
    with _admin_client() as http:
        resp = http.get(
            "/api/admin/openai-plus/proxy-exits",
            headers=_AUTH,
        )
    assert resp.status_code == 200
    assert resp.json()["exits"] == []


def test_quick_assign_picks_online_node_port(client):
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/quick-assign",
            headers=_AUTH,
            json={},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["port"] in (17901, 17902)
    assert data["proxy_url"] == f"http://127.0.0.1:{data['port']}"
    assert data["node"]
    assert admin_router.export_config["openai_plus_proxy_url"] == data["proxy_url"]


def test_quick_assign_excludes_given_port(client):
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/quick-assign",
            headers=_AUTH,
            json={"exclude_port": 17901},
        )
    assert resp.status_code == 200
    assert resp.json()["port"] == 17902


def test_quick_assign_falls_back_to_shared_when_no_node_ports(client):
    stub = client
    stub.exits = [item for item in stub.exits if item["port"] < 17900 and not item["error"]]
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/quick-assign",
            headers=_AUTH,
            json={},
        )
    assert resp.status_code == 200
    assert resp.json()["port"] in (7890, 7891)


def test_quick_assign_404_when_all_offline(client):
    stub = client
    stub.exits = [dict(item, error="down") for item in stub.exits]
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/quick-assign",
            headers=_AUTH,
            json={},
        )
    assert resp.status_code == 404


def test_unconfigured_pool_returns_not_configured(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "master_key", "test-admin-key", raising=False)
    admin_router.export_config["mihomo_pool_url"] = ""
    try:
        with _admin_client() as http:
            resp = http.get(
                "/api/admin/openai-plus/proxy-exits",
                headers=_AUTH,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False and data["exits"] == []
    finally:
        admin_router.export_config["mihomo_pool_url"] = "http://127.0.0.1:8006"
        admin_router.export_config["mihomo_pool_token"] = "test-token"
