import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from workflow_engine.errors import PolicyError


RELEASE_PATTERN = re.compile(r"^R(\d{4})([ab])$", re.IGNORECASE)


def normalize_release(value):
    text = str(value).strip()
    if not text.upper().startswith("R"): text = "R" + text
    match = RELEASE_PATTERN.fullmatch(text)
    if not match: raise PolicyError(f"invalid MATLAB release: {value}")
    return f"R{match.group(1)}{match.group(2).lower()}"


def release_key(value):
    match = RELEASE_PATTERN.fullmatch(normalize_release(value))
    return int(match.group(1)), 0 if match.group(2).lower() == "a" else 1


class MatlabRuntimeManager:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.policy_path = self.root / "MATLAB_RUNTIME_POLICY.json"
        if not self.policy_path.is_file():
            candidate = self.root / "source" / "MATLAB_RUNTIME_POLICY.json"
            if candidate.is_file():
                self.policy_path = candidate
        if not self.policy_path.is_file(): raise PolicyError("MATLAB runtime policy is missing")
        self.policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        self.registry_path = self.root / ".workflow" / "matlab-runtimes.json"

    def _candidate_executable(self, matlab_root):
        return Path(matlab_root) / "bin" / "matlab.exe"

    def discover(self):
        roots = set()
        roots.add(str(Path(self.policy["fallback_root"])))
        if os.environ.get("MATLAB_ROOT"): roots.add(os.environ["MATLAB_ROOT"])
        path_executable = shutil.which("matlab")
        if path_executable: roots.add(str(Path(path_executable).resolve().parents[1]))
        for scan_root in self.policy.get("scan_roots", []):
            folder = Path(scan_root)
            if folder.is_dir():
                roots.update(str(item) for item in folder.iterdir() if item.is_dir() and self._candidate_executable(item).is_file())
        roots.update(self._registry_roots())
        candidates = []
        for root in sorted(roots):
            executable = self._candidate_executable(root)
            if executable.is_file(): candidates.append({"root":str(Path(root).resolve()),"executable":str(executable.resolve())})
        return candidates

    def _registry_roots(self):
        if os.name != "nt": return set()
        try: import winreg
        except ImportError: return set()
        roots = set()
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\MathWorks\MATLAB", 0, winreg.KEY_READ | view) as key:
                        index = 0
                        while True:
                            try: release = winreg.EnumKey(key,index); index += 1
                            except OSError: break
                            try:
                                with winreg.OpenKey(key,release) as release_key_handle:
                                    root, _ = winreg.QueryValueEx(release_key_handle,"MATLABROOT"); roots.add(root)
                            except OSError: pass
                except OSError: pass
        return roots

    def probe(self, candidate, timeout=90):
        expression = "p=struct('release',version('-release'),'version',version,'root',matlabroot,'architecture',computer); disp(['WORKFLOW_MATLAB_PROBE=' jsonencode(p)]);"
        completed = subprocess.run([candidate["executable"],"-noFigureWindows","-batch",expression], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=0x08000000 if os.name == "nt" else 0)
        marker = next((line.split("=",1)[1] for line in completed.stdout.splitlines() if line.startswith("WORKFLOW_MATLAB_PROBE=")), None)
        if completed.returncode != 0 or not marker:
            return {**candidate,"status":"probe_failed","exit_code":completed.returncode,"error":completed.stderr[-2000:]}
        payload = json.loads(marker); release = normalize_release(payload["release"])
        engine_dir = self.policy.get("engine_environments",{}).get(release)
        engine_python = (self.root / engine_dir / "Scripts" / "python.exe").resolve() if engine_dir else None
        return {**candidate,**payload,"release":release,"status":"verified","engine_python":str(engine_python) if engine_python and engine_python.is_file() else None}

    def inventory(self, refresh=True):
        if not refresh and self.registry_path.is_file(): return json.loads(self.registry_path.read_text(encoding="utf-8"))
        runtimes = [self.probe(candidate) for candidate in self.discover()]
        payload = {"schema":"matlab-runtime-inventory.v1","fallback_release":normalize_release(self.policy["fallback_release"]),"runtimes":runtimes}
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        return payload

    def select(self, requested_release=None, refresh=False):
        inventory = self.inventory(refresh=refresh)
        verified = [item for item in inventory["runtimes"] if item.get("status") == "verified"]
        fallback_release = normalize_release(self.policy["fallback_release"])
        fallback = next((item for item in verified if item["release"] == fallback_release and Path(item["root"]).resolve() == Path(self.policy["fallback_root"]).resolve()), None)
        if not fallback: raise PolicyError("fallback MATLAB R2025b is missing or failed verification")
        if requested_release:
            requested = normalize_release(requested_release)
            selected = next((item for item in verified if item["release"] == requested), None)
            if selected: return {**selected,"selection_reason":"requested_verified"}
            return {**fallback,"selection_reason":"requested_unavailable_fallback"}
        minimum = release_key(self.policy.get("minimum_release","R2024b"))
        compatible = [item for item in verified if release_key(item["release"]) >= minimum]
        selected = max(compatible, key=lambda item: release_key(item["release"]), default=fallback)
        return {**selected,"selection_reason":"highest_verified_compatible" if selected is not fallback else "verified_fallback"}
