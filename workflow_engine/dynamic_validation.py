"""Safe, deterministic dynamic validation for MATLAB functions."""

from __future__ import annotations

import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "dynamic-validation.v1"
# This registry intentionally contains deterministic, side-effect-free Base
# MATLAB functions.  Functions that open UI, touch hardware, write files, or
# depend on an unavailable product remain classified instead of being guessed
# safe at runtime.
SAFE_FUNCTIONS = {
    "abs", "cumsum", "det", "diff", "eig", "length", "max", "mean",
    "min", "ndims", "norm", "numel", "prod", "reshape", "size", "sort",
    "strcmp", "strlength", "sum", "trace", "transpose", "unique", "upper",
    "lower",
}
RISK_WORDS = {
    "gui": "GUI/interactive function",
    "hardware": "hardware access",
    "network": "network access",
    "file_write": "file write side effect",
    "filesystem": "filesystem side effect",
    "interactive": "interactive input",
    "external_service": "external service",
    "unknown_high_risk": "unknown high-risk function",
    "license": "license/toolbox restricted",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return str(value)
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    return repr(value)


def normalize_validation_spec(spec):
    if isinstance(spec, list):
        spec = {"cases": spec}
    if not isinstance(spec, dict):
        raise ValueError("validation specification must be an object or case list")
    raw_cases = spec.get("cases", [])
    if not isinstance(raw_cases, list):
        raise ValueError("cases must be a list")
    seed = int(spec.get("seed", 0))
    options = dict(spec.get("options") or {})
    return {
        "schema_version": SCHEMA_VERSION,
        "backend": str(spec.get("backend", options.get("backend", "auto"))),
        "seed": seed,
        "timeout_seconds": int(spec.get("timeout_seconds", options.get("timeout_seconds", 30))),
        "report_dir": spec.get("report_dir"),
        "cases": [dict(case) if isinstance(case, dict) else {"function": case} for case in raw_cases],
    }


def classify_function_case(case):
    if not isinstance(case, dict):
        return {"status": "invalid_case", "reason": "case must be an object"}
    function = str(case.get("function", case.get("name", ""))).strip()
    tags = {str(tag).lower() for tag in (case.get("risk_tags") or [])}
    lowered = function.lower()
    if not function:
        return {"status": "invalid_case", "reason": "missing function"}
    for tag, reason in RISK_WORDS.items():
        if tag in tags or tag in lowered:
            status = "capability_limited" if tag == "license" else "classified_skip"
            return {"status": status, "reason": reason, "function": function, "risk_tags": sorted(tags)}
    if function not in SAFE_FUNCTIONS:
        return {"status": "classified_skip", "reason": "function is not in the safe registry", "function": function, "risk_tags": sorted(tags)}
    return {"status": "safe", "reason": "registered deterministic Base MATLAB function", "function": function, "risk_tags": sorted(tags)}


def _fixture_value(fixture, seed):
    if fixture is None:
        return None
    if not isinstance(fixture, str):
        return fixture
    values = {
        "scalar": 2,
        "vector": [3, 1, 2],
        "signed_vector": [-3, 1, -2],
        "matrix": [[1, 2], [3, 4]],
        "matrix3x2": [[1, 2], [3, 4], [5, 6]],
        "string": "codex",
        "logical": True,
        "empty": [],
    }
    if fixture == "random_vector":
        rng = random.Random(seed)
        return [round(rng.random(), 8) for _ in range(4)]
    if fixture not in values:
        raise ValueError(f"unknown fixture: {fixture}")
    return values[fixture]


def _arguments(case, seed):
    if "arguments" in case:
        args = case["arguments"]
        if not isinstance(args, list):
            raise ValueError("arguments must be a list")
        return [_jsonable(item.get("value")) if isinstance(item, dict) and "value" in item else _jsonable(item) for item in args]
    fixture = case.get("fixture")
    if fixture is None:
        return []
    fixtures = fixture if isinstance(fixture, list) else [fixture]
    return [_fixture_value(item, seed + index) for index, item in enumerate(fixtures)]


def _expected_matches(expected, outputs):
    if expected is None:
        return True, None
    value = outputs[0] if isinstance(outputs, list) and len(outputs) == 1 else outputs
    if isinstance(expected, dict):
        if "equals" in expected:
            ok = _jsonable(value) == _jsonable(expected["equals"])
        elif "contains" in expected:
            ok = expected["contains"] in value
        elif "length" in expected:
            ok = len(value) == int(expected["length"])
        else:
            ok = True
    else:
        ok = _jsonable(value) == _jsonable(expected)
    return ok, None if ok else {"expected": _jsonable(expected), "actual": _jsonable(value)}


def _invoke(agent, project_root, function, arguments, nargout, backend, timeout):
    request = {"project_root": str(project_root), "action": "call_function", "parameters": {
        "function": function,
        "arguments": [{"value": value} for value in arguments],
        "nargout": nargout,
        "backend": backend,
    }, "timeout_seconds": timeout}
    if hasattr(agent, "execute"):
        return agent.execute(request)
    return agent.call_function(project_root, function, arguments, nargout=nargout, backend=backend, timeout_seconds=timeout)


def validate_function_cases(agent, project_root, cases, options=None):
    options = dict(options or {})
    spec = normalize_validation_spec({"cases": cases, **options})
    root = Path(project_root).resolve()
    started_at = _utc_now()
    results = []
    for index, case in enumerate(spec["cases"]):
        classification = classify_function_case(case)
        item = {"index": index, "request": _jsonable(case), **classification}
        if classification["status"] != "safe":
            results.append(item)
            continue
        function = classification["function"]
        timeout = int(case.get("timeout_seconds", spec["timeout_seconds"]))
        backend = str(case.get("backend", spec["backend"]))
        try:
            args = _arguments(case, spec["seed"] + index)
            nargout = int(case.get("nargout", 1))
            if nargout < 0:
                raise ValueError("nargout must be non-negative")
            started = time.monotonic()
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                future = pool.submit(_invoke, agent, root, function, args, nargout, backend, timeout)
                payload = future.result(timeout=timeout)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            if payload and payload.get("status") not in (None, "succeeded"):
                raise RuntimeError((payload.get("result") or {}).get("error") or payload.get("error") or payload)
            payload_result = (payload or {}).get("result") or {}
            outputs = payload_result.get("outputs", (payload or {}).get("outputs"))
            matches, mismatch = _expected_matches(case.get("expected"), outputs)
            item.update({"status": "dynamic_pass" if matches else "dynamic_failed", "backend": backend,
                         "nargout": nargout, "arguments": _jsonable(args), "outputs": _jsonable(outputs),
                         "duration_ms": round((time.monotonic() - started) * 1000, 3)})
            if mismatch:
                item["error"] = {"type": "ExpectationMismatch", **mismatch}
        except FutureTimeout:
            item.update({"status": "dynamic_failed", "error": {"type": "TimeoutError", "message": f"case exceeded {timeout}s"}})
        except Exception as error:
            item.update({"status": "dynamic_failed", "error": {"type": type(error).__name__, "message": str(error)}})
        results.append(item)
    counts = {status: sum(1 for item in results if item.get("status") == status) for status in ("dynamic_pass", "dynamic_failed", "classified_skip", "invalid_case", "capability_limited")}
    report_dir = Path(spec["report_dir"]) if spec.get("report_dir") else root / ".matlab-agent" / "dynamic_validation"
    report_dir.mkdir(parents=True, exist_ok=True)
    completed_at = _utc_now()
    report = {"schema_version": SCHEMA_VERSION, "summary": {"total": len(results), **counts,
              "safe_registry_size": len(SAFE_FUNCTIONS)}, "cases": results,
              "backend": spec["backend"], "seed": spec["seed"],
              "safe_registry": sorted(SAFE_FUNCTIONS), "started_at": started_at, "completed_at": completed_at,
              "evidence_paths": [str(report_dir / "dynamic_validation_report.json"), str(report_dir / "dynamic_validation_report.md")]}
    (report_dir / "dynamic_validation_report.json").write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Dynamic validation report", "", f"- total: {len(results)}", *[f"- {key}: {value}" for key, value in counts.items()], "", "| # | Function | Status | Reason |", "|---:|---|---|---|"]
    lines.extend(f"| {item['index']} | {item.get('function', '')} | {item.get('status')} | {item.get('reason', '')} |" for item in results)
    (report_dir / "dynamic_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
