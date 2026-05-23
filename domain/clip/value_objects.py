from __future__ import annotations


class TimeRange:
    __slots__ = ("start_sec", "end_sec")

    def __init__(self, start_sec: float, end_sec: float) -> None:
        if start_sec < 0:
            raise ValueError("start_sec must be >= 0")
        if end_sec <= start_sec:
            raise ValueError("end_sec must be greater than start_sec")
        self.start_sec = start_sec
        self.end_sec = end_sec

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, TimeRange)
            and self.start_sec == other.start_sec
            and self.end_sec == other.end_sec
        )

    def __hash__(self) -> int:
        return hash((self.start_sec, self.end_sec))

    def __repr__(self) -> str:
        return f"TimeRange({self.start_sec}, {self.end_sec})"
