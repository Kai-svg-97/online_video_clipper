"""워치 폴더 판정 — 무엇을 읽고, 언제 읽고, 어디로 옮기나.

위험한 쪽은 "못 담는 것"이 아니라 **반쯤 담는 것**이다. 복사 중인 파일을 읽으면
주소가 잘린 채 들어오고, 그건 되돌리기 어렵다. 그리고 같은 파일을 두 번 담으면
라이브러리에 중복이 쌓인다.
"""

from __future__ import annotations

from domain.library.watch_folder import (
    DONE_DIR_NAME,
    MAX_PER_SCAN,
    SETTLE_SECONDS,
    WATCHED_SUFFIXES,
    done_name,
    extract_urls,
    is_settled,
    is_watched,
)


class TestWhichFiles:
    def test_주소가_담길_만한_것만_본다(self):
        assert is_watched("links.txt") is True
        assert is_watched("bookmarks.html") is True
        assert is_watched("영상.url") is True

    def test_대소문자를_가리지_않는다(self):
        assert is_watched("LINKS.TXT") is True

    def test_다른_파일은_건드리지_않는다(self):
        """폴더에 사진이나 문서가 섞여 있어도 손대면 안 된다."""
        assert is_watched("사진.jpg") is False
        assert is_watched("문서.docx") is False
        assert is_watched("") is False

    def test_윈도우_링크_파일을_본다(self):
        """링크를 폴더로 끌면 .url 파일이 생긴다 — 그것만으로 수집이 끝나야 한다."""
        assert ".url" in WATCHED_SUFFIXES


class TestSettling:
    def test_방금_만들어진_파일은_건너뛴다(self):
        """복사 중에 읽으면 주소가 잘린 채 들어온다."""
        assert is_settled(0.0) is False
        assert is_settled(1.0) is False

    def test_조용해지면_읽는다(self):
        assert is_settled(SETTLE_SECONDS) is True
        assert is_settled(60.0) is True

    def test_기다리는_시간이_너무_길지_않다(self):
        """늦게 담는 것은 괜찮지만, 분 단위로 기다리면 기능처럼 느껴지지 않는다."""
        assert SETTLE_SECONDS <= 10


class TestExtractUrls:
    def test_글에서_주소를_뽑는다(self):
        text = "여기 보세요 https://youtu.be/aaa 그리고 http://example.com/b 입니다"
        assert extract_urls(text) == ["https://youtu.be/aaa", "http://example.com/b"]

    def test_순서를_지킨다(self):
        text = "https://b.com\nhttps://a.com"
        assert extract_urls(text) == ["https://b.com", "https://a.com"]

    def test_중복은_한_번만(self):
        text = "https://youtu.be/x\nhttps://youtu.be/x"
        assert extract_urls(text) == ["https://youtu.be/x"]

    def test_끝에_붙은_문장부호를_턴다(self):
        """안 털면 받을 수 없는 주소가 된다."""
        assert extract_urls("보세요 (https://youtu.be/x).") == ["https://youtu.be/x"]
        assert extract_urls('"https://youtu.be/y",') == ["https://youtu.be/y"]

    def test_HTML에서도_뽑는다(self):
        html = '<a href="https://youtu.be/z">제목</a>'
        assert extract_urls(html) == ["https://youtu.be/z"]

    def test_윈도우_링크_파일을_읽는다(self):
        """이 형식에는 아이콘 경로도 들어 있어, 통째로 훑으면 엉뚱한 게 섞인다."""
        content = (
            "[InternetShortcut]\n"
            "URL=https://www.youtube.com/watch?v=abc\n"
            "IconIndex=0\n"
            "IconFile=C:\\Users\\x\\icon.ico\n"
        )
        assert extract_urls(content) == ["https://www.youtube.com/watch?v=abc"]

    def test_http가_아닌_것은_버린다(self):
        assert extract_urls("ftp://example.com/a file:///c:/x") == []

    def test_빈_입력은_빈_목록(self):
        assert extract_urls("") == []
        assert extract_urls("주소가 없는 글") == []

    def test_상한을_지킨다(self):
        """각 건이 네트워크 조회를 한 번씩 한다 — 수천 개를 한꺼번에 밀면 먹통이다."""
        text = "\n".join(f"https://youtu.be/{i:011d}" for i in range(500))
        assert len(extract_urls(text)) == MAX_PER_SCAN

    def test_상한을_직접_줄_수_있다(self):
        text = "\n".join(f"https://youtu.be/{i:011d}" for i in range(10))
        assert len(extract_urls(text, limit=3)) == 3


class TestDoneName:
    def test_겹치지_않으면_그대로(self):
        assert done_name("links.txt", []) == "links.txt"

    def test_겹치면_번호를_붙인다(self):
        """덮어쓰면 사용자가 되돌릴 수 없다 — 같은 파일을 여러 번 떨구는 일이 흔하다."""
        assert done_name("links.txt", ["links.txt"]) == "links (2).txt"

    def test_번호도_겹치면_계속_올린다(self):
        taken = ["a.txt", "a (2).txt"]
        assert done_name("a.txt", taken) == "a (3).txt"

    def test_확장자가_없어도_된다(self):
        assert done_name("links", ["links"]) == "links (2)"

    def test_처리됨_폴더_이름이_있다(self):
        """폴더를 보는 것만으로 무엇이 처리됐는지 알 수 있어야 한다."""
        assert DONE_DIR_NAME
