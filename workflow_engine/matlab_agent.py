import json
import os
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from workflow_engine.errors import PolicyError
from workflow_engine.executors.runner import ExecutorRunner
from workflow_engine.matlab_runtime import MatlabRuntimeManager
from workflow_engine.matlab_engine_client import MatlabEngineClient
from workflow_engine.unattended import UnattendedPolicy
from workflow_engine.diagnostics import diagnose_execution
from workflow_engine.artifacts import snapshot_project, collect_changes
from workflow_engine.dynamic_validation import validate_function_cases
from workflow_engine.simulink_modeling import normalize_advanced_model_spec, normalize_basic_model_spec


SUPPORTED_ACTIONS = frozenset({
    "call_function", "run_script", "run_tests", "run_simulink", "check_code",
    "eval_expression", "workflow", "toolbox_info", "identify_model",
    "design_controller", "design_observer", "robustness_sweep", "export_results",
    "workspace_get", "workspace_set", "compiler_status", "build_mex",
    "run_rapid_accelerator", "matlab_codegen", "simulink_codegen",
    "create_simulink_model", "configure_simulink_model",
})


def _agent_home():
    configured = os.environ.get("MATLAB_AGENT_HOME")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[2]


def _safe_environment(home=None):
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "MW_MINGW64_LOC", "MATLAB_AGENT_MATLAB_ROOT"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    if home is not None:
        home = Path(home)
        candidates = []
        for config_path in (home / "MATLAB_COMPILER.json", home.parent / "MATLAB_COMPILER.json"):
            if config_path.is_file():
                try:
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                    configured = config.get("mingw_root")
                    if configured:
                        candidates.append(Path(configured))
                    compatible_root = config.get("matlab_root_compat")
                    if compatible_root and Path(compatible_root).is_dir():
                        environment["MATLAB_AGENT_MATLAB_ROOT"] = compatible_root
                except (OSError, ValueError):
                    pass
        candidates.extend((
            Path(home) / "工具链" / "mingw81",
            Path(home).parent / "工具链" / "mingw81",
        ))
        for bundled_mingw in candidates:
            if (bundled_mingw / "bin" / "gcc.exe").is_file():
                environment["MW_MINGW64_LOC"] = str(bundled_mingw)
                break
    return environment


