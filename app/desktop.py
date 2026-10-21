"""Launch the Electron desktop from a source checkout without importing legacy Qt."""

import shutil
import subprocess
from pathlib import Path


def main() -> int:
    desktop = Path(__file__).resolve().parents[1] / "desktop"
    npm = shutil.which("npm")
    if not npm or not (desktop / "dist-electron/desktop/electron/main.js").is_file():
        print("请打开 Lobuddy.app；源码开发请先构建 bridge/dsh 和 desktop，再运行 lobuddy。")
        return 2
    return subprocess.call([npm, "start", "--prefix", str(desktop)])


if __name__ == "__main__":
    raise SystemExit(main())
