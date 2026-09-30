"""메인 창의 셸 부품 — 사이드바·라이브러리 페이지·다운로드 상태바·DB 백업 워커.

`gui/main_window.py`는 이 부품들을 **배치하고 배선만** 한다. 창 자체(frameless
타이틀바·`nativeEvent`·`closeEvent`·중복 실행 복원)는 `MainWindow`에 남는다 —
창 수명과 네이티브 훅은 한 클래스에 있어야 순서가 어긋나지 않는다.
"""
