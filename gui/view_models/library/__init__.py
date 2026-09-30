"""LibraryViewModel을 주제별로 나눈 mixin 모음 + 백그라운드 워커.

런타임 클래스는 `gui/view_models/library_vm.py`의 `LibraryViewModel` 하나다 — 여기
모듈들은 그 클래스를 **파일 단위로 나눴을 뿐**이다. 시그널·생성자·`shutdown()`은
전부 `library_vm.py`에 남는다(시그널은 QObject 서브클래스에 있어야 하고, 워커 수명
규약 `WorkerOwnerMixin`은 한곳에서 섞어야 어긋나지 않는다).

테스트에서 워커를 `monkeypatch`할 때는 **그 워커를 쓰는 mixin 모듈**을 패치한다
(예: `_ListVideosWorker` → `gui.view_models.library.listing`). `library_vm`에 남은
재수출 이름을 바꿔도 mixin이 보는 이름은 그대로다.
"""
