"""An OS-owned exclusive service lock; process death releases ownership automatically."""

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import Self


class RuntimeLock:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.fd: int | None = None

    def __enter__(self) -> Self:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            self.directory / "service.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if sys.platform == "win32":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            raise RuntimeError("该数据目录已有运行中的服务") from error
        self.fd = fd
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        # Never unlink: another owner may already hold the same inode.
