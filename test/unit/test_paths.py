from __future__ import annotations

from pathlib import Path

from infrastructure.paths import (
    default_character_assets_dir,
    default_character_memory_dir,
    get_app_paths,
    load_storage_paths,
    project_root,
    resolve_character_asset_path,
    resolve_storage_path,
    seed_defaults,
    save_storage_paths,
    storage_paths_config_path,
)


def test_default_storage_paths_follow_app_home(tmp_path, monkeypatch):
    app_home = tmp_path / "here-home"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))

    paths = get_app_paths()

    assert paths.memory_dir == app_home / "memory"
    assert paths.characters_dir == app_home / "characters"
    assert paths.memory_dir.is_dir()
    assert paths.characters_dir.is_dir()


def test_storage_path_overrides_can_be_absolute(tmp_path, monkeypatch):
    app_home = tmp_path / "here-home"
    memory_dir = tmp_path / "custom-memory"
    assets_dir = tmp_path / "custom-assets"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))

    save_storage_paths(
        character_memory_dir=str(memory_dir),
        character_assets_dir=str(assets_dir),
    )
    paths = get_app_paths()

    assert paths.memory_dir == memory_dir
    assert paths.characters_dir == assets_dir
    assert load_storage_paths().character_memory_dir == str(memory_dir)
    assert storage_paths_config_path() == app_home / "config" / "storage_paths.yaml"


def test_relative_storage_path_overrides_are_app_home_relative(tmp_path, monkeypatch):
    app_home = tmp_path / "here-home"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))

    save_storage_paths(
        character_memory_dir="memory-alt",
        character_assets_dir="assets-alt",
    )
    paths = get_app_paths()

    assert paths.memory_dir == app_home / "memory-alt"
    assert paths.characters_dir == app_home / "assets-alt"
    assert resolve_storage_path(
        "",
        fallback=default_character_memory_dir(app_home),
    ) == app_home / "memory"
    assert resolve_storage_path(
        Path("assets-alt"),
        root=app_home,
        fallback=default_character_assets_dir(app_home),
    ) == app_home / "assets-alt"


def test_seed_defaults_rewrites_default_character_assets_to_configured_dir(tmp_path, monkeypatch):
    app_home = tmp_path / "here-home"
    source_root = tmp_path / "defaults"
    character_frame = source_root / "characters" / "here" / "animations" / "neutral" / "frame_001.png"
    character_frame.parent.mkdir(parents=True)
    character_frame.write_bytes(b"png")
    config_dir = source_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "characters.yaml").write_text(
        """
- name: here
  color: '#fff'
  sprite_prefix: here
  sprites:
  - path: defaults/characters/here/animations/neutral/frame_001.png
    frames:
    - defaults/characters/here/animations/neutral/frame_001.png
  character_profile:
    identity: {}
    personality: {}
    speech: {}
    relationship: {}
    preferences: {}
    boundaries: {}
  visual_reference_image: defaults/characters/here/animations/neutral/frame_001.png
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    save_storage_paths(character_assets_dir=str(tmp_path / "custom-assets"))

    paths = get_app_paths()
    seed_defaults(paths, source_root=source_root)

    seeded_config = (app_home / "config" / "characters.yaml").read_text(encoding="utf-8")
    expected = (tmp_path / "custom-assets" / "here" / "animations" / "neutral" / "frame_001.png").as_posix()
    assert expected in seeded_config
    assert "defaults/characters" not in seeded_config


def test_resolve_character_asset_path_maps_legacy_defaults_prefix(tmp_path, monkeypatch):
    app_home = tmp_path / "here-home"
    assets_dir = tmp_path / "custom-assets"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    save_storage_paths(character_assets_dir=str(assets_dir))

    resolved = resolve_character_asset_path(
        "defaults/characters/here/animations/neutral/frame_001.png"
    )

    assert resolved == assets_dir / "here" / "animations" / "neutral" / "frame_001.png"


def test_resolve_character_asset_path_maps_project_assets_from_any_cwd(tmp_path, monkeypatch):
    app_home = tmp_path / "here-home"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    monkeypatch.chdir(tmp_path)

    resolved = resolve_character_asset_path("assets/system/picture/Icon.png")

    assert resolved == project_root() / "assets" / "system" / "picture" / "Icon.png"
