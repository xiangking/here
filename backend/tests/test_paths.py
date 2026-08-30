from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from infrastructure.paths import install_user_python_packages_path  # noqa: E402


class PythonPackagePathTests(unittest.TestCase):
    def test_user_packages_do_not_override_bundled_native_dependencies(self) -> None:
        original = sys.path[:]
        user_packages = Path("/tmp/here-user-python-packages")
        try:
            sys.path[:] = [user_packages.as_posix(), "/app/bundled-site-packages", user_packages.as_posix()]
            result = install_user_python_packages_path(
                SimpleNamespace(python_packages_dir=user_packages)
            )

            self.assertEqual(result, user_packages)
            self.assertEqual(
                sys.path,
                ["/app/bundled-site-packages", user_packages.as_posix()],
            )
        finally:
            sys.path[:] = original


if __name__ == "__main__":
    unittest.main()
