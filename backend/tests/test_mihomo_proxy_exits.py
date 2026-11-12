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
    # 测试期间禁止真实落盘：quick-assign 会调 persist_export_config，
    # 不 patch 会把测试地址写进 backend/data/export_config.json
    monkeypatch.setattr(admin_router, "persist_export_config", lambda: None)
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


def test_probe_requires_configured_pool(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "master_key", "test-admin-key", raising=False)
    admin_router.export_config["mihomo_pool_url"] = ""
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/probe",
            headers=_AUTH,
        )
    assert resp.status_code == 400


def test_probe_returns_empty_when_no_online_exits(client):
    stub = client
    stub.exits = [dict(item, error="down") for item in stub.exits]
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/probe",
            headers=_AUTH,
        )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


class _ControllerStub:
    """最小 mihomo 内核 controller 替身：/proxies /configs /delay PUT 切组。"""

    def __init__(self):
        self.proxies = {
            "GLOBAL": {"type": "Selector", "now": "香港01", "all": ["香港01", "美国01", "HUB-FIXED"]},
            "HUB-FIXED": {"type": "Selector", "now": "香港01", "all": ["香港01"]},
            "🚀 节点选择": {
                "type": "Selector",
                "now": "香港01",
                "all": ["香港01", "美国01", "日本01", "DIRECT", "REJECT", "HUB-FIXED"],
                "history": [{"time": "t", "mean_delay": 234}],
            },
            "香港01": {"type": "Vless", "alive": True, "history": [{"time": "t", "mean_delay": 234}]},
            "美国01": {"type": "Vmess", "alive": True, "history": [{"time": "t", "mean_delay": 567}]},
            "日本01": {"type": "Trojan", "alive": False, "history": []},
            "DIRECT": {"type": "Direct", "alive": True, "history": []},
            "REJECT": {"type": "Reject", "alive": True, "history": []},
        }
        self.switched = []
        self.delay_map = {"香港01": 234, "美国01": 567}

    def handler(self, path, method="GET", body=None):
        if "?" in path:
            path = path.split("?", 1)[0]
        if method == "PUT" and path.startswith("/proxies/"):
            import urllib.parse as _up
            group = _up.unquote(path[len("/proxies/"):])
            self.switched.append((group, (body or {}).get("name")))
            return (204, [], b"")
        if path == "/version":
            return (200, [("Content-Type", "application/json")], b'{"meta":true,"version":"test"}')
        if path == "/configs":
            body = json.dumps({"mixed-port": 7890, "socks-port": 0, "port": 0}).encode()
            return (200, [("Content-Type", "application/json")], body)
        if path == "/proxies":
            payload = json.dumps({"proxies": self.proxies}).encode()
            return (200, [("Content-Type", "application/json")], payload)
        if path.startswith("/proxies/") and path.endswith("/delay"):
            name = path[len("/proxies/"):-len("/delay")]
            import urllib.parse as _up
            name = _up.unquote(name)
            ms = self.delay_map.get(name)
            if ms is None:
                return (504, [], b'{"message":"timeout"}')
            payload = json.dumps({"delay": ms}).encode()
            return (200, [("Content-Type", "application/json")], payload)
        return (404, [], b"{}")


