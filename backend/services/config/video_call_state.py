from pathlib import Path
import shutil


def migrate_here_video_call(characters: list, characters_dir: Path, defaults: Path) -> bool:
    """Separate the original Here portrait and the bundled call video once."""
    here = next((item for item in characters if item.get("name") == "here"), None)
    if not here:
        return False
    sprites = here.get("sprites", [])
    neutral = next((item for item in sprites if item.get("state_name") == "neutral"), None)
    if not neutral:
        return False
    path = str(neutral.get("path", "")).replace("\\", "/")
    if not (path.endswith("here/here_neutral.png") or path.endswith("here/animations/neutral/frame_001.png")):
        return False
    target = characters_dir / "here"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("here_neutral.png", "video_call.mp4"):
        if not (target / name).exists():
            shutil.copy2(defaults / "here" / name, target / name)
    changed = False
    if path.endswith("here/animations/neutral/frame_001.png"):
        neutral.update(path=(target / "here_neutral.png").as_posix(), frames=[],
                       frame_count=1, fps=0, spritesheet_path="")
        changed = True
    if not any(item.get("state_name") == "video_call" for item in sprites):
        sprites.append({"path": (target / "video_call.mp4").as_posix(), "frames": [],
                        "state_name": "video_call", "source_state": "video_call", "state_group": "custom"})
        changed = True
    return changed
