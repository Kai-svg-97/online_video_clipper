"""DownloadSectionMixin — 다운로드 섹션 — 폴더·화질·형식, 받는 방식(프리셋), 파일에 포함(굽기) 설정.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
)

from gui.panels.settings.helpers import _t
from gui.text import tr
from gui.text.labels import (
    default_preset_name,
    download_preset_name,
)

logger = logging.getLogger(__name__)


class DownloadSectionMixin:
    """다운로드 섹션 — 폴더·화질·형식, 받는 방식(프리셋), 파일에 포함(굽기) 설정."""

    def _build_download_section(self, layout) -> None:
        """다운로드 기본값(화질·형식·경로)."""
        # ── 다운로드 섹션 ──
        dl_label = QLabel(tr("다운로드"))
        dl_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(dl_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            cur_dl_dir = str(s.DOWNLOAD_DIR)
            cur_quality = s.DEFAULT_QUALITY
            cur_format = s.DEFAULT_FORMAT
        except Exception:
            logger.exception("다운로드 설정 로드 실패")
            cur_dl_dir = ""
            cur_quality = "best[ext=mp4]/best"
            cur_format = "mp4"

        # 다운로드 폴더
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_lbl = QLabel(tr("다운로드 폴더"))
        folder_lbl.setMinimumWidth(100)
        folder_lbl.setStyleSheet("font-size: 11px;")
        self._folder_edit = QLineEdit(cur_dl_dir)
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setStyleSheet("font-size: 10px; font-family: monospace;")
        browse_btn = QPushButton(tr("찾아보기"))
        browse_btn.setMinimumWidth(72)
        browse_btn.clicked.connect(self._on_browse_folder)
        folder_row.addWidget(folder_lbl)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)
        layout.addSpacing(10)

        # 기본 품질
        quality_row = QHBoxLayout()
        quality_row.setContentsMargins(0, 0, 0, 0)
        quality_lbl = QLabel(tr("기본 품질"))
        quality_lbl.setMinimumWidth(100)
        quality_lbl.setStyleSheet("font-size: 11px;")
        self._quality_combo = QComboBox()
        quality_options = [
            (tr("자동 (최고 품질)"), "best[ext=mp4]/best"),
            ("4K / UHD (2160p)", "bestvideo[height<=2160][ext=mp4]+bestaudio/best[height<=2160]"),
            ("1440p / QHD", "bestvideo[height<=1440][ext=mp4]+bestaudio/best[height<=1440]"),
            ("1080p / FHD", "bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]"),
            ("720p / HD", "bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720]"),
            ("480p", "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]"),
            ("360p", "bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360]"),
        ]
        for label, fmt in quality_options:
            self._quality_combo.addItem(label, fmt)
        matched = next((i for i, (_, f) in enumerate(quality_options) if f == cur_quality), 0)
        self._quality_combo.setCurrentIndex(matched)
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        quality_row.addWidget(quality_lbl)
        quality_row.addWidget(self._quality_combo)
        quality_row.addStretch()
        layout.addLayout(quality_row)
        layout.addSpacing(10)

        # 기본 포맷
        format_row = QHBoxLayout()
        format_row.setContentsMargins(0, 0, 0, 0)
        format_lbl = QLabel(tr("기본 포맷"))
        format_lbl.setMinimumWidth(100)
        format_lbl.setStyleSheet("font-size: 11px;")
        self._format_combo = QComboBox()
        for fmt in ("mp4", "mkv", "webm", "mp3", "m4a"):
            self._format_combo.addItem(fmt)
        fmt_idx = self._format_combo.findText(cur_format)
        self._format_combo.setCurrentIndex(fmt_idx if fmt_idx >= 0 else 0)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_row.addWidget(format_lbl)
        format_row.addWidget(self._format_combo)
        format_row.addStretch()
        layout.addLayout(format_row)
        layout.addSpacing(18)

        self._build_preset_rows(layout)
        self._build_embed_rows(layout)
        layout.addSpacing(28)

    def _on_browse_folder(self) -> None:
        from config import settings as s
        folder = QFileDialog.getExistingDirectory(
            self, tr("다운로드 폴더 선택"), self._folder_edit.text()
        )
        if folder:
            self._folder_edit.setText(folder)
            s.save_path_setting("downloads", folder)

    def _on_quality_changed(self, index: int) -> None:
        from config import settings as s
        fmt = self._quality_combo.itemData(index)
        if fmt:
            s.save_setting("default_quality", fmt)

    def _on_format_changed(self, index: int) -> None:
        from config import settings as s
        fmt = self._format_combo.currentText()
        s.save_setting("default_format", fmt)

    # ── 다운로드 프리셋 ───────────────────────────────────────────

    def _build_preset_rows(self, layout) -> None:
        """받는 방식을 이름 붙여 고르기.

        같은 사람이 영상을 받는 방식은 몇 가지로 갈린다(보관용·음악·가볍게). 그때마다
        아래 설정을 오가는 대신 골라 쓴다. **전송 옵션(속도·프록시)은 프리셋이 정하지
        않는다** — 회선의 성질이라 무엇을 받든 같기 때문이다.
        """
        from application.download.defaults import available_presets  # noqa: PLC0415
        from config import settings as cfg  # noqa: PLC0415

        layout.addSpacing(10)
        row = QHBoxLayout()
        lbl = QLabel(tr("받는 방식"))
        lbl.setMinimumWidth(100)
        self._preset_combo = QComboBox()
        self._preset_combo.addItem(tr("프리셋 없음 (아래 설정 그대로)"), "")
        for preset in available_presets():
            self._preset_combo.addItem(download_preset_name(preset), preset.key)
        idx = self._preset_combo.findData(cfg.ACTIVE_PRESET_KEY or "")
        self._preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._preset_combo.setMinimumWidth(240)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        row.addWidget(lbl)
        row.addWidget(self._preset_combo)
        row.addStretch()

        self._preset_save_btn = QPushButton(tr("지금 설정을 프리셋으로…"))
        self._preset_save_btn.setMinimumWidth(160)
        self._preset_save_btn.clicked.connect(self._on_preset_save)
        row.addWidget(self._preset_save_btn)

        self._preset_del_btn = QPushButton(tr("프리셋 지우기"))
        self._preset_del_btn.setMinimumWidth(100)
        self._preset_del_btn.clicked.connect(self._on_preset_delete)
        row.addWidget(self._preset_del_btn)
        layout.addLayout(row)

        self._preset_hint = QLabel("")
        self._preset_hint.setWordWrap(True)
        self._preset_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._preset_hint)
        self._refresh_preset_hint()

    def _refresh_preset_hint(self) -> None:
        from application.download.defaults import available_presets  # noqa: PLC0415
        from domain.download.download_presets import find  # noqa: PLC0415

        key = self._preset_combo.currentData() or ""
        preset = find(available_presets(), key) if key else None
        self._preset_del_btn.setEnabled(preset is not None)
        if preset is None:
            self._preset_hint.setText(
                tr(
                    "프리셋을 고르면 아래 화질·형식·자막·굽기 설정 대신 그 방식으로 받습니다. "
                    "속도 제한·프록시 같은 전송 옵션은 프리셋과 무관하게 늘 적용됩니다."
                )
            )
            return
        langs = preset.subtitle_langs or tr("자막 없음")
        if preset.sponsorblock_remove:
            summary = tr("{quality} · {fmt} · 자막 {langs} · 광고 잘라내기")
        else:
            summary = tr("{quality} · {fmt} · 자막 {langs}")
        self._preset_hint.setText(
            summary.format(quality=preset.quality, fmt=preset.fmt, langs=langs)
        )

    def _on_preset_changed(self, _index: int) -> None:
        self._save_setting("active_preset_key", self._preset_combo.currentData() or "")
        self._refresh_preset_hint()

    def _on_preset_save(self) -> None:
        """지금 화면의 설정을 프리셋으로 굳힌다."""
        from config import settings as cfg  # noqa: PLC0415
        from domain.download.download_presets import (  # noqa: PLC0415
            DownloadPreset,
            quality_from_selector,
            unique_name,
        )
        from application.download.defaults import available_presets  # noqa: PLC0415
        import uuid as _uuid  # noqa: PLC0415

        name, ok = QInputDialog.getText(self, tr("프리셋 저장"), tr("이름"), text=tr("내 프리셋"))
        if not ok:
            return
        existing = [p.name for p in available_presets()]
        preset = DownloadPreset(
            key=f"user:{_uuid.uuid4().hex[:8]}",
            name=unique_name(name, existing, fallback=default_preset_name()),
            quality=quality_from_selector(self._quality_combo.currentData()),
            fmt=self._format_combo.currentText() or "mp4",
            subtitle_langs=self._sub_langs_edit.text().strip(),
            embed_subtitles=self._embed_subs_check.isChecked(),
            embed_thumbnail=self._embed_thumb_check.isChecked(),
            embed_chapters=self._embed_chapters_check.isChecked(),
            sponsorblock_remove=self._sb_remove_check.isChecked(),
        )
        saved = list(cfg.DOWNLOAD_PRESETS or []) + [preset.to_payload()]
        self._save_setting("download_presets", saved)
        self._preset_combo.addItem(download_preset_name(preset), preset.key)
        self._preset_combo.setCurrentIndex(self._preset_combo.count() - 1)

    def _on_preset_delete(self) -> None:
        """고른 프리셋을 목록에서 뺀다.

        내장 프리셋은 지울 수 없으니 **숨긴다** — 코드에 있는 것을 설정으로 없앨
        방법이 달리 없고, 안 쓰는 항목이 목록에 남으면 고르기를 방해한다.
        """
        from config import settings as cfg  # noqa: PLC0415
        from domain.download.download_presets import BUILTIN_PREFIX  # noqa: PLC0415

        key = self._preset_combo.currentData() or ""
        if not key:
            return
        if key.startswith(BUILTIN_PREFIX):
            hidden = list(cfg.HIDDEN_PRESET_KEYS or [])
            if key not in hidden:
                hidden.append(key)
            self._save_setting("hidden_preset_keys", hidden)
        else:
            self._save_setting(
                "download_presets",
                [p for p in (cfg.DOWNLOAD_PRESETS or []) if p.get("key") != key],
            )
        self._preset_combo.removeItem(self._preset_combo.currentIndex())
        self._preset_combo.setCurrentIndex(0)

    def _build_embed_rows(self, layout) -> None:
        """부가 정보를 받은 파일 안에 굽는 설정(자막·표지·챕터·노래 태그)."""
        try:
            from config import settings as s
            cur_sub_langs = s.DOWNLOAD_SUBTITLE_LANGS
            cur_embed_subs = s.EMBED_SUBTITLES
            cur_embed_thumb = s.EMBED_THUMBNAIL
            cur_embed_chapters = s.EMBED_CHAPTERS
            cur_song_tags = s.WRITE_SONG_TAGS
        except Exception:
            logger.exception("굽기 설정 로드 실패")
            cur_sub_langs = ""
            cur_embed_subs = cur_embed_thumb = cur_embed_chapters = cur_song_tags = True

        embed_lbl = QLabel(tr("파일에 포함"))
        embed_lbl.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(embed_lbl)
        layout.addSpacing(8)

        # 자막 언어 — 비우면 자막을 아예 받지 않는다(굽기 체크도 무의미해진다).
        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(0, 0, 0, 0)
        sub_lbl = QLabel(tr("자막 언어"))
        sub_lbl.setMinimumWidth(100)
        sub_lbl.setStyleSheet("font-size: 11px;")
        self._sub_langs_edit = QLineEdit(cur_sub_langs)
        self._sub_langs_edit.setPlaceholderText(tr("비우면 자막을 받지 않습니다 (예: ko,en)"))
        self._sub_langs_edit.editingFinished.connect(self._on_sub_langs_changed)
        sub_row.addWidget(sub_lbl)
        sub_row.addWidget(self._sub_langs_edit, 1)
        layout.addLayout(sub_row)
        layout.addSpacing(10)

        self._embed_subs_check = QCheckBox(tr("자막을 영상 파일에 포함"))
        self._embed_subs_check.setChecked(cur_embed_subs)
        self._embed_subs_check.checkStateChanged.connect(self._on_embed_subs_changed)
        layout.addWidget(self._embed_subs_check)

        self._embed_thumb_check = QCheckBox(tr("썸네일을 표지로 포함"))
        self._embed_thumb_check.setChecked(cur_embed_thumb)
        self._embed_thumb_check.checkStateChanged.connect(self._on_embed_thumb_changed)
        layout.addWidget(self._embed_thumb_check)

        self._embed_chapters_check = QCheckBox(tr("챕터 정보를 포함"))
        self._embed_chapters_check.setChecked(cur_embed_chapters)
        self._embed_chapters_check.checkStateChanged.connect(self._on_embed_chapters_changed)
        layout.addWidget(self._embed_chapters_check)

        self._song_tags_check = QCheckBox(tr("음원에 노래 정보(가수·앨범·가사·표지) 기록"))
        self._song_tags_check.setChecked(cur_song_tags)
        self._song_tags_check.checkStateChanged.connect(self._on_song_tags_changed)
        layout.addWidget(self._song_tags_check)

        embed_hint = QLabel(
            tr(
                "받은 파일 하나만 옮겨도 자막·표지·챕터가 따라가므로 다른 플레이어·차량·"
                "휴대폰에서도 그대로 보입니다. 굽기를 켜면 자막은 별도 파일로 남기지 "
                "않습니다(플레이어가 같은 자막을 두 번 잡는 것을 막습니다)."
            )
        )
        embed_hint.setWordWrap(True)
        embed_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;"
        )
        layout.addWidget(embed_hint)
        layout.addSpacing(18)
        self._build_transfer_rows(layout)
        layout.addSpacing(18)
        self._build_sponsorblock_rows(layout)

    def _on_sub_langs_changed(self) -> None:
        self._save_setting("download_subtitle_langs", self._sub_langs_edit.text().strip())

    def _on_embed_subs_changed(self, _state) -> None:
        self._save_setting("embed_subtitles", self._embed_subs_check.isChecked())

    def _on_embed_thumb_changed(self, _state) -> None:
        self._save_setting("embed_thumbnail", self._embed_thumb_check.isChecked())

    def _on_embed_chapters_changed(self, _state) -> None:
        self._save_setting("embed_chapters", self._embed_chapters_check.isChecked())

    def _on_song_tags_changed(self, _state) -> None:
        self._save_setting("write_song_tags", self._song_tags_check.isChecked())
