# Upgrade

Run the platform `update` script with the target version. It backs up first, downloads and verifies the release bundle, builds locally, preserves data, applies migrations, recreates the service, and runs health checks.

On failure, the previous bundle, image, and backup remain available. Do not automatically downgrade the database. Use the restore script and a matching application version. Standard proxy variables are forwarded to Docker build.
