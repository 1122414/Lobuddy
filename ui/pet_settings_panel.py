"""Pet settings panel for Lobuddy."""

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QMovie, QPixmap

from core.models.appearance import PetAppearance, save_appearance
from core.services.pet_asset_service import PetAssetService
from ui.styles import PET_SETTINGS_PREVIEW


class PetSettingsPanel(QDialog):
    """Dialog for customizing pet appearance."""

    def __init__(self, appearance: PetAppearance, parent=None):
        super().__init__(parent)
        self.appearance = appearance
        self.asset_service = PetAssetService()
        self.preview_movie = None
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("Pet Settings")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        preview_container = QWidget()
        preview_container.setStyleSheet(PET_SETTINGS_PREVIEW)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(16, 16, 16, 16)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(128, 128)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._update_preview()
        layout.addWidget(preview_container)

        upload_layout = QHBoxLayout()
        upload_btn = QPushButton("Upload Image/GIF")
        upload_btn.clicked.connect(self._on_upload)
        upload_layout.addWidget(upload_btn)

        reset_asset_btn = QPushButton("Reset to Default")
        reset_asset_btn.clicked.connect(self._on_reset)
        upload_layout.addWidget(reset_asset_btn)
        layout.addLayout(upload_layout)

        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(50, 200)
        self.scale_slider.setValue(int(self.appearance.scale * 100))
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        scale_layout.addWidget(self.scale_slider)
        self.scale_value = QLabel(f"{self.appearance.scale:.1f}x")
        scale_layout.addWidget(self.scale_value)
        layout.addLayout(scale_layout)

        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(int(self.appearance.opacity * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        self.opacity_value = QLabel(f"{int(self.appearance.opacity * 100)}%")
        opacity_layout.addWidget(self.opacity_value)
        layout.addLayout(opacity_layout)

        btn_layout = QHBoxLayout()
        reset_pos_btn = QPushButton("Reset Position")
        reset_pos_btn.clicked.connect(self._on_reset_position)
        btn_layout.addWidget(reset_pos_btn)
        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _update_preview(self):
        self.preview_label.clear()
        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
            self.preview_movie = None

        path = self.appearance.custom_asset_path
        if path and Path(path).exists():
            if self.appearance.custom_asset_type == "gif":
                movie = QMovie(path)
                if movie.isValid():
                    movie.setScaledSize(self.preview_label.size())
                    self.preview_label.setMovie(movie)
                    movie.start()
                    self.preview_movie = movie
                    return
                movie.deleteLater()

            pixmap = QPixmap(path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    self.preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.preview_label.setPixmap(pixmap)
                return

        pixmap = QPixmap(128, 128)
        pixmap.fill(Qt.GlobalColor.lightGray)
        self.preview_label.setPixmap(pixmap)

    def _on_upload(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Pet Image or GIF",
            "",
            "Pet Assets (*.png *.jpg *.jpeg *.webp *.gif)",
        )
        if not file_path:
            return

        path = Path(file_path)
        result = self.asset_service.validate_asset(path)
        if not result.valid:
            QMessageBox.warning(self, "Invalid File", result.error)
            return

        asset_type = self.asset_service.detect_asset_type(path)
        dest_path = self.asset_service.copy_to_app_data(path)

        if self.appearance.custom_asset_path:
            old_path = Path(self.appearance.custom_asset_path)
            self.asset_service.remove_asset(old_path)

        self.appearance.custom_asset_path = str(dest_path)
        self.appearance.custom_asset_type = asset_type
        self._update_preview()

    def _on_reset(self):
        if self.appearance.custom_asset_path:
            old_path = Path(self.appearance.custom_asset_path)
            self.asset_service.remove_asset(old_path)

        self.appearance.custom_asset_path = None
        self.appearance.custom_asset_type = "default"
        self._update_preview()

    def _on_scale_changed(self, value: int):
        self.appearance.scale = value / 100.0
        self.scale_value.setText(f"{self.appearance.scale:.1f}x")

    def _on_opacity_changed(self, value: int):
        self.appearance.opacity = value / 100.0
        self.opacity_value.setText(f"{int(self.appearance.opacity * 100)}%")

    def _on_reset_position(self):
        self.appearance.position_x = 100
        self.appearance.position_y = 100
        QMessageBox.information(self, "Reset Position", "Position will be reset to default (100, 100) after saving.")

    def _on_save(self):
        save_appearance(self.appearance)
        self.accept()

    def closeEvent(self, event):
        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
        super().closeEvent(event)
