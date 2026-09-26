#!/usr/bin/env python3
"""Build a relocatable Python runtime consumed by the packaged Electron app."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
BUILD_DIR = ROOT / ".runtime-build"
PY_STANDALONE_TAG = "20260510"
PY_STANDALONE_VERSION = "3.11.15"


def run(command: list[str], *, env: dict[str, str] | None = None, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def runtime_python(runtime: Path = RUNTIME) -> Path:
    return runtime / ("python.exe" if sys.platform == "win32" else "bin/python3")


def target_name() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "aarch64-pc-windows-msvc" if machine in {"arm64", "aarch64"} else "x86_64-pc-windows-msvc"
    if sys.platform == "darwin":
        return "aarch64-apple-darwin" if machine in {"arm64", "aarch64"} else "x86_64-apple-darwin"
    if sys.platform.startswith("linux"):
        return "aarch64-unknown-linux-gnu" if machine in {"arm64", "aarch64"} else "x86_64-unknown-linux-gnu"
    raise SystemExit(f"Unsupported runtime build platform: {sys.platform}")


def archive_url() -> str:
    target = target_name()
    return (
        "https://github.com/indygreg/python-build-standalone/releases/download/"
        f"{PY_STANDALONE_TAG}/cpython-{PY_STANDALONE_VERSION}%2B{PY_STANDALONE_TAG}-{target}-install_only.tar.gz"
    )


def download_archive(explicit: str = "") -> Path:
    if explicit:
        archive = Path(explicit).expanduser().resolve()
        if not archive.is_file():
            raise SystemExit(f"Runtime archive does not exist: {archive}")
        return archive
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    archive = BUILD_DIR / f"python-{target_name()}.tar.gz"
    if not archive.is_file():
        print(f"Downloading {archive_url()}", flush=True)
        urllib.request.urlretrieve(archive_url(), archive)
    return archive


def extract_runtime(archive: Path) -> None:
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True)
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 2 or parts[0] != "python":
                continue
            member.name = str(Path(*parts[1:]))
            destination = (RUNTIME / member.name).resolve()
            if RUNTIME.resolve() not in (destination, *destination.parents):
                raise RuntimeError(f"Unsafe path in runtime archive: {member.name}")
            source.extract(member, RUNTIME)


def macos_portaudio_prefix() -> Path:
    brew = shutil.which("brew")
    if not brew:
        raise SystemExit("Homebrew is required for bundled microphone support. Install Homebrew and portaudio first.")
    completed = subprocess.run(
        [brew, "--prefix", "portaudio"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        run([brew, "install", "portaudio"])
        completed = subprocess.run([brew, "--prefix", "portaudio"], text=True, stdout=subprocess.PIPE, check=True)
    return Path(completed.stdout.strip())


def install_dependencies() -> None:
    env = os.environ.copy()
    if sys.platform == "darwin":
        prefix = macos_portaudio_prefix()
        env["CPPFLAGS"] = f"-I{prefix / 'include'} {env.get('CPPFLAGS', '')}".strip()
        env["LDFLAGS"] = f"-L{prefix / 'lib'} {env.get('LDFLAGS', '')}".strip()
        env["PKG_CONFIG_PATH"] = f"{prefix / 'lib/pkgconfig'}{os.pathsep}{env.get('PKG_CONFIG_PATH', '')}".rstrip(os.pathsep)
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is required to build the sidecar runtime.")
    run([uv, "pip", "install", "--python", str(runtime_python()), "-r", str(ROOT / "requirements-runtime.txt")], env=env)


def bundle_macos_portaudio() -> None:
    if sys.platform != "darwin":
        return
    source = macos_portaudio_prefix() / "lib/libportaudio.2.dylib"
    destination = RUNTIME / "lib/libportaudio.2.dylib"
    shutil.copy2(source, destination)
    site_packages = next((RUNTIME / "lib").glob("python*/site-packages"), None)
    if site_packages is None:
        raise SystemExit("Runtime site-packages was not found.")
    for extension in site_packages.glob("pyaudio/_portaudio*.so"):
        run(["install_name_tool", "-change", str(source), "@loader_path/../../../libportaudio.2.dylib", str(extension)])
        run(["codesign", "--force", "--sign", "-", str(extension)])
    run(["install_name_tool", "-id", "@rpath/libportaudio.2.dylib", str(destination)])
    run(["codesign", "--force", "--sign", "-", str(destination)])


def prune_runtime() -> None:
    for site_packages in RUNTIME.rglob("site-packages"):
        for name in ("test", "tests", "__pycache__"):
            for path in site_packages.rglob(name):
                shutil.rmtree(path, ignore_errors=True)
        for path in site_packages.rglob("*.pyc"):
            path.unlink(missing_ok=True)


def smoke_test() -> None:
    py = runtime_python()
    if not py.is_file():
        raise SystemExit(f"Runtime Python is missing: {py}")
    with tempfile.TemporaryDirectory(prefix="here-electron-runtime-") as app_home:
        env = {
            **os.environ,
            "HERE_APP_HOME": app_home,
            "HERE_PROJECT_ROOT": str(ROOT),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        if sys.platform == "darwin":
            env["DYLD_LIBRARY_PATH"] = str(RUNTIME / "lib")
        process = subprocess.Popen(
            [str(py), str(ROOT / "rpc_bridge.py")],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert process.stdin is not None and process.stdout is not None
        try:
            ready = json.loads(process.stdout.readline())
            if ready.get("event") != "ready":
                raise RuntimeError(f"Sidecar did not become ready: {ready}")
            process.stdin.write(json.dumps({"id": "smoke", "method": "ping", "params": {}}) + "\n")
            process.stdin.flush()
            while True:
                response = json.loads(process.stdout.readline())
                if response.get("id") == "smoke":
                    if not response.get("ok"):
                        raise RuntimeError(str(response))
                    break
        finally:
            process.stdin.close()
            process.wait(timeout=20)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", default=os.environ.get("HERE_PYTHON_STANDALONE_ARCHIVE", ""))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if runtime_python().is_file() and not args.force:
        smoke_test()
        print(f"Runtime already ready: {RUNTIME}")
        return
    extract_runtime(download_archive(args.archive))
    install_dependencies()
    bundle_macos_portaudio()
    prune_runtime()
    smoke_test()
    print(f"Runtime ready: {RUNTIME}")


if __name__ == "__main__":
    main()
