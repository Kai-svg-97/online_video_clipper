# Qt 수명 — 프로세스가 조용히 죽는 경로

> 로그도 예외도 없이 앱이 사라지는 경로들: 실행 중 애니메이션·싱글턴 람다·paint 안의 예외.
> 색인: [`../design-decisions.md`](../design-decisions.md).

## 실행 중 애니메이션을 위젯의 자식으로 두면 프로세스가 죽는다 (2026-09)

`LibraryPanel`을 만들고 파괴하면 **access violation으로 프로세스가 즉사**했다. 원인은
프로젝트가 이미 QThread에 대해 문서화한 것과 **똑같은 구조**였다
(`gui/workers.py`: "워커를 위젯의 부모로 매달면, 그 위젯을 지우는 순간 C++가 자식
스레드까지 지운다"):

```python
anim = QVariantAnimation(self)    # 부모 = 패널
anim.valueChanged.connect(_step)  # _step 은 위젯을 캡처한 클로저
anim.start()                      # 실행 중
```

패널의 C++ 객체가 파괴될 때 소멸자가 **실행 중인** 자식 애니메이션을 함께 지운다.
`~QAbstractAnimation`은 암묵적으로 `stop()`을 부르고 그것이 신호를 발화하는데, 그
시점의 수신 슬롯은 이미 파괴 중이라 해제된 메모리를 건드린다.

### 실측으로 좁힌 과정

부품을 하나씩 단독으로 만들고 버려 봤을 때는 **전부 정상**이었다(플레이어·상세·트리·
오버레이·스켈레톤·추천 스트립·미니바). 조립된 패널에서만 났고, `_setup_ui`만 돌리면
정상이지만 `_connect_signals`까지 돌리면 죽었다 — 그 안에서 `_recommend_vm`이 없을 때
`_reveal_recommend_strip(False)`가 **실제 애니메이션을 시작**하기 때문이다.

| 조건 | 결과 |
| --- | --- |
| 애니메이션 객체만 만들고 `start()` 안 함 | 정상 |
| 클로저를 연결하고 `start()` 안 함 | 정상 |
| 실행 중 + 파괴 | **크래시** |
| 실행 중 + `destroyed`에서 `stop()` | **크래시** — stop이 신호를 죽어가는 슬롯에 쏜다 |
| 실행 중 + `destroyed`에서 `disconnect()` | **크래시** — 그 시점엔 이미 늦다 |
| **부모 없이** 생성 + 실행 중 + 파괴 | **정상** |

### 해결

`gui/anim.py:track_animation()` — `track_thread()`와 같은 방식이다: 부모를 떼고,
멈출 때까지 모듈 레지스트리가 붙든다. **`finished`가 아니라 `stateChanged`로 놓아
준다** — `finished`는 끝까지 재생됐을 때만 나오므로 중간에 `stop()`으로 멈춘
애니메이션은 레지스트리에 영원히 남는다.

대가가 하나 있다: 부모를 떼면 애니메이션이 **대상 위젯보다 오래 살 수 있다.** 실제로
고친 직후 `_step`이 죽은 `RecommendStrip`을 건드려 `RuntimeError`가 났다. 그래서
콜백(`_step`·`_done`·`_stop_recommend_anim`)에 `RuntimeError` 가드를 넣고, 대상이
사라지면 애니메이션을 멈춘다 — **잡을 수 있는 예외가 access violation보다 낫다**는
판단이다. `fade_in`도 같은 패턴이었으므로(측정 시점엔 크래시하지 않았지만) 같은 규약으로
옮겼고, 예전의 `widget._fade_anim = anim`(GC 방지용 참조)은 위젯→애니메이션→클로저→위젯
순환을 만들어 파괴 순서를 GC에 맡기는 형태였으므로 제거했다.

### 조사에서 배운 측정 함정

**`QApplication.processEvents()`는 DeferredDelete 이벤트를 처리하지 않는다**(Qt 규약).
`deleteLater()` 뒤에 `sendPostedEvents(None, QEvent.Type.DeferredDelete)`를 함께
불러야 C++ 객체가 실제로 지워진다. 이걸 모른 채 한동안 "C++ 객체가 아직 살아 있는
상태"를 파괴 후라고 착각하며 측정했고, 그 때문에 원인을 **바운드 메서드로 잘못
지목**했다(아래 항목 참고). 회귀 테스트는 `_DRAIN` 절차로 이것을 고정한다.

또 하나: 프로브 스크립트 이름을 `bisect.py`로 두어 **표준 라이브러리 `bisect`를
가렸고**, 그 때문에 `lyrics_overlay`·`requests` 임포트가 깨져 무관한 부품이 범인처럼
보였다. 프로브 파일 이름은 표준 모듈명을 피할 것.

회귀 테스트: `tests/gui/test_panel_teardown.py`(자식 프로세스에서 종료 코드로 판정 —
access violation은 파이썬 예외가 아니라 프로세스를 즉사시켜 pytest가 보고할 수 없다).

---

## 해결: ThemeManager 싱글턴 람다 연결 (2026-09)

`LibraryPanel._connect_signals`가 좌측 트리 스타일을 이렇게 연결하고 있었다:

```python
ThemeManager.instance().theme_changed.connect(lambda _: self._apply_sidebar_tree_style())
```

`ThemeManager`는 앱 수명 내내 사는 싱글턴이라 패널보다 오래 살고, 위젯을 캡처한
람다는 Qt의 자동 연결 해제 보호를 받지 못한다 — 패널이 파괴된 뒤 테마가 바뀌면 이미
지워진 `_PlaylistTree`를 건드려
`RuntimeError: wrapped C/C++ object of type _PlaylistTree has been deleted`가 났다.
또한 싱글턴이 람다를 강한 참조로 붙들고 람다가 `self`를 캡처하므로 **패널 자체가
회수되지 않았다.**

이 누수는 예전부터 알려져 있었고 테스트에서 우회되고 있었다 —
`tests/gui/test_theme_transition.py`가 싱글턴 대신 `ThemeManager()`를 새로 만들어
쓰는 이유를 문서에 이렇게 적어 두었다: "여러 패널이 앱 수명 동안 살아있다고 가정하고
연결한 뒤 해제하지 않는 기존 코드… 그 신호를 실제로 emit하면 이미 죽은 다른
테스트의 위젯을 건드려" 실패한다. 전수 조사 결과 싱글턴 신호에 남은 람다 연결은
**그 한 곳뿐**이었고 나머지 20여 곳은 전부 바운드 메서드였다.

해결은 교과서적이다: 인자를 받아 버리는 **바운드 메서드**
(`SidebarTreeMixin._on_theme_changed`)를 두고 그것을 연결한다.

### 한 번 잘못 짚었던 기록

이 수정을 처음 적용했을 때 패널 파괴 시 access violation이 나서 **원인을 바운드
메서드로 지목하고 되돌린 적이 있다.** 그것은 틀렸다. 두 가지가 겹쳐 오판했다:

1. **`processEvents()`가 DeferredDelete를 처리하지 않는다**는 것을 몰라, C++ 객체가
   아직 살아 있는 상태를 "파괴 후"로 착각하며 측정했다.
2. 람다는 싱글턴이 강한 참조로 붙들어 **패널의 파이썬 래퍼가 아예 회수되지 않았다.**
   그래서 람다 상태에서는 파괴 경로가 실행되지 않았고, 바운드 메서드로 바꾸자 비로소
   회수되면서 **원래 있던 다른 결함**(실행 중 애니메이션이 패널의 자식 — 위 항목)이
   드러났다. 결정적 증거는 "테마 연결을 **아예 제거**해도 똑같이 죽는다"였다.

애니메이션 결함을 고친 뒤 이 수정은 문제없이 성립한다. 검증은 수정 전/후 대조로
했다 — 패널을 파괴한 뒤 싱글턴 `theme_changed`를 emit했을 때 수정 전에는 위 트레이스백이
나오고, 수정 후에는 나오지 않는다.

회귀 테스트: `tests/gui/test_theme_signal_lifetime.py`(규칙 자체를 AST로 — 새 위반
차단)와 `tests/gui/test_panel_teardown.py`(런타임 — 자식 프로세스에서 패널 파괴 후
테마 변경).

### 확인된 최종 상태

애니메이션 결함까지 고친 뒤 올바른 파괴 절차(`deleteLater()` +
`sendPostedEvents(None, DeferredDelete)` + 애니메이션이 끝날 시간)로 측정한 결과:

* **패널의 파이썬 래퍼가 완전히 회수된다**(`weakref`가 None). 애니메이션이 도는
  동안에는 그 `_done` 클로저 하나가 패널을 붙들지만, 멈추면 놓아 준다.
* **패널을 파괴한 뒤 테마를 바꿔도 아무 오류가 나지 않는다.**
* `receivers(theme_changed)` 수치는 패널마다 7씩 **누적된 채 남는다.** 다만
  `ThemeManager.children()`은 0이고 실제로 emit해 봐도 **아무것도 발화하지 않는다** —
  Qt 내부 집계에 남는 비활성 항목이고 기능적 누수가 아니다. 그래서
  `receivers()`는 "구독이 걸렸는가"를 확인하는 데만 쓰고(값이 늘어나는지),
  "해제됐는가"를 판정하는 데는 쓰지 않는다.

조사 도중 한때 "`self`를 캡처한 클로저 14개가 패널을 붙든다"고 적었는데, 그것도
`processEvents()`만으로 측정한 잘못된 값이었다 — C++ 객체를 제대로 지우면 자식 위젯
신호에 걸린 클로저는 함께 풀린다. 다만 그 조사 과정에서 `_step`이 `self`를 캡처하도록
고쳤던 부분은 한 칸짜리 목록(`holder`)으로 되돌려, 패널을 붙드는 클로저를 늘리지
않게 했다.

---

## 델리게이트 paint() 안의 예외는 앱을 통째로 끈다 (v1.27.1)

`DownloadProgressDTO`에는 `percent`·`speed_bps`·`eta_sec` 셋뿐이었는데, v1.27.0의
라이브 녹화 표시가 `progress.is_indeterminate`를 읽었다(그 속성은 도메인
`DownloadProgress`에만 있다). 결과는 **다운로드 카드가 하나라도 보이면 앱이 죽는
것**이었다 — `QStyledItemDelegate.paint()` 안에서 난 `AttributeError`를 PyQt가
프로세스 종료로 처리하기 때문이다(Windows에서 `0xC0000409`).

이 실패 방식이 고약한 이유는 **아무 흔적도 없다는 점**이다. 예외 메시지도, 로그도
없이 앱이 사라진다. 실제로 이 세션에서도 오프스크린 검증 스크립트가 조용히 죽어,
"기존 현상"으로 넘길 뻔했다. 원인을 좁힌 방법은 대조군이었다:

1. 이번 수정을 하나도 쓰지 않는 스크립트로 같은 절차를 밟았더니 **똑같이 죽었다**
   → 이번 변경 탓이 아니다.
2. 목록 위젯만 숨기고 돌렸더니 **살았다** → 그리는 경로다.
3. `option.rect`를 주고 델리게이트를 직접 호출해 재현했다.

DTO와 도메인 값 객체를 따로 두는 한 이 어긋남은 또 생긴다. 그래서 규칙을
`CLAUDE.md`에 적고, 회귀 테스트는 **실제로 그려 보는 것**으로 두었다
(`tests/gui/test_download_card_paint.py`) — 값만 검사하면 이 경로를 밟지 않는다.
