import secrets

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAINTAINER_", env_file=".env", extra="ignore")
    admin_token: SecretStr = Field(min_length=32)
    encryption_key: SecretStr
    database_url: str = "sqlite:///data/maintainer.db"
    workspace_root: str = "data/workspaces"
    static_dir: str = "frontend/dist"
    plugin_root: str = "data/plugins"


class Vault:
    def __init__(self, key: str):
        self.cipher = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str:
        return self.cipher.decrypt(value.encode()).decode() if value else ""


def authenticate(request: Request) -> None:
    expected = "Bearer " + request.app.state.settings.admin_token.get_secret_value()
    actual = request.headers.get("Authorization", "")
    if not secrets.compare_digest(actual.encode(), expected.encode()):
        raise HTTPException(401, "Administrator authentication required")
