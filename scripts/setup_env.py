"""Create local credentials once. Never print secret values."""
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

path = Path(".env")
with path.open("x", encoding="utf-8") as stream:
    stream.write(f"MAINTAINER_ADMIN_TOKEN={secrets.token_urlsafe(36)}\n")
    stream.write(f"MAINTAINER_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n")
path.chmod(0o600)
print("Created .env. Read MAINTAINER_ADMIN_TOKEN locally to sign in. Back up the encryption key separately.")
