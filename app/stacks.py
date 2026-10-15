import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StackProfile:
    name: str
    display_name: str
    guidance: str
    codeql_language: str
    commands: dict[str, list[list[str]]]
    detection: list[dict]

    def checks(self, workspace: str) -> list[list[str]]:
        root = Path(workspace)
        tool = next((marker for marker in self.commands if marker != "default" and (root / marker).is_file()), "default")
        if tool not in self.commands:
            raise ValueError(f"No supported build file found for stack {self.name}")
        return self.commands[tool]


class StackRegistry:
    def __init__(self, directory=None):
        directory = Path(directory) if directory else Path(__file__).resolve().parent.parent / "stacks"
        self.profiles = {}
        for path in sorted(directory.glob("*.json")):
            profile = StackProfile(**json.loads(path.read_text(encoding="utf-8")))
            if not profile.commands or any(
                not commands or any(not command or not all(isinstance(arg, str) for arg in command) for command in commands)
                for commands in profile.commands.values()
            ):
                raise ValueError(f"Invalid command profile: {profile.name}")
            self.profiles[profile.name] = profile

    def get(self, name):
        if name not in self.profiles:
            raise ValueError(f"Unsupported stack: {name}")
        return self.profiles[name]

    def detect(self, workspace):
        root = Path(workspace)
        matches = [profile.name for profile in self.profiles.values()
                   if any(self._matches(root, rule) for rule in profile.detection)]
        if len(matches) != 1:
            raise ValueError("Stack is unsupported or ambiguous; configure a target and stack explicitly")
        return self.get(matches[0])

    @staticmethod
    def _matches(root, rule):
        if not all((root / name).is_file() for name in rule.get("files", [])):
            return False
        for name, content in rule.get("contains", {}).items():
            path = root / name
            if not path.is_file() or content not in path.read_text(encoding="utf-8"):
                return False
        dependencies = rule.get("dependencies", [])
        if dependencies:
            path = root / "package.json"
            if not path.is_file():
                return False
            package = json.loads(path.read_text(encoding="utf-8"))
            installed = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
            if not all(dependency in installed for dependency in dependencies):
                return False
        return bool(rule)


stacks = StackRegistry()