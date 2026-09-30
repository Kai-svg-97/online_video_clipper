"""화면에 보일 한 덩어리를 **문장이 아니라 키와 값으로** 나르는 값 객체.

## 왜 필요한가

도메인이 완성된 한국어 문장을 만들어 GUI로 올리고 있었다(업데이트 툴팁·필터 요약·
모델 안내·트레이 알림). 레이어 규칙 위반이기도 하지만, 다국어화에서는 그것 때문에
**GUI만 번역해도 이 문장들은 한국어로 남는다**.

그렇다고 단순한 문자열 키만으로는 부족하다 — 대부분 숫자나 이름이 끼어 있다
("새 영상 3개", "약 5분"). 그래서 `Message`는 **키 + 파라미터**를 함께 나른다.
도메인은 *무엇을 말할지*를 정하고, 표시 계층(`gui/text/messages.py`)이 *어떤 말로
할지*를 정한다.

## 설계 원칙 — 키 하나가 완성된 문장 하나를 고른다

**문장 조각을 파라미터로 넘기지 않는다.** 예전 `DownloadWindow.describe()`가
`" (다음 날)"` 같은 조각을 f-string으로 이어 붙였는데, 언어가 바뀌면 어순이 달라져
조각을 끼워 넣을 자리가 없다. 그런 경우는 **키를 둘로 쪼갠다**
(`schedule.window` / `schedule.window_crossing`).

파라미터는 숫자·이름처럼 **값**만 담는다.

## 왜 dict가 아니라 정렬된 튜플인가

두 가지 이유다. frozen 데이터클래스가 해시 가능해야 집합·딕셔너리 키로 쓸 수 있고,
테스트가 `assert got == Message.of("key", n=3)` 한 줄로 끝난다 — 지금처럼 부분 문자열을
`in`으로 확인하는 것보다 강한 단언이다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    """표시할 문구 하나 — `key`가 문장을 고르고 `params`가 값을 채운다."""

    key: str
    params: tuple[tuple[str, object], ...] = ()

    @classmethod
    def of(cls, key: str, **params: object) -> "Message":
        """`Message.of("watch.count_only", total=3)` — 이 생성자를 쓴다.

        키워드 인자를 **정렬해** 담으므로 인자 순서가 달라도 같은 값이 된다.
        """
        return cls(key, tuple(sorted(params.items())))

    def as_dict(self) -> dict[str, object]:
        """템플릿에 채워 넣기 위한 형태."""
        return dict(self.params)


class DisplayError(Exception):
    """사용자에게 보여 줄 사유를 **문장이 아니라 `Message`로** 나르는 예외.

    애플리케이션·인프라가 `raise RuntimeError("YouTube API가 연결되지 않았습니다…")`처럼
    한국어 문장을 예외에 담으면, 뷰모델의 `error_occurred.emit(str(exc))`가 그 문장을
    그대로 화면에 올려 영어 화면에서도 한국어로 남는다. 이 예외는 `.message`에 키와
    값을 담고, 표시 계층의 `gui/text/messages.describe_error()`가 문장으로 바꾼다.

    `str(exc)`는 **로그용**이다 — 키(+파라미터)만 돌려주고 한국어 문장은 만들지 않는다.
    파라미터가 없으면 키 그대로라 화면 쪽이 키로 오류 종류를 판정할 수 있다
    (문장 비교는 번역하는 순간 어긋난다).

    기존 예외 계층을 지켜야 하는 곳(`except RuntimeError`가 잡고 있는 자리)은
    **다중 상속**으로 쓴다: `class SyncSchemaError(DisplayError, RuntimeError)`.
    """

    def __init__(self, message: Message) -> None:
        super().__init__(message.key)
        self.message = message

    def __str__(self) -> str:
        if not self.message.params:
            return self.message.key
        args = ", ".join(f"{k}={v}" for k, v in self.message.params)
        return f"{self.message.key} ({args})"


def error_message(exc: BaseException) -> Message:
    """예외 → `Message`. `DisplayError`면 그 메시지, 아니면 `str(exc)`를 값으로 싣는다.

    다른 예외의 사유를 **파라미터로** 끼워 넣을 때 쓴다(재생목록 가져오기가 두 경로의
    실패를 한 문장에 담는 것처럼). 문자열로 먼저 바꿔 버리면 안쪽 `DisplayError`가
    키 문자열로 굳어 번역할 기회를 잃는다.
    """
    if isinstance(exc, DisplayError):
        return exc.message
    return Message.of("error.raw", reason=str(exc))
