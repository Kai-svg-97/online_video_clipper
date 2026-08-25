"""`_PlaylistTree`의 동작 묶음 — 런타임 클래스는 하나(mixin 합성)다.

`tree.py`가 시그널·`__init__`·행 그리기·선택/탐색을 들고, 부피가 큰 동작
(스피너·로드/아이템 팩토리·드래그앤드롭·컨텍스트 메뉴)을 이 패키지가 나눠 갖는다.
상태 공유 방식은 분할 전과 같다 — 전부 같은 인스턴스의 `self`를 쓴다.

**테스트에서 monkeypatch할 때는 쓰는 쪽 모듈을 패치해야 한다**(여기서 재수출한
이름을 바꿔도 소용없다 — 다른 분할에서 실제로 3건이 이 이유로 깨졌다).
"""
from __future__ import annotations

from gui.panels.library.tree_mixins.context_menu import _TreeContextMenuMixin
from gui.panels.library.tree_mixins.dnd import _TreeDragDropMixin
from gui.panels.library.tree_mixins.items import _TreeItemsMixin
from gui.panels.library.tree_mixins.spinner import _TreeSpinnerMixin

__all__ = [
    "_TreeContextMenuMixin",
    "_TreeDragDropMixin",
    "_TreeItemsMixin",
    "_TreeSpinnerMixin",
]
