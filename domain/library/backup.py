"""DB 백업 보관 규칙 — **순수 판정**, 파일을 만지지 않는다.

라이브러리 DB는 사용자가 몇 년에 걸쳐 쌓은 것이다. 영상 메타데이터·태그·메모·가사·
자막 색인·이어보기 위치가 전부 여기 있고, **다시 만들 수 없다**(원본 영상을 다시
받아도 메모와 태그는 돌아오지 않는다). 그런데 지금까지 백업이 없었다 —
`data/config.yaml.example`에는 "daily backups (keeps last 7)"라고 적혀 있는데
그렇게 도는 코드가 없었다. 설정 파일을 보고 보호받는다고 믿을 수 있어 더 나쁘다.

**왜 하루 한 번인가**: 백업은 DB 전체를 복사하므로 자주 돌리면 시작이 느려지고
디스크가 는다. 반대로 주 1회면 잃는 폭이 너무 크다. 하루치 작업을 잃는 선에서
타협한다 — 그 이상 자주 필요한 사람은 클라우드 동기화를 쓴다.

**왜 이름에 날짜를 넣나**: 같은 날 여러 번 켜도 하나만 남기려면 "오늘 것이 있나"를
파일 이름만으로 판정할 수 있어야 한다. 파일 수정 시각은 복사·이동에 흔들린다.
"""

from __future__ import annotations

from datetime import date

# 며칠치를 남기나. 7일이면 "어제 뭔가 잘못 지웠다"를 주말 지나 알아차려도 복구된다.
KEEP_COUNT = 7

_PREFIX = "library-"
_SUFFIX = ".db"


def backup_name(day: date) -> str:
    """그 날짜의 백업 파일 이름."""
    return f"{_PREFIX}{day:%Y%m%d}{_SUFFIX}"


def is_backup_name(name: str) -> bool:
    """우리가 만든 백업인가 — 남의 파일을 지우지 않기 위한 판정이다.

    백업 폴더는 클라우드 동기화의 충돌 백업도 쓰는 곳이라, 이름이 맞는 것만 센다.
    """
    if not (name.startswith(_PREFIX) and name.endswith(_SUFFIX)):
        return False
    stamp = name[len(_PREFIX) : -len(_SUFFIX)]
    return len(stamp) == 8 and stamp.isdigit()


def needs_backup(existing: list[str], today: date) -> bool:
    """오늘치를 만들어야 하는가 — 이미 있으면 다시 만들지 않는다.

    하루에 앱을 열 번 켜도 복사는 한 번이다.
    """
    return backup_name(today) not in set(existing)


def prune(existing: list[str], keep: int = KEEP_COUNT) -> list[str]:
    """지워야 할 백업 이름들(오래된 것부터).

    이름이 `library-YYYYMMDD.db`라 **문자열 정렬이 곧 날짜 정렬**이다.
    우리가 만든 것이 아닌 파일은 세지도, 지우지도 않는다.
    """
    ours = sorted(n for n in existing if is_backup_name(n))
    if keep <= 0:
        return ours
    return ours[: max(0, len(ours) - keep)]
