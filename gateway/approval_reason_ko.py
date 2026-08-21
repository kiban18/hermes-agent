"""Korean, contextual reasons for Telegram exec-approval prompts.

The approval engine stores English pattern descriptions for logs and LLM
guards. Telegram users need a short Korean briefing: what is about to run,
why it is gated, and how far this tap applies.
"""

from __future__ import annotations

import os
import platform
import re
from typing import Iterable, Optional

_EXECUTE_CODE_OPEN = re.compile(
    r"^\s*execute_code\b(?:\s+<<['\"]?\w+['\"]?)?\s*\n?",
    re.IGNORECASE,
)
_EXECUTE_CODE_CLOSE = re.compile(r"\nPY\s*$")
_PATH_RE = re.compile(
    r"""(?:Path\(\s*|['"])((?:/|~/|\./)[^'"\s)]{2,220})"""
)
_BARE_PATH_RE = re.compile(r"(?:^|[\s=])((?:/|~/|\./)[^\s;|&\"']{2,220})")
_MAX_PATHS = 3
_MAX_REASON_CHARS = 900
_URL_RE = re.compile(r"https?://[^\s'\"|;]+", re.I)

_DESCRIPTION_LINES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"recursive delete|delete in root|destructive delete", re.I),
     "파일을 폴더 단위로 지우거나, 되돌리기 어렵게 만들 수 있습니다."),
    (re.compile(r"pipe remote|pipe decoded|obfuscation|invoke-expression|iwr \| iex", re.I),
     "인터넷이나 변환된 내용을 바로 실행할 수 있습니다."),
    (re.compile(r"world/other-writable|chmod|icacls|grant Everyone", re.I),
     "파일 권한을 열어 다른 사용자도 쓰게 만들 수 있습니다."),
    (re.compile(r"overwrite system|overwrite project env|sensitive", re.I),
     "시스템이나 프로젝트 설정·비밀 파일을 덮어쓸 수 있습니다."),
    (re.compile(r"SQL DROP|SQL DELETE|TRUNCATE", re.I),
     "데이터베이스 내용을 지울 수 있습니다."),
    (re.compile(r"format filesystem|disk copy|block device|wipe disk|diskpart", re.I),
     "디스크나 파일시스템을 지우거나 다시 포맷할 수 있습니다."),
    (re.compile(r"force kill|kill all|self-termination|taskkill|Stop-Process", re.I),
     "실행 중인 프로세스를 강제로 종료할 수 있습니다."),
    (re.compile(r"stop/restart system service|gateway|docker .*lifecycle|compose", re.I),
     "서비스나 컨테이너를 멈추거나 재시작할 수 있습니다."),
    (re.compile(r"remote daemon|DOCKER_HOST", re.I),
     "이 기기가 아닌 원격 도커 환경에 명령을 보낼 수 있습니다."),
    (re.compile(r"SSH keys|Hermes secrets|registry delete", re.I),
     "키·비밀값·레지스트리에 접근하거나 지울 수 있습니다."),
    (re.compile(r"fork bomb", re.I),
     "프로세스를 폭증시켜 기기를 멈추게 할 수 있습니다."),
    (re.compile(r"execute_code script execution", re.I),
     "Python 코드를 바로 실행합니다."),
)


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _script_from_command(command: str) -> Optional[str]:
    text = str(command or "")
    if not _EXECUTE_CODE_OPEN.search(text):
        if "execute_code" not in text:
            return None
    body = _EXECUTE_CODE_OPEN.sub("", text, count=1)
    body = _EXECUTE_CODE_CLOSE.sub("", body)
    return body.strip() or None


def _paths_in(text: str) -> list[str]:
    blob = text or ""
    found = [m.group(1).rstrip("\\") for m in _PATH_RE.finditer(blob)]
    found.extend(m.group(1).rstrip("\\") for m in _BARE_PATH_RE.finditer(blob))
    return _unique(found)[:_MAX_PATHS]


def _execute_code_facts(script: str) -> list[str]:
    facts: list[str] = []
    if re.search(r"write_text|open\([^)]*['\"]w|\.write\(|Path\([^)]*\)\.write", script):
        facts.append("파일을 만들거나 내용을 바꿀 수 있습니다.")
    if re.search(r"unlink|os\.remove|shutil\.rmtree|rmtree|Path\([^)]*\)\.unlink", script):
        facts.append("파일을 삭제할 수 있습니다.")
    if re.search(r"subprocess|os\.system|Popen|os\.popen", script):
        facts.append("다른 프로그램을 실행할 수 있습니다.")
    if re.search(r"\b(requests|httpx|urllib|aiohttp)\b|\bsocket\b", script):
        facts.append("네트워크로 데이터를 보내거나 받을 수 있습니다.")
    paths = _paths_in(script)
    if paths:
        facts.append("보이는 대상: " + ", ".join(paths))
    return facts


def _description_facts(description: str) -> list[str]:
    facts: list[str] = []
    blob = description or ""
    for pattern, line in _DESCRIPTION_LINES:
        if pattern.search(blob):
            facts.append(line)
    return _unique(facts)


