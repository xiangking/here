"""Desktop entrypoint for Here."""

from __future__ import annotations

from app.desktop.bootstrap import run_desktop_app


def main() -> None:
    run_desktop_app()


if __name__ == "__main__":
    main()
