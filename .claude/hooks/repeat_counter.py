"""UserPromptSubmit 반복 감지 훅: 제안의 근거만 남기고 아무것도 자동 반영하지 않는다.

- 긴 요청(80자 이상)이 이전 요청과 비슷하면 횟수를 센다. 3번째에 skill 후보로 알린다.
- 지적 표현이 있는 요청이 이전 지적과 비슷하면 횟수를 센다. 2번째에 CLAUDE.md 후보로 알린다.
- 원문은 저장하지 않는다. 공백·문장부호를 뺀 글자 2개 조각의 해시 집합과 시각만 .claude/state/에 둔다.
  조각 해시로 내용 일부를 추정할 수는 있으므로 이 폴더는 git에서 제외한다.
- 비교는 조각 집합의 Jaccard 유사도다. 기준값은 2026-10-17 대화 예문으로 잰 값이다(같은 지적0.40~0.50, 다른 지적 최대0.17).
- 오류가 나면 조용히 통과한다(exit 0). 이 훅은 요청을 막지 않는다.
"""
import hashlib
import json
import os
import re
import sys
import time

LONG_MIN_CHARS = 80
SKILL_AT = 3
CLAUDE_MD_AT = 2
SIMILAR = {"procedure": 0.6, "correction": 0.3}
KEEP_DAYS = 60
CORRECTION_RE = re.compile(r"했잖|하라고|하라니|말라고|말라니|아니라고|아니잖|다시\s*말|몇\s*번|또\s|또야|왜\s*또")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def signature(text: str, kind: str) -> list[int]:
    t = CORRECTION_RE.sub(" ", text) if kind == "correction" else text
    t = re.sub(r"[\W_]+", "", t)
    grams = {t[i : i + 2] for i in range(max(len(t) - 1, 1))}
    return sorted(int.from_bytes(hashlib.blake2b(g.encode("utf-8"), digest_size=4).digest(), "big") for g in grams)


def similarity(a: list[int], b: list[int]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def main() -> None:
    data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    prompt = normalize(str(data.get("prompt", "")))
    kind = "correction" if CORRECTION_RE.search(prompt) else ("procedure" if len(prompt) >= LONG_MIN_CHARS else "")
    if not kind:
        return
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    state_dir = os.path.join(project, ".claude", "state")
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "repeat-log.json")
    now = time.time()
    try:
        with open(path, encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        log = []
    log = [e for e in log if now - e.get("t", 0) < KEEP_DAYS * 86400]

    sig = signature(prompt, kind)
    thr = SIMILAR[kind]
    peers = [e for e in log if e.get("kind") == kind]
    direct = [e for e in peers if similarity(sig, e["sig"]) >= thr]
    # 한 단계 이어진 요청까지 같은 묶음으로 본다(A~B, A~C이면 B·C도 같은 묶음).
    same = [e for e in peers if e in direct or any(similarity(e["sig"], d["sig"]) >= thr for d in direct)]
    count = len(same) + 1
    already = any(e.get("notified") for e in same)
    threshold = CLAUDE_MD_AT if kind == "correction" else SKILL_AT
    notify = count >= threshold and not already
    log.append({"t": now, "kind": kind, "sig": sig, "notified": notify})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f)

    if notify:
        first = time.strftime("%Y-%m-%d", time.localtime(min(e["t"] for e in same)))
        target = "CLAUDE.md 규칙 후보" if kind == "correction" else "skill 후보"
        what = "비슷한 지적" if kind == "correction" else "비슷한 긴 요청"
        sys.stdout.reconfigure(encoding="utf-8")
        print(f"[반복 감지 훅] {what}이 이 프로젝트에서 {count}번째다(처음 {first}). "
              f"CLAUDE.md의 반복 처리 규칙상 {target}이며, 반영은 사용자 승인 뒤에만 한다.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
