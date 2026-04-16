"""Regression tests for UI GIF support and transparency."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _ensure_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestAssetManagerGifSupport:
    def test_get_pet_movie_returns_movie_for_gif(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        gif_path = tmp_path / "pet_idle.gif"
        gif_path.write_bytes(b"GIF89a")

        movie = am.get_pet_movie("idle")
        assert movie is not None
        assert Path(movie.fileName()) == gif_path

    def test_get_pet_movie_returns_none_for_png(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.png",
                "running_image": "pet_running.png",
                "success_image": "pet_success.png",
                "error_image": "pet_error.png",
                "width": 128,
            },
        )()

        png_path = tmp_path / "pet_idle.png"
        png_path.write_bytes(b"\x89PNG")

        movie = am.get_pet_movie("idle")
        assert movie is None

    def test_tray_icon_fallback_to_png(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtGui import QPixmap
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        png_path = tmp_path / "icon_tray.png"
        pixmap = QPixmap(16, 16)
        pixmap.fill()
        pixmap.save(str(png_path))

        icon = am.get_tray_icon()
        assert not icon.isNull()

    def test_tray_icon_returns_empty_when_no_icon_exists(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        icon = am.get_tray_icon()
        assert icon.isNull()

    def test_tray_movie_returns_movie_for_gif(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        gif_path = tmp_path / "icon_tray.gif"
        gif_path.write_bytes(b"GIF89a")

        movie = am.get_tray_movie()
        assert movie is not None
        assert Path(movie.fileName()) == gif_path

    def test_tray_movie_returns_none_when_no_gif(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        movie = am.get_tray_movie()
        assert movie is None

    def test_get_pet_movie_returns_none_for_invalid_gif(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        gif_path = tmp_path / "pet_idle.gif"
        gif_path.write_text("not a real gif")

        movie = am.get_pet_movie("idle")
        assert movie is None

    def test_get_pet_movie_fallback_to_png_when_gif_missing(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtGui import QPixmap
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        png_path = tmp_path / "pet_idle.png"
        pixmap = QPixmap(16, 16)
        pixmap.fill()
        pixmap.save(str(png_path))

        from core.models.pet import TaskStatus

        movie = am.get_pet_movie(TaskStatus.IDLE)
        assert movie is None

        pixmap_result = am.get_pet_pixmap(TaskStatus.IDLE)
        assert not pixmap_result.isNull()


class TestPetWindowGif:
    def test_pet_window_loads_actual_gif_asset(self, monkeypatch):
        _ensure_qapp()
        from pathlib import Path
        from core.models.pet import TaskStatus
        from ui.asset_manager import AssetManager
        from ui.pet_window import PetWindow

        real_gif = Path(__file__).parent.parent / "ui" / "assets" / "pet_idle.gif"
        if not real_gif.exists():
            pytest.skip("Real pet_idle.gif not found")

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = real_gif.parent
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_idle.gif",
                "success_image": "pet_idle.gif",
                "error_image": "pet_idle.gif",
                "width": 128,
            },
        )()

        movie = am.get_pet_movie(TaskStatus.IDLE)
        assert movie is not None
        assert Path(movie.fileName()) == real_gif

    def test_pet_window_stops_movie_on_close(self, monkeypatch):
        _ensure_qapp()
        from pathlib import Path
        from core.models.pet import TaskStatus
        from ui.asset_manager import AssetManager
        from ui.pet_window import PetWindow

        real_gif = Path(__file__).parent.parent / "ui" / "assets" / "pet_idle.gif"
        if not real_gif.exists():
            pytest.skip("Real pet_idle.gif not found")

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = real_gif.parent
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_idle.gif",
                "success_image": "pet_idle.gif",
                "error_image": "pet_idle.gif",
                "width": 128,
            },
        )()

        window = PetWindow()
        window.set_pet_state(TaskStatus.IDLE)
        assert window._current_movie is not None
        assert window._current_movie.state().value == 2

        window.closeEvent(
            type("E", (), {"accept": lambda self: None, "ignore": lambda self: None})()
        )
        assert window._current_movie is None


class TestTaskPanelGifPreview:
    @pytest.mark.asyncio
    async def test_task_panel_gif_preview_uses_movie(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtWidgets import QWidget
        from ui.task_panel import TaskPanel

        gif_path = tmp_path / "test.gif"
        gif_path.write_bytes(b"GIF89a")

        panel = TaskPanel.__new__(TaskPanel)
        panel.image_preview = QWidget()

        class MockLabel:
            def clear(self):
                pass

            def setMovie(self, m):
                pass

            def setPixmap(self, p):
                pass

        class MockText:
            def clear(self):
                pass

            def setText(self, t):
                pass

        panel.image_preview_label = MockLabel()
        panel.image_preview_text = MockText()
        panel._stop_image_preview_movie = lambda: None

        movies_started = []
        original_movie_cls = None
        try:
            from PySide6.QtGui import QMovie

            original_movie_cls = QMovie

            class FakeMovie:
                def __init__(self, path):
                    self.path = path
                    self.started = False
                    self._parent = None

                def isValid(self):
                    return True

                def setScaledSize(self, size):
                    pass

                def setParent(self, parent):
                    self._parent = parent

                def start(self):
                    self.started = True
                    movies_started.append(self.path)

            monkeypatch.setattr("ui.task_panel.QMovie", FakeMovie)
            panel._update_image_preview(str(gif_path))
        finally:
            if original_movie_cls:
                monkeypatch.setattr("ui.task_panel.QMovie", original_movie_cls)

        assert len(movies_started) == 1
        assert movies_started[0] == str(gif_path)

    def test_task_panel_stops_movie_on_hide(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtWidgets import QWidget, QLabel
        from PySide6.QtGui import QMovie
        from ui.task_panel import TaskPanel

        gif_path = tmp_path / "test.gif"
        gif_path.write_bytes(b"GIF89a")

        panel = TaskPanel.__new__(TaskPanel)
        panel.image_preview = QWidget()
        panel.image_preview_label = QLabel()
        panel.image_preview_text = QLabel()
        panel.messages = []

        panel._update_image_preview(str(gif_path))
        assert panel.image_preview_label._movie is not None

        # Directly test the cleanup logic used by hideEvent; a __new__-created
        # QWidget cannot call super().hideEvent() due to shiboken guard.
        panel._stop_image_preview_movie()
        assert getattr(panel.image_preview_label, "_movie", None) is None

    def test_task_panel_message_movie_pauses_on_hide(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtWidgets import QWidget, QLabel
        from PySide6.QtGui import QMovie
        from ui.task_panel import TaskPanel

        gif_path = tmp_path / "test.gif"
        gif_path.write_bytes(b"GIF89a")

        panel = TaskPanel.__new__(TaskPanel)
        panel.image_preview = QWidget()
        panel.image_preview_label = QLabel()
        panel.image_preview_text = QLabel()
        panel.messages = []
        panel.input_box = QWidget()
        panel.chat_layout = type(
            "CL",
            (object,),
            {
                "insertWidget": lambda self, idx, w: None,
                "count": lambda self: 1,
            },
        )()

        panel._add_message_to_display("hello", image_path=str(gif_path))
        msg_label = panel.messages[0].findChildren(QLabel)[0]
        assert msg_label._movie is not None

        # Spy stop/start without asserting on QMovie.state(),
        # because headless Qt may not transition minimal GIFs to Running.
        stops = []
        starts = []
        original_stop = msg_label._movie.stop
        original_start = msg_label._movie.start
        msg_label._movie.stop = lambda: (stops.append(1), original_stop())
        msg_label._movie.start = lambda: (starts.append(1), original_start())

        panel._pause_all_message_movies()
        assert len(stops) == 1
        assert len(starts) == 0

        panel._resume_all_message_movies()
        assert len(starts) == 1

        panel._pause_all_message_movies()
        assert len(stops) == 2


class TestAssetManagerInvalidGifFallback:
    def test_invalid_pet_gif_fallback_to_png(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtGui import QPixmap
        from ui.asset_manager import AssetManager
        from core.models.pet import TaskStatus

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        (tmp_path / "pet_idle.gif").write_bytes(b"not-a-valid-gif")
        png_path = tmp_path / "pet_idle.png"
        pixmap = QPixmap(16, 16)
        pixmap.fill()
        pixmap.save(str(png_path))

        movie = am.get_pet_movie(TaskStatus.IDLE)
        assert movie is None
        pixmap = am.get_pet_pixmap(TaskStatus.IDLE)
        assert not pixmap.isNull()

    def test_invalid_tray_gif_fallback_to_png(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtGui import QPixmap
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        (tmp_path / "icon_tray.gif").write_bytes(b"not-a-valid-gif")
        png_path = tmp_path / "icon_tray.png"
        pixmap = QPixmap(16, 16)
        pixmap.fill()
        pixmap.save(str(png_path))

        movie = am.get_tray_movie()
        assert movie is None
        icon = am.get_tray_icon()
        assert not icon.isNull()


class TestPlaceholderTransparency:
    def test_placeholder_has_transparent_background(self, tmp_path, monkeypatch):
        _ensure_qapp()
        from PySide6.QtGui import QPixmap
        from ui.asset_manager import AssetManager

        monkeypatch.setattr(AssetManager, "_instance", None)
        monkeypatch.setattr(AssetManager, "_pixmap_cache", {})

        am = AssetManager.__new__(AssetManager)
        am.assets_dir = tmp_path
        am.appearance = type(
            "obj",
            (object,),
            {
                "idle_image": "pet_idle.gif",
                "running_image": "pet_running.gif",
                "success_image": "pet_success.gif",
                "error_image": "pet_error.gif",
                "width": 128,
            },
        )()

        # Trigger placeholder creation for pet_idle.png
        placeholder_path = tmp_path / "pet_idle.png"
        am._ensure_assets_exist()
        assert placeholder_path.exists()

        pixmap = QPixmap(str(placeholder_path))
        # Sample a corner pixel (outside the rounded rect) and verify alpha == 0
        corner = pixmap.toImage().pixelColor(2, 2)
        assert corner.alpha() == 0
