"""브라우저 북마크 HTML 해석.

이 형식(Netscape Bookmark File Format)은 **닫는 태그가 없다** — `<DT>`·`<p>`가 열린
채로 끝난다. 제대로 된 HTML이 아니라서 엄격한 파서는 구조를 잘못 잡거나 통째로
실패한다. 그래서 필요한 두 가지(`<A HREF>`, `<H3>`)만 순서대로 훑는다.

고정하는 함정:

1. 폴더 이름을 **링크와 같은 순서로** 읽어야 그 링크가 어느 폴더 아래였는지 안다.
2. `javascript:`·`place:` 같은 것은 받을 수 없다 — 목록에 섞이면 고르기만 번거롭다.
3. 같은 영상을 여러 폴더에 넣어 두는 일이 흔하다 — 중복은 한 번만.
4. 제목에 HTML 엔티티(`&amp;`)와 태그가 섞여 온다.
"""

from __future__ import annotations

from domain.library.bookmarks import Bookmark, is_likely_video, parse_bookmarks

SAMPLE = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1700000000">음악</H3>
    <DL><p>
        <DT><A HREF="https://youtu.be/aaaaaaaaaaa" ADD_DATE="1">노래 &amp; 가사</A>
        <DT><A HREF="https://www.youtube.com/watch?v=bbbbbbbbbbb">두 번째</A>
    </DL><p>
    <DT><H3>참고</H3>
    <DL><p>
        <DT><A HREF="https://example.com/article">글 하나</A>
        <DT><A HREF="javascript:void(0)">북마클릿</A>
        <DT><A HREF="https://youtu.be/aaaaaaaaaaa">같은 영상 또</A>
    </DL><p>
</DL><p>
"""


class TestParsing:
    def test_링크를_순서대로_읽는다(self):
        marks = parse_bookmarks(SAMPLE)
        assert [m.url for m in marks] == [
            "https://youtu.be/aaaaaaaaaaa",
            "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            "https://example.com/article",
        ]

    def test_폴더_이름을_함께_준다(self):
        """카테고리를 제안하는 근거다."""
        marks = {m.url: m.folder for m in parse_bookmarks(SAMPLE)}
        assert marks["https://youtu.be/aaaaaaaaaaa"] == "음악"
        assert marks["https://example.com/article"] == "참고"

    def test_엔티티와_태그를_푼다(self):
        assert parse_bookmarks(SAMPLE)[0].title == "노래 & 가사"

    def test_받을_수_없는_주소는_버린다(self):
        urls = [m.url for m in parse_bookmarks(SAMPLE)]
        assert not any(u.startswith("javascript:") for u in urls)

    def test_같은_주소는_한_번만(self):
        """같은 영상을 여러 폴더에 넣어 두는 일이 흔하다."""
        urls = [m.url for m in parse_bookmarks(SAMPLE)]
        assert len(urls) == len(set(urls))

    def test_제목이_없으면_주소를_쓴다(self):
        marks = parse_bookmarks('<DT><A HREF="https://youtu.be/x"></A>')
        assert marks[0].title == "https://youtu.be/x"

    def test_빈_입력은_빈_목록(self):
        assert parse_bookmarks("") == []
        assert parse_bookmarks("<html></html>") == []

    def test_대문자_태그도_읽는다(self):
        """브라우저마다 태그 대소문자가 다르다."""
        marks = parse_bookmarks('<DT><A HREF="https://youtu.be/x">제목</A>')
        assert len(marks) == 1

    def test_작은따옴표_속성도_읽는다(self):
        marks = parse_bookmarks("<a href='https://youtu.be/x'>제목</a>")
        assert marks[0].url == "https://youtu.be/x"


class TestLikelyVideo:
    def test_흔한_영상_호스트를_알아본다(self):
        assert is_likely_video("https://youtu.be/abc") is True
        assert is_likely_video("https://www.youtube.com/watch?v=abc") is True
        assert is_likely_video("https://music.youtube.com/watch?v=abc") is True
        assert is_likely_video("https://vimeo.com/123") is True

    def test_서브도메인도_알아본다(self):
        assert is_likely_video("https://m.youtube.com/watch?v=abc") is True

    def test_흉내내는_주소에_속지_않는다(self):
        """`youtube.com.evil.example`을 영상으로 보면 안 된다."""
        assert is_likely_video("https://youtube.com.evil.example/x") is False

    def test_그_외는_사용자가_고른다(self):
        """목록에 없다고 못 받는 게 아니다 — 미리 체크만 안 할 뿐이다."""
        assert is_likely_video("https://example.com/video.mp4") is False

    def test_http가_아니면_아니다(self):
        assert is_likely_video("javascript:void(0)") is False
        assert is_likely_video("") is False

    def test_북마크가_스스로_판정한다(self):
        assert Bookmark("https://youtu.be/x", "제목").is_likely_video is True
        assert Bookmark("https://example.com", "제목").is_likely_video is False
