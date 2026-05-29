from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PY_STANDALONE_TAG = "20260510"
PY_STANDALONE_VERSION = "3.11.15"


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def download(url: str, dest: Path) -> None:
    if dest.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, dest)


def mac_arch() -> str:
    machine = platform.machine().lower()
    return "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"


def runtime_python(runtime: Path, target: str) -> Path:
    return runtime / ("python.exe" if target.startswith("windows") else "bin/python3")


def ensure_host_can_build_target(target: str) -> None:
    if target.startswith("windows") and sys.platform != "win32":
        raise SystemExit("windows-x64 bundles must be built on Windows. Use the release workflow for Windows artifacts.")
    if target.startswith("macos") and sys.platform != "darwin":
        raise SystemExit("macOS bundles must be built on macOS. Use the release workflow for macOS artifacts.")


def prepare_runtime(build_dir: Path, target: str) -> Path:
    runtime = build_dir / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)

    if target == "windows-x64":
        archive = build_dir / "python-embed.zip"
        download(
            "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip",
            archive,
        )
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(runtime)
        pth = runtime / "python311._pth"
        pth.write_text(
            pth.read_text(encoding="utf-8").replace("#import site", "import site"),
            encoding="utf-8",
        )
        return runtime

    arch = "aarch64" if target == "macos-arm64" else "x86_64"
    archive = build_dir / f"python-standalone-{arch}.tar.gz"
    download(
        "https://github.com/indygreg/python-build-standalone/releases/download/"
        f"{PY_STANDALONE_TAG}/cpython-{PY_STANDALONE_VERSION}%2B{PY_STANDALONE_TAG}-"
        f"{arch}-apple-darwin-install_only.tar.gz",
        archive,
    )
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 2:
                continue
            member.name = str(Path(*parts[1:]))
            tf.extract(member, runtime)
    return runtime


def prune_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def prune_runtime(runtime: Path) -> None:
    for site_packages in runtime.rglob("site-packages"):
        for pattern in ("__pycache__", "test", "tests"):
            for path in site_packages.rglob(pattern):
                prune_path(path)
        for pattern in ("*.pyc", "*.pyo"):
            for path in site_packages.rglob(pattern):
                prune_path(path)

        pyside6 = site_packages / "PySide6"
        if not pyside6.exists():
            continue
        for rel in (
            "Assistant.app",
            "Designer.app",
            "Linguist.app",
            "Qt/qml",
            "Qt/translations",
            "include",
            "typesystems",
            "lrelease",
            "lupdate",
            "qmllint",
            "qmlls",
            "qmlformat",
            "svgtoqml",
        ):
            prune_path(pyside6 / rel)
        for pattern in ("*.pyi", "*.debug", "*.pdb"):
            for path in pyside6.rglob(pattern):
                prune_path(path)


def install_dependencies(runtime: Path, target: str) -> None:
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(runtime_python(runtime, target)),
            "-r",
            str(ROOT / "requirements.bundle.txt"),
        ]
    )
    prune_runtime(runtime)


def copy_project(bundle_root: Path, runtime: Path) -> None:
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    ignore = shutil.ignore_patterns(
        ".git",
        ".venv",
        ".local",
        "dist",
        "__pycache__",
        ".pytest_cache",
        "test",
        "tests",
        "assets/system/models",
        "*.pyc",
    )
    shutil.copytree(ROOT, bundle_root, ignore=ignore)
    shutil.rmtree(bundle_root / "assets" / "system" / "models", ignore_errors=True)
    shutil.rmtree(bundle_root / "test", ignore_errors=True)
    shutil.rmtree(bundle_root / "tests", ignore_errors=True)
    shutil.move(str(runtime), str(bundle_root / "runtime"))
    for rel in ("scripts/start.sh", "scripts/install.sh"):
        path = bundle_root / rel
        if path.exists():
            path.chmod(path.stat().st_mode | 0o755)


def smoke_test(bundle_root: Path, target: str) -> None:
    py = runtime_python(bundle_root / "runtime", target)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    env["HERE_APP_HOME"] = str(bundle_root.parent / "_smoke_home")
    run(
        [
            str(py),
            "-c",
            "import PySide6, openai, yaml, pygame; import app.desktop.main; print('bundle imports ok')",
        ],
        cwd=bundle_root,
        env=env,
    )


def make_zip(bundle_root: Path, output: Path) -> None:
    if output.exists():
        output.unlink()
    shutil.make_archive(str(output.with_suffix("")), "zip", bundle_root.parent, bundle_root.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    default_target = "macos-arm64" if sys.platform == "darwin" and mac_arch() == "aarch64" else "macos-x64"
    parser.add_argument("--target", default=default_target, choices=("macos-arm64", "macos-x64", "windows-x64"))
    parser.add_argument("--name", default="")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()
    ensure_host_can_build_target(args.target)

    name = args.name or f"here-local-{args.target}"
    build_dir = ROOT / "dist" / "bundle-build" / args.target
    bundle_root = build_dir / name
    build_dir.mkdir(parents=True, exist_ok=True)
    runtime = prepare_runtime(build_dir, args.target)
    install_dependencies(runtime, args.target)
    copy_project(bundle_root, runtime)
    if not args.skip_smoke:
        smoke_test(bundle_root, args.target)
    output = ROOT / "dist" / f"{name}.zip"
    make_zip(bundle_root, output)
    print(output)


if __name__ == "__main__":
    main()
