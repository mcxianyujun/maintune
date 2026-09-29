# SPDX-License-Identifier: MIT
"""Interactive setup; translations live in a separate JSON resource."""

import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from gateway import validate_config

ROOT = Path(__file__).resolve().parent


def repository(value):
    value = value.strip().rstrip("/")
    if value.startswith("https://github.com/"):
        value = value[len("https://github.com/"):]
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Use owner/repository or its GitHub HTTPS URL")
    return value


def main():
    messages = json.loads((ROOT / "locales" / "zh-CN.json").read_text(encoding="utf-8"))
    folder = ROOT / ".private"
    if folder.exists():
        raise SystemExit(messages["exists"])
    print(messages["intro"])
    base = input(messages["maintune"]).strip().rstrip("/")
    public = input(messages["public"]).strip().rstrip("/")
    parsed = urlsplit(public)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise SystemExit(messages["https"])
    repos = [repository(item) for item in input(messages["repos"]).split(",")]
    config = {"maintune_url": base, "access_token": secrets.token_urlsafe(32),
              "path_secret": secrets.token_urlsafe(32), "bind": "127.0.0.1", "port": 8787}
    validate_config(config)
    folder.mkdir(mode=0o700)
    values = {
        "gateway.json": json.dumps(config, indent=2),
        "plugin-config.json": json.dumps({"access_token": config["access_token"], "repositories": repos,
                                         "review_bot": "Maintune"}, indent=2),
        "connection.txt": messages["connection"].format(url=public + "/" + config["path_secret"] + "/mcp"),
    }
    for name, text in values.items():
        descriptor = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(text + "\n")
    print(messages["done"])


if __name__ == "__main__":
    main()
