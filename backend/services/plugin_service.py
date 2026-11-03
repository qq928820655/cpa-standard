"""Optional plugin registry and GitHub Release installer."""
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import threading
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import DATA_DIR


class PluginService:
    ROOT = DATA_DIR / "plugins"
    INSTALLED_DIR = ROOT / "installed"
    REGISTRY_PATH = ROOT / "registry.json"
    MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
    MAX_FILES = 5000
    MAX_UNPACKED_BYTES = 500 * 1024 * 1024
    GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    DEFAULT_GITHUB_REPO = "qq928820655/cpa-standard"

    def _registry(self) -> dict[str, Any]:
        if not self.REGISTRY_PATH.exists():
            return {"github_repo": self.DEFAULT_GITHUB_REPO, "plugins": {}}
        try:
            value = json.loads(self.REGISTRY_PATH.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {"github_repo": "", "plugins": {}}
        except (OSError, json.JSONDecodeError):
            return {"github_repo": self.DEFAULT_GITHUB_REPO, "plugins": {}}

    def _save_registry(self, registry: dict[str, Any]) -> None:
        self.ROOT.mkdir(parents=True, exist_ok=True)
        temp = self.REGISTRY_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.REGISTRY_PATH)

    def get_source(self) -> dict[str, str]:
        configured = str(self._registry().get("github_repo") or "").strip()
        return {"github_repo": configured or self.DEFAULT_GITHUB_REPO}

    def set_source(self, github_repo: str) -> dict[str, str]:
        normalized = github_repo.strip().removesuffix("/")
        if normalized.startswith("https://github.com/"):
            normalized = normalized.removeprefix("https://github.com/")
        if not self.GITHUB_REPO_PATTERN.fullmatch(normalized):
            raise ValueError("GitHub repository must use owner/repo format")
        registry = self._registry()
        registry["github_repo"] = normalized
        self._save_registry(registry)
        return {"github_repo": normalized}

    def _discover_local_plugins(self) -> None:
        if not self.INSTALLED_DIR.is_dir():
            return
        registry = self._registry()
        plugins = registry.setdefault("plugins", {})
        changed = False
        for root in self.INSTALLED_DIR.iterdir():
            if not root.is_dir() or root.name.endswith(".backup") or root.name in plugins:
                continue
            manifest_path = root / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                plugin_id = str(manifest.get("id") or "")
                files = manifest.get("files")
                if plugin_id != root.name or not isinstance(files, dict):
                    continue
                if not all(self._safe_member(str(path)) for path in files):
                    continue
                declared_paths = {str(path) for path in files}
                actual_paths = {
                    path.relative_to(root).as_posix()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                if actual_paths != declared_paths | {"manifest.json"}:
                    continue
                if any(not (root / str(path)).is_file() or hashlib.sha256((root / str(path)).read_bytes()).hexdigest().lower() != str(digest).lower() for path, digest in files.items()):
                    continue
                entry = str(manifest.get("backend_entry") or "")
                if not entry or not (root / entry.partition(":")[0]).is_file():
                    continue
                plugins[plugin_id] = {
                    "version": str(manifest.get("version") or ""),
                    "enabled": True,
                    "backend_entry": entry,
                    "frontend_entry": str(manifest.get("frontend_entry") or ""),
                    "frontend_css": str(manifest.get("frontend_css") or ""),
                    "archive_sha256": "",
                    "restart_required": True,
                    "load_error": "",
                }
                changed = True
            except (OSError, json.JSONDecodeError):
                continue
        if changed:
            self._save_registry(registry)

    def list_installed(self) -> list[dict[str, Any]]:
        self._discover_local_plugins()
        plugins = self._registry().get("plugins") or {}
        return [dict({"id": plugin_id}, **value) for plugin_id, value in plugins.items() if isinstance(value, dict)]

    def list_releases(self) -> list[dict[str, Any]]:
        repo = self.get_source()["github_repo"]
        if not repo:
            raise ValueError("GitHub repository is not configured")
        request = Request(
            f"https://api.github.com/repos/{repo}/releases",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "CPA-Plugin-Installer"},
        )
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Unexpected GitHub Release response")
        return [
            {
                "tag_name": str(item.get("tag_name") or ""),
                "name": str(item.get("name") or item.get("tag_name") or ""),
                "published_at": item.get("published_at"),
                "assets": [
                    {"name": str(asset.get("name") or ""), "size": int(asset.get("size") or 0), "download_url": str(asset.get("browser_download_url") or "")}
                    for asset in item.get("assets") or []
                    if isinstance(asset, dict)
                ],
            }
            for item in payload
            if isinstance(item, dict)
        ]

    @staticmethod
    def _safe_member(name: str) -> bool:
        normalized = name.replace("\\", "/")
        path = Path(normalized)
        return bool(normalized) and not normalized.startswith("/") and not re.match(r"^[A-Za-z]:/", normalized) and not path.is_absolute() and ".." not in path.parts

    def _read_manifest(self, archive: zipfile.ZipFile) -> dict[str, Any]:
        try:
            value = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Plugin archive requires a valid manifest.json") from exc
        if not isinstance(value, dict):
            raise ValueError("Plugin manifest must be an object")
        for key in ("id", "version", "backend_entry", "files"):
            if not value.get(key):
                raise ValueError(f"Plugin manifest missing {key}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", str(value["id"])):
            raise ValueError("Plugin id is invalid")
        if not isinstance(value["files"], dict):
            raise ValueError("Plugin manifest files must be an object")
        return value

    def install_archive(self, archive_path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
        if archive_path.stat().st_size > self.MAX_ARCHIVE_BYTES:
            raise ValueError("Plugin archive is too large")
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise ValueError("Plugin archive checksum mismatch")
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > self.MAX_FILES or any(not self._safe_member(item.filename) for item in infos):
                raise ValueError("Plugin archive contains unsafe files")
            if sum(item.file_size for item in infos) > self.MAX_UNPACKED_BYTES:
                raise ValueError("Plugin archive expands beyond allowed size")
            manifest = self._read_manifest(archive)
            expected_files = {str(path): str(digest) for path, digest in manifest["files"].items()}
            if not all(self._safe_member(path) for path in expected_files):
                raise ValueError("Plugin manifest contains unsafe paths")
            actual_files = {item.filename for item in infos if not item.is_dir()}
            if actual_files != set(expected_files) | {"manifest.json"}:
                raise ValueError("Plugin archive files do not match manifest")
            for path, expected in expected_files.items():
                actual = hashlib.sha256(archive.read(path)).hexdigest()
                if actual.lower() != expected.lower():
                    raise ValueError(f"Plugin file checksum mismatch: {path}")
            target = self.INSTALLED_DIR / str(manifest["id"])
            self.ROOT.mkdir(parents=True, exist_ok=True)
            self.INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.ROOT) as temp_dir:
                unpacked = Path(temp_dir) / "plugin"
                archive.extractall(unpacked)
                backup = target.with_name(f"{target.name}.backup")
                if backup.exists():
                    shutil.rmtree(backup)
                if target.exists():
                    target.replace(backup)
                try:
                    unpacked.replace(target)
                except Exception:
                    if backup.exists():
                        backup.replace(target)
                    raise
                if backup.exists():
                    shutil.rmtree(backup)
        registry = self._registry()
        plugins = registry.setdefault("plugins", {})
        plugins[str(manifest["id"])] = {
            "version": str(manifest["version"]),
            "enabled": True,
            "backend_entry": str(manifest["backend_entry"]),
            "frontend_entry": str(manifest.get("frontend_entry") or ""),
            "frontend_css": str(manifest.get("frontend_css") or ""),
            "archive_sha256": digest,
            "restart_required": True,
            "load_error": "",
        }
        self._save_registry(registry)
        return {"id": manifest["id"], "version": manifest["version"], "restart_required": True}

    def install_release(self, tag_name: str, plugin_id: str = "video-world") -> dict[str, Any]:
        release = next((item for item in self.list_releases() if item["tag_name"] == tag_name), None)
        if not release:
            raise ValueError("Plugin release was not found")
        assets = release["assets"]
        archive = next((item for item in assets if item["name"].endswith(".zip") and plugin_id in item["name"]), None)
        checksum = next((item for item in assets if item["name"].endswith(".sha256") and plugin_id in item["name"]), None)
        if not archive or not checksum:
            raise ValueError("Release must include plugin ZIP and SHA-256 assets")
        for item in (archive, checksum):
            host = urlparse(item["download_url"]).hostname or ""
            if host not in {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}:
                raise ValueError("Plugin asset host is not trusted")
        if archive["size"] <= 0 or archive["size"] > self.MAX_ARCHIVE_BYTES:
            raise ValueError("Plugin archive exceeds allowed size")
        self.ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.ROOT) as temp_dir:
            temp = Path(temp_dir)
            archive_path = temp / archive["name"]
            with urlopen(Request(archive["download_url"], headers={"User-Agent": "CPA-Plugin-Installer"}), timeout=60) as response:
                archive_path.write_bytes(response.read(self.MAX_ARCHIVE_BYTES + 1))
            if archive_path.stat().st_size > self.MAX_ARCHIVE_BYTES:
                raise ValueError("Plugin archive exceeds allowed size")
            with urlopen(Request(checksum["download_url"], headers={"User-Agent": "CPA-Plugin-Installer"}), timeout=20) as response:
                expected = response.read(1024).decode("utf-8").strip().split()[0]
            if not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
                raise ValueError("Plugin checksum asset is invalid")
            return self.install_archive(archive_path, expected)

    def restart_strategy(self) -> dict[str, Any]:
        package_root = DATA_DIR.parent.parent
        if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
            return {"restart_required": True, "restart_scheduled": False, "message": "Plugin installed. Restart the container through its orchestrator."}
        script = package_root / ("restart.bat" if sys.platform == "win32" else "restart.sh")
        if script.is_file():
            return {"restart_required": True, "restart_scheduled": True, "script": str(script), "message": "Plugin installed. CPA will restart automatically."}
        return {"restart_required": True, "restart_scheduled": False, "message": "Plugin installed. Restart CPA to load it."}

    def schedule_restart(self) -> dict[str, Any]:
        strategy = self.restart_strategy()
        if not strategy["restart_scheduled"]:
            return strategy
        script = strategy["script"]
        def run() -> None:
            time.sleep(1)
            subprocess.Popen([script] if sys.platform == "win32" else ["/bin/bash", script], cwd=str(Path(script).parent), close_fds=sys.platform != "win32")
        threading.Thread(target=run, daemon=True).start()
        return strategy

    def enabled_plugins(self) -> list[tuple[dict[str, Any], Path]]:
        result = []
        for item in self.list_installed():
            if item.get("enabled"):
                root = self.INSTALLED_DIR / str(item["id"])
                if root.is_dir():
                    result.append((item, root))
        return result

    def list_frontend_plugins(self) -> list[dict[str, str]]:
        result = []
        for item, root in self.enabled_plugins():
            entry = str(item.get("frontend_entry") or "")
            stylesheet = str(item.get("frontend_css") or "")
            if not entry or not self._safe_member(entry) or not (root / entry).is_file():
                continue
            if stylesheet and (not self._safe_member(stylesheet) or not (root / stylesheet).is_file()):
                stylesheet = ""
            plugin_id = str(item["id"])
            result.append({
                "id": plugin_id,
                "entry_url": f"/api/admin/plugins/{plugin_id}/frontend/{entry}",
                "css_url": f"/api/admin/plugins/{plugin_id}/frontend/{stylesheet}" if stylesheet else "",
            })
        return result

    def frontend_file(self, plugin_id: str, path: str) -> Path:
        if not self._safe_member(path):
            raise ValueError("Plugin frontend path is invalid")
        item = next((item for item in self.list_installed() if item.get("id") == plugin_id and item.get("enabled")), None)
        if not item:
            raise ValueError("Plugin is not enabled")
        root = self.INSTALLED_DIR / plugin_id
        target = root / path
        if not target.is_file() or not target.is_relative_to(root):
            raise ValueError("Plugin frontend file was not found")
        return target

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", plugin_id):
            raise ValueError("Plugin id is invalid")
        registry = self._registry()
        item = (registry.get("plugins") or {}).get(plugin_id)
        root = self.INSTALLED_DIR / plugin_id
        if not isinstance(item, dict) or not root.is_dir():
            raise ValueError("Plugin is not installed")
        item["enabled"] = enabled
        item["restart_required"] = True
        self._save_registry(registry)
        return {"id": plugin_id, "enabled": enabled, "restart_required": True}

    def uninstall(self, plugin_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", plugin_id):
            raise ValueError("Plugin id is invalid")
        registry = self._registry()
        plugins = registry.get("plugins") or {}
        root = self.INSTALLED_DIR / plugin_id
        if plugin_id not in plugins or not root.is_dir() or root.parent != self.INSTALLED_DIR:
            raise ValueError("Plugin is not installed")
        shutil.rmtree(root)
        plugins.pop(plugin_id, None)
        registry["plugins"] = plugins
        self._save_registry(registry)
        return {"id": plugin_id, "data_retained": True, "restart_required": True, "message": "Plugin code was removed. Business data was retained."}

    def _load_module(self, item: dict[str, Any], root: Path) -> Any:
        module_path, separator, factory_name = str(item["backend_entry"]).partition(":")
        if not separator or not module_path.endswith(".py") or not self._safe_member(module_path):
            raise ValueError("Plugin backend entry is invalid")
        source = root / module_path
        if not source.is_file():
            raise ValueError("Plugin backend entry is missing")
        module_name = f"cpa_plugin_{item['id'].replace('-', '_')}_{hashlib.sha256(str(root).encode()).hexdigest()[:12]}"
        module = sys.modules.get(module_name)
        if module is None:
            spec = importlib.util.spec_from_file_location(
                module_name,
                source,
                submodule_search_locations=[str(source.parent)],
            )
            if not spec or not spec.loader:
                raise ValueError("Plugin backend module cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        return module

    def load_plugin_models(self) -> None:
        for item, root in self.enabled_plugins():
            try:
                module = self._load_module(item, root)
                factory = getattr(module, "register_models", None)
                if callable(factory):
                    factory()
            except Exception as exc:
                registry = self._registry()
                registry.setdefault("plugins", {}).setdefault(str(item["id"]), {})["load_error"] = str(exc)[:1000]
                self._save_registry(registry)

    async def migrate_plugins(self) -> None:
        for item, root in self.enabled_plugins():
            try:
                module = self._load_module(item, root)
                migration = getattr(module, "migrate", None)
                if callable(migration):
                    await migration()
            except Exception as exc:
                registry = self._registry()
                registry.setdefault("plugins", {}).setdefault(str(item["id"]), {})["load_error"] = str(exc)[:1000]
                self._save_registry(registry)

    def load_backend_plugins(self, app: Any) -> None:
        for item, root in self.enabled_plugins():
            try:
                module = self._load_module(item, root)
                factory_name = str(item["backend_entry"]).partition(":")[2]
                factory = getattr(module, factory_name)
                factory(app)
                registry = self._registry()
                registry.setdefault("plugins", {}).setdefault(str(item["id"]), {})["load_error"] = ""
                self._save_registry(registry)
            except Exception as exc:
                registry = self._registry()
                registry.setdefault("plugins", {}).setdefault(str(item["id"]), {})["load_error"] = str(exc)[:1000]
                self._save_registry(registry)


plugin_service = PluginService()
