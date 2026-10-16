"""Native image admission boundaries and durable opaque references."""

from pathlib import Path

import pytest
from PIL import Image

from core.config import Settings
from core.service.images import ImageStore
from core.service.protocol import TurnSend
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from core.storage.service_repo import ServiceRepository


class TestServiceImages:
    def test_native_import_integrity_and_preview(self, tmp_path: Path) -> None:
        source = tmp_path / "sample.png"
        Image.new("RGB", (60, 30), "red").save(source)
        store = ImageStore(tmp_path / "private")
        result = store.import_file(str(source))
        assert result.width == 60 and result.height == 30
        assert result.media_type == "image/png"
        assert result.preview.startswith("data:image/jpeg;base64,")
        assert store.import_file(str(source)) == result
        assert (store.root / result.image_id).stat().st_mode & 0o777 == 0o600
        (store.root / result.image_id).write_bytes(b"tampered")
        with pytest.raises(ValueError, match="校验"):
            store.get(result.image_id)

    def test_small_encoded_oversized_raster_is_rejected(self, tmp_path: Path) -> None:
        source = tmp_path / "wide.png"
        Image.new("RGB", (16385, 1)).save(source)
        assert source.stat().st_size < 1000
        with pytest.raises(ValueError, match="尺寸"):
            ImageStore(tmp_path / "private").import_file(str(source))

    def test_mismatch_symlink_corruption_and_traversal(self, tmp_path: Path) -> None:
        store = ImageStore(tmp_path / "private")
        source = tmp_path / "wrong.jpg"
        Image.new("RGB", (10, 10)).save(source, "PNG")
        with pytest.raises(ValueError, match="不一致"):
            store.import_file(str(source))
        link = tmp_path / "link.png"
        link.symlink_to(source)
        with pytest.raises(OSError):
            store.import_file(str(link))
        with pytest.raises(ValueError):
            store.get("../wrong.jpg")
        source = tmp_path / "broken.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n")
        with pytest.raises(OSError):
            store.import_file(str(source))
        assert list(store.root.iterdir()) == []

    def test_image_identity_persists_and_request_replay_uses_defaults(self, tmp_path: Path) -> None:
        settings = Settings(llm_api_key="test", data_dir=tmp_path)
        db = Database(settings)
        db.init_database()
        repo = ServiceRepository(db)
        chat = ChatRepository(db)
        chat.get_or_create_session("session")
        params = TurnSend(session_id="session", text="看看", image_id="a" * 64)
        state, created, _ = repo.submit("request", params)
        assert created and repo.get(state.turn_id).image_id == "a" * 64
        assert chat.get_messages("session")[0].image_path == "a" * 64
        assert not repo.submit("request", params)[1]
        plain = TurnSend(session_id="session", text="plain")
        repo.submit("old-request", plain)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE service_turn SET request_json=? WHERE request_id='old-request'",
                ('{"session_id":"session","text":"plain","lane":"foreground"}',),
            )
        assert not repo.submit("old-request", plain)[1]
