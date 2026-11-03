"""Plugin service safety tests."""
import json
import tempfile
import unittest
from pathlib import Path

from services.plugin_service import PluginService


class PluginServiceTests(unittest.TestCase):
    def test_default_source_uses_cpa_repository(self):
        service = PluginService()
        self.assertEqual(service.DEFAULT_GITHUB_REPO, "qq928820655/cpa-standard")

    def test_rejects_invalid_repository_name(self):
        service = PluginService()
        with self.assertRaises(ValueError):
            service.set_source("https://example.com/not-github")

    def test_rejects_unsafe_archive_members(self):
        self.assertFalse(PluginService._safe_member("../outside.py"))
        self.assertFalse(PluginService._safe_member("/absolute.py"))
        self.assertTrue(PluginService._safe_member("backend/plugin_entry.py"))

    def test_enable_and_disable_only_update_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self._make_service(temp_dir, "demo-plugin")
            plugin_file = service.INSTALLED_DIR / "demo-plugin" / "plugin.py"
            plugin_file.write_text("plugin", encoding="utf-8")

            result = service.set_enabled("demo-plugin", False)
            self.assertFalse(result["enabled"])
            self.assertTrue(plugin_file.exists())
            self.assertFalse(service._registry()["plugins"]["demo-plugin"]["enabled"])

            result = service.set_enabled("demo-plugin", True)
            self.assertTrue(result["enabled"])
            self.assertTrue(plugin_file.exists())
            self.assertTrue(service._registry()["plugins"]["demo-plugin"]["enabled"])

    def test_uninstall_removes_only_plugin_code_and_retains_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self._make_service(temp_dir, "demo-plugin")
            plugin_file = service.INSTALLED_DIR / "demo-plugin" / "plugin.py"
            plugin_file.write_text("plugin", encoding="utf-8")
            sentinel = service.ROOT / "business-data.sentinel"
            sentinel.write_text("retain", encoding="utf-8")

            result = service.uninstall("demo-plugin")

            self.assertTrue(result["data_retained"])
            self.assertFalse(plugin_file.parent.exists())
            self.assertTrue(sentinel.exists())
            self.assertNotIn("demo-plugin", service._registry()["plugins"])

    def test_lifecycle_rejects_invalid_or_missing_plugins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self._make_service(temp_dir, "demo-plugin")
            with self.assertRaises(ValueError):
                service.set_enabled("../outside", False)
            with self.assertRaises(ValueError):
                service.uninstall("missing-plugin")

    @staticmethod
    def _make_service(temp_dir, plugin_id):
        root = Path(temp_dir) / "plugins"
        installed = root / "installed" / plugin_id
        installed.mkdir(parents=True)
        registry_path = root / "registry.json"
        registry_path.write_text(json.dumps({
            "github_repo": PluginService.DEFAULT_GITHUB_REPO,
            "plugins": {
                plugin_id: {
                    "version": "1.0.0",
                    "enabled": True,
                    "restart_required": False,
                }
            },
        }), encoding="utf-8")
        service = PluginService()
        service.ROOT = root
        service.INSTALLED_DIR = root / "installed"
        service.REGISTRY_PATH = registry_path
        return service


if __name__ == "__main__":
    unittest.main()
