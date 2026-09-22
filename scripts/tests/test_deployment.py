import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("deployment", Path(__file__).resolve().parents[1] / "support/deployment.py")
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source, self.destination = self.root / "source", self.root / "app"
        self.source.mkdir()
        self.destination.mkdir()
        (self.source / "services").mkdir()
        (self.source / "services/__init__.py").write_text("new package")
        (self.destination / "services.py").write_text("legacy module")

    def test_module_to_package_deployment_removes_obsolete_module_and_preserves_data(self):
        data = self.root / "data"
        data.mkdir()
        (data / "registry.sqlite").write_text("user data")
        deployment.replace_code_tree(self.source, self.destination)
        self.assertFalse((self.destination / "services.py").exists())
        self.assertEqual((self.destination / "services/__init__.py").read_text(), "new package")
        self.assertEqual((data / "registry.sqlite").read_text(), "user data")
        self.assertFalse(list(self.root.glob(".app-deploy-*")))

    def test_failed_copy_leaves_original_module_in_place(self):
        with patch.object(deployment.shutil, "copytree", side_effect=OSError("disk full")), self.assertRaises(OSError):
            deployment.replace_code_tree(self.source, self.destination)
        self.assertEqual((self.destination / "services.py").read_text(), "legacy module")

    def test_failed_swap_restores_previous_source(self):
        replace = Path.replace
        def fail_new(source, target):
            if source.name == "next":
                raise OSError("swap failed")
            return replace(source, target)
        with patch.object(Path, "replace", fail_new), self.assertRaises(OSError):
            deployment.replace_code_tree(self.source, self.destination)
        self.assertEqual((self.destination / "services.py").read_text(), "legacy module")

    def test_same_source_or_symlink_destination_is_rejected(self):
        with self.assertRaises(ValueError):
            deployment.replace_code_tree(self.source, self.source)
        link = self.root / "linked-app"
        link.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaises(ValueError):
            deployment.replace_code_tree(self.source, link)
        self.assertEqual((self.destination / "services.py").read_text(), "legacy module")


if __name__ == "__main__":
    unittest.main()
