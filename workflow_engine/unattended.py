import json
from pathlib import Path

from workflow_engine.errors import PolicyError


DENIED_FLAGS = {
    "allow_update": "software_update",
    "install_dependencies": "dependency_install",
    "allow_login": "login",
    "allow_telemetry": "telemetry",
    "use_credentials": "credential_use",
    "allow_network": "network_access",
    "external_write": "external_path_write",
    "production": "production_change",
    "database_migration": "database_migration",
    "hardware_authorized": "real_hardware",
    "flash": "firmware_flash",
    "reset": "device_reset",
    "irreversible": "irreversible_delete",
}


class UnattendedPolicy:
    def __init__(self, root):
        self.root = Path(root).resolve()
        path = self.root / "UNATTENDED_POLICY.json"
        if not path.is_file():
            candidate = self.root / "source" / "UNATTENDED_POLICY.json"
            if candidate.is_file():
                path = candidate
        if not path.is_file(): raise PolicyError("unattended policy is missing")
        self.config = json.loads(path.read_text(encoding="utf-8"))
        if self.config.get("mode") != "safe_unattended": raise PolicyError("unsupported unattended policy mode")

    def check(self, parameters):
        blocked = [category for flag, category in DENIED_FLAGS.items() if parameters.get(flag) is True]
        if blocked: raise PolicyError("policy_blocked: unattended denies " + ",".join(sorted(blocked)))
        return {"decision":"allow","mode":"safe_unattended"}
