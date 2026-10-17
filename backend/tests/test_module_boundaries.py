"""모듈 의존 방향 검사(docs/architecture/04-module-map.md의 허용 의존 표).

modules/<패키지>는 표에 있는 모듈과 agent.shared만 import한다. 공급자 SDK는 MOD-07만 쓴다.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "agent"

# 패키지 이름 → 모듈 ID. MOD-08은 프런트엔드라 여기 없다.
PACKAGES = {
    "conversation": "MOD-01",
    "agent_runtime": "MOD-02",
    "tool_execution": "MOD-03",
    "training": "MOD-04",
    "knowledge": "MOD-05",
    "ingestion": "MOD-06",
    "model_integration": "MOD-07",
    "identity_access": "MOD-09",
    "wiki": "MOD-10",
    "retrieval": "MOD-11",
    "it_support": "MOD-12",
}

# 04-module-map.md "허용 의존" 열. 주입 포트(CT-11, CP-06/07)는 agent.shared 계약으로 받는다.
ALLOWED = {
    "MOD-01": {"MOD-02", "MOD-09", "MOD-11", "MOD-12"},
    "MOD-02": {"MOD-03", "MOD-07"},
    "MOD-03": {"MOD-04", "MOD-11", "MOD-12"},
    "MOD-04": set(),
    "MOD-05": {"MOD-07", "MOD-09"},
    "MOD-06": {"MOD-05", "MOD-07"},
    "MOD-07": set(),
    "MOD-09": set(),
    "MOD-10": {"MOD-05", "MOD-07"},
    "MOD-11": {"MOD-05", "MOD-10"},
    "MOD-12": {"MOD-09"},
}

PROVIDER_SDKS = ("anthropic", "google")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def _files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def test_package_table_matches_module_map():
    assert set(PACKAGES.values()) == set(ALLOWED)
    for package in (SRC / "modules").iterdir():
        if package.is_dir() and package.name != "__pycache__":
            assert package.name in PACKAGES, f"모듈 지도에 없는 패키지: {package.name}"


@pytest.mark.parametrize("path", _files(SRC / "modules"), ids=lambda p: p.relative_to(SRC).as_posix())
def test_module_imports_follow_allowed_dependencies(path: Path):
    relative = path.relative_to(SRC / "modules")
    if len(relative.parts) == 1:  # modules/__init__.py
        return
    owner = PACKAGES[relative.parts[0]]
    for name in _imports(path):
        parts = name.split(".")
        if parts[0] in PROVIDER_SDKS:
            assert owner == "MOD-07", f"{path.name}: 공급자 SDK {name}는 MOD-07만 쓴다"
        if parts[0] != "agent":
            continue
        assert parts[1] != "app", f"{path.name}: 모듈이 앱 조립 코드({name})를 import한다"
        if parts[1] == "modules" and len(parts) > 2:
            target = PACKAGES[parts[2]]
            assert target == owner or target in ALLOWED[owner], f"{owner} → {target} 금지: {name}"


@pytest.mark.parametrize("path", _files(SRC / "shared"), ids=lambda p: p.relative_to(SRC).as_posix())
def test_shared_does_not_depend_on_modules_or_app(path: Path):
    for name in _imports(path):
        assert not name.startswith(("agent.modules", "agent.app")), f"{path.name}: {name}"
        assert name.split(".")[0] not in PROVIDER_SDKS


def test_checker_catches_forbidden_import(tmp_path: Path):
    """검사기 자체가 금지 import를 실제로 잡는지 확인한다."""
    bad = tmp_path / "bad.py"
    bad.write_text("from agent.modules.conversation import x\nimport anthropic\n", encoding="utf-8")
    assert _imports(bad) == ["agent.modules.conversation", "anthropic"]
    assert "MOD-01" not in ALLOWED["MOD-12"]
