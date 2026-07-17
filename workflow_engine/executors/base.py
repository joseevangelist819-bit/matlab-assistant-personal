import hashlib
import json
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from workflow_engine.errors import PolicyError


@dataclass(frozen=True)
class CapabilityReport:
    executor: str
    available: bool
    version: str | None = None
    executable: str | None = None
    features: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutorTask:
    executor: str
    action: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    timeout_seconds: int = 60
    risk_level: int = 1


@dataclass(frozen=True)
class ExecutionContext:
    root: Path
    attempt_id: str
    safe_environment: Mapping[str, str]

    def path(self, value, *, must_exist=False):
        path = Path(str(value))
        if path.is_absolute() or ".." in path.parts:
            raise PolicyError(f"unsafe_path: {value}")
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise PolicyError(f"unsafe_path: {value}")
        if must_exist and not resolved.exists():
            raise PolicyError(f"path does not exist: {value}")
        return resolved


@dataclass(frozen=True)
class PreparedExecution:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    timeout_seconds: int
    resources: tuple[tuple[str, str], ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    state: str
    exit_code: int | None
    error_type: str | None
    started_at: str
    completed_at: str
    evidence: tuple[Mapping[str, object], ...] = ()


class ExecutorAdapter(ABC):
    name = ""
    actions = frozenset()
    executables: tuple[str, ...] = ()

    def detect(self):
        executable = next((shutil.which(item) for item in self.executables if shutil.which(item)), None)
        return CapabilityReport(self.name, executable is not None, executable=executable, features=tuple(sorted(self.actions)), problems=() if executable else ("executable_not_found",))

    def validate(self, task):
        if task.action not in self.actions:
            raise PolicyError(f"unsupported_action: {self.name}.{task.action}")
        if task.timeout_seconds <= 0:
            raise PolicyError("invalid_executor_parameters: timeout_seconds")

    @abstractmethod
    def prepare(self, task, context): ...

    def collect_evidence(self, prepared, process_result):
        command_hash = hashlib.sha256(json.dumps(prepared.argv, ensure_ascii=False).encode()).hexdigest()
        return [{"type": "executor_invocation", "executor": self.name, "argv_hash": command_hash, "cwd": str(prepared.cwd), "metadata": dict(prepared.metadata), "exit_code": process_result.get("exit_code")}]

    def normalize_trace(self, trace):
        return {key: value for key, value in trace.items() if key not in {"pid", "timestamp", "started_at", "completed_at"}}
