"""`Message` — 도메인이 문장 대신 나르는 값.

이 타입의 값어치는 **테스트가 `==` 한 줄로 끝난다**는 데 있다. 지금까지 도메인
테스트는 `assert "하루 종일" in describe()` 처럼 부분 문자열을 봤는데, 그건 번역하면
깨질 뿐 아니라 애초에 약한 단언이다("하루 종일 받습니다"와 "하루 종일 안 받습니다"를
구분하지 못한다).
"""

from __future__ import annotations

from domain.shared.messages import Message


class TestEquality:
    def test_같은_키와_값이면_같다(self):
        assert Message.of("watch.count", total=3) == Message.of("watch.count", total=3)

    def test_인자_순서는_상관없다(self):
        """키워드 인자 순서가 단언을 좌우하면 시험이 쓸모없어진다."""
        assert Message.of("k", a=1, b=2) == Message.of("k", b=2, a=1)

    def test_값이_다르면_다르다(self):
        assert Message.of("watch.count", total=3) != Message.of("watch.count", total=4)

    def test_키가_다르면_다르다(self):
        assert Message.of("a") != Message.of("b")


class TestHashable:
    def test_집합에_담을_수_있다(self):
        """frozen + 튜플 파라미터라 해시가 된다 — 딕셔너리 키로도 쓸 수 있다."""
        assert len({Message.of("k", n=1), Message.of("k", n=1), Message.of("k", n=2)}) == 2


class TestParams:
    def test_파라미터가_없어도_된다(self):
        assert Message.of("schedule.always").params == ()

    def test_템플릿에_채울_형태로_돌려준다(self):
        assert Message.of("k", start=9, end=18).as_dict() == {"start": 9, "end": 18}

    def test_값을_바꿀_수_없다(self):
        """도메인이 돌려준 뒤 화면이 고쳐 쓰는 일이 없어야 한다."""
        import dataclasses

        import pytest

        with pytest.raises(dataclasses.FrozenInstanceError):
            Message.of("k").key = "other"   # type: ignore[misc]
