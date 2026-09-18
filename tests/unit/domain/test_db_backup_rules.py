"""DB 백업 보관 규칙 — **순수 판정**.

라이브러리 DB는 다시 만들 수 없다(원본 영상을 다시 받아도 메모·태그는 안 돌아온다).
그런데 `config.yaml.example`이 "daily backups (keeps last 7)"라고 적어 둔 채 **그렇게
도는 코드가 없었다** — 설정 파일을 보고 보호받는다고 믿을 수 있어 더 나빴다.

여기서 고정하는 함정은 셋이다.

1. 하루에 앱을 열 번 켜도 복사는 한 번이다.
2. 백업 폴더는 **클라우드 동기화의 충돌 백업도 쓰는 곳**이라, 우리 이름이 아닌 파일을
   세거나 지우면 안 된다.
3. 지울 때는 오래된 것부터 — 최신 7개는 남아야 한다.
"""

from __future__ import annotations

from datetime import date

from domain.library.backup import (
    KEEP_COUNT,
    backup_name,
    is_backup_name,
    needs_backup,
    prune,
)


def _names(*days: int) -> list[str]:
    return [backup_name(date(2026, 9, d)) for d in days]


class TestNaming:
    def test_날짜가_이름에_들어간다(self):
        """파일 수정 시각은 복사·이동에 흔들린다 — 이름으로 판정해야 한다."""
        assert backup_name(date(2026, 9, 18)) == "library-20260918.db"

    def test_우리_백업만_알아본다(self):
        assert is_backup_name("library-20260918.db") is True
        assert is_backup_name("library-2026918.db") is False      # 자릿수 부족
        assert is_backup_name("library-notadate.db") is False
        assert is_backup_name("conflict-20260918.db") is False    # 동기화 충돌 백업
        assert is_backup_name("library-20260918.db.part") is False  # 만들다 만 것


class TestNeedsBackup:
    def test_오늘치가_없으면_만든다(self):
        assert needs_backup(_names(16, 17), date(2026, 9, 18)) is True

    def test_오늘치가_있으면_건너뛴다(self):
        """하루에 열 번 켜도 복사는 한 번이다."""
        assert needs_backup(_names(17, 18), date(2026, 9, 18)) is False

    def test_아무것도_없으면_만든다(self):
        assert needs_backup([], date(2026, 9, 18)) is True

    def test_남의_파일은_오늘치로_치지_않는다(self):
        assert needs_backup(["conflict-20260918.db"], date(2026, 9, 18)) is True


class TestPrune:
    def test_상한_이하면_아무것도_안_지운다(self):
        assert prune(_names(11, 12, 13)) == []

    def test_오래된_것부터_지운다(self):
        existing = _names(*range(10, 20))        # 10개
        doomed = prune(existing, keep=7)
        assert doomed == _names(10, 11, 12)      # 가장 오래된 3개

    def test_최신_7개는_남는다(self):
        existing = _names(*range(10, 20))
        kept = set(existing) - set(prune(existing, keep=7))
        assert kept == set(_names(*range(13, 20)))

    def test_남의_파일은_세지도_지우지도_않는다(self):
        """동기화 충돌 백업을 우리 상한에 끼워 넣으면 남의 것을 지운다."""
        existing = _names(*range(10, 20)) + ["conflict-20260101.db", "readme.txt"]

        doomed = prune(existing, keep=7)

        assert "conflict-20260101.db" not in doomed
        assert "readme.txt" not in doomed
        assert len(doomed) == 3

    def test_기본_상한은_일주일이다(self):
        """어제 뭔가 잘못 지운 것을 주말 지나 알아차려도 복구된다."""
        assert KEEP_COUNT == 7
        assert len(prune(_names(*range(1, 21)))) == 20 - 7
