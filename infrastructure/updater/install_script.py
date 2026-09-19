"""업데이트 설치 배치 스크립트 생성 — **문자열만 만든다**(실행은 하지 않는다).

앱이 제 파일을 교체할 수는 없다. 실행 중인 `.exe`와 `_internal/*.dll`은 Windows가
잠그기 때문이다. 그래서 별도 프로세스(배치)를 띄워 두고 앱이 죽기를 기다리게 한다.

## 왜 고정 대기가 아니라 PID를 기다리나

예전에는 `timeout /t 5`로 무조건 5초를 기다렸다. 느린 PC에서는 그 사이 앱이 다 못
죽어 인스톨러가 잠긴 파일을 만나고(`DeleteFile failed; code 5`), 빠른 PC에서는 5초가
통째로 낭비였다. 프로세스가 사라지는 것을 직접 확인하면 **둘 다 없어진다** — 죽는
즉시 시작하고, 오래 걸리면 오래 기다린다.

상한(`_MAX_WAIT_TICKS`)을 두는 이유는 앱이 끝내 죽지 않는 경우다. 영원히 도는 배치를
사용자 PC에 남기지 않는다. 상한에 걸리면 그냥 설치를 시작하고, 그때는 인스톨러의
`CloseApplications=force`(Restart Manager)가 2차 방어로 남는다.

## 왜 `/VERYSILENT`이 아니라 `/SILENT`인가

`/VERYSILENT`는 창을 아예 띄우지 않는다. 앱이 닫힌 뒤 설치가 끝날 때까지 화면에
**아무것도 없어서** 사용자는 앱이 죽은 줄 안다. `/SILENT`은 마법사 없이 진행 막대만
보여 준다 — 그 공백을 메우는 것이 이 기능의 체감을 좌우한다.

## 왜 실패를 파일로 남기나

배치는 조용히 죽는다. 디스크가 모자라거나 인스톨러가 거부돼도 아무도 모르고,
사용자는 "업데이트를 눌렀는데 버전이 그대로"인 상태에 남는다. 종료 코드를 적어 두면
다음 기동에서 읽어 알려 줄 수 있다.
"""

from __future__ import annotations

# 1틱 = ping 1회(약 1초). 120틱 ≈ 2분이면 어떤 종료 절차보다 넉넉하다.
_MAX_WAIT_TICKS = 120

# Inno Setup 인자. `/CLOSEAPPLICATIONS`는 PID 대기가 상한에 걸렸을 때를 위한 2차 방어다.
INSTALLER_ARGS = "/SILENT /NORESTART /CLOSEAPPLICATIONS /SUPPRESSMSGBOXES"


def build_update_batch(
    installer: str,
    exe: str,
    pid: int,
    fail_log: str,
) -> str:
    """설치 배치 내용을 만든다.

    `exe`가 비면(개발 실행 등 frozen이 아닌 경우) 재실행 줄을 넣지 않는다 —
    `python main.py`로 띄운 것을 exe로 되살릴 수는 없다.

    줄바꿈은 CRLF다. 배치 파일은 LF만으로도 대개 동작하지만, 레이블(`:wait`)과
    `goto`가 섞이면 해석이 깨지는 경우가 있어 맞춰 준다.
    """
    lines = [
        "@echo off",
        "setlocal",
        "rem 앱이 완전히 죽을 때까지 기다린다 — 실행 중에는 파일이 잠겨 있다.",
        "set /a n=0",
        ":wait",
        f'tasklist /FI "PID eq {pid}" /NH | find "{pid}" >nul || goto ready',
        "set /a n+=1",
        f"if %n% GEQ {_MAX_WAIT_TICKS} goto ready",
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":ready",
        f'"{installer}" {INSTALLER_ARGS}',
        "rem 실패를 남겨야 다음 기동에서 사용자에게 알릴 수 있다.",
        f'if errorlevel 1 echo %ERRORLEVEL%> "{fail_log}"',
    ]
    if exe:
        lines.append(f'start "" "{exe}"')
    lines.append('del "%~f0"')
    return "\r\n".join(lines) + "\r\n"
