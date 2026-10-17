"""고정 교육 fixture(docs/12-first-milestone-spec.md). 모든 일정과 설명은 가상 데이터다.

기준 주 월요일은 2026-10-12다. 데모 seed는 anchor 날짜가 속한 주의 월요일과의 차이만큼
모든 시작·종료를 함께 옮긴다(요일·시각·기간·UUID·코드는 유지).
"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from agent.modules.training.models import TrainingStatus
from agent.shared.clock import KST

BASE_MONDAY = date(2026, 10, 12)


@dataclass(frozen=True)
class TrainingFixture:
    id: UUID
    code: str
    title: str
    description: str
    starts_at: datetime
    ends_at: datetime
    location: str
    status_override: TrainingStatus


def _at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=KST)


def _id(n: int) -> UUID:
    # 첫 두 ID는 API 문서 예시와 같다(…101, …102).
    return UUID(f"11111111-1111-4111-8111-1111111111{n:02d}")


FIXTURES: tuple[TrainingFixture, ...] = (
    TrainingFixture(
        _id(1),
        "TR-SEC-001",
        "신입사원 정보보안 교육",
        "신입사원이 사내 계정·비밀번호·자료 반출 기본 수칙을 익히는 가상 교육입니다.",
        _at(10, 20, 14),
        _at(10, 20, 16),
        "3층 교육장",
        "scheduled",
    ),
    TrainingFixture(
        _id(2),
        "TR-COLLAB-001",
        "신입사원 협업 도구 교육",
        "메신저·일정·문서 공유 도구의 기본 사용법을 실습하는 가상 교육입니다.",
        _at(10, 22, 10),
        _at(10, 22, 11, 30),
        "온라인",
        "scheduled",
    ),
    TrainingFixture(
        _id(3),
        "TR-ONBOARD-001",
        "신입사원 회사 소개",
        "회사 조직과 주요 업무 흐름을 소개하는 가상 오리엔테이션입니다.",
        _at(10, 16, 11),
        _at(10, 16, 12),
        "2층 세미나실",
        "scheduled",
    ),
    TrainingFixture(
        _id(4),
        "TR-SEC-OLD",
        "이전 정보보안 교육",
        "지난 차수로 진행된 정보보안 기본 교육입니다. 가상 데이터입니다.",
        _at(10, 13, 14),
        _at(10, 13, 16),
        "3층 교육장",
        "completed",
    ),
    TrainingFixture(
        _id(5),
        "TR-PRIVACY-001",
        "개인정보 보호 교육",
        "업무 중 개인정보를 다룰 때의 기본 원칙을 안내하는 가상 교육입니다. 이번 차수는 취소되었습니다.",
        _at(10, 21, 15),
        _at(10, 21, 16),
        "온라인",
        "cancelled",
    ),
    TrainingFixture(
        _id(6),
        "TR-DATA-001",
        "데이터 활용 기초",
        "스프레드시트로 업무 데이터를 정리하고 요약하는 방법을 다루는 가상 교육입니다.",
        _at(10, 26, 9),
        _at(10, 26, 10),
        "4층 회의실",
        "scheduled",
    ),
    TrainingFixture(
        _id(7),
        "TR-CS-001",
        "고객 응대 기초",
        "전화·메일 문의에 응대하는 기본 절차를 역할극으로 연습하는 가상 교육입니다.",
        _at(10, 27, 13),
        _at(10, 27, 15),
        "2층 세미나실",
        "scheduled",
    ),
    TrainingFixture(
        _id(8),
        "TR-LEAD-001",
        "업무 계획 세우기",
        "주간 업무 목표를 세우고 우선순위를 정하는 방법을 다루는 가상 교육입니다.",
        _at(11, 2, 10),
        _at(11, 2, 11),
        "온라인",
        "scheduled",
    ),
    TrainingFixture(
        _id(9),
        "TR-SALES-001",
        "영업 업무 소개",
        "영업 부서의 업무 흐름과 협업 방식을 소개한 가상 교육입니다.",
        _at(10, 15, 10),
        _at(10, 15, 12),
        "2층 세미나실",
        "completed",
    ),
    TrainingFixture(
        _id(10),
        "TR-SAFETY-001",
        "사무실 안전 교육",
        "화재·대피 경로와 사무실 안전 수칙을 안내하는 가상 교육입니다.",
        _at(10, 30, 14),
        _at(10, 30, 15),
        "3층 교육장",
        "scheduled",
    ),
)
