import pytest

from app.repositories import RepositoryConfig, RepositoryRegistry, Target, resolve_workspace, select_target


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


def test_central_registry_approves_requested_repositories_and_reports_quality_gaps():
    registry = RepositoryRegistry()
    doat = registry.get("RogersCommunications/DOAT-Client-UI")
    msst = registry.get("RogersCommunications/msst-ui")
    assert registry.is_approved("RogersCommunications/DOAT-Client-UI")
    assert registry.is_approved("RogersCommunications/msst-ui")
    assert doat.targets[0].stack == "angular"
    assert msst.targets[0].stack is None
    assert doat.quality is None and doat.setup_blockers
    assert msst.quality is None and msst.setup_blockers
    assert not registry.is_approved("RogersCommunications/unregistered")