class MatlabAgent:
    def __init__(self, home=None):
        self.home = Path(home).resolve() if home else _agent_home()
        self._engine_sessions = {}
        self._task_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="matlab-agent-task")
        self._tasks = {}
        self._tasks_lock = threading.Lock()

    def close(self):
        with self._tasks_lock:
            for task in self._tasks.values():
                task["cancel_event"].set()
        self._task_executor.shutdown(wait=True, cancel_futures=True)
        sessions, self._engine_sessions = self._engine_sessions, {}
        for client in sessions.values():
            try:
                client.close()
            except Exception:
                pass

    def _engine_client(self, project_root, runtime):
        key = runtime["release"]
        client = self._engine_sessions.get(key)
        if client is not None:
            try:
                client.ping()
                client.cd(project_root)
                return client, True
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass
                self._engine_sessions.pop(key, None)
        client = MatlabEngineClient(project_root, engine_python=runtime["engine_python"], expected_release=runtime["release"])
        self._engine_sessions[key] = client
        return client, False

    def _execute_engine(self, action, parameters, project_root, runtime, result_path, attempt_id, attempt_dir, before_snapshot):
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        client = None
        reused = False
        result = {"protocol_version": "1.0", "action": action, "backend": "engine", "status": "failed", "error": None}
        try:
            client, reused = self._engine_client(project_root, runtime)
            if action == "call_function":
                arguments = [item["value"] for item in parameters.get("arguments", [])]
                result["outputs"] = client.call(parameters["function"], *arguments, nargout=int(parameters.get("nargout", 1)))
            elif action == "toolbox_info":
                result["outputs"] = client.toolbox_info()
            elif action == "run_script":
                script = (project_root / parameters["script"]).resolve()
                result["details"] = client.run_script(script)
            elif action == "run_tests":
                test_path = (project_root / parameters["path"]).resolve()
                summary = client.run_tests(test_path)
                result["details"] = summary
                if int(summary.get("failed", 0)) or int(summary.get("incomplete", 0)):
                    raise RuntimeError(f"MATLAB tests failed: {summary}")
            elif action == "check_code":
                code_path = (project_root / parameters["path"]).resolve()
                result["outputs"] = client.check_code(code_path)
            elif action == "workspace_set":
                result["details"] = client.set_workspace(parameters["name"], parameters["value"])
            elif action == "workspace_get":
                result["outputs"] = client.get_workspace(parameters["name"])
            else:
                raise ValueError(f"engine backend action not supported: {action}")
            result["matlab_version"] = client.startup["version"]
            result["status"] = "succeeded"
        except Exception as error:
            result["error"] = {"type": type(error).__name__, "message": str(error)}
            engine_alive = False
            if client is not None:
                try:
                    client.ping()
                    engine_alive = True
                except Exception:
                    pass
            if not engine_alive:
                key = runtime["release"]
                failed = self._engine_sessions.pop(key, None)
                if failed is not None:
                    try:
                        failed.close()
                    except Exception:
                        pass
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        process = {
            "state": "succeeded" if result["status"] == "succeeded" else "failed",
            "exit_code": 0 if result["status"] == "succeeded" else 1,
            "error_type": None if result["status"] == "succeeded" else "engine_request_failure",
            "error_detail": result.get("error"),
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "pid": client.process.pid if client is not None else None,
            "metadata": {"backend": "engine", "release": runtime["release"], "persistent_session": True, "session_reused": reused},
        }
        payload = {
            "status": result["status"], "action": action, "attempt_id": attempt_id, "backend": "engine",
            "runtime": {"release": runtime["release"], "version": runtime.get("version"), "selection_reason": runtime["selection_reason"]},
            "process": process, "result": result, "artifacts_root": str(attempt_dir),
        }
        payload["file_changes"] = collect_changes(project_root, before_snapshot)
        if payload["status"] != "succeeded":
            payload["diagnostic"] = diagnose_execution(payload)
        return payload

    def doctor(self, refresh=False):
        manager = MatlabRuntimeManager(self.home)
        inventory = manager.inventory(refresh=refresh)
        selected = manager.select(refresh=False)
        return {
            "status": "ready",
            "agent_home": str(self.home),
            "selected_runtime": selected,
            "runtime_count": len(inventory.get("runtimes", [])),
            "interfaces": ["mcp", "cli"],
            "actions": sorted(SUPPORTED_ACTIONS | {"control_benchmark", "validate_functions"}),
        }

    def validate_functions(self, specification):
        if not isinstance(specification, dict):
            raise ValueError("specification must be a JSON object")
        project_root = specification.get("project_root")
        if not project_root:
            raise ValueError("project_root is required")
        cases = specification.get("cases", [])
        return validate_function_cases(self, project_root, cases, specification)

    def create_simulink_model(self, specification):
        spec = normalize_basic_model_spec(specification)
        project_root = spec.pop("project_root")
        timeout_seconds = spec.pop("timeout_seconds")
        return self.execute({
            "project_root": project_root,
            "action": "create_simulink_model",
            "parameters": {**spec, "backend": "batch"},
            "timeout_seconds": timeout_seconds,
        })

    def configure_simulink_model(self, specification):
        spec = normalize_advanced_model_spec(specification)
        project_root = spec.pop("project_root")
        timeout_seconds = spec.pop("timeout_seconds")
        return self.execute({
            "project_root": project_root,
            "action": "configure_simulink_model",
            "parameters": {**spec, "backend": "batch"},
            "timeout_seconds": timeout_seconds,
        })

    def run_control_benchmark(self, specification):
        from workflow_engine.control_benchmarks import prepare_control_benchmark, load_control_benchmark_result
        if not isinstance(specification, dict):
            raise ValueError("specification must be a JSON object")
        project_root = specification.get("project_root")
        benchmark = specification.get("benchmark")
        if not project_root or not benchmark:
            raise ValueError("project_root and benchmark are required")
        options = dict(specification.get("options") or {})
        timeout = int(specification.get("timeout_seconds", options.get("timeout_seconds", 180)))
        backend = str(specification.get("backend", options.get("backend", "auto")))
        prepared = prepare_control_benchmark(project_root, benchmark, {**options, "execute": False})
        execution = self.execute({"project_root": project_root, "action": "run_script", "parameters": {
            "script": prepared["script"], "backend": backend, "export_figures": True,
        }, "timeout_seconds": timeout})
        if execution.get("status") != "succeeded":
            return {"benchmark": benchmark, "status": "failed", "required_products": prepared["required_products"],
                    "parameters": prepared["parameters"], "metrics": {}, "acceptance": prepared["acceptance"],
                    "artifacts": [], "limitations": ["MATLAB execution failed"], "execution": execution}
        result = load_control_benchmark_result(prepared)
        result["execution"] = execution
        return result

    def requirements(self, project_root, path):
        project_root = Path(project_root).resolve()
        target = (project_root / path).resolve()
        runtime = MatlabRuntimeManager(self.home).select()
        if not runtime.get("engine_python"):
            raise PolicyError("MATLAB Engine environment is unavailable")
        client, reused = self._engine_client(project_root, runtime)
        result = client.requirements(target)
        products = result.get("products") or []
        if isinstance(products, dict): products = [products]
        features = {"MATLAB":"matlab","Simulink":"simulink","Control System Toolbox":"Control_Toolbox","Signal Processing Toolbox":"Signal_Toolbox","Wavelet Toolbox":"Wavelet_Toolbox","Optimization Toolbox":"Optimization_Toolbox","Statistics and Machine Learning Toolbox":"Statistics_Toolbox","System Identification Toolbox":"Identification_Toolbox","Robust Control Toolbox":"Robust_Toolbox"}
        normalized = []
        for product in products:
            item = dict(product)
            item["installed"] = True
            feature = features.get(item.get("Name"))
            item["license_feature"] = feature
            item["licensed"] = bool(client.eval(f"license('test','{feature}')", nargout=1, allow_eval=True)) if feature else None
            normalized.append(item)
        return {"status":"succeeded","project_root":str(project_root),"path":str(target),"files":result.get("files",[]),"products":normalized,"engine_session_reused":reused}

    def run_project(self, specification):
        project_root = Path(specification["project_root"]).resolve()
        script = specification["script"]
        test_path = specification.get("test_path")
        required_artifacts = list(specification.get("required_artifacts", []))
        timeout = int(specification.get("timeout_seconds", 300))
        phases = []
        try:
            requirements = self.requirements(project_root, script)
            phases.append({"phase":"requirements","status":"succeeded","result":requirements})
        except Exception as error:
            phases.append({"phase":"requirements","status":"failed","error":{"type":type(error).__name__,"message":str(error)}})
        check = self.execute({"project_root":str(project_root),"action":"check_code","parameters":{"path":script,"backend":"auto"},"timeout_seconds":timeout})
        phases.append({"phase":"check_code","status":check["status"],"result":check})
        run = self.execute({"project_root":str(project_root),"action":"run_script","parameters":{"script":script,"backend":"auto","export_figures":True},"timeout_seconds":timeout})
        phases.append({"phase":"run_script","status":run["status"],"result":run})
        if run["status"] != "succeeded" and (run.get("diagnostic") or {}).get("category") == "engine_unavailable":
            run = self.execute({"project_root":str(project_root),"action":"run_script","parameters":{"script":script,"backend":"batch","export_figures":True},"timeout_seconds":timeout})
            phases.append({"phase":"run_script_batch_fallback","status":run["status"],"result":run})
        if run["status"] != "succeeded":
            diagnostic = run.get("diagnostic") or {}
            return {"status":"needs_ai_fix" if diagnostic.get("retryable") else "blocked","phases":phases,"repair_request":{"diagnostic":diagnostic,"action":"modify_project_and_retry" if diagnostic.get("retryable") else diagnostic.get("recommended_action")}}
        if test_path:
            tests = self.execute({"project_root":str(project_root),"action":"run_tests","parameters":{"path":test_path,"backend":"auto"},"timeout_seconds":timeout})
            phases.append({"phase":"run_tests","status":tests["status"],"result":tests})
            if tests["status"] != "succeeded":
                return {"status":"needs_ai_fix","phases":phases,"repair_request":{"diagnostic":tests.get("diagnostic"),"action":"fix_tests_or_implementation"}}
        missing = [item for item in required_artifacts if not (project_root / item).is_file()]
        artifact_result = {"required":required_artifacts,"missing":missing,"passed":not missing}
        phases.append({"phase":"artifact_acceptance","status":"succeeded" if not missing else "failed","result":artifact_result})
        if missing:
            return {"status":"needs_ai_fix","phases":phases,"repair_request":{"category":"missing_artifacts","missing":missing,"action":"generate_required_artifacts"}}
        return {"status":"verified_done","phases":phases,"artifacts":run.get("file_changes",{}).get("artifacts",[])}

    def submit(self, request):
        task_id = str(uuid.uuid4())
        record = {"task_id": task_id, "status": "queued", "request": request, "cancel_event": threading.Event(), "result": None, "error": None, "future": None}
        with self._tasks_lock:
            self._tasks[task_id] = record
        record["future"] = self._task_executor.submit(self._run_task, task_id)
        return {"task_id": task_id, "status": "queued"}

    def _run_task(self, task_id):
        with self._tasks_lock:
            record = self._tasks[task_id]
            if record["cancel_event"].is_set():
                record["status"] = "cancelled"
                return
            record["status"] = "running"
        try:
            result = self.execute(record["request"], cancel_event=record["cancel_event"], task_record=record)
            with self._tasks_lock:
                record["result"] = result
                record["status"] = "cancelled" if result.get("process", {}).get("state") == "cancelled" else ("succeeded" if result.get("status") == "succeeded" else "failed")
        except Exception as error:
            with self._tasks_lock:
                record["error"] = {"type": type(error).__name__, "message": str(error)}
                record["status"] = "cancelled" if record["cancel_event"].is_set() else "failed"

    def task_status(self, task_id):
        with self._tasks_lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise ValueError(f"unknown task: {task_id}")
            return {"task_id": task_id, "status": record["status"], "result": record["result"], "error": record["error"]}

    def task_cancel(self, task_id):
        with self._tasks_lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise ValueError(f"unknown task: {task_id}")
            record["cancel_event"].set()
            if record["future"].cancel():
                record["status"] = "cancelled"
            return {"task_id": task_id, "status": record["status"], "cancel_requested": True}

    def task_retry(self, task_id):
        with self._tasks_lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise ValueError(f"unknown task: {task_id}")
            request = json.loads(json.dumps(record["request"]))
        return self.submit(request)

    def task_logs(self, task_id, offset=0):
        status = self.task_status(task_id)
        with self._tasks_lock:
            record = self._tasks[task_id]
            root = record.get("artifacts_root")
        logs = {}
        if root:
            for name in ("stdout.log", "stderr.log"):
                path = Path(root) / name
                text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
                logs[name] = {"text": text[int(offset):], "next_offset": len(text)}
        return {"task_id": task_id, "status": status["status"], "logs": logs}

    def execute(self, request, cancel_event=None, task_record=None):
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        action = request.get("action")
        if action not in SUPPORTED_ACTIONS:
            raise PolicyError(f"unsupported_action: {action}")
        project_root = Path(str(request.get("project_root", ""))).expanduser().resolve()
        if not project_root.is_dir():
            raise PolicyError("project_root must be an existing directory")
        timeout = int(request.get("timeout_seconds", 120))
        if timeout <= 0 or timeout > 3600:
            raise PolicyError("timeout_seconds must be 1..3600")
        before_snapshot = snapshot_project(project_root)
        attempt_id = str(uuid.uuid4())
        attempt_dir = project_root / ".matlab-agent" / "attempts" / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=False)
        if task_record is not None:
            task_record["artifacts_root"] = str(attempt_dir)
        parameters = dict(request.get("parameters") or {})
        UnattendedPolicy(self.home).check(parameters)
        runtime = MatlabRuntimeManager(self.home).select(parameters.get("release"))
        payload = {
            "protocol_version": "1.0", "action": action, "parameters": parameters,
            "project_root": project_root.as_posix(), "attempt_dir": attempt_dir.as_posix(),
            "runtime": runtime,
        }
        request_path = attempt_dir / "request.json"
        result_path = attempt_dir / "result.json"
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        backend = str(parameters.get("backend", "batch"))
        engine_python = Path(runtime["engine_python"]) if runtime.get("engine_python") else None
        engine_actions = {"call_function", "toolbox_info", "run_script", "run_tests", "check_code", "workspace_get", "workspace_set"}
        if backend == "auto":
            backend = "engine" if engine_python and engine_python.is_file() and action in engine_actions else "batch"
        if backend not in {"batch", "engine"}:
            raise PolicyError("backend must be batch, engine, or auto")
        if backend == "engine":
            if action not in engine_actions:
                raise PolicyError(f"engine backend does not support {action}")
            if not engine_python or not engine_python.is_file():
                raise PolicyError("MATLAB Engine environment is unavailable")
            return self._execute_engine(action, parameters, project_root, runtime, result_path, attempt_id, attempt_dir, before_snapshot)
        else:
            bridge = self.home / "src" / "workflow_engine" / "bridges" / "matlab"
            if not bridge.is_dir():
                bridge = self.home / "workflow_engine" / "bridges" / "matlab"
            if not bridge.is_dir():
                bridge = self.home / "source" / "workflow_engine" / "bridges" / "matlab"
            expression = "workflow_bridge('" + request_path.as_posix().replace("'", "''") + "','" + result_path.as_posix().replace("'", "''") + "')"
            argv = (runtime["executable"], "-sd", str(bridge), "-noFigureWindows", "-batch", expression)
        from workflow_engine.executors.base import PreparedExecution
        prepared = PreparedExecution(argv, project_root, _safe_environment(self.home), timeout, (("tool:matlab", "exclusive"),), {"backend": backend, "release": runtime["release"]})
        process = ExecutorRunner(project_root).run(prepared, attempt_dir / "stdout.log", attempt_dir / "stderr.log", cancel_requested=(cancel_event.is_set if cancel_event else None))
        matlab_result = None
        if result_path.is_file():
            matlab_result = json.loads(result_path.read_text(encoding="utf-8"))
        payload = {
            "status": "succeeded" if process["state"] == "succeeded" and matlab_result and matlab_result.get("status") == "succeeded" else process["state"],
            "action": action, "attempt_id": attempt_id, "backend": backend,
            "runtime": {"release": runtime["release"], "version": runtime.get("version"), "selection_reason": runtime["selection_reason"]},
            "process": process, "result": matlab_result,
            "artifacts_root": str(attempt_dir),
        }
        payload["file_changes"] = collect_changes(project_root, before_snapshot)
        if payload["status"] != "succeeded":
            payload["diagnostic"] = diagnose_execution(payload)
        return payload
