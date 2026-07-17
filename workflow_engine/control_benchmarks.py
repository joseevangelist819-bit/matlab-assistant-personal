"""Deterministic control-engineering benchmark registry and MATLAB asset runner.

The module is intentionally independent from MatlabAgent.  It creates a complete,
self-contained benchmark folder below the caller supplied ``project_root`` and
optionally executes the generated MATLAB batch script.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "control-benchmarks.v1"
BENCHMARK_NAMES = (
    "pid_tracking",
    "lqr_regulation",
    "kalman_estimation",
    "mpc_constraints",
    "system_identification",
    "robustness_sweep",
)


def _spec(name: str, model: dict, parameters: dict, seed: int, products: list[str],
          metrics: dict, acceptance: dict, artifacts: list[str], limitations: list[str],
          script_kind: str) -> dict:
    return {
        "benchmark": name,
        "model": model,
        "parameters": parameters,
        "seed": seed,
        "required_products": products,
        "metrics": metrics,
        "acceptance": acceptance,
        "artifacts": artifacts,
        "limitations": limitations,
        "script_kind": script_kind,
    }


_REGISTRY = {
    "pid_tracking": _spec(
        "pid_tracking", {"type": "second_order", "transfer_function": "1/(s^2+2s+1)"},
        {"reference": 1.0, "duration": 8.0, "sample_time": 0.01}, 101,
        ["MATLAB", "Control System Toolbox"],
        {"overshoot_percent": "<= 25", "settling_time_seconds": "<= 6", "steady_state_error": "<= 0.05"},
        {"stable": True, "overshoot_percent_max": 25.0, "settling_time_seconds_max": 6.0, "steady_state_error_max": 0.05},
        ["control_benchmarks/pid_tracking/results/pid_tracking/result.json", "control_benchmarks/pid_tracking/results/pid_tracking/response.png", "control_benchmarks/pid_tracking/results/pid_tracking/response.mat"],
        ["Uses a fixed unit-step reference and a nominal second-order plant."], "pid",
    ),
    "lqr_regulation": _spec(
        "lqr_regulation", {"type": "state_space", "A": [[0, 1], [-2, -0.5]], "B": [[0], [1]], "C": [[1, 0]], "D": [[0]]},
        {"Q": [[10, 0], [0, 1]], "R": [[0.5]], "duration": 6.0, "sample_time": 0.01}, 202,
        ["MATLAB", "Control System Toolbox"],
        {"closed_loop_stable": True, "final_state_norm": "<= 0.05", "peak_control": "<= 10"},
        {"closed_loop_stable": True, "final_state_norm_max": 0.05, "peak_control_max": 10.0},
        ["control_benchmarks/lqr_regulation/results/lqr_regulation/result.json", "control_benchmarks/lqr_regulation/results/lqr_regulation/regulation.png", "control_benchmarks/lqr_regulation/results/lqr_regulation/regulation.mat"],
        ["Full-state feedback is assumed; no actuator saturation is simulated."], "lqr",
    ),
    "kalman_estimation": _spec(
        "kalman_estimation", {"type": "discrete_state_space", "A": [[1, 0.1], [0, 1]], "B": [[0], [0.1]], "C": [[1, 0]], "Ts": 0.1},
        {"process_noise_covariance": [[0.0025, 0], [0, 0.0025]], "measurement_noise_variance": 0.04, "samples": 120}, 303,
        ["MATLAB"],
        {"estimate_rmse_comparison": "< measurement_rmse", "estimate_rmse": "<= 0.5"},
        {"estimate_rmse_below_measurement_rmse": True, "estimate_rmse_max": 0.5},
        ["control_benchmarks/kalman_estimation/results/kalman_estimation/result.json", "control_benchmarks/kalman_estimation/results/kalman_estimation/estimation.png", "control_benchmarks/kalman_estimation/results/kalman_estimation/estimation.mat"],
        ["A base-MATLAB covariance-form Kalman filter is used so the benchmark remains runnable without Control System Toolbox."], "kalman",
    ),
    "mpc_constraints": _spec(
        "mpc_constraints", {"type": "discrete_state_space", "A": [[1, 0.1], [0, 1]], "B": [[0], [0.1]], "Ts": 0.1},
        {"prediction_horizon": 10, "control_horizon": 3, "input_bounds": [-1, 1], "output_bounds": [-2, 2]}, 404,
        ["MATLAB", "MPC Toolbox"],
        {"feasible_fraction": ">= 0.95", "max_input_violation": "<= 1e-9"},
        {"feasible_fraction_min": 0.95, "max_input_violation_max": 1e-9},
        ["control_benchmarks/mpc_constraints/results/mpc_constraints/result.json", "control_benchmarks/mpc_constraints/results/mpc_constraints/closed_loop.png", "control_benchmarks/mpc_constraints/results/mpc_constraints/closed_loop.mat"],
        ["Requires MPC Toolbox and a valid license; execution failures must be reported rather than converted to success."], "mpc",
    ),
    "system_identification": _spec(
        "system_identification", {"type": "first_order_discrete", "A": [[0.92]], "B": [[0.08]], "C": [[1]], "D": [[0]], "Ts": 0.1},
        {"samples": 200, "train_fraction": 0.7, "input_amplitude": 1.0}, 505,
        ["MATLAB", "System Identification Toolbox"],
        {"validation_rmse": "<= 0.2", "fit_percent": ">= 70"},
        {"validation_rmse_max": 0.2, "fit_percent_min": 70.0},
        ["control_benchmarks/system_identification/results/system_identification/result.json", "control_benchmarks/system_identification/results/system_identification/identification.png", "control_benchmarks/system_identification/results/system_identification/data.mat"],
        ["Requires System Identification Toolbox and a valid license; no success is claimed without a real estimate and validation run."], "identification",
    ),
    "robustness_sweep": _spec(
        "robustness_sweep", {"type": "second_order_parameter_grid", "nominal": "1/(s^2+2s+1)"},
        {"damping_values": [0.8, 1.0, 1.2], "gain_values": [0.8, 1.0, 1.2], "duration": 8.0, "sample_time": 0.01}, 606,
        ["MATLAB", "Control System Toolbox"],
        {"stable_fraction": ">= 1", "worst_overshoot_percent": "<= 35"},
        {"stable_fraction_min": 1.0, "worst_overshoot_percent_max": 35.0},
        ["control_benchmarks/robustness_sweep/results/robustness_sweep/result.json", "control_benchmarks/robustness_sweep/results/robustness_sweep/sweep.png", "control_benchmarks/robustness_sweep/results/robustness_sweep/sweep.mat"],
        ["A fixed 3x3 damping/gain grid is used; unmodelled nonlinearities are out of scope."], "robustness",
    ),
}


def list_control_benchmarks() -> list[dict]:
    """Return a deep-copy-like JSON-safe list of the six frozen benchmark specs."""
    return json.loads(json.dumps(list(_REGISTRY.values())))


def _safe_root(project_root: os.PathLike[str] | str) -> Path:
    root = Path(project_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError(f"project_root is not a directory: {root}")
    return root


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"generated path escapes project_root: {path}") from exc


def _matlab_quote(value: str) -> str:
    return value.replace("'", "''")


def _script_for(spec: dict) -> str:
    kind = spec["script_kind"]
    common = f"% Auto-generated {spec['benchmark']} benchmark; deterministic seed {spec['seed']}\n"
    common += f"scriptDir = fileparts(mfilename('fullpath')); outDir = fullfile(scriptDir,'results','{spec['benchmark']}'); resultPath = fullfile(outDir,'result.json'); if ~isfolder(outDir), mkdir(outDir); end\n"
    common += f"rng({spec['seed']}, 'twister'); started = datetime('now','TimeZone','UTC');\n"
    if kind == "pid":
        body = """s = tf('s'); plant = 1/(s^2 + 2*s + 1); controller = pidtune(plant, 'PID'); closed = feedback(controller*plant, 1); t = (0:0.01:8)'; [y,t] = step(closed,t); info = stepinfo(y,t,1); ess = abs(1-y(end)); stable = all(real(pole(closed)) < 0); metrics = struct('overshoot_percent',info.Overshoot,'settling_time_seconds',info.SettlingTime,'steady_state_error',ess,'stable',stable); status = 'succeeded'; limitations={}; save(fullfile(outDir,'response.mat'),'t','y','metrics'); f=figure('Visible','off'); plot(t,y,'LineWidth',1.2); grid on; xlabel('Time (s)'); ylabel('Output'); title('PID tracking'); saveas(f,fullfile(outDir,'response.png')); close(f);"""
    elif kind == "lqr":
        body = """A=[0 1;-2 -0.5]; B=[0;1]; C=[1 0]; D=0; Q=diag([10 1]); R=0.5; controllability_rank=rank(ctrb(A,B)); K=lqr(A,B,Q,R); Acl=A-B*K; t=(0:0.01:6)'; x0=[1;0]; [~,x]=ode45(@(tt,xx) Acl*xx,t,x0); u=-(K*x')'; final_state_norm=norm(x(end,:)); peak_control=max(abs(u)); poles=eig(Acl); stable=all(real(poles)<0) && controllability_rank==2; metrics=struct('closed_loop_stable',stable,'final_state_norm',final_state_norm,'peak_control',peak_control,'closed_loop_poles_real',real(poles)); status='succeeded'; limitations={}; save(fullfile(outDir,'regulation.mat'),'t','x','u','K','metrics'); f=figure('Visible','off'); plot(t,x,'LineWidth',1.2); grid on; xlabel('Time (s)'); ylabel('State'); legend('x_1','x_2'); title('LQR regulation'); saveas(f,fullfile(outDir,'regulation.png')); close(f);"""
    elif kind == "kalman":
        body = """A=[1 0.1;0 1]; C=[1 0]; Q=[0.0025 0;0 0.0025]; R=0.04; N=120; Ts=0.1; x=zeros(2,N); xhat=zeros(2,N); z=zeros(1,N); P=eye(2); Lq=chol(Q,'lower'); for k=2:N, x(:,k)=A*x(:,k-1)+Lq*randn(2,1); z(k)=C*x(:,k)+sqrt(R)*randn; Pm=A*P*A'+Q; Kg=Pm*C'/(C*Pm*C'+R); xhat(:,k)=A*xhat(:,k-1)+Kg*(z(k)-C*A*xhat(:,k-1)); P=(eye(2)-Kg*C)*Pm; end; measurement_rmse=sqrt(mean((z-C*x).^2)); estimate_rmse=sqrt(mean((xhat(1,:)-x(1,:)).^2)); metrics=struct('estimate_rmse',estimate_rmse,'measurement_rmse',measurement_rmse,'estimate_rmse_below_measurement_rmse',estimate_rmse<measurement_rmse); status='succeeded'; limitations={}; t=(0:N-1)'*Ts; save(fullfile(outDir,'estimation.mat'),'t','x','xhat','z','metrics'); f=figure('Visible','off'); plot(t,x(1,:),t,z,t,xhat(1,:),'LineWidth',1.0); grid on; legend('True','Measured','Estimated'); xlabel('Time (s)'); title('Kalman estimation'); saveas(f,fullfile(outDir,'estimation.png')); close(f);"""
    elif kind == "robustness":
        body = """damping=[0.8 1.0 1.2]; gain=[0.8 1.0 1.2]; overs=zeros(numel(damping),numel(gain)); stableMask=false(size(overs)); t=(0:0.01:8)'; for i=1:numel(damping), for j=1:numel(gain), den=[1 2*damping(i) gain(j)]; [y,~]=step(tf(gain(j),den),t); info=stepinfo(y,t,1); overs(i,j)=info.Overshoot; stableMask(i,j)=all(real(roots(den))<0); end, end; metrics=struct('stable_fraction',mean(stableMask(:)),'worst_overshoot_percent',max(overs(:)),'stable_cases',sum(stableMask(:)),'total_cases',numel(stableMask)); status='succeeded'; limitations={}; save(fullfile(outDir,'sweep.mat'),'damping','gain','overs','stableMask','metrics'); f=figure('Visible','off'); imagesc(gain,damping,overs); colorbar; xlabel('Gain'); ylabel('Damping'); title('Robustness overshoot sweep'); saveas(f,fullfile(outDir,'sweep.png')); close(f);"""
    elif kind == "mpc":
        body = """if ~license('test','MPC_Toolbox')
metrics=struct('feasible_fraction',NaN,'max_input_violation',NaN); status='capability_limited'; limitations={'MPC Toolbox license unavailable; benchmark not executed'};
else
Ts=0.1; A=[1 Ts;0 1]; B=[0;Ts]; C=[1 0]; D=0; plant=ss(A,B,C,D,Ts); controller=mpc(plant,Ts,10,3); controller.MV.Min=-1; controller.MV.Max=1; controller.OV.Min=-2; controller.OV.Max=2; controller.Weights.ManipulatedVariablesRate=0.1; controller.Weights.OutputVariables=1; xc=mpcstate(controller); N=60; x=zeros(2,N+1); y=zeros(N,1); u=zeros(N,1); feasible=false(N,1); reference=ones(N,1); for k=1:N, y(k)=C*x(:,k); [u(k),info]=mpcmove(controller,xc,y(k),reference(k)); feasible(k)=strcmp(info.QPCode,'feasible'); x(:,k+1)=A*x(:,k)+B*u(k); end; inputViolation=max([max(u-1),max(-1-u),0]); outputViolation=max([max(y-2),max(-2-y),0]); metrics=struct('feasible_fraction',mean(feasible),'max_input_violation',inputViolation,'max_output_violation',outputViolation,'peak_input',max(abs(u))); status='succeeded'; limitations={}; t=(0:N-1)'*Ts; save(fullfile(outDir,'closed_loop.mat'),'t','x','y','u','reference','metrics'); f=figure('Visible','off'); tiledlayout(2,1); nexttile; plot(t,y,t,reference,'--','LineWidth',1.1); grid on; ylabel('Output'); legend('y','reference'); nexttile; stairs(t,u,'LineWidth',1.1); grid on; xlabel('Time (s)'); ylabel('Input'); ylim([-1.1 1.1]); saveas(f,fullfile(outDir,'closed_loop.png')); close(f);
end"""
    else:
        body = """if ~license('test','Identification_Toolbox')
metrics=struct('validation_rmse',NaN,'fit_percent',NaN); status='capability_limited'; limitations={'System Identification Toolbox license unavailable; benchmark not executed'};
else
Ts=0.1; N=200; u=2*(rand(N,1)>0.5)-1; y=zeros(N,1); noiseStd=0.02; for k=2:N, y(k)=0.92*y(k-1)+0.08*u(k-1)+noiseStd*randn; end; split=140; train=iddata(y(1:split),u(1:split),Ts); validation=iddata(y(split+1:end),u(split+1:end),Ts); model=arx(train,[1 1 1]); [predicted,fit]=compare(validation,model); yhat=predicted.OutputData; yval=validation.OutputData; validation_rmse=sqrt(mean((yhat-yval).^2)); fit_percent=fit(1); metrics=struct('validation_rmse',validation_rmse,'fit_percent',fit_percent,'estimated_a',model.A(2),'estimated_b',model.B(2)); status='succeeded'; limitations={}; t=(0:numel(yval)-1)'*Ts; save(fullfile(outDir,'data.mat'),'u','y','train','validation','model','predicted','metrics'); f=figure('Visible','off'); plot(t,yval,t,yhat,'--','LineWidth',1.1); grid on; xlabel('Validation time (s)'); ylabel('Output'); legend('Measured','ARX'); title('System identification validation'); saveas(f,fullfile(outDir,'identification.png')); close(f);
end"""
    products_json = json.dumps(spec["required_products"]).replace("'", "''")
    parameters_json = json.dumps(spec["parameters"]).replace("'", "''")
    acceptance_json = json.dumps(spec["acceptance"]).replace("'", "''")
    artifacts_json = json.dumps(spec["artifacts"]).replace("'", "''")
    tail = f"""requiredProducts=jsondecode('{products_json}'); parameters=jsondecode('{parameters_json}'); acceptance=jsondecode('{acceptance_json}'); artifactList=jsondecode('{artifacts_json}'); result=struct(); result.schema_version='control-benchmarks.v1'; result.benchmark='{spec['benchmark']}'; result.status=status; result.required_products=requiredProducts; result.parameters=parameters; result.seed={spec['seed']}; result.metrics=metrics; result.acceptance=acceptance; result.artifacts=artifactList; result.limitations=limitations; result.started_at=char(started); result.completed_at=char(datetime('now','TimeZone','UTC')); fid=fopen(resultPath,'w'); fprintf(fid,'%s',jsonencode(result)); fclose(fid);\n"""
    return common + body + "\n" + tail