def _is_read_only_http_inspection(command: str) -> bool:
    """Recognise HTTP reads whose response is parsed as data, not executed."""
    text = command or ""
    if not re.search(r"\b(curl|wget)\b", text):
        return False
    if re.search(
        r"(?:^|\s)(?:-X\s*)?(?:POST|PUT|PATCH|DELETE)\b|"
        r"--data(?:-raw|-binary|-urlencode)?\b|(?:^|\s)-d(?:\s|$)|"
        r"--upload-file\b|(?:^|\s)-T(?:\s|$)",
        text,
        re.I,
    ):
        return False
    if re.search(
        r"\|\s*(?:ba)?sh\b|\|\s*(?:zsh|fish|powershell|pwsh)\b",
        text,
        re.I,
    ):
        return False
    if re.search(r"\|\s*python(?:3)?\s+-c\b", text, re.I):
        return not re.search(
            r"open\([^)]*['\"](?:w|a|x)|write_text|write_bytes|unlink|"
            r"remove\(|rmtree|subprocess|os\.system|Popen",
            text,
            re.I,
        )
    return True


def _targets(command: str) -> list[str]:
    urls = _unique(
        m.group(0).rstrip(").,\"") for m in _URL_RE.finditer(command or "")
    )
    paths = _paths_in(command)
    return (urls + [path for path in paths if path not in urls])[:3]


def _execution_target(command: str, local_host: str) -> str:
    ssh_match = re.search(
        r"(?:^|[;&|]\s*)ssh\s+(?:(?:-[^\s]+)(?:\s+[^\s]+)?\s+)*([^\s;&|]+)",
        command or "",
    )
    if not ssh_match:
        return local_host
    remote_host = ssh_match.group(1)
    return f"원격 호스트 {remote_host} (명령 시작 호스트 {local_host})"


def build_approval_brief(
    command: str,
    description: str = "",
    *,
    host: Optional[str] = None,
    workspace: Optional[str] = None,
) -> str:
    """Build the decision-ready context shown before the raw approval card."""
    text = str(command or "")
    local_host = (host or platform.node() or "현재 Hermes 실행 호스트").strip()
    execution_target = _execution_target(text, local_host)
    working_dir = (workspace or os.getenv("TERMINAL_CWD") or os.getcwd()).strip()
    targets = _targets(text)
    target_text = ", ".join(targets) if targets else "구체 대상 자동 판별 불가"
    read_only = _is_read_only_http_inspection(text)
    recursive_delete = bool(
        re.search(r"\brm\b", text) and re.search(r"-[^\s]*r|--recursive", text)
    )
    delete = recursive_delete or bool(re.search(r"\brm\b", text))

    if read_only:
        decision = "읽기 전용 조회를 한 번 실행합니다."
        purpose = "웹 응답의 상태·본문을 읽고 필요한 정보만 출력"
        doing = "HTTP GET 응답을 내려받아 로컬 명령에서 텍스트로 파싱"
        not_doing = "로컬 파일 수정·삭제, 원격 데이터 변경, 업로드·고객 발송"
        risk = "외부 상태 변경은 없습니다. 원격 서버에는 일반 조회 요청 1회가 기록될 수 있습니다."
        rollback = "상태를 바꾸지 않으므로 롤백할 변경이 없습니다."
        approve = "이 조회 명령 한 번만 실행하고 응답을 확인합니다."
        deny = "명령을 실행하지 않고 대상 URL·조회 목적을 다시 확인합니다."
        verify = "명령 종료코드와 출력만 확인하며 원격 변경 작업은 수행하지 않습니다."
        recommendation = "대상 URL이 맞으면 이번 한 번만 허용을 권고합니다."
    elif delete:
        decision = "표시된 파일 또는 폴더를 삭제합니다."
        purpose = "명령에 지정된 삭제 대상 정리"
        if recursive_delete:
            doing = f"{target_text}와 그 하위 내용을 재귀 삭제"
        else:
            doing = f"{target_text} 파일 삭제"
        not_doing = "명령에 표시되지 않은 다른 경로와 외부 시스템 변경"
        risk = (
            "하위 내용까지 휴지통을 거치지 않고 지워 즉시 복구가 어려울 수 있습니다."
            if recursive_delete
            else "파일이 휴지통을 거치지 않고 삭제될 수 있습니다."
        )
        rollback = "휴지통으로 이동하지 않으므로 백업·스냅샷이 없으면 복구를 보장할 수 없습니다."
        approve = "표시된 범위만 삭제한 뒤 대상 경로의 부재와 주변 경로 보존을 확인합니다."
        deny = "아무것도 삭제하지 않고 대상·범위·백업을 다시 확인합니다."
        verify = "삭제 대상은 없어지고 상위·인접 경로는 남아 있는지 확인합니다."
        recommendation = "대상·범위·백업을 확인했을 때만 이번 한 번 허용하고, 하나라도 불명확하면 거부를 권고합니다."
    else:
        facts = _description_facts(description) or _command_facts(text)
        decision = "표시된 터미널 명령을 한 번 실행합니다."
        purpose = "명령 원문 밖의 업무 목적은 승인 경로에 전달되지 않아 자동 확인할 수 없음"
        doing = "; ".join(facts) if facts else "명령 원문에 표시된 동작 실행"
        not_doing = "명령 원문에 없는 추가 작업"
        risk = "구체 영향은 명령과 대상에 따라 달라지며 자동 판별되지 않았습니다."
        rollback = "자동 판별할 수 없습니다. 변경 명령이면 별도 복구 수단을 확인해야 합니다."
        approve = "표시된 명령 한 번만 실행하고 종료코드와 실제 결과를 확인합니다."
        deny = "명령을 실행하지 않고 업무 목적·대상·복구 방법을 다시 확인합니다."
        verify = "종료코드와 명령 대상의 전후 상태를 확인합니다."
        recommendation = "업무 목적과 대상이 직전 대화에서 명확하지 않으면 거부를 권고합니다."

    return "\n".join(
        [
            "[결정 필요] 명령 실행 전 확인",
            f"- 결정: {decision}",
            f"- 목적: {purpose}",
            f"- 대상: {execution_target} · 작업공간 {working_dir} · {target_text}",
            f"- 하는 일: {doing}",
            f"- 안 하는 일: {not_doing}",
            f"- 위험: {risk}",
            f"- 롤백: {rollback}",
            f"- 권고: {recommendation}",
            f"- 승인 시: {approve}",
            f"- 거부 시: {deny}",
            f"- 검증: {verify}",
        ]
    )


