"""Finding and saving the Garmin Personal API key on a local machine."""
from __future__ import annotations

import os
from pathlib import Path

from creed.garmin.client import AuthFailed

KEY_ENV_VAR = "GARMIN_PERSONAL_API_KEY"
# Same location Garmin's official client reads, so the key is only stored once.
DEFAULT_KEY_FILE = Path("~/.config/garmin/connect-personal-api-key")


def resolve_api_key(key_file: str | None = None) -> str:
    """Explicit file, then environment variable, then the default file."""
    if key_file:
        return _read_key_file(Path(key_file).expanduser())
    env = os.environ.get(KEY_ENV_VAR)
    if env is not None:
        if not env.strip():
            raise AuthFailed(f"{KEY_ENV_VAR} is set but empty.")
        return env.strip()
    default = DEFAULT_KEY_FILE.expanduser()
    if default.exists():
        return _read_key_file(default)
    raise AuthFailed(
        "No API key found. Create one at https://connect.garmin.com/app/settings/personalApiToken "
        "then run: python tools/garmin_probe.py --save-key"
    )


def _read_key_file(path: Path) -> str:
    try:
        key = path.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise AuthFailed(f"Could not read key file {path}: {type(exc).__name__}") from exc
    if not key:
        raise AuthFailed(f"Key file {path} is empty.")
    return key


def save_api_key(key: str, path: Path | None = None) -> Path:
    key = key.strip()
    if not key:
        raise AuthFailed("No key entered; nothing saved.")
    target = (path or DEFAULT_KEY_FILE).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key)
    return target
