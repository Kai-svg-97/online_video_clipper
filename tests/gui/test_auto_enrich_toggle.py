"""AUTO_ENRICH_ON_ADD 토글이 보강 워커 생성을 실제로 막는지 검증한다."""
from __future__ import annotations

from uuid import uuid4


class TestAutoEnrichToggle:
    def test_skipped_when_setting_off(self, library_vm, monkeypatch):
        """설정이 꺼져 있으면 워커도 큐도 생기지 않는다."""
        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", False)

        library_vm._maybe_enrich(uuid4(), "https://youtu.be/abc")

        assert library_vm._enrich_workers == []
        assert len(library_vm._pending_enrich) == 0

    def test_queued_when_setting_on(self, library_vm, monkeypatch):
        """설정이 켜져 있으면 워커가 하나 생성되고 올바른 커맨드로 핸들러를 부른다."""
        from application.library.commands import EnrichVideoResult

        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", True)
        library_vm._enrich_video.is_song_video.return_value = True
        # 실제 결과 타입을 돌려줘야 워커가 시그널을 정상 방출하고 스스로 끝난다.
        library_vm._enrich_video.handle.return_value = EnrichVideoResult("song", True, "2줄")
        video_id = uuid4()

        library_vm._maybe_enrich(video_id, "https://youtu.be/abc")

        assert len(library_vm._enrich_workers) == 1
        worker = library_vm._enrich_workers[0]
        # terminate() 없이 정상 종료를 기다린다 — 강제 종료는 로깅 락을 물고 죽을 수 있다.
        assert worker.wait(5000) is True
        library_vm._enrich_workers.clear()
        assert library_vm._enrich_video.handle.call_args.args[0].video_id == video_id

    def test_skipped_when_handler_missing(self, library_vm, monkeypatch):
        """보강 핸들러가 주입되지 않았으면 아무것도 하지 않는다."""
        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", True)
        library_vm._enrich_video = None

        library_vm._maybe_enrich(uuid4(), "https://youtu.be/abc")

        assert library_vm._enrich_workers == []

    def test_second_add_queues_behind_first(self, library_vm, monkeypatch):
        """동시 1건 — 두 번째 요청은 큐에서 대기한다."""
        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", True)
        library_vm._enrich_video.is_song_video.return_value = False

        library_vm._pending_enrich.append((uuid4(), "https://youtu.be/first"))
        library_vm._enrich_workers.append(object())   # 실행 중인 것처럼 위장
        library_vm._maybe_enrich(uuid4(), "https://youtu.be/second")

        # 실행 중인 워커가 있으므로 새 워커를 만들지 않고 큐에만 쌓는다.
        assert len(library_vm._enrich_workers) == 1
        assert len(library_vm._pending_enrich) == 2
        library_vm._enrich_workers.clear()
        library_vm._pending_enrich.clear()