def prepare_control_benchmark(project_root, benchmark, options=None) -> dict:
    options = dict(options or {})
    root = _safe_root(project_root)
    if benchmark not in _REGISTRY:
        raise ValueError(f"unknown control benchmark: {benchmark}")
    spec = json.loads(json.dumps(_REGISTRY[benchmark]))
    bench_dir = root / "control_benchmarks" / benchmark
    result_dir = bench_dir / "results" / benchmark
    script_path = bench_dir / f"run_{benchmark}.m"
    for path in (bench_dir, result_dir, script_path):
        _relative_path(root, path)
    result_dir.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_script_for(spec), encoding="utf-8")
    prepared = {"schema_version": SCHEMA_VERSION, **spec, "project_root": str(root), "script": _relative_path(root, script_path), "result": _relative_path(root, result_dir / "result.json"), "prepared_at": datetime.now(timezone.utc).isoformat()}
    manifest_path = bench_dir / "benchmark.json"
    manifest_path.write_text(json.dumps(prepared, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if options.get("execute"):
        result_path = root / prepared["result"]
        if result_path.is_file():
            result_path.unlink()
        _run_batch(root, script_path, int(options.get("timeout_seconds", 180)))
        prepared["execution"] = load_control_benchmark_result(prepared)
    return prepared


def _run_batch(root: Path, script_path: Path, timeout: int) -> None:
    matlab = os.environ.get("MATLAB_EXECUTABLE") or "matlab"
    command = f"run('{_matlab_quote(str(script_path))}')"
    completed = subprocess.run([matlab, "-batch", command], cwd=root, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    if completed.returncode:
        raise RuntimeError(f"MATLAB batch failed ({completed.returncode}): {completed.stderr[-2000:]}")


def load_control_benchmark_result(prepared) -> dict:
    root = _safe_root(prepared["project_root"])
    result_path = (root / prepared["result"]).resolve()
    _relative_path(root, result_path)
    if not result_path.is_file():
        return {"benchmark": prepared["benchmark"], "status": "needs_verification", "required_products": prepared["required_products"], "parameters": prepared["parameters"], "metrics": {}, "acceptance": prepared["acceptance"], "artifacts": [], "limitations": ["Result has not been generated; execute the MATLAB script."], "result_path": prepared["result"]}
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload.setdefault("benchmark", prepared["benchmark"])
    payload.setdefault("required_products", prepared["required_products"])
    payload.setdefault("parameters", prepared["parameters"])
    payload.setdefault("acceptance", prepared["acceptance"])
    payload.setdefault("artifacts", [])
    payload.setdefault("limitations", prepared.get("limitations", []))
    payload["result_path"] = prepared["result"]
    return payload
