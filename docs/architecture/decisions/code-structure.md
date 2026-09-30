# 코드 구조 — 큰 파일을 나누는 방식

> 파일을 나눌 때의 기준과 나누다 밟은 함정.
> 색인: [`../design-decisions.md`](../design-decisions.md).

## 큰 파일 넷을 조립부 + mixin으로 (2026-09-30)

유지보수 점검에서 한 파일이 1,100~2,200줄인 곳이 넷 나왔다. 패널에 이미 쓰던 방식
(`*_panel.py`는 조립부, 동작은 옆 패키지의 `mixins/`)을 그대로 적용했다 — **런타임 클래스는
그대로**이고 파일만 나뉜다.

| 파일 | 전 → 후 | 나눈 곳 |
| --- | --- | --- |
| `gui/panels/settings_panel.py` | 2,219 → 230 | `gui/panels/settings/mixins/` 8개(섹션별) |
| `gui/widgets/video_player.py` | 1,705 → 348 | `gui/widgets/player/mixins/` 7개(동작별) |
| `gui/view_models/library_vm.py` | 1,388 → 280 | `gui/view_models/library/` 워커 + mixin 7개 |
| `gui/main_window.py` | 1,166 → 792 | 셸 부품을 `gui/shell/`로 |

### 경계는 화면의 순서를 따른다

설정 화면은 `_build_ui`가 섹션을 쌓는 순서대로 나눴다 — 화면에서 본 섹션을 코드에서 바로
찾을 수 있다. 너무 큰 섹션(다운로드)은 둘로, 합치면 460줄이 넘는 둘(YouTube 계정·구독 피드
쿠키)은 따로 뒀다. 여러 mixin이 함께 쓰는 것(`_save_setting`)과 시그널·`showEvent`에 곧바로
묶인 것(숨김 태그)은 조립부에 남긴다.

플레이어는 **재생 스트림 규칙**이 나뉘어도 살아 있는지를 기준으로 봤다. 재생기 위치를 직접
읽고 쓰는 호출(`_player.position()`/`setPosition()`)의 개수를 분할 전후로 세어 늘지 않았음을
확인했다(8 → 8) — 새 경로가 `_seek_to`·`position_ms`를 건너뛰면 그 경로만 조용히 죽는다.

### 재수출은 임포트만 지킨다 — 패치는 쓰는 쪽에

옛 경로로 임포트하던 코드·시험을 위해 이름을 재수출했다. 하지만 **monkeypatch는 재수출된
이름에 걸면 효과가 없다** — mixin은 자기 모듈의 이름을 본다. 이번에도 시험 4건
(`open_folder` 3건, `_ListVideosWorker` 1건)을 쓰는 쪽 모듈로 옮겨야 했다(CLAUDE.md 규칙).

### 상수 하나가 순환 임포트를 막는다

셸 부품을 나눌 때 `_PAGE_*` 상수를 `gui/shell/pages.py`로 따로 뺐다. 사이드바·다운로드 바·
`MainWindow`가 모두 이 값을 쓰는데, 어느 한쪽에 두면 나머지가 그 모듈을 임포트해 서로
물린다.

### 파일을 옮기면 파일 단위 가드가 조용히 빠진다

`tests/gui/test_vm_worker_contract.py`는 "`*_vm.py` 안에 QThread 클래스가 있으면" 대상으로
삼았다. 워커를 `gui/view_models/library/workers.py`로 옮기자 `library_vm.py`가 대상에서
빠졌다 — 시험은 통과하지만 아무것도 지키지 않는 상태다(분할 에이전트가 발견). 이제 뷰모델이
워커를 정의·임포트하거나 **워커를 쓰는 mixin을 섞으면** 대상으로 보고, `library_vm.py`가
잡히는지 시험으로 고정했다.

**교훈**: 파일 경로·이름 패턴으로 대상을 고르는 가드는 파일을 옮기면 조용히 느슨해진다.
분할할 때는 그런 가드의 대상 목록이 줄지 않았는지 확인한다.
