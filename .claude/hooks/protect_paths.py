"""PreToolUse 보호 훅: PDF 원본과 .env 비밀값을 지킨다.

- data/raw/pdfs/ 아래 파일(README.md 제외)의 생성·수정·삭제·이동을 막는다.
- .env, .env.* (.env.example 제외)의 읽기·쓰기를 막는다.
- Bash/PowerShell 명령은 문자열 기준 최선의 차단이며 보안 경계가 아니다.
차단하면 사유를 stderr에 쓰고 exit 2로 끝낸다. 판단할 수 없는 입력도 막는다(fail closed).
"""
import json
import os
import re
import sys

PDF_DIR = ("data", "raw", "pdfs")
PDF_DIR_RE = r"data[\\/]+raw[\\/]+pdfs"
ALLOWED_IN_PDF_DIR = {"readme.md"}
ENV_TOKEN_RE = re.compile(r"(?<![\w.-])\.env(?:\.(?!example\b)[\w-]+)?(?![\w.-])")
WRITE_CMD_RE = re.compile(
    r"\b(rm|rmdir|del|erase|mv|move|ren|rename|truncate|shred|unlink|"
    r"remove-item|move-item|rename-item|set-content|add-content|out-file|clear-content|new-item)\b",
    re.IGNORECASE,
)
INPLACE_RE = re.compile(r"\b(sed|perl)\b[^|;&]*\s-i", re.IGNORECASE)


def block(reason: str) -> None:
    sys.stderr.reconfigure(encoding="utf-8")  # Windows 기본 cp949 대신 UTF-8로 사유를 전달한다
    print(f"차단(보호 훅): {reason}", file=sys.stderr)
    sys.exit(2)


def parts(path: str, cwd: str) -> list[str]:
    p = path.strip().strip("\"'")
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    p = os.path.normpath(p).replace("\\", "/")
    return [s.lower() for s in p.split("/") if s]


def in_pdf_dir(path: str, cwd: str, project: str) -> bool:
    full, root = parts(path, cwd), parts(project, project)
    rel = full[len(root):] if full[: len(root)] == root else full
    for i in range(len(rel) - len(PDF_DIR) + 1):
        if tuple(rel[i : i + len(PDF_DIR)]) == PDF_DIR:
            tail = rel[i + len(PDF_DIR) :]
            return not (len(tail) == 1 and tail[0] in ALLOWED_IN_PDF_DIR)
    return False


def is_env_file(path: str) -> bool:
    name = os.path.basename(path.strip().strip("\"'").replace("\\", "/")).lower()
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def check_file_tool(tool: str, tool_input: dict, cwd: str, project: str) -> None:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
    if not path:
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            block(f"{tool}의 대상 경로를 확인할 수 없음")
        return
    if is_env_file(path):
        block(f"{tool}로 비밀값 파일({os.path.basename(path)})에 접근할 수 없음. 키 이름은 .env.example에만 적는다")
    if tool != "Read" and tool != "Grep" and in_pdf_dir(path, cwd, project):
        block("data/raw/pdfs의 PDF 원본은 읽기 전용이다")


def check_command(tool: str, command: str) -> None:
    if ENV_TOKEN_RE.search(command):
        block(f"{tool} 명령이 .env 비밀값 파일을 참조함")
    if re.search(r"\bgit\s+clean\b", command, re.IGNORECASE):
        block("git clean은 커밋 전 PDF 원본을 지울 수 있어 막는다")
    if not re.search(PDF_DIR_RE, command, re.IGNORECASE):
        return
    if WRITE_CMD_RE.search(command) or INPLACE_RE.search(command):
        block(f"{tool} 명령이 data/raw/pdfs를 변경할 수 있음")
    if re.search(r">>?\s*[\"']?[^\s\"'|;&]*" + PDF_DIR_RE, command, re.IGNORECASE):
        block(f"{tool} 명령이 data/raw/pdfs로 출력을 쓰려 함")
    if re.search(r"\b(cp|copy|copy-item|xcopy|robocopy|rsync)\b[^|;&]*" + PDF_DIR_RE + r"[^\s\"'|;&]*[\"']?\s*($|[|;&])",
                 command, re.IGNORECASE):
        block(f"{tool} 명령이 data/raw/pdfs로 복사하려 함")
    if re.search(r"\bgit\s+(rm|mv|checkout|restore)\b", command, re.IGNORECASE):
        block(f"{tool} 명령이 git으로 data/raw/pdfs를 변경할 수 있음")


def main() -> None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))  # Windows 기본 cp949로 읽지 않는다
    except Exception:
        block("훅 입력(JSON)을 읽을 수 없음")
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    if tool in ("Bash", "PowerShell"):
        check_command(tool, str(tool_input.get("command", "")))
    else:
        check_file_tool(tool, tool_input, cwd, project)
    sys.exit(0)


if __name__ == "__main__":
    main()
