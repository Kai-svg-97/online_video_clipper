"""다운로드 파일에 부가 정보를 굽는 yt-dlp 옵션 구성 회귀 테스트.

여기서 고정하는 것은 **후처리기의 순서와 조합**이다. yt-dlp는 준 순서대로 실행할
뿐 재정렬하지 않으므로, 음원 추출이 뒤로 밀리면 앞에서 넣은 태그·표지가 새 파일로
옮겨지지 않는다. 순서가 깨져도 다운로드 자체는 성공하기 때문에 눈으로는 잡히지
않는다 — 그래서 테스트로 고정한다.
"""

from __future__ import annotations

import pytest

from domain.download.value_objects import DownloadSettings, MediaFormat, Quality
from infrastructure.downloader.ytdlp_adapter import _apply_sidecar_and_embed_opts


def _build(settings: DownloadSettings) -> dict:
    opts: dict = {}
    _apply_sidecar_and_embed_opts(opts, settings)
    return opts


def _pp_keys(opts: dict) -> list[str]:
    return [pp["key"] for pp in opts.get("postprocessors", [])]


def _pp(opts: dict, key: str) -> dict:
    return next(pp for pp in opts["postprocessors"] if pp["key"] == key)


class TestSubtitles:
    def test_자막_언어가_없으면_자막을_받지_않는다(self):
        opts = _build(DownloadSettings(embed_subtitles=True))
        assert "writesubtitles" not in opts
        assert "FFmpegEmbedSubtitle" not in _pp_keys(opts)

    def test_자막_언어가_있으면_자동생성_자막까지_받는다(self):
        opts = _build(DownloadSettings(subtitle_langs=("ko", "en")))
        assert opts["writesubtitles"] is True
        assert opts["writeautomaticsub"] is True
        assert opts["subtitleslangs"] == ["ko", "en"]

    def test_굽기가_켜지면_자막_파일은_남기지_않는다(self):
        opts = _build(
            DownloadSettings(subtitle_langs=("ko",), embed_subtitles=True)
        )
        assert _pp(opts, "FFmpegEmbedSubtitle")["already_have_subtitle"] is False

    @pytest.mark.parametrize("fmt", [MediaFormat.MP3, MediaFormat.M4A])
    def test_음원에는_자막을_굽지_않는다(self, fmt):
        """mp3·m4a 컨테이너는 자막 트랙을 담지 못한다 — 붙이면 경고만 남는다."""
        opts = _build(
            DownloadSettings(fmt=fmt, subtitle_langs=("ko",), embed_subtitles=True)
        )
        assert "FFmpegEmbedSubtitle" not in _pp_keys(opts)

    def test_webm_이_아닌_컨테이너만_자막을_굽는다(self):
        opts = _build(
            DownloadSettings(
                fmt=MediaFormat.MKV, subtitle_langs=("ko",), embed_subtitles=True
            )
        )
        assert "FFmpegEmbedSubtitle" in _pp_keys(opts)


class TestThumbnail:
    def test_굽기만_켜도_썸네일을_받는다(self):
        """받지 않으면 구울 것이 없다 — writethumbnail 을 빠뜨리면 조용히 실패한다."""
        opts = _build(DownloadSettings(include_thumbnail=False, embed_thumbnail=True))
        assert opts["writethumbnail"] is True
        assert _pp(opts, "EmbedThumbnail")["already_have_thumbnail"] is False

    def test_파일로도_남기면_구운_뒤_삭제하지_않는다(self):
        opts = _build(DownloadSettings(include_thumbnail=True, embed_thumbnail=True))
        assert _pp(opts, "EmbedThumbnail")["already_have_thumbnail"] is True

    def test_둘_다_끄면_썸네일을_받지_않는다(self):
        opts = _build(DownloadSettings(include_thumbnail=False, embed_thumbnail=False))
        assert "writethumbnail" not in opts
        assert "EmbedThumbnail" not in _pp_keys(opts)


class TestChapters:
    def test_챕터_굽기는_FFmpegMetadata_로_전달된다(self):
        opts = _build(DownloadSettings(include_metadata=False, embed_chapters=True))
        meta = _pp(opts, "FFmpegMetadata")
        assert meta["add_chapters"] is True
        assert meta["add_metadata"] is False

    def test_메타데이터도_챕터도_끄면_후처리기가_붙지_않는다(self):
        opts = _build(DownloadSettings(include_metadata=False, embed_chapters=False))
        assert "FFmpegMetadata" not in _pp_keys(opts)


class TestOrder:
    def test_음원_추출이_가장_먼저다(self):
        opts = _build(
            DownloadSettings(
                fmt=MediaFormat.MP3,
                quality=Quality.AUDIO,
                include_metadata=True,
                embed_thumbnail=True,
                embed_chapters=True,
            )
        )
        keys = _pp_keys(opts)
        assert keys[0] == "FFmpegExtractAudio"
        assert keys.index("FFmpegMetadata") < keys.index("EmbedThumbnail")

    def test_영상_전체_조합_순서(self):
        opts = _build(
            DownloadSettings(
                fmt=MediaFormat.MP4,
                subtitle_langs=("ko",),
                embed_subtitles=True,
                embed_thumbnail=True,
                embed_chapters=True,
                include_metadata=True,
            )
        )
        assert _pp_keys(opts) == [
            "FFmpegEmbedSubtitle",
            "FFmpegMetadata",
            "EmbedThumbnail",
        ]


class TestSponsorBlock:
    def test_비어_있으면_후처리기가_붙지_않는다(self):
        opts = _build(DownloadSettings())
        assert "SponsorBlock" not in _pp_keys(opts)
        assert "ModifyChapters" not in _pp_keys(opts)

    def test_카테고리를_주면_조회와_잘라내기가_함께_붙는다(self):
        opts = _build(DownloadSettings(sponsorblock_remove=("sponsor", "intro")))
        sb = _pp(opts, "SponsorBlock")
        assert sb["categories"] == ["sponsor", "intro"]
        # after_filter 여야 다운로드 전에 구간을 확보한다.
        assert sb["when"] == "after_filter"
        assert _pp(opts, "ModifyChapters")["remove_sponsor_segments"] == ["sponsor", "intro"]

    def test_자막을_구운_뒤에_잘라낸다(self):
        """순서가 바뀌면 잘라낸 만큼 자막 타이밍이 어긋난다."""
        opts = _build(
            DownloadSettings(
                subtitle_langs=("ko",),
                embed_subtitles=True,
                sponsorblock_remove=("sponsor",),
            )
        )
        keys = _pp_keys(opts)
        assert keys.index("FFmpegEmbedSubtitle") < keys.index("ModifyChapters")

    def test_메타데이터보다_먼저_잘라낸다(self):
        opts = _build(
            DownloadSettings(include_metadata=True, sponsorblock_remove=("sponsor",))
        )
        keys = _pp_keys(opts)
        assert keys.index("ModifyChapters") < keys.index("FFmpegMetadata")
