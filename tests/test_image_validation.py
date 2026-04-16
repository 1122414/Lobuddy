"""Tests for image validation utilities."""

from pathlib import Path

import pytest

from core.agent.image_validation import (
    _MAX_IMAGE_SIZE,
    image_to_base64_data_url,
    validate_image_file,
)


class TestImageValidation:
    def _make_png(self, tmp_path: Path, name: str = "test.png") -> Path:
        img = tmp_path / name
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake-body")
        return img

    def test_validate_success(self, tmp_path: Path):
        img = self._make_png(tmp_path)
        data = validate_image_file(str(img))
        assert data.startswith(b"\x89PNG")

    def test_validate_missing_file(self, tmp_path: Path):
        missing = tmp_path / "missing.png"
        with pytest.raises(ValueError, match="not found"):
            validate_image_file(str(missing))

    def test_validate_file_too_large(self, tmp_path: Path):
        img = tmp_path / "huge.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * _MAX_IMAGE_SIZE)
        with pytest.raises(ValueError, match="too large"):
            validate_image_file(str(img))

    def test_validate_unsupported_extension(self, tmp_path: Path):
        img = tmp_path / "malware.exe"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")
        with pytest.raises(ValueError, match="Unsupported file type"):
            validate_image_file(str(img))

    def test_validate_invalid_magic_bytes(self, tmp_path: Path):
        img = tmp_path / "fake.png"
        img.write_bytes(b"not-an-image")
        with pytest.raises(ValueError, match="not appear to be a valid image"):
            validate_image_file(str(img))

    def test_validate_fake_svg_without_svg_tag_rejected(self, tmp_path: Path):
        img = tmp_path / "fake.svg"
        img.write_bytes(b"<?xml version='1.0'?><not-svg></not-svg>")
        with pytest.raises(ValueError, match="not appear to be a valid image"):
            validate_image_file(str(img))


class TestImageCompression:
    def _create_large_image_exceeding_5mb(self, path: Path):
        from PIL import Image
        import os

        raw = os.urandom(2500 * 2500 * 3)
        img = Image.frombytes("RGB", (2500, 2500), raw)
        img.save(str(path), format="JPEG", quality=100)

    def test_large_image_gets_compressed(self, tmp_path: Path):
        img_path = tmp_path / "large.jpg"
        self._create_large_image_exceeding_5mb(img_path)

        original_size = img_path.stat().st_size
        assert original_size > _MAX_IMAGE_SIZE, f"Test image too small: {original_size} bytes"

        data = validate_image_file(str(img_path))
        assert len(data) <= _MAX_IMAGE_SIZE, f"Compressed image still too large: {len(data)} bytes"

    def test_compression_disabled_raises_for_large_files(self, tmp_path: Path):
        img_path = tmp_path / "large_nocompress.jpg"
        self._create_large_image_exceeding_5mb(img_path)

        with pytest.raises(ValueError, match="too large"):
            validate_image_file(str(img_path), compress=False)


class TestImageToBase64DataUrl:
    def test_returns_correct_data_url(self):
        data = b"\x89PNG\r\n\x1a\nfake"
        url = image_to_base64_data_url(data, "image/png")
        assert url.startswith("data:image/png;base64,")

    def test_accepts_mime_subtype(self):
        data = b"\x89PNG\r\n\x1a\nfake"
        url = image_to_base64_data_url(data, "png")
        assert url.startswith("data:image/png;base64,")
