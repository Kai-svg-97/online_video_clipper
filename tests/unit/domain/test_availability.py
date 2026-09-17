"""원본 생존 판정 규칙.

핵심은 **'확인 불가'를 '사라짐'으로 보고하지 않는 것**이다. 네트워크가 잠깐 끊기거나
서버가 속도 제한을 걸었을 뿐인데 사라졌다고 알리면, 사용자가 멀쩡한 영상을 지운다.
"""

from __future__ import annotations

import pytest

from domain.library.availability import (
    MISSING_STATUSES,
    STATUS_OK,
    STATUS_PRIVATE,
    STATUS_REMOVED,
    STATUS_UNKNOWN,
    AvailabilityResult,
    classify_http_status,
)


class TestClassify:
    def test_200은_정상(self):
        assert classify_http_status(200).status == STATUS_OK

    def test_404는_삭제됨(self):
        assert classify_http_status(404).status == STATUS_REMOVED

    @pytest.mark.parametrize("code", [401, 403])
    def test_권한_오류는_비공개(self, code):
        assert classify_http_status(code).status == STATUS_PRIVATE

    @pytest.mark.parametrize("code", [429, 500, 502, 503])
    def test_서버_문제는_확인_불가(self, code):
        """영상의 문제가 아니다 — 서버가 잠깐 아픈 것을 두고 영상을 지우게 하면 안 된다."""
        assert classify_http_status(code).status == STATUS_UNKNOWN

    def test_확인_불가에는_응답_코드를_남긴다(self):
        assert "503" in classify_http_status(503).detail


class TestMissing:
    def test_삭제와_비공개만_사라짐으로_본다(self):
        assert MISSING_STATUSES == {STATUS_REMOVED, STATUS_PRIVATE}

    def test_확인_불가는_사라짐이_아니다(self):
        assert not AvailabilityResult(STATUS_UNKNOWN).is_missing

    def test_정상은_사라짐이_아니다(self):
        assert not AvailabilityResult(STATUS_OK).is_missing

    @pytest.mark.parametrize("status", [STATUS_REMOVED, STATUS_PRIVATE])
    def test_사라짐_판정(self, status):
        assert AvailabilityResult(status).is_missing


class TestLabels:
    @pytest.mark.parametrize(
        "status,label",
        [(STATUS_OK, "정상"), (STATUS_REMOVED, "삭제됨"),
         (STATUS_PRIVATE, "비공개"), (STATUS_UNKNOWN, "확인 불가")],
    )
    def test_한글_라벨(self, status, label):
        assert AvailabilityResult(status).label == label

    def test_모르는_상태는_키를_그대로_보여준다(self):
        assert AvailabilityResult("weird").label == "weird"
