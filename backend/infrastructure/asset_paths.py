"""Confine character asset paths to a single owned directory under a root.

``sprite_prefix`` is a public, user-editable folder name. Joining it with a
storage root is only safe when the value is a single path segment that cannot
replace the root, walk upward, or resolve through a symlink to another tree.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

SPRITE_PREFIX_PATTERN = re.compile(r"^[0-9A-Za-z_\-\u4e00-\u9fff]+$")


class UnsafeSpritePrefixError(ValueError):
    """Raised when a sprite prefix cannot be used as an asset folder name."""


def is_strict_child(path: Path, parent: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    resolved_parent = parent.expanduser().resolve(strict=False)
    if resolved == resolved_parent:
        return False
    try:
        resolved.relative_to(resolved_parent)
    except ValueError:
        return False
    return True


def validate_sprite_prefix(value: str | os.PathLike[str] | None) -> str:
    """Return a single-segment folder name or raise ``UnsafeSpritePrefixError``."""
    text = str(value or "").strip()
    if not text:
        raise UnsafeSpritePrefixError("资源前缀不能为空。")
    if text in {".", ".."}:
        raise UnsafeSpritePrefixError("资源前缀不能是当前目录或上级目录。")
    if text.startswith("~") or os.path.isabs(text) or Path(text).is_absolute():
        raise UnsafeSpritePrefixError("资源前缀不能是绝对路径。")
    if any(separator in text for separator in ("/", "\\")):
        raise UnsafeSpritePrefixError("资源前缀不能包含路径分隔符。")
    if not SPRITE_PREFIX_PATTERN.fullmatch(text):
        raise UnsafeSpritePrefixError("资源前缀只能包含字母、数字、下划线、连字符或中文。")
    return text


def sprite_prefix_in_use(
    characters: list[object],
    prefix: str,
    *,
    exclude_name: str | None = None,
) -> bool:
    wanted = str(prefix or "").strip()
    if not wanted:
        return False
    for character in characters:
        name = str(getattr(character, "name", "") or "").strip()
        if exclude_name and name == exclude_name:
            continue
        if str(getattr(character, "sprite_prefix", "") or "").strip() == wanted:
            return True
    return False


def _root(base: str | Path) -> Path:
    return Path(base).expanduser().resolve(strict=False)


def owned_character_dir(base: str | Path, prefix: str) -> Path:
    """Return ``base / prefix`` after proving it is a strict child of ``base``."""
    name = validate_sprite_prefix(prefix)
    root = _root(base)
    candidate = root / name
    if candidate.is_symlink():
        raise UnsafeSpritePrefixError("资源目录不能是指向其他位置的符号链接。")
    if not candidate.exists():
        return candidate
    resolved = candidate.resolve(strict=False)
    if not is_strict_child(resolved, root):
        raise UnsafeSpritePrefixError("资源路径超出允许的目录。")
    if resolved.relative_to(root).parts != (name,):
        raise UnsafeSpritePrefixError("资源路径超出允许的目录。")
    return resolved


def prepare_owned_character_dir(base: str | Path, prefix: str) -> Path:
    """Create ``base / prefix`` and re-check ownership after mkdir."""
    name = validate_sprite_prefix(prefix)
    root = _root(base)
    candidate = root / name
    if candidate.is_symlink():
        raise UnsafeSpritePrefixError("资源目录不能是指向其他位置的符号链接。")
    candidate.mkdir(parents=True, exist_ok=True)
    if candidate.is_symlink():
        raise UnsafeSpritePrefixError("资源目录不能是指向其他位置的符号链接。")
    resolved = candidate.resolve(strict=False)
    if not is_strict_child(resolved, root) or resolved.relative_to(root).parts != (name,):
        raise UnsafeSpritePrefixError("资源路径超出允许的目录。")
    return resolved


def remove_owned_character_dir(base: str | Path, prefix: str) -> bool:
    """Recursively delete an owned character folder. Returns True if removed."""
    try:
        name = validate_sprite_prefix(prefix)
    except UnsafeSpritePrefixError:
        return False
    root = _root(base)
    candidate = root / name
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return False
    resolved = candidate.resolve(strict=False)
    if not is_strict_child(resolved, root):
        return False
    if resolved.relative_to(root).parts != (name,):
        return False
    shutil.rmtree(resolved)
    return True


def is_inside_owned_dir(path: str | Path, owned_dir: str | Path, *, allow_root: bool = False) -> bool:
    """True when ``path`` resolves strictly inside ``owned_dir``."""
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        root = Path(owned_dir).expanduser().resolve(strict=False)
    except OSError:
        return False
    if resolved == root:
        return allow_root
    return is_strict_child(resolved, root)
