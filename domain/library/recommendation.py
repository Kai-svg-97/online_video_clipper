"""추천 검색어 파생 — 지금 보고 있는 영상 목록에서 YouTube 검색어를 뽑는 순수 로직.

YouTube Data API v3의 ``search.list(relatedToVideoId=...)``는 2023-08-07에
제거되어 '관련 영상'을 API로 직접 받을 수 없다. 그래서 현재 목록의
제목·태그·채널에서 **대표 검색어 몇 개**를 뽑아 YouTube 검색으로 후보를 모은다.

단, 사용자가 검색창에 낱말을 입력한 상태라면 짐작을 그만두고 **그 낱말을 그대로**
검색어로 쓴다(검색어를 결정하는 곳이 한 군데뿐이어야 두 경로가 어긋나지 않는다).

규칙을 순수 함수로 고정해 QApplication·네트워크 없이 단위 테스트로 검증한다
(``tests/unit/domain/test_recommendation.py``).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

MAX_SEED_QUERIES = 3

# 제목 앞뒤에 붙는 장식 구간([MV], (Official Video), 【4K】 …)은 내용 식별에
# 도움이 안 되므로 토큰화 전에 제거한다.
_BRACKETED = re.compile(r"[\[\(【《][^\]\)】》]*[\]\)】》]")
# 한글·영문·숫자만 토큰으로 인정한다(이모지·기호·구두점은 구분자).
_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z가-힣]+")

# 어느 영상 제목에나 흔히 붙어 검색어로서 정보량이 없는 토큰.
_STOPWORDS = frozenset({
    "official", "video", "audio", "lyrics", "lyric", "mv", "hd", "fhd", "uhd",
    "4k", "8k", "1080p", "720p", "full", "ver", "version", "feat", "ft",
    "the", "and", "for", "with", "you", "your", "this", "that", "from",
    "shorts", "teaser", "trailer", "clip", "live", "sub", "eng",
    "영상", "공식", "뮤직비디오", "자막", "한글", "한글자막", "다시보기",
    "무료", "최신", "모음", "그리고", "하는", "입니다", "합니다", "했습니다",
})

_MIN_TOKEN_LEN = 2
_MAX_KEYWORDS_PER_QUERY = 3


def _tokenize(title: str) -> set[str]:
    """제목 한 건에서 의미 있는 토큰 집합을 뽑는다(중복 제거)."""
    cleaned = _BRACKETED.sub(" ", title or "")
    tokens: set[str] = set()
    for raw in _TOKEN_SPLIT.split(cleaned):
        tok = raw.strip()
        if len(tok) < _MIN_TOKEN_LEN or tok.isdigit():
            continue
        if tok.lower() in _STOPWORDS:
            continue
        tokens.add(tok)
    return tokens


def _top_keywords(titles: Iterable[str], count: int = _MAX_KEYWORDS_PER_QUERY) -> list[str]:
    """제목들에서 대표 키워드를 문서빈도(df) 순으로 뽑는다.

    df(그 토큰을 포함한 제목 수)를 쓰는 이유: 한 제목에서 같은 단어가 반복돼도
    목록 전체를 대표하지는 않기 때문이다. df가 2 이상인 토큰이 하나도 없으면
    (목록이 아주 작거나 제목이 제각각인 경우) df 1 토큰 중 긴 것을 쓴다.
    """
    df: Counter[str] = Counter()
    for title in titles:
        df.update(_tokenize(title))
    if not df:
        return []
    shared = [t for t, n in df.items() if n >= 2]
    pool = shared or list(df)
    # 1순위 df 내림차순, 2순위 길이 내림차순(긴 토큰이 더 구체적), 3순위 사전순(결정성).
    pool.sort(key=lambda t: (-df[t], -len(t), t))
    return pool[:count]


def _most_common(values: Iterable[str]) -> str:
    """가장 자주 등장한 값(동률이면 사전순)을 반환한다."""
    counter = Counter(v.strip() for v in values if v and v.strip())
    if not counter:
        return ""
    return min(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def derive_seed_queries(
    titles: Iterable[str],
    channels: Iterable[str] = (),
    tags: Iterable[str] = (),
    max_queries: int = MAX_SEED_QUERIES,
    search_text: str = "",
) -> list[str]:
    """현재 목록을 대표하는 YouTube 검색어를 최대 ``max_queries``개 만든다.

    ``search_text``(사용자가 검색창에 직접 입력한 낱말)가 있으면 **그것만** 검색어로
    쓴다. 사용자가 이미 무엇을 찾는지 말했으므로 목록에서 검색어를 짐작할 이유가
    없고, 짐작한 검색어를 섞으면 그 키워드와 무관한 후보가 함께 올라온다. 검색
    결과가 0건이어도(그래서 목록이 비어도) 이 검색어는 유효하다 — 애초에
    "라이브러리에 없는 영상"을 찾는 것이 추천 스트립의 목적이다.

    ``search_text``가 없을 때의 반환 순서는 대표성이 높은 순이다:

    1. 제목 대표 키워드 묶음 (목록 전체를 가장 잘 대표)
    2. 가장 많이 쓰인 태그 (사용자가 직접 붙인 분류라 신뢰도가 높다)
    3. 가장 많은 영상을 가진 채널명 (그 채널·유사 채널 영상을 끌어온다)

    같은 검색어가 중복되지 않게 대소문자 무시로 중복 제거하며, 빈 문자열은
    버린다. 목록이 비어 있으면 빈 리스트를 반환한다(호출 측은 조회를 건너뛴다).
    """
    if max_queries <= 0:
        return []
    explicit = (search_text or "").strip()
    if explicit:
        return [explicit]
    title_list = [t for t in titles if t]
    queries: list[str] = []

    keywords = _top_keywords(title_list)
    if keywords:
        queries.append(" ".join(keywords))

    top_tag = _most_common(tags)
    if top_tag:
        queries.append(top_tag)

    top_channel = _most_common(channels)
    if top_channel:
        queries.append(top_channel)

    result: list[str] = []
    seen: set[str] = set()
    for q in queries:
        q = q.strip()
        key = q.lower()
        if not q or key in seen:
            continue
        seen.add(key)
        result.append(q)
        if len(result) >= max_queries:
            break
    return result
