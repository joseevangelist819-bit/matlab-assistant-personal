import json
import os
import subprocess
import uuid
from pathlib import Path


class MatlabEngineClient:
    def __init__(self, root, engine_python=None, expected_release=None):
        self.root = Path(root).resolve()
        if engine_python is None:
            from workflow_engine.matlab_runtime import MatlabRuntimeManager
            runtime = MatlabRuntimeManager(self.root).select("R2025b")
            engine_python = runtime.get("engine_python")
            expected_release = expected_release or runtime["release"]
        python = Path(engine_python) if engine_python else Path()
        if not python.is_file(): raise RuntimeError("MATLAB Engine virtual environment is not installed")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        agent_root = Path(__file__).resolve().parents[1]
        candidates = []
        for config_path in (agent_root / "MATLAB_COMPILER.json", agent_root.parent / "MATLAB_COMPILER.json"):
            if config_path.is_file():
                try:
                    configured = json.loads(config_path.read_text(encoding="utf-8")).get("mingw_root")
                    if configured:
                        candidates.append(Path(configured))
                except (OSError, ValueError):
                    pass
        candidates.extend((agent_root / "工具链" / "mingw81", agent_root.parent / "工具链" / "mingw81"))
        for bundled_mingw in candidates:
            if (bundled_mingw / "bin" / "gcc.exe").is_file():
                environment["MW_MINGW64_LOC"] = str(bundled_mingw)
                break
        self.process = subprocess.Popen([str(python), "-m", "workflow_engine.matlab_engine_host"], cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=environment, creationflags=0x08000000 if os.name == "nt" else 0)
        startup = self._read()
        if not startup.get("ok"): raise RuntimeError(startup)
        self.startup = startup["result"]
        if expected_release and self.startup.get("release") != expected_release:
            self.close()
            raise RuntimeError(f"MATLAB Engine release mismatch: expected {expected_release}, got {self.startup.get('release')}")

    def _read(self):
        line = self.process.stdout.readline()
        if not line: raise RuntimeError(self.process.stderr.read() or "MATLAB Engine host exited")
        return json.loads(line)

    def request(self, command, **parameters):
        command_id = str(uuid.uuid4())
        payload = {"id": command_id, "command": command, **parameters}
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n"); self.process.stdin.flush()
        result = self._read()
        if result.get("id") != command_id: raise RuntimeError("MATLAB Engine protocol response mismatch")
        if not result.get("ok"): raise RuntimeError(result["error"])
        return result["result"]

    def call(self, function, *arguments, nargout=1): return self.request("call", function=function, arguments=list(arguments), nargout=nargout)
    def run_script(self, path): return self.request("run_script", path=str(Path(path).resolve()))
    def run_tests(self, path): return self.request("run_tests", path=str(Path(path).resolve()))
    def check_code(self, path): return self.request("check_code", path=str(Path(path).resolve()))
    def toolbox_info(self): return self.request("toolbox_info")
    def requirements(self, path): return self.request("requirements", path=str(Path(path).resolve()))
    def cd(self, path): return self.request("cd", path=str(Path(path).resolve()))
    def start_call(self, function, *arguments, nargout=1): return self.request("start_call", function=function, arguments=list(arguments), nargout=nargout)["token"]
    def cancel(self, token): return self.request("cancel", token=token)["cancelled"]
    def future_result(self, token, timeout=None): return self.request("future_result", token=token, timeout=timeout)
    def set_workspace(self, name, value): return self.request("workspace_set", name=name, value=value)
    def get_workspace(self, name): return self.request("workspace_get", name=name)
    def eval(self, expression, nargout=0, allow_eval=False): return self.request("eval", expression=expression, nargout=nargout, allow_eval=allow_eval)
    def ping(self): return self.request("ping")

    def close(self):
        if self.process.poll() is None:
            try: self.request("quit")
            finally: self.process.wait(timeout=30)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
