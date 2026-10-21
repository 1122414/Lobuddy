"""Bundle the pinned local Python runtime and installed runtime-only dependency closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOTS = (
    "pydantic",
    "pydantic-settings",
    "python-dotenv",
    "httpx",
    "Pillow",
    "tiktoken",
    "Markdown",
    "loguru",
    "deepseek-harness-sdk",
    "faster-whisper",
    "numpy",
    "onnxruntime",
)


def bundle(destination: Path, project: Path) -> None:
    if destination.exists():
        raise ValueError("Runtime destination already exists")
    destination.mkdir(parents=True)
    base = Path(sys.base_prefix)
    python = destination / "python"
    lib = python / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    shutil.copytree(
        base / "lib" / lib.name,
        lib,
        ignore=shutil.ignore_patterns(
            "site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "ensurepip"
        ),
    )
    (python / "bin").mkdir(parents=True)
    executable = f"python{sys.version_info.major}.{sys.version_info.minor}"
    shutil.copy2(base / "bin" / executable, python / "bin" / executable)
    (python / "bin" / "python").symlink_to(executable)
    for library in (base / "lib").glob("libpython*.dylib"):
        shutil.copy2(library, python / "lib" / library.name)
    licenses = python / "licenses"
    if (base / "share" / "licenses").exists():
        shutil.copytree(base / "share" / "licenses", licenses)
    packages = lib / "site-packages"
    packages.mkdir()
    versions: dict[str, str] = {}
    pending = list(ROOTS)
    while pending:
        name = canonicalize_name(pending.pop())
        if name in versions:
            continue
        installed = distribution(name)
        versions[name] = installed.version
        for requirement in installed.requires or []:
            dependency = Requirement(requirement)
            if dependency.marker and not dependency.marker.evaluate({"extra": ""}):
                continue
            actual = distribution(dependency.name)
            if dependency.specifier and actual.version not in dependency.specifier:
                raise ValueError(f"Installed dependency does not satisfy {dependency.name}")
            pending.append(dependency.name)
        for relative in installed.files or []:
            path = Path(str(relative))
            # Console-script wrappers contain build-machine paths; services use python -m.
            if ".." in path.parts or path.is_absolute() or "__pycache__" in path.parts:
                continue
            source = Path(str(installed.locate_file(relative)))
            if source.is_file():
                target = packages / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    source_root = destination / "app"
    source_root.mkdir()
    for folder in ("app", "core"):
        shutil.copytree(
            project / folder,
            source_root / folder,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    plugin = source_root / "bridge" / "dsh"
    plugin.mkdir(parents=True)
    shutil.copytree(project / "bridge" / "dsh" / "dist", plugin / "dist")
    shutil.copy2(project / "bridge/dsh/package.json", plugin / "package.json")
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required to resolve the workspace's locked DSH dependencies")
    subprocess.run(
        [
            node,
            str(project / "scripts/ts/copy-runtime-dependencies.mjs"),
            str(project / "bridge/dsh/package.json"),
            "@deepseek-ai/dsh-llm",
            str(plugin / "node_modules"),
        ],
        check=True,
    )
    if (project / "LICENSE").exists():
        shutil.copy2(project / "LICENSE", source_root / "LICENSE")
    files = {}
    for path in destination.rglob("*"):
        if path.is_file():
            files[str(path.relative_to(destination))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "distributions": versions,
                "files_sha256": files,
                "credential_files_included": False,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    bundle(args.destination, args.project)
