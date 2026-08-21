from gateway.approval_reason_ko import build_approval_brief, humanize_approval_reason


def test_execute_code_reason_is_korean_and_names_the_file():
    command = (
        "execute_code <<'PY'\n"
        "from pathlib import Path\n"
        'p2 = Path("/Users/khlee/.hermes/hermes-agent/tests/agent/test_auxiliary_client.py")\n'
        "p2.write_text(text2.replace(old2, new2, 1))\n"
        "PY"
    )
    text = humanize_approval_reason(
        command,
        "execute_code script execution. The script can spawn subprocesses or "
        "mutate files without passing through terminal command approval; "
        "approval is one-shot for this run.",
    )
    assert "execute_code script execution" not in text
    assert "one-shot" not in text
    assert "Python 코드를 바로 실행" in text
    assert "별도 터미널 승인" in text
    assert "이번만 허용" in text
    assert "파일을 만들거나 내용을 바꿀 수 있습니다." in text
    assert "test_auxiliary_client.py" in text


def test_rm_reason_explains_recursive_delete():
    text = humanize_approval_reason("rm -rf /important", "recursive delete")
    assert "recursive delete" not in text
    assert "터미널 명령" in text
    assert "재귀적으로 지우는" in text
    assert "/important" in text


def test_unknown_reason_stays_korean():
    text = humanize_approval_reason("obscure-tool --yes", "some internal flag")
    assert "some internal flag" not in text
    assert "자동으로 판별하지 못했습니다" in text
    assert "시스템에 영향을 줄 수" not in text
    assert "이번만 허용" in text


def test_read_only_http_pipe_is_not_described_as_system_mutation():
    command = (
        "curl -sL https://example.test/login | python3 -c \""
        "import sys,re; html=sys.stdin.read(); print(re.sub('<[^>]+>',' ',html)[:800])\""
    )
    reason = humanize_approval_reason(command, "pipe to interpreter")
    brief = build_approval_brief(command, "pipe to interpreter", host="Mac mini")
    assert "외부 상태는 변경하지 않습니다" in reason
    assert "시스템에 영향을 줄 수" not in reason
    assert "대상: Mac mini" in brief
    assert "https://example.test/login" in brief
    assert "로컬 파일 수정·삭제" in brief
    assert "이번 한 번만 허용" in brief


def test_delete_brief_names_target_scope_and_recovery_risk():
    brief = build_approval_brief(
        "rm -rf /tmp/approval-fixture",
        "recursive delete",
        host="MacBook Pro",
        workspace="/Users/khlee/project",
    )
    assert "대상: MacBook Pro · 작업공간 /Users/khlee/project" in brief
    assert "/tmp/approval-fixture" in brief
    assert "하는 일: /tmp/approval-fixture와 그 하위 내용을 재귀 삭제" in brief
    assert "안 하는 일:" in brief
    assert "위험:" in brief
    assert "롤백:" in brief
    assert "백업·스냅샷이 없으면 복구를 보장할 수 없습니다" in brief
    assert "승인 시:" in brief
    assert "거부 시:" in brief
    assert "검증:" in brief


def test_ssh_delete_brief_names_remote_execution_host():
    brief = build_approval_brief(
        "ssh macmini-local rm -rf /tmp/approval-fixture",
        "recursive delete",
        host="MacBook Pro",
        workspace="/Users/khlee/project",
    )
    assert "원격 호스트 macmini-local" in brief
    assert "명령 시작 호스트 MacBook Pro" in brief
