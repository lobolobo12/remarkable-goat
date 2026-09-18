import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

from .models import Settings


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        os.chmod(tmp, 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.private = self.root / ".private"
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.private, 0o700)
        self.output = self.root / "output"
        self.settings_file = self.private / "settings.json"
        self.token_file = self.private / "remarkable.conf"
        self.key_file = self.private / "openai-key"

    def settings(self) -> Settings:
        if not self.settings_file.exists():
            return Settings()
        return Settings.model_validate_json(self.settings_file.read_text())

    def save_settings(self, settings: Settings):
        write_json(self.settings_file, settings.model_dump(mode="json"))

    @contextmanager
    def lock(self):
        import fcntl

        with (self.private / "run.lock").open("w") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another study command is running") from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
