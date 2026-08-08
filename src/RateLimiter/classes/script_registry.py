from classes.errors import ConfigurationError
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "lua"

SCRIPT_FILES = {
    "token_bucket_v1": "token_bucket_v1.lua",
    "fixed_window_v1": "fixed_window_v1.lua",
    "sliding_window_v1": "sliding_window_v1.lua",
}

class ScriptRegistry:
    def __init__(self, client):
        self.client = client
        self._scripts = {}

    def get(self, algorithm: str):

        if algorithm in self._scripts:
            return self._scripts[algorithm]

        filename = SCRIPT_FILES.get(algorithm)

        if filename is None:
            raise ConfigurationError(
                f"Unknown rate-limit algorithm: {algorithm}"
            )

        path = SCRIPT_DIR / filename

        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigurationError(
                f"Unable to load Lua script for {algorithm}"
            ) from error

        script = self.client.register_script(source)

        self._scripts[algorithm] = script

        return script