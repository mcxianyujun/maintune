# GitHub App

Use `https://your-domain/webhooks/github` as the webhook URL. Grant Metadata read-only; Contents, Issues, and Pull requests read/write; Checks and Commit statuses read-only. Subscribe to `Issues`, `Issue comment`, and `Pull request`.

Enter the App ID, optional default Installation ID, private-key PEM, and Webhook Secret. Keep `https://api.github.com` for GitHub.com or use the configured GitHub Enterprise Server API URL. Private keys and webhook secrets are encrypted at rest.
