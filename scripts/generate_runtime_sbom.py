"""Emit a deterministic CycloneDX inventory for the active Python runtime."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import uuid


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


components = []
for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get("Name") or distribution.name
    version = distribution.version
    license_name = (
        distribution.metadata.get("License-Expression")
        or distribution.metadata.get("License")
        or "UNKNOWN"
    ).strip()
    component = {
        "type": "library",
        "name": name,
        "version": version,
        "purl": f"pkg:pypi/{normalized(name)}@{version}",
    }
    if license_name:
        component["licenses"] = [{"license": {"name": license_name}}]
    components.append(component)

components.sort(key=lambda item: (normalized(item["name"]), item["version"]))
fingerprint = hashlib.sha256(
    json.dumps(components, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
bom = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "serialNumber": "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "maintune-runtime:" + fingerprint)),
    "version": 1,
    "metadata": {
        "component": {
            "type": "application",
            "name": "Maintune",
            "version": "0.1.0-preview.2",
        }
    },
    "components": components,
}
print(json.dumps(bom, indent=2, sort_keys=True))
