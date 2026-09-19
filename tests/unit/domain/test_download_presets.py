"""다운로드 프리셋 — 값 객체·내장 묶음·병합 규칙.

프리셋이 담는 것은 **어떤 파일을 원하는가**(화질·형식·자막·굽기)이고, 담지 않는 것은
**어떻게 받는가**(속도 제한·프록시·조각 수)다. 후자는 회선의 성질이라 무엇을 받든
같고, 프리셋마다 따로 두면 "왜 이 프리셋만 느리지"가 된다.
"""

from __future__ import annotations

from domain.download.download_presets import (
    BUILTIN_PRESETS,
    MAX_NAME_LEN,
    DownloadPreset,
    find,
    merge,
    normalize_name,
    quality_from_selector,
    unique_name,
)


class TestBuiltins:
    def test_흔한_세_가지를_미리_둔다(self):
        """빈 목록에서 시작하면 무엇을 만들 수 있는지 모른다."""
        assert len(BUILTIN_PRESETS) == 3

    def test_전부_내장으로_표시된다(self):
        assert all(p.is_builtin for p in BUILTIN_PRESETS)

    def test_이름과_키가_모두_있다(self):
        assert all(p.name and p.key for p in BUILTIN_PRESETS)

    def test_키가_겹치지_않는다(self):
        keys = [p.key for p in BUILTIN_PRESETS]
        assert len(keys) == len(set(keys))

    def test_음악은_음원_형식이다(self):
        music = next(p for p in BUILTIN_PRESETS if "음악" in p.name)
        assert music.fmt in ("m4a", "mp3")
        assert music.subtitle_langs == ""      # 음원에 자막은 쓸모가 없다

    def test_전송_설정은_담지_않는다(self):
        """속도·프록시는 회선의 성질이라 프리셋마다 달라야 할 이유가 없다."""
        fields = set(DownloadPreset.__slots__)
        assert "rate_limit" not in fields
        assert "proxy" not in fields
        assert "concurrent_fragments" not in fields


class TestSerialization:
    def test_왕복해도_같다(self):
        original = BUILTIN_PRESETS[0]
        assert DownloadPreset.from_payload(original.to_payload()) == original

    def test_이름이_없으면_버린다(self):
        """이름이 없으면 목록에서 고를 수 없다."""
        assert DownloadPreset.from_payload({"key": "x", "name": ""}) is None

    def test_사전이_아니면_버린다(self):
        assert DownloadPreset.from_payload("문자열") is None
        assert DownloadPreset.from_payload(None) is None

    def test_모르는_키는_무시한다(self):
        """앱 버전을 오르내리면 필드가 늘거나 준다."""
        got = DownloadPreset.from_payload({"name": "내 것", "옛날필드": 1})
        assert got is not None and got.name == "내 것"

    def test_빠진_키는_기본값으로_채운다(self):
        got = DownloadPreset.from_payload({"name": "내 것"})
        assert got.quality == "1080p"


class TestNames:
    def test_공백을_턴다(self):
        assert normalize_name("  내   프리셋 ") == "내 프리셋"

    def test_너무_길면_자른다(self):
        assert len(normalize_name("가" * 100)) == MAX_NAME_LEN

    def test_겹치면_번호를_붙인다(self):
        assert unique_name("내 것", ["내 것"]) == "내 것 2"

    def test_비면_기본값을_준다(self):
        assert unique_name("  ", []) == "내 프리셋"


class TestMerge:
    def _user(self, key="user:1", name="내 것"):
        return DownloadPreset(key=key, name=name, quality="480p")

    def test_내장과_사용자_것을_모두_준다(self):
        got = merge(BUILTIN_PRESETS, [self._user()], hidden_keys=[])
        assert len(got) == len(BUILTIN_PRESETS) + 1

    def test_같은_키면_사용자_것이_이긴다(self):
        """내장을 고쳐 쓴 경우다."""
        overridden = DownloadPreset(key=BUILTIN_PRESETS[0].key, name="고친 것",
                                    quality="4K")
        got = merge(BUILTIN_PRESETS, [overridden], hidden_keys=[])

        assert find(got, BUILTIN_PRESETS[0].key).name == "고친 것"
        assert len(got) == len(BUILTIN_PRESETS)

    def test_숨긴_내장은_빠진다(self):
        """안 쓰는 항목이 목록에 남아 고르기를 방해하면 안 된다."""
        hidden = BUILTIN_PRESETS[1].key
        got = merge(BUILTIN_PRESETS, [], hidden_keys=[hidden])

        assert find(got, hidden) is None
        assert len(got) == len(BUILTIN_PRESETS) - 1

    def test_고쳐_둔_것은_숨김보다_우선한다(self):
        """숨김은 '원래 것'에만 걸린다 — 고쳐 쓴 것까지 지우면 작업이 사라진다."""
        key = BUILTIN_PRESETS[0].key
        mine = DownloadPreset(key=key, name="내가 고친 것")

        got = merge(BUILTIN_PRESETS, [mine], hidden_keys=[key])

        assert find(got, key) is not None

    def test_사용자_것만_있어도_된다(self):
        got = merge((), [self._user()], hidden_keys=[])
        assert [p.name for p in got] == ["내 것"]


class TestFind:
    def test_없으면_None(self):
        """설정이 낡아 사라진 프리셋을 가리킬 수 있다."""
        assert find(list(BUILTIN_PRESETS), "없는키") is None

    def test_있으면_그것을_준다(self):
        assert find(list(BUILTIN_PRESETS), BUILTIN_PRESETS[0].key) == BUILTIN_PRESETS[0]


class TestQualityFromSelector:
    """설정 콤보는 yt-dlp 선택자를, 프리셋은 화질 이름을 쓴다."""

    def test_높이를_알아본다(self):
        assert quality_from_selector(
            "bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]"
        ) == "1080p"
        assert quality_from_selector("bestvideo[height<=720]+bestaudio") == "720p"
        assert quality_from_selector("bestvideo[height<=2160]+bestaudio") == "2160p"

    def test_자동은_best(self):
        assert quality_from_selector("best[ext=mp4]/best") == "best"

    def test_모르는_높이는_낮추지_않는다(self):
        """1440p를 1080p로 내리면 사용자가 고른 것보다 낮은 화질을 받는다."""
        assert quality_from_selector("bestvideo[height<=1440]+bestaudio") == "best"

    def test_빈_값도_안전하다(self):
        assert quality_from_selector("") == "best"
        assert quality_from_selector(None) == "best"
