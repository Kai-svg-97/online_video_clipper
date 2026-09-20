# `gui/text/` — 화면에 나가는 말

## 규약 (테스트로 강제됨)

1. **PyQt6를 임포트하지 않는다.** — `tests/unit/gui/test_gui_text_purity.py`
   순수 파이썬이라 헤드리스 단위 테스트가 되고, 나중에 `presentation/` 계층으로
   이름만 바꿔 승격할 수 있다.
2. **도메인·애플리케이션은 이 패키지를 임포트하지 않는다.** 의존 방향은
   `gui → application → domain` 그대로다.
3. **번역은 `gui/text/__init__.py`의 `_()` 한 곳만 거친다.**

## 파일

| 파일 | 담당 |
| --- | --- |
| `__init__.py` | `_()` 번역 지점 |
| `labels.py` | 닫힌 키 집합 → 표시 이름 (dict) |
| `formats.py` | 숫자·시간·용량·상대시간 (언어 의존 포맷) |
| `messages.py` | `Message`(키+파라미터) → 문장 |

## 넣지 말 것

- **한 패널만 쓰는 라벨** — 그 패널의 `constants.py`에 두는 것이 맞다
  (`MATCH_FIELD_LABELS`, `ORIGIN_LABELS`가 그 예다)
- **사용자가 입력했거나 DB에 저장되는 이름** — 언어를 바꿨다고 저장된 행 이름이
  바뀌면 안 된다
- **데이터 처리용 한글** — `_STOPWORDS`·`_NOISE_WORDS` 같은 것은 화면 문구가 아니라
  언어 데이터다. 도메인에 그대로 둔다
