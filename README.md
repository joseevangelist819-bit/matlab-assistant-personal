# MATLAB Assistant Personal

Private source repository for a local MATLAB, Simulink, and control-engineering execution assistant. It exposes CLI and MCP interfaces so an AI client can run structured MATLAB workflows, simulations, tests, code checks, and control benchmarks.

## Repository contents

- `workflow_engine/`: Python implementation and MATLAB bridge.
- `tests/`: deterministic unit tests and MATLAB fixtures.
- `examples/`: PID, LQR, MPC, Kalman, robust-control, and system-identification examples.
- `docs/`: verified-capability and safety-boundary notes.
- `packaging/`: source archive helper.

MATLAB, MathWorks products, licenses, the bundled Python runtime, compiler toolchains, local caches, configuration backups, and generated validation evidence are intentionally not stored in this repository.

## Requirements

- Windows
- Python 3.12 or newer
- A separately installed and legally licensed MATLAB environment
- Required MathWorks toolboxes for the workflows being used

## Local development

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m pip install -e .
matlab-agent doctor --refresh
matlab-agent mcp
```

The MCP client configuration should point to the locally installed `matlab-agent` command. Do not commit account credentials, AI configuration files, MATLAB license files, or local runtime paths.

## Repository status

This repository is intended to remain private and proprietary. See `RIGHTS.md`.
