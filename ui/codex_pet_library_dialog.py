"""Local and online Codex pet library dialog."""

from __future__ import annotations

import html
import logging
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.services.codex_pet_service import (
    CodexPetCatalogItem,
    CodexPetCatalogPage,
    CodexPetError,
    CodexPetImportResult,
    CodexPetPackage,
    CodexPetService,
)
from ui.styles import current_theme
from ui.theme import generate_button_style, generate_input_style

logger = logging.getLogger(__name__)


class _CodexPetDiscoveryWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service: CodexPetService) -> None:
        super().__init__()
        self._service = service

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._service.discover_pets())
        except Exception as exc:  # pragma: no cover - final Qt worker boundary
            logger.exception("Unexpected local Codex pet discovery failure")
            self.failed.emit(str(exc) or "读取本机 Codex 宠物时发生未知错误")


class _CodexPetImportWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: CodexPetService,
        pet: CodexPetPackage | CodexPetCatalogItem,
    ) -> None:
        super().__init__()
        self._service = service
        self._pet = pet

    @Slot()
    def run(self) -> None:
        try:
            if isinstance(self._pet, CodexPetCatalogItem):
                result = self._service.activate_remote_pet(self._pet)
            else:
                result = self._service.activate_pet(self._pet)
            self.finished.emit(result)
        except CodexPetError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.exception("Unexpected Codex pet import failure")
            self.failed.emit(str(exc) or "准备宠物动画时发生未知错误")


class _CodexPetCatalogWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: CodexPetService,
        *,
        page: int,
        query: str,
        sort: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._page = page
        self._query = query
        self._sort = sort

    @Slot()
    def run(self) -> None:
        try:
            result = self._service.fetch_remote_catalog(
                page=self._page,
                query=self._query,
                sort=self._sort,
            )
            self.finished.emit(result)
        except CodexPetError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.exception("Unexpected Codex Pets catalog failure")
            self.failed.emit(str(exc) or "同步在线宠物时发生未知错误")


class _CodexPetPreviewWorker(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, service: CodexPetService, pet: CodexPetCatalogItem) -> None:
        super().__init__()
        self._service = service
        self._pet = pet

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._pet.pet_id, self._service.fetch_remote_preview(self._pet))
        except CodexPetError as exc:
            self.failed.emit(self._pet.pet_id, str(exc))
        except Exception as exc:
            logger.exception("Unexpected Codex pet preview failure")
            self.failed.emit(self._pet.pet_id, str(exc) or "预览下载失败")


