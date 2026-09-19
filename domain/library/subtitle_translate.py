"""자막 번역 규칙 — **순수 판정**, 네트워크도 저장도 없다.

외국어 영상에 자막이 있어도 읽지 못하면 없는 것과 같다. 음성 인식으로 만든 자막도
마찬가지다 — 소리는 들었는데 뜻을 모른다. 이미 있는 번역기(`ITranslator`)를 자막에도
쓴다.

## 왜 묶어 보내나

번역기는 **한 줄씩** 호출한다(가사 40줄에 맞춘 설계다). 자막은 수백~수천 줄이라
그대로 쓰면 왕복이 그만큼 나고, 몇 분이 걸리며 백엔드가 막기도 한다. 그래서 여러
줄을 줄바꿈으로 이어 한 번에 보낸다.

**대신 정렬이 깨질 수 있다.** 번역기가 줄을 합치거나 나누면 원문과 번역의 짝이
어긋나고, 그러면 **엉뚱한 시점에 엉뚱한 말이 뜬다** — 틀렸다는 티도 안 난다. 그래서
묶음마다 **줄 수를 확인**하고, 맞지 않으면 그 묶음만 한 줄씩 다시 한다.

## 왜 원본을 덮지 않나

번역은 원문을 대체하는 것이 아니다. 원문으로 검색하고 싶을 수도 있고, 번역이 엉망일
수도 있다. 그래서 `tr-ko` 같은 **별도 언어 키**로 저장한다(음성 인식이 `asr-auto`를
쓰는 것과 같은 이유다).
"""

from __future__ import annotations

# 한 번에 보낼 줄 수. 크게 잡을수록 왕복이 줄지만, 정렬이 깨졌을 때 다시 해야 할
# 양도 그만큼 는다. 40줄이면 500줄짜리 자막이 13번 왕복이다.
CHUNK_LINES = 40

# 번역 결과를 담는 언어 키의 접두. 원문(`ko`·`en`·`asr-auto`)과 겹치지 않아야
# 다시 받은 자막이 번역을 덮어쓰지 않는다.
TRANSLATED_PREFIX = "tr-"

# 번역할 가치가 있는 최소 글자 수 — 숫자나 기호뿐인 줄은 보내도 그대로 온다.
_MIN_TEXT_LEN = 2


def translated_lang(target: str = "ko") -> str:
    """번역 결과를 담을 언어 키."""
    return f"{TRANSLATED_PREFIX}{target}"


def is_translated_lang(lang: str) -> bool:
    """이미 번역본인가 — 번역본을 또 번역하지 않기 위한 판정."""
    return (lang or "").startswith(TRANSLATED_PREFIX)


def needs_translation(texts: list[str], detected: str, target: str = "ko") -> bool:
    """번역할 것이 있는가.

    **이미 목표 언어면 하지 않는다.** 한국어 자막을 한국어로 번역하면 왕복만 낭비하고
    결과도 원문보다 나빠진다(번역기가 문장을 다시 쓴다).
    """
    if detected and detected == target:
        return False
    return any(t and len(t.strip()) >= _MIN_TEXT_LEN for t in texts)


def chunks(texts: list[str], size: int = CHUNK_LINES) -> list[tuple[int, list[str]]]:
    """`(시작 인덱스, 줄들)` 묶음으로 나눈다 — 인덱스가 있어야 제자리에 돌려놓는다."""
    if size <= 0:
        size = CHUNK_LINES
    return [(i, texts[i : i + size]) for i in range(0, len(texts), size)]


def join_chunk(lines: list[str]) -> str:
    """묶음을 한 덩어리로 — 빈 줄은 자리를 지키되 내용은 비운다."""
    return "\n".join((line or "").strip() for line in lines)


def split_chunk(original: list[str], translated: str) -> list[str] | None:
    """번역 덩어리를 줄로 되돌린다. **줄 수가 맞지 않으면 None**.

    None은 "이 묶음은 믿을 수 없으니 한 줄씩 다시 하라"는 뜻이다. 억지로 맞추면
    엉뚱한 시점에 엉뚱한 말이 뜨는데, 그건 틀렸다는 티조차 나지 않는다.
    """
    if not translated:
        return None
    parts = translated.split("\n")
    if len(parts) != len(original):
        return None
    # 원문이 비어 있던 자리는 비운 채 둔다 — 번역기가 뭔가 채워 넣기도 한다.
    return [
        (part.strip() if (orig or "").strip() else "")
        for orig, part in zip(original, parts)
    ]


def merge(original: list[str], translated: list[str]) -> list[str]:
    """번역이 비었거나 실패한 자리는 **원문을 남긴다**.

    빈 줄로 두면 그 시점에 자막이 사라져, 사용자는 번역이 실패한 것인지 원래 말이
    없는 것인지 알 수 없다.
    """
    out: list[str] = []
    for orig, tr in zip(original, translated):
        text = (tr or "").strip()
        out.append(text or (orig or ""))
    return out
