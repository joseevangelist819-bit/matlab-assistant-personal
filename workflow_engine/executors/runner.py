import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from workflow_engine.database import utc_now
from workflow_engine.windows_job import WindowsJob


class ExecutorRunner:
    def __init__(self, root): self.root = Path(root).resolve()

    def run(self, prepared, stdout_path, stderr_path, heartbeat=None, started_callback=None, cancel_requested=None):
        started = utc_now()
        start = time.monotonic()
        process = None
        job = None
        try:
            with Path(stdout_path).open("wb") as stdout, Path(stderr_path).open("wb") as stderr:
                flags = 0x08000000 if os.name == "nt" else 0
                process = subprocess.Popen(prepared.argv, cwd=prepared.cwd, shell=False, stdout=stdout, stderr=stderr, env=dict(prepared.env), creationflags=flags)
                if os.name == "nt":
                    job = WindowsJob(); job.assign(process._handle)
                if started_callback:
                    started_callback(process.pid, started, hashlib.sha256(json.dumps(prepared.argv).encode()).hexdigest())
                deadline = time.monotonic() + prepared.timeout_seconds
                while True:
                    if cancel_requested and cancel_requested():
                        if job: job.terminate(130)
                        else: process.kill()
                        process.wait(timeout=5)
                        return self._result(started, start, process, 130, "process_cancelled", prepared)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        if job: job.terminate(124)
                        else: process.kill()
                        process.wait(timeout=5)
                        return self._result(started, start, process, None, "process_timed_out", prepared)
                    try:
                        code = process.wait(timeout=min(0.25, remaining))
                        return self._result(started, start, process, code, None if code == 0 else "tool_exit_failure", prepared)
                    except subprocess.TimeoutExpired:
                        if heartbeat: heartbeat()
        except Exception as error:
            if process and process.poll() is None:
                if job: job.terminate(125)
                else: process.kill()
                process.wait(timeout=5)
            return self._result(started, start, process, None, "process_start_failed", prepared, str(error))
        finally:
            if job: job.close()

    def _result(self, started, start, process, exit_code, error_type, prepared, detail=None):
        state = "succeeded" if exit_code == 0 and not error_type else ("timed_out" if error_type == "process_timed_out" else ("cancelled" if error_type == "process_cancelled" else "failed"))
        return {"state": state, "exit_code": exit_code, "error_type": error_type, "error_detail": detail, "started_at": started, "completed_at": utc_now(), "duration_ms": round((time.monotonic()-start)*1000, 3), "pid": process.pid if process else None, "command_hash": hashlib.sha256(json.dumps(prepared.argv).encode()).hexdigest(), "metadata": dict(prepared.metadata)}