@pytest.fixture()
def controller_client(pool_stub, monkeypatch):
    from config import settings

    _, _base = pool_stub
    controller = _ControllerStub()

    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode() or "{}") if length else {}
            code, headers, payload = controller.handler(self.path, self.command, body)
            self.send_response(code)
            for key, value in headers or []:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_PUT = _handle

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(settings, "master_key", "test-admin-key", raising=False)
    monkeypatch.setattr(admin_router, "persist_export_config", lambda: None)
    admin_router.export_config["mihomo_pool_url"] = ""
    admin_router.export_config["mihomo_pool_token"] = ""
    admin_router.export_config["clash_controller_url"] = f"http://127.0.0.1:{server.server_address[1]}"
    admin_router.export_config["clash_controller_secret"] = "ctrl-secret"
    admin_router.export_config["clash_shared_ports"] = ""
    admin_router.export_config["clash_main_group"] = ""
    admin_router._controller_cache.update({"at": 0.0, "exits": [], "group": "", "shared_port": None, "nodes": []})
    saved_proxy = admin_router.export_config.get("openai_plus_proxy_url")
    yield controller
    admin_router.export_config["clash_controller_url"] = ""
    admin_router.export_config["clash_controller_secret"] = ""
    admin_router.export_config["clash_shared_ports"] = ""
    admin_router.export_config["clash_main_group"] = ""
    admin_router.export_config["openai_plus_proxy_url"] = saved_proxy
    admin_router._controller_cache.update({"at": 0.0, "exits": [], "group": "", "shared_port": None, "nodes": []})
    server.shutdown()


def test_controller_exits_lists_shared_and_switch_items(controller_client):
    with _admin_client() as http:
        resp = http.get("/api/admin/openai-plus/proxy-exits", headers=_AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "controller"
    assert data["configured"] is True
    # 主组选择：GLOBAL 与含 HUB- 前缀的组被排除，🚀 节点选择 胜出
    assert data["switch_group"] == "🚀 节点选择"
    assert data["shared_port"] == 7890
    shared = [item for item in data["exits"] if item["kind"] == "shared"]
    switches = [item for item in data["exits"] if item["kind"] == "switch"]
    assert len(shared) == 1 and shared[0]["port"] == 7890
    switch_names = {item["node"] for item in switches}
    # 虚拟节点与组引用被过滤，只留真实节点
    assert switch_names == {"香港01", "美国01", "日本01"}
    assert any(item["history_ms"] == 234 for item in data["exits"])


def test_controller_switch_calls_kernel(controller_client):
    controller = controller_client
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/switch",
            headers=_AUTH,
            json={"node": "美国01"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True and data["node"] == "美国01"
    assert data["proxy_url"] == "http://127.0.0.1:7890"
    assert controller.switched == [("🚀 节点选择", "美国01")]


def test_controller_quick_assign_switches_group(controller_client):
    controller = controller_client
    with _admin_client() as http:
        resp = http.post(
            "/api/admin/openai-plus/proxy-exits/quick-assign",
            headers=_AUTH,
            json={},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["port"] == 7890
    assert data["node"] in {"香港01", "美国01", "日本01"}
    assert controller.switched and controller.switched[0][0] == "🚀 节点选择"
    assert admin_router.export_config["openai_plus_proxy_url"] == "http://127.0.0.1:7890"


def test_controller_probe_uses_kernel_delay(controller_client):
    with _admin_client() as http:
        resp = http.post("/api/admin/openai-plus/proxy-exits/probe", headers=_AUTH)
    assert resp.status_code == 200
    by_node = {item["node"]: item for item in resp.json()["results"]}
    assert by_node["香港01"]["ok"] is True and by_node["香港01"]["ms"] == 234
    # alive=False 的节点（日本01）被标记 unreachable，直接排除出探测
    assert "日本01" not in by_node
    assert by_node["美国01"]["ms"] == 567


def test_pool_source_wins_when_both_configured(pool_stub, monkeypatch):
    from config import settings

    _, base = pool_stub
    monkeypatch.setattr(settings, "master_key", "test-admin-key", raising=False)
    monkeypatch.setattr(admin_router, "persist_export_config", lambda: None)
    admin_router.export_config["clash_controller_url"] = "http://127.0.0.1:1"
    admin_router.export_config["mihomo_pool_url"] = base
    admin_router.export_config["mihomo_pool_token"] = "t"
    try:
        assert admin_router._pick_exits_source() == "pool"
    finally:
        admin_router.export_config["mihomo_pool_url"] = ""
        admin_router.export_config["mihomo_pool_token"] = ""
        admin_router.export_config["clash_controller_url"] = ""


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
