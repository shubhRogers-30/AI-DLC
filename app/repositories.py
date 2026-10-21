from pathlib import Path, PurePosixPath
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.stacks import stacks


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    path: str = "."
    stack: str | None = None

    @field_validator("path")
    @classmethod
    def safe_path(cls, value):
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
            raise ValueError("Target must be a relative directory inside the repository")
        return value

    @field_validator("stack")
    @classmethod
    def supported_stack(cls, value):
        if value:
            stacks.get(value)
        return value


class QualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sonar_project_key: str = Field(min_length=1)
    sonar_workflow: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.ya?ml$")
    codeql_workflow: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.ya?ml$")


class RepositoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    enabled: bool = False
    targets: list[Target] = Field(default_factory=lambda: [Target(name="default")], min_length=1)
    quality: QualityConfig | None = None
    setup_blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_targets(self):
        names = [target.name for target in self.targets]
        if len(names) != len(set(names)):
            raise ValueError("Target names must be unique")
        return self

    @property
    def workflow_ready(self):
        return self.enabled and self.quality is not None and not self.setup_blockers


def select_target(config, name=None, stack=None):
    if len(config.targets) > 1 and not name:
        raise ValueError("Repository has multiple targets; specify target")
    target = next((item for item in config.targets if name is None or item.name == name), None)
    if target is None:
        raise ValueError("Unknown repository target")
    if stack and target.stack and stack != target.stack:
        raise ValueError("Requested stack conflicts with the repository target")
    if stack:
        stacks.get(stack)
    return target


def resolve_workspace(root, target):
    root = Path(root).resolve()
    workspace = (root / target.path).resolve()
    if not workspace.is_relative_to(root) or not workspace.is_dir():
        raise ValueError("Target directory does not exist or escapes the repository")
    return str(workspace)


class RepositoryRegistry:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(__file__).resolve().parents[1] / "config" / "repositories.json"
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.organization = data.get("organization", "")
        self.repositories = {
            name.casefold(): RepositoryConfig.model_validate(config)
            for name, config in data.get("repositories", {}).items()
        }

    def get(self, repository):
        return self.repositories.get(repository.casefold(), RepositoryConfig())

    def is_approved(self, repository):
        config = self.repositories.get(repository.casefold())
        return bool(config and config.enabled)


repository_registry = RepositoryRegistry()