def _command_facts(command: str) -> list[str]:
    text = command or ""
    facts: list[str] = []
    if "write_file" in text:
        facts.append("파일을 새로 쓰거나 덮어씁니다.")
    if "replace" in text:
        facts.append("파일의 일부 내용을 다른 내용으로 교체합니다.")
    if re.search(r"\brm\b", text) and re.search(r"-[^\s]*r|--recursive", text):
        facts.append("폴더를 재귀적으로 지우는 명령입니다.")
    elif re.search(r"\brm\b", text):
        facts.append("파일을 지우는 명령입니다.")
    if re.search(r"\bgit\b.*\bpush\b", text) and re.search(r"\bforce\b|--force|-f\b", text):
        facts.append("이미 올린 커밋을 덮어쓰는 git push입니다.")
    if re.search(r"curl|wget", text) and re.search(r"\|\s*(ba)?sh\b", text):
        facts.append("내려받은 내용을 셸에서 바로 실행합니다.")
    elif _is_read_only_http_inspection(text):
        facts.append("지정한 URL 응답을 읽어 로컬에서 텍스트로 정리합니다. 외부 상태는 변경하지 않습니다.")
    elif re.search(r"\b(curl|wget)\b", text) and not re.search(
        r"(?:^|\s)(?:-X\s*)?(?:POST|PUT|PATCH|DELETE)\b|"
        r"--data(?:-raw|-binary|-urlencode)?\b|(?:^|\s)-d(?:\s|$)|"
        r"--upload-file\b|(?:^|\s)-T(?:\s|$)",
        text,
        re.I,
    ):
        facts.append("지정한 URL에서 응답을 읽습니다. 전송·업로드 옵션은 보이지 않습니다.")
    paths = _paths_in(text)
    if paths and "보이는 대상:" not in " ".join(facts):
        facts.append("보이는 대상: " + ", ".join(paths))
    return facts


def humanize_approval_reason(command: str, description: str = "") -> str:
    """Return a Korean briefing for the Telegram approval card."""
    script = _script_from_command(command)
    lines: list[str] = []
    if script is not None:
        lines.append("이 작업은 터미널 한 줄이 아니라 Python 코드를 바로 실행합니다.")
        lines.append("")
        lines.append("왜 확인이 필요한가")
        lines.append("코드 안에서 파일 변경이나 다른 프로그램 실행이 가능하고, 그 안의 동작은 별도 터미널 승인을 거치지 않습니다.")
        lines.append("「이번만 허용」은 위에 보이는 이 코드 한 번에만 적용됩니다.")
        facts = _execute_code_facts(script)
        if facts:
            lines.append("")
            lines.append("이번 코드에서 보이는 내용")
            lines.extend(f"- {fact}" for fact in facts)
    else:
        lines.append("이 작업은 터미널 명령을 실행합니다.")
        lines.append("")
        lines.append("왜 확인이 필요한가")
        facts = _description_facts(description) or _command_facts(command)
        if not facts:
            facts = ["구체 위험을 자동으로 판별하지 못했습니다. 직전 브리핑의 목적·대상·영향을 확인해야 합니다."]
        extra_paths = _command_facts(command)
        for fact in extra_paths:
            if fact not in facts:
                facts.append(fact)
        lines.extend(f"- {fact}" for fact in _unique(facts))
        lines.append("「이번만 허용」은 이 명령 한 번에만 적용됩니다.")

    lines.append("")
    lines.append("아래 버튼을 눌러 허용하거나 거부하세요.")
    text = "\n".join(lines).strip()
    if len(text) > _MAX_REASON_CHARS:
        text = text[: _MAX_REASON_CHARS - 1].rstrip() + "…"
    return text