class CodexPetLibraryDialog(QDialog):
    """Browse local Codex pets or adopt one directly from codex-pets.net."""

    def __init__(
        self,
        service: CodexPetService,
        parent: QWidget | None = None,
        *,
        initial_source: str = "local",
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._initial_source = initial_source if initial_source in {"local", "online"} else "local"
        self.selected_result: CodexPetImportResult | None = None
        self._discovery_thread: QThread | None = None
        self._discovery_worker: _CodexPetDiscoveryWorker | None = None
        self._import_thread: QThread | None = None
        self._import_worker: _CodexPetImportWorker | None = None
        self._catalog_thread: QThread | None = None
        self._catalog_worker: _CodexPetCatalogWorker | None = None
        self._preview_thread: QThread | None = None
        self._preview_worker: _CodexPetPreviewWorker | None = None
        self._preview_pet_id = ""
        self._import_error = ""
        self._online_loaded_once = False
        self._online_page = 1
        self._online_total_pages = 1
        self._build_ui()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _path: self.refresh_pets())
        self.refresh_pets()
        if self._initial_source == "online":
            self.source_tabs.setCurrentIndex(1)

    def _build_ui(self) -> None:
        self.setWindowTitle("Codex 宠物库")
        self.setMinimumSize(780, 560)
        self.resize(860, 620)
        theme = current_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("选择一个真正与你一起工作的伙伴")
        title.setObjectName("libraryTitle")
        layout.addWidget(title)

        intro = QLabel(
            "自动读取 Codex 桌面端内置伙伴、本机宠物与 codex-pets.net 社区资源。" "领养后，伙伴会随 Lobuddy 的等待、执行、成功和受阻状态一起变化。"
        )
        intro.setObjectName("libraryIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        content = QHBoxLayout()
        content.setSpacing(18)

        self.source_tabs = QTabWidget()
        self.source_tabs.setObjectName("codexPetSourceTabs")
        self.source_tabs.addTab(self._build_local_tab(), "Codex 桌面端")
        self.source_tabs.addTab(self._build_online_tab(), "codex-pets.net")
        self.source_tabs.currentChanged.connect(self._on_source_tab_changed)
        content.addWidget(self.source_tabs, stretch=3)

        preview_panel = QWidget()
        preview_panel.setObjectName("petPreviewPanel")
        preview_panel.setMinimumWidth(254)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(10)

        source_badge = QLabel("CODEX PET")
        source_badge.setObjectName("sourceBadge")
        source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(source_badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.preview_label = QLabel("选择一只宠物")
        self.preview_label.setObjectName("petPreviewImage")
        self.preview_label.setFixedSize(208, 208)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(
            self.preview_label,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        self.name_label = QLabel("尚未选择")
        self.name_label.setObjectName("petPreviewName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.name_label.setWordWrap(True)
        preview_layout.addWidget(self.name_label)

        self.meta_label = QLabel("从左侧挑选你的新搭档")
        self.meta_label.setObjectName("petPreviewMeta")
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meta_label.setTextFormat(Qt.TextFormat.PlainText)
        self.meta_label.setWordWrap(True)
        preview_layout.addWidget(self.meta_label)

        self.description_label = QLabel("")
        self.description_label.setObjectName("petPreviewDescription")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.description_label.setTextFormat(Qt.TextFormat.PlainText)
        self.description_label.setWordWrap(True)
        preview_layout.addWidget(self.description_label)
        preview_layout.addStretch()
        content.addWidget(preview_panel, stretch=2)
        layout.addLayout(content, stretch=1)

        footer = QHBoxLayout()
        self.open_website_button = QPushButton("在浏览器查看社区")
        self.open_website_button.clicked.connect(self._open_website)
        footer.addWidget(self.open_website_button)
        footer.addStretch()
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        self.use_button = QPushButton("使用这个宠物")
        self.use_button.setObjectName("useCodexPetButton")
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self._use_selected_pet)
        footer.addWidget(self.use_button)
        layout.addLayout(footer)

        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.background};
                color: {theme.text};
            }}
            QLabel#libraryTitle {{
                color: {theme.text};
                font-size: 21px;
                font-weight: 700;
            }}
            QLabel#libraryIntro, QLabel#petPreviewDescription {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QTabWidget::pane {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
                top: -1px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {theme.text_secondary};
                padding: 9px 18px;
                border: none;
            }}
            QTabBar::tab:selected {{
                color: {theme.primary};
                font-weight: 700;
                border-bottom: 2px solid {theme.primary};
            }}
            QListWidget {{
                background: {theme.surface};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                min-height: 42px;
                padding: 7px 9px;
                border-radius: {theme.radius_sm - 2}px;
            }}
            QListWidget::item:selected {{
                background: {theme.primary_soft};
                color: {theme.text};
            }}
            QPushButton {{
                background: {theme.surface};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 7px 12px;
            }}
            QPushButton:hover {{
                background: {theme.surface_soft};
                border-color: {theme.primary};
            }}
            QPushButton:disabled {{
                color: {theme.text_muted};
                background: {theme.surface_soft};
            }}
            QComboBox {{
                background: {theme.surface};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 7px 10px;
            }}
            QWidget#petPreviewPanel {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QLabel#sourceBadge {{
                background: {theme.primary_soft};
                color: {theme.primary};
                border: none;
                border-radius: 8px;
                padding: 4px 9px;
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#petPreviewImage {{
                background: {theme.surface_soft};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
            }}
            QLabel#petPreviewName {{
                color: {theme.text};
                border: none;
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#petPreviewMeta {{
                color: {theme.text_muted};
                border: none;
                font-size: 11px;
            }}
            """
        )
        self.search_input.setStyleSheet(generate_input_style(theme))
        self.use_button.setStyleSheet(generate_button_style(theme, variant="primary"))
        self.cancel_button.setStyleSheet(generate_button_style(theme, variant="secondary"))
        self.open_website_button.setStyleSheet(generate_button_style(theme, variant="ghost"))

    def _build_local_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        source_path = QLabel("Codex 自带伙伴会从本机桌面应用安全读取；自定义宠物来自\n" f"{self.service.codex_pets_dir}")
        source_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_path.setWordWrap(True)
        layout.addWidget(source_path)

        source_actions = QHBoxLayout()
        folder_button = QPushButton("打开本机目录")
        folder_button.clicked.connect(self._open_local_folder)
        source_actions.addWidget(folder_button)
        import_button = QPushButton("导入宠物包目录")
        import_button.clicked.connect(self._import_package_directory)
        source_actions.addWidget(import_button)
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("refreshCodexPetsButton")
        refresh_button.clicked.connect(self.refresh_pets)
        source_actions.addWidget(refresh_button)
        source_actions.addStretch()
        layout.addLayout(source_actions)

        self.pet_list = QListWidget()
        self.pet_list.setObjectName("codexPetList")
        self.pet_list.currentItemChanged.connect(self._on_local_selection_changed)
        self.pet_list.itemDoubleClicked.connect(lambda _item: self._use_selected_pet())
        layout.addWidget(self.pet_list, stretch=1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return tab

    def _build_online_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        online_intro = QLabel("直接浏览社区宠物；只有你点击领养时才会下载图集。")
        online_intro.setWordWrap(True)
        layout.addWidget(online_intro)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("codexPetOnlineSearch")
        self.search_input.setPlaceholderText("按名字、作者或标签搜索")
        self.search_input.returnPressed.connect(self._start_online_search)
        search_layout.addWidget(self.search_input, stretch=1)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("最新", "newest")
        self.sort_combo.addItem("最受喜欢", "liked")
        self.sort_combo.addItem("最多浏览", "viewed")
        self.sort_combo.currentIndexChanged.connect(self._start_online_search)
        search_layout.addWidget(self.sort_combo)
        self.search_button = QPushButton("搜索")
        self.search_button.clicked.connect(self._start_online_search)
        search_layout.addWidget(self.search_button)
        layout.addLayout(search_layout)

        self.online_pet_list = QListWidget()
        self.online_pet_list.setObjectName("codexPetOnlineList")
        self.online_pet_list.currentItemChanged.connect(self._on_remote_selection_changed)
        self.online_pet_list.itemDoubleClicked.connect(lambda _item: self._use_selected_pet())
        layout.addWidget(self.online_pet_list, stretch=1)

        paging = QHBoxLayout()
        self.previous_page_button = QPushButton("上一页")
        self.previous_page_button.clicked.connect(lambda: self._change_online_page(-1))
        paging.addWidget(self.previous_page_button)
        self.online_page_label = QLabel("第 1 页")
        self.online_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        paging.addWidget(self.online_page_label, stretch=1)
        self.next_page_button = QPushButton("下一页")
        self.next_page_button.clicked.connect(lambda: self._change_online_page(1))
        paging.addWidget(self.next_page_button)
        layout.addLayout(paging)

        self.online_status_label = QLabel("切换到这里后会同步 Codex Pets 公开目录。")
        self.online_status_label.setWordWrap(True)
        layout.addWidget(self.online_status_label)
        self._update_paging_buttons()
        return tab

    def refresh_pets(self) -> None:
        if self._discovery_thread is not None:
            return
        self._watch_local_directory()
        self.pet_list.clear()
        self.pet_list.setEnabled(False)
        self.status_label.setText("正在读取 Codex 桌面端伙伴与本机宠物…")
        if self.source_tabs.currentIndex() == 0:
            self._clear_preview("正在连接 Codex 桌面端…")

        thread = QThread(self)
        worker = _CodexPetDiscoveryWorker(self.service)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_local_pets_ready)
        worker.failed.connect(self._on_local_pets_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_discovery_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._discovery_thread = thread
        self._discovery_worker = worker
        thread.start()

    @Slot(object)
    def _on_local_pets_ready(self, result: object) -> None:
        if not isinstance(result, list) or not all(
            isinstance(pet, CodexPetPackage) for pet in result
        ):
            self.status_label.setText("本机 Codex 宠物返回了无法识别的数据。")
            return
        pets = result
        for pet in pets:
            self._add_local_pet(pet)

        invalid_count = len(self.service.last_errors)
        if pets:
            builtin_count = sum(pet.source_kind == "codex_builtin" for pet in pets)
            custom_count = len(pets) - builtin_count
            status = f"发现 {builtin_count} 只 Codex 自带伙伴"
            if custom_count:
                status += f"，另有 {custom_count} 只本机或已领养伙伴"
            if invalid_count:
                status += f"，另有 {invalid_count} 个宠物包未通过安全校验"
            self.status_label.setText(status)
            self.pet_list.setCurrentRow(0)
        else:
            status = "未发现 Codex 桌面端宠物。仍可导入宠物包或前往在线社区领养。"
            if invalid_count:
                status += f"（{invalid_count} 个包未通过安全校验）"
            self.status_label.setText(status)
            if self.source_tabs.currentIndex() == 0:
                self._clear_preview()

    @Slot(str)
    def _on_local_pets_failed(self, error: str) -> None:
        self.status_label.setText(f"暂时无法读取本机 Codex 宠物：{error}")
        if self.source_tabs.currentIndex() == 0:
            self._clear_preview("本机宠物暂时不可用")

    @Slot()
    def _on_discovery_thread_finished(self) -> None:
        self._discovery_thread = None
        self._discovery_worker = None
        self.pet_list.setEnabled(True)

    def refresh_online(self) -> None:
        if self._catalog_thread is not None:
            return
        self._online_loaded_once = True
        self.online_status_label.setText("正在与 Codex Pets 同步…")
        self.online_pet_list.setEnabled(False)
        self.search_button.setEnabled(False)
        self._update_paging_buttons(busy=True)

        thread = QThread(self)
        worker = _CodexPetCatalogWorker(
            self.service,
            page=self._online_page,
            query=self.search_input.text().strip(),
            sort=str(self.sort_combo.currentData() or "newest"),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_catalog_ready)
        worker.failed.connect(self._on_catalog_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_catalog_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._catalog_thread = thread
        self._catalog_worker = worker
        thread.start()

    @Slot(object)
    def _on_catalog_ready(self, result: object) -> None:
        if not isinstance(result, CodexPetCatalogPage):
            self.online_status_label.setText("在线目录返回了无法识别的数据。")
            return
        self._online_page = result.page
        self._online_total_pages = result.total_pages
        self.online_pet_list.clear()
        for pet in result.items:
            self._add_remote_pet(pet)

        status = f"社区共有 {result.total} 只宠物，本页显示 {len(result.items)} 只"
        if result.skipped_items:
            status += f"，{result.skipped_items} 个条目未通过安全校验"
        self.online_status_label.setText(status)
        self.online_page_label.setText(f"第 {self._online_page} / {self._online_total_pages} 页")
        if result.items:
            self.online_pet_list.setCurrentRow(0)
        elif self.source_tabs.currentIndex() == 1:
            self._clear_preview("没有找到匹配的在线宠物")

    @Slot(str)
    def _on_catalog_failed(self, error: str) -> None:
        self.online_status_label.setText(f"暂时无法同步在线目录：{error}\n" "Codex 桌面端内置伙伴与已安装宠物仍可正常使用。")

    @Slot()
    def _on_catalog_thread_finished(self) -> None:
        self._catalog_thread = None
        self._catalog_worker = None
        self.online_pet_list.setEnabled(True)
        self.search_button.setEnabled(True)
        self._update_paging_buttons()

    def _add_local_pet(self, pet: CodexPetPackage) -> None:
        source_labels = {
            "codex_builtin": "Codex 自带",
            "codex_pets": "Codex Pets 已领养",
            "custom": "本机自定义",
        }
        source = source_labels.get(pet.source_kind, "本机伙伴")
        item = QListWidgetItem(
            f"{pet.display_name}\n{source}  ·  Sprite v{pet.sprite_version_number}"
        )
        item.setData(Qt.ItemDataRole.UserRole, pet)
        if pet.source_kind == "codex_builtin":
            item.setToolTip("来自本机 Codex 桌面应用；Lobuddy 只读取并缓存兼容副本。")
        else:
            item.setToolTip(str(pet.directory_path))
        self.pet_list.addItem(item)

    def _add_remote_pet(self, pet: CodexPetCatalogItem) -> None:
        owner = f"by {pet.owner_name}" if pet.owner_name else "社区创作者"
        item = QListWidgetItem(
            f"{pet.display_name}\n{owner}  ·  ♥ {pet.like_count}  ·  浏览 {pet.view_count}"
        )
        item.setData(Qt.ItemDataRole.UserRole, pet)
        tags = " · ".join(pet.tags[:5])
        tooltip = "\n".join(part for part in (pet.description, tags) if part)
        item.setToolTip(html.escape(tooltip))
        self.online_pet_list.addItem(item)

    def _on_local_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if self.source_tabs.currentIndex() != 0:
            return
        pet = self._local_pet_from_item(current)
        if pet is None:
            self._clear_preview()
            return
        self._show_local_pet(pet)

    def _on_remote_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if self.source_tabs.currentIndex() != 1:
            return
        pet = self._remote_pet_from_item(current)
        if pet is None:
            self._clear_preview()
            return
        self._show_remote_pet(pet)

    def _show_local_pet(self, pet: CodexPetPackage) -> None:
        pixmap = QPixmap(str(pet.spritesheet_path))
        if pixmap.isNull():
            self._set_preview_text("预览不可用")
        else:
            frame = pixmap.copy(0, 0, self.service.FRAME_WIDTH, self.service.FRAME_HEIGHT)
            self._set_preview_pixmap(frame)
        self.name_label.setText(pet.display_name)
        source_labels = {
            "codex_builtin": "Codex 桌面端自带",
            "codex_pets": "已从 Codex Pets 领养",
            "custom": "本机 Codex 宠物",
        }
        source = source_labels.get(pet.source_kind, "本机 Codex 宠物")
        self.meta_label.setText(f"{source} · Sprite v{pet.sprite_version_number}")
        self.description_label.setText(pet.description or "一只来自 Codex 的本机搭档")
        self.use_button.setText(
            "立即使用这只 Codex 伙伴" if pet.source_kind == "codex_builtin" else "使用这个宠物"
        )
        self.use_button.setEnabled(True)

    def _show_remote_pet(self, pet: CodexPetCatalogItem) -> None:
        self._set_preview_text("正在加载社区预览…")
        self.name_label.setText(pet.display_name)
        owner = pet.owner_name or "Codex Pets 创作者"
        tags = " · ".join(pet.tags[:4])
        meta = f"{owner} · {pet.kind} · Sprite v{pet.sprite_version_number}"
        if tags:
            meta += f"\n{tags}"
        self.meta_label.setText(meta)
        self.description_label.setText(pet.description or "一只等待被领养的社区伙伴")
        self.use_button.setText("领养并立即使用")
        self.use_button.setEnabled(True)
        self._start_remote_preview(pet)

    def _start_remote_preview(self, pet: CodexPetCatalogItem) -> None:
        if self._preview_thread is not None:
            return
        self._preview_pet_id = pet.pet_id
        thread = QThread(self)
        worker = _CodexPetPreviewWorker(self.service, pet)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_preview_ready)
        worker.failed.connect(self._on_preview_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_preview_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._preview_thread = thread
        self._preview_worker = worker
        thread.start()

    @Slot(str, object)
    def _on_preview_ready(self, pet_id: str, path: object) -> None:
        current = self._selected_remote_pet()
        if current is None or current.pet_id != pet_id or not isinstance(path, Path):
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._set_preview_text("社区预览不可用")
        else:
            self._set_preview_pixmap(pixmap)

    @Slot(str, str)
    def _on_preview_failed(self, pet_id: str, _error: str) -> None:
        current = self._selected_remote_pet()
        if current is not None and current.pet_id == pet_id:
            self._set_preview_text("社区预览暂不可用\n仍可直接领养")

    @Slot()
    def _on_preview_thread_finished(self) -> None:
        finished_pet_id = self._preview_pet_id
        self._preview_thread = None
        self._preview_worker = None
        self._preview_pet_id = ""
        current = self._selected_remote_pet()
        if (
            current is not None
            and self.source_tabs.currentIndex() == 1
            and current.pet_id != finished_pet_id
        ):
            self._start_remote_preview(current)

    def _set_preview_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(scaled)

    def _set_preview_text(self, text: str) -> None:
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(text)

    def _clear_preview(self, message: str = "选择一只宠物") -> None:
        self._set_preview_text(message)
        self.name_label.setText("尚未选择")
        self.meta_label.setText("从左侧挑选你的新搭档")
        self.description_label.setText("")
        self.use_button.setText("使用这个宠物")
        self.use_button.setEnabled(False)

    def _on_source_tab_changed(self, index: int) -> None:
        if index == 1:
            if not self._online_loaded_once:
                self.refresh_online()
            pet = self._selected_remote_pet()
            if pet is not None:
                self._show_remote_pet(pet)
            else:
                self._clear_preview("正在连接 Codex Pets…")
        else:
            pet = self._selected_local_pet()
            if pet is not None:
                self._show_local_pet(pet)
            else:
                self._clear_preview()

    def _start_online_search(self, _index: int | None = None) -> None:
        self._online_page = 1
        self.refresh_online()

    def _change_online_page(self, offset: int) -> None:
        target = self._online_page + offset
        if target < 1 or target > self._online_total_pages:
            return
        self._online_page = target
        self.refresh_online()

    def _update_paging_buttons(self, *, busy: bool = False) -> None:
        self.previous_page_button.setEnabled(not busy and self._online_page > 1)
        self.next_page_button.setEnabled(not busy and self._online_page < self._online_total_pages)

    def _use_selected_pet(self) -> None:
        if self._import_thread is not None:
            return
        pet = self._selected_pet()
        if pet is None:
            return
        self.use_button.setEnabled(False)
        if isinstance(pet, CodexPetCatalogItem):
            self.use_button.setText("正在安全领养并准备动画…")
        else:
            self.use_button.setText("正在准备动画…")
        self.cancel_button.setEnabled(False)
        self.source_tabs.setEnabled(False)
        self._import_error = ""

        thread = QThread(self)
        worker = _CodexPetImportWorker(self.service, pet)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_import_ready)
        worker.failed.connect(self._on_import_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_import_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._import_thread = thread
        self._import_worker = worker
        thread.start()

    @Slot(object)
    def _on_import_ready(self, result: object) -> None:
        if isinstance(result, CodexPetImportResult):
            self.selected_result = result
        else:
            self._import_error = "宠物动画转换返回了无效结果"

    @Slot(str)
    def _on_import_failed(self, error: str) -> None:
        self._import_error = error

    @Slot()
    def _on_import_thread_finished(self) -> None:
        self._import_thread = None
        self._import_worker = None
        self.cancel_button.setEnabled(True)
        self.source_tabs.setEnabled(True)
        if self._import_error:
            QMessageBox.warning(self, "无法使用这个宠物", self._import_error)
            self._restore_use_button()
            return
        if self.selected_result is not None:
            self.accept()

    def _restore_use_button(self) -> None:
        pet = self._selected_pet()
        self.use_button.setEnabled(pet is not None)
        if isinstance(pet, CodexPetCatalogItem):
            self.use_button.setText("领养并立即使用")
        else:
            self.use_button.setText("使用这个宠物")

    def _import_package_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择包含 pet.json 的宠物包目录")
        if not directory:
            return
        try:
            pet = self.service.load_package(Path(directory))
        except CodexPetError as exc:
            QMessageBox.warning(self, "无效的 Codex 宠物包", str(exc))
            return
        self._add_local_pet(pet)
        self.pet_list.setCurrentRow(self.pet_list.count() - 1)
        self.status_label.setText("宠物包已通过校验，可以直接使用。")

    def _open_website(self) -> None:
        if not QDesktopServices.openUrl(QUrl(self.service.WEBSITE_URL)):
            QMessageBox.warning(self, "无法打开网站", self.service.WEBSITE_URL)

    def _open_local_folder(self) -> None:
        try:
            directory = self.service.ensure_codex_pets_dir()
        except (CodexPetError, OSError) as exc:
            QMessageBox.warning(self, "无法打开目录", str(exc))
            return
        self._watch_local_directory()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            QMessageBox.warning(self, "无法打开目录", str(directory))

    def _watch_local_directory(self) -> None:
        directory = str(self.service.codex_pets_dir.resolve())
        if self.service.codex_pets_dir.is_dir() and directory not in self._watcher.directories():
            self._watcher.addPath(directory)

    def _selected_pet(self) -> CodexPetPackage | CodexPetCatalogItem | None:
        if self.source_tabs.currentIndex() == 1:
            return self._selected_remote_pet()
        return self._selected_local_pet()

    def _selected_local_pet(self) -> CodexPetPackage | None:
        return self._local_pet_from_item(self.pet_list.currentItem())

    def _selected_remote_pet(self) -> CodexPetCatalogItem | None:
        return self._remote_pet_from_item(self.online_pet_list.currentItem())

    def reject(self) -> None:
        if self._has_active_worker():
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._has_active_worker():
            event.ignore()
            return
        super().closeEvent(event)

    def _has_active_worker(self) -> bool:
        return any(
            thread is not None
            for thread in (
                self._discovery_thread,
                self._import_thread,
                self._catalog_thread,
                self._preview_thread,
            )
        )

    @staticmethod
    def _local_pet_from_item(item: QListWidgetItem | None) -> CodexPetPackage | None:
        if item is None:
            return None
        pet = item.data(Qt.ItemDataRole.UserRole)
        return pet if isinstance(pet, CodexPetPackage) else None

    @staticmethod
    def _remote_pet_from_item(
        item: QListWidgetItem | None,
    ) -> CodexPetCatalogItem | None:
        if item is None:
            return None
        pet = item.data(Qt.ItemDataRole.UserRole)
        return pet if isinstance(pet, CodexPetCatalogItem) else None
