"""닫힌 키 집합 → 표시 이름.

도메인은 영어 키를 갖고(`STATUS_OK = "ok"`, SponsorBlock 카테고리 값) 표시 이름은
여기가 갖는다. 프로젝트가 이미 세 번 내린 판단을 한곳으로 모은 것이다 —
`gui/panels/library/constants.py`의 `MATCH_FIELD_LABELS`, `gui/panels/album_panel.py`의
`ORIGIN_LABELS`, `gui/panels/detail/text_format.py`의 `_SUMMARY_STATUS_LABELS`.

**한 패널만 쓰는 라벨은 옮기지 않는다** — 위 셋은 지금 자리 그대로 둔다. 여기로
오는 것은 도메인에서 걷어낸, 여러 곳에서 쓰이는 라벨이다.

키마다 라벨이 있는지(그리고 남는 라벨이 없는지)는
`tests/unit/gui/test_label_coverage.py`가 지킨다 — 도메인에 키를 더하고 라벨을
빠뜨리면 화면에 키가 그대로 뜬다.

덩어리 C2에서 채워진다.
"""

from __future__ import annotations
