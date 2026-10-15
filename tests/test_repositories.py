import pytest

from app.repositories import RepositoryConfig, Target, resolve_workspace, select_target


@pytest.mark.parametrize("path", ["../outside", "/absolute", "C:/outside", "backend\\..\\outside"])
def test_target_path_cannot_escape(path):
    with pytest.raises(ValueError):
        Target(name="backend", path=path)


def test_monorepo_requires_target():
    config = RepositoryConfig(targets=[Target(name="backend", stack="springboot"), Target(name="frontend", stack="angular")])
    with pytest.raises(ValueError, match="multiple targets"):
        select_target(config)
    assert select_target(config, "frontend").stack == "angular"
    with pytest.raises(ValueError, match="conflicts"):
        select_target(config, "frontend", "springboot")


def test_target_resolution(tmp_path):
    (tmp_path / "frontend").mkdir()
    assert resolve_workspace(tmp_path, Target(name="frontend", path="frontend")) == str(tmp_path / "frontend")
    with pytest.raises(ValueError):
        resolve_workspace(tmp_path, Target(name="missing", path="missing"))