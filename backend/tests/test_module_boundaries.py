"""모듈 의존 방향 검사(docs/architecture/04-module-map.md의 허용 의존 표).

- modules/<패키지>는 표에 있는 모듈과 agent.shared만 import한다. 앱 조립 코드(agent.app)는 import하지 않는다.
- 공급자 SDK(anthropic, google)는 MOD-07만 쓴다.
- shared는 modules·app·공급자 SDK를 import하지 않는다.
- 허용 표는 손으로 옮기지 않고 문서 표를 직접 읽는다(문서가 바뀌면 검사도 따라 바뀐다).
"""

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "agent"
MODULE_MAP = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "04-module-map.md"

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
PROVIDER_SDKS = ("anthropic", "google")


def load_allowed() -> dict[str, set[str]]:
    """`| MOD-02 | 03, 07, 주입 …` 행에서 쉼표로 나뉜 두 자리 숫자만 모듈 ID로 읽는다.

    "주입 CP-06/07 읽기 포트"처럼 숫자가 섞인 설명 칸은 모듈 의존이 아니므로 건너뛴다.
    """
    allowed: dict[str, set[str]] = {}
    for line in MODULE_MAP.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*(MOD-\d\d)\s*\|([^|]*)\|", line)
        if not match or match.group(1) == "MOD-08":
            continue
        deps = {
            f"MOD-{token.strip()}"
            for token in match.group(2).split(",")
            if re.fullmatch(r"\d\d", token.strip())
        }
        allowed.setdefault(match.group(1), set()).update(deps)
    return allowed


ALLOWED = load_allowed()


def _module_of(path: Path) -> list[str]:
    """src/agent/... 파일의 패키지 경로(agent.modules.x.y). __init__.py는 패키지 자신."""
    parts = ["agent", *path.relative_to(SRC).with_suffix("").parts]
    return parts[:-1] if parts[-1] == "__init__" else parts


def imported_names(path: Path, source: str | None = None) -> list[str]:
    """파일이 import하는 전체 경로. `from a.b import c`는 a.b와 a.b.c, 상대 import는 절대 경로로 낸다."""
    tree = ast.parse(source if source is not None else path.read_text(encoding="utf-8"))
    package = _module_of(path)
    if path.name != "__init__.py":
        package = package[:-1]
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            names.append(module)
            names.extend(f"{module}.{alias.name}" for alias in node.names if alias.name != "*")
    return names


def violations(path: Path, source: str | None = None) -> list[str]:
    """path(src/agent 아래 파일)의 import 중 규칙 위반을 사람이 읽을 문장으로 돌려준다."""
    relative = path.relative_to(SRC).parts
    owner = PACKAGES.get(relative[1]) if relative[0] == "modules" and len(relative) > 2 else None
    in_shared = relative[0] == "shared"
    found: list[str] = []
    for name in imported_names(path, source):
        parts = name.split(".")
        if parts[0] in PROVIDER_SDKS and owner != "MOD-07":
            found.append(f"공급자 SDK {name}는 MOD-07만 쓴다")
        if parts[0] != "agent" or len(parts) < 2:
            continue
        if parts[1] == "app" and (owner or in_shared):
            found.append(f"앱 조립 코드 import 금지: {name}")
        if parts[1] == "modules" and len(parts) > 2 and (owner or in_shared):
            target = PACKAGES.get(parts[2])
            if target is None:
                found.append(f"모듈 지도에 없는 패키지: {name}")
            elif in_shared:
                found.append(f"shared가 업무 모듈을 import: {name}")
            elif target != owner and target not in ALLOWED[owner]:
                found.append(f"{owner} → {target} 금지: {name}")
    return found


def _files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def test_allowed_table_is_read_from_module_map():
    assert set(ALLOWED) == set(PACKAGES.values())
    assert ALLOWED["MOD-02"] == {"MOD-03", "MOD-07"}
    assert ALLOWED["MOD-03"] == {"MOD-04", "MOD-11", "MOD-12"}
    assert ALLOWED["MOD-12"] == {"MOD-09"}  # "주입 CP-06/07"의 06·07은 모듈 의존이 아니다
    assert ALLOWED["MOD-04"] == ALLOWED["MOD-07"] == ALLOWED["MOD-09"] == set()


def test_every_module_package_is_in_module_map():
    for package in (SRC / "modules").iterdir():
        if package.is_dir() and package.name != "__pycache__":
            assert package.name in PACKAGES, f"모듈 지도에 없는 패키지: {package.name}"


@pytest.mark.parametrize(
    "path", _files(SRC / "modules") + _files(SRC / "shared"), ids=lambda p: p.relative_to(SRC).as_posix()
)
def test_source_follows_dependency_rules(path: Path):
    assert violations(path) == []


# 판정 함수가 실제로 위반을 잡는지 금지 예시로 확인한다(파일은 만들지 않고 가상 경로에 소스를 넣는다).
_IT = SRC / "modules" / "it_support" / "service.py"
_SHARED = SRC / "shared" / "x.py"


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        (_IT, "from agent.modules.conversation import repo\n", "MOD-12 → MOD-01"),
        (_IT, "from agent.modules import conversation\n", "MOD-12 → MOD-01"),
        (_IT, "import agent.modules.conversation.repo\n", "MOD-12 → MOD-01"),
        (_IT, "from ..conversation import repo\n", "MOD-12 → MOD-01"),
        (_IT, "from ...modules.conversation import repo\n", "MOD-12 → MOD-01"),
        (_IT, "from agent.app.main import create_app\n", "앱 조립"),
        (_IT, "from agent import app\n", "앱 조립"),
        (_IT, "import anthropic\n", "공급자 SDK"),
        (_SHARED, "from agent.modules.training import service\n", "shared가 업무 모듈"),
        (_SHARED, "from google import genai\n", "공급자 SDK"),
    ],
)
def test_checker_catches_forbidden_imports(path, source, expected):
    found = violations(path, source)
    assert any(expected in item for item in found), found


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (_IT, "from agent.modules.identity_access import test_stub\n"),  # MOD-12 → MOD-09 허용
        (_IT, "from . import models\n"),  # 같은 모듈 안
        (_IT, "from agent.shared.errors import AppError\n"),
    ],
)
def test_checker_allows_permitted_imports(path, source):
    assert violations(path, source) == []
