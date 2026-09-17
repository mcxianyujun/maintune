# Troubleshooting

- **Blank page:** verify hashed JS/CSS return 200 with correct MIME types, inspect Console and Network, and check visible login controls in a fresh browser context.
- **Build failure:** check the Docker daemon, Compose v2, disk, DNS, and access to GitHub, PyPI, and the base-image registry.
- **Model diagnostic:** verify the API path, credentials, and that `GET /models` includes the configured ID.
- **GitHub:** verify App ID, private key, installation, permissions, event subscriptions, and Webhook Secret.
- **Sandbox:** check local data-directory permissions or Shipyard base URL, key, profile, and the 300-second request cap.
- **Task failure:** read failure stage/type/message/attempt in the Task timeline, then inspect the full server traceback. Never review an empty diff or missing CI context as if it were valid.

Run the platform `doctor` script for installation diagnostics.
