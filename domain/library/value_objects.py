from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def normalize_video_url(url: str) -> str:
    """Return canonical URL form.

    YouTube/youtu.be → https://www.youtube.com/watch?v=ID  (strips list=, si=, etc.)
    Everything else  → unchanged.
    """
    url = url.strip()
    parsed = urlparse(url)
    host = parsed.netloc.lower().lstrip("www.")
    if host == "youtube.com":
        params = parse_qs(parsed.query, keep_blank_values=False)
        vid = params.get("v", [None])[0]
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    elif host == "youtu.be":
        vid = parsed.path.lstrip("/").split("?")[0].split("/")[0]
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    return url


class VideoUrl:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        value = normalize_video_url(value)
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL: {value!r}")
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def __str__(self) -> str:
        return self._value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VideoUrl) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"VideoUrl({self._value!r})"


class Duration:
    """Video duration stored as whole seconds."""

    __slots__ = ("_seconds",)

    def __init__(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("Duration cannot be negative")
        self._seconds = seconds

    @property
    def seconds(self) -> int:
        return self._seconds

    def formatted(self) -> str:
        h, rem = divmod(self._seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Duration) and self._seconds == other._seconds

    def __hash__(self) -> int:
        return hash(self._seconds)

    def __repr__(self) -> str:
        return f"Duration({self._seconds})"


class ChannelInfo:
    __slots__ = ("name", "url", "channel_id")

    def __init__(self, name: str, url: str, channel_id: str) -> None:
        self.name = name
        self.url = url
        self.channel_id = channel_id

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ChannelInfo) and self.channel_id == other.channel_id

    def __hash__(self) -> int:
        return hash(self.channel_id)

    def __repr__(self) -> str:
        return f"ChannelInfo({self.name!r})"
