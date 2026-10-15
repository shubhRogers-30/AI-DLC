import json
import tempfile
import unittest
from pathlib import Path

from app.stacks import StackRegistry


class StackTests(unittest.TestCase):
    def test_registered_stacks_and_unknown_stack(self):
        registry = StackRegistry()
        self.assertEqual(registry.get("angular").codeql_language, "javascript-typescript")
        with self.assertRaises(ValueError):
            registry.get("unknown")

    def test_detect_angular(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "angular.json").write_text("{}", encoding="utf-8")
            (root / "package.json").write_text(json.dumps({"dependencies": {"@angular/core": "20"}}), encoding="utf-8")
            self.assertEqual(StackRegistry().detect(directory).name, "angular")

    def test_maven_is_not_necessarily_springboot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pom.xml").write_text("plain maven", encoding="utf-8")
            with self.assertRaises(ValueError):
                StackRegistry().detect(directory)
            (root / "pom.xml").write_text("org.springframework.boot", encoding="utf-8")
            self.assertEqual(StackRegistry().detect(directory).name, "springboot")

    def test_ambiguous_stack_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "angular.json").write_text("{}", encoding="utf-8")
            (root / "package.json").write_text(json.dumps({"dependencies": {"@angular/core": "20"}}), encoding="utf-8")
            (root / "pom.xml").write_text("org.springframework.boot", encoding="utf-8")
            with self.assertRaises(ValueError):
                StackRegistry().detect(directory)

    def test_new_stack_requires_only_a_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "profiles"
            profiles.mkdir()
            (profiles / "python.json").write_text(json.dumps({
                "name": "python", "display_name": "Python", "guidance": "Use existing Python conventions",
                "codeql_language": "python", "commands": {"default": [["python", "-m", "pytest"]]},
                "detection": [{"files": ["pyproject.toml"]}],
            }), encoding="utf-8")
            (root / "pyproject.toml").write_text("", encoding="utf-8")
            registry = StackRegistry(profiles)
            self.assertEqual(registry.detect(root).name, "python")
            self.assertEqual(registry.get("python").checks(root), [["python", "-m", "pytest"]])