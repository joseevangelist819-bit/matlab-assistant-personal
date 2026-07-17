from __future__ import annotations

import re
from pathlib import PurePath, PureWindowsPath


SAFE_BASIC_BLOCKS = frozenset({
    "simulink/Continuous/Integrator",
    "simulink/Continuous/State-Space",
    "simulink/Continuous/Transfer Fcn",
    "simulink/Discrete/Unit Delay",
    "simulink/Math Operations/Gain",
    "simulink/Math Operations/Sum",
    "simulink/Ports & Subsystems/In1",
    "simulink/Ports & Subsystems/Out1",
    "simulink/Signal Routing/Demux",
    "simulink/Signal Routing/Mux",
    "simulink/Sinks/Display",
    "simulink/Sinks/Scope",
    "simulink/Sinks/To Workspace",
    "simulink/Sources/Constant",
    "simulink/Sources/Sine Wave",
    "simulink/Sources/Step",
    "simulink/Discontinuities/Saturation",
})


def _relative_path(value: str, field: str) -> str:
    value = str(value).strip().replace("\\", "/")
    if not value or PurePath(value).is_absolute() or PureWindowsPath(value).is_absolute() or ".." in PurePath(value).parts:
        raise ValueError(f"{field} must be a project-relative path")
    return value


def _identifier(value: str, field: str) -> str:
    value = str(value).strip()
    if not re.fullmatch(r"[A-Za-z]\w*", value):
        raise ValueError(f"{field} must be a MATLAB identifier")
    return value


def normalize_basic_model_spec(specification):
    if not isinstance(specification, dict):
        raise ValueError("specification must be a JSON object")
    project_root = specification.get("project_root")
    if not project_root:
        raise ValueError("project_root is required")
    model = _relative_path(specification.get("model", ""), "model")
    stem = PurePath(model).stem
    _identifier(stem, "model name")
    raw_blocks = specification.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("blocks must be a non-empty list")
    blocks = []
    seen = set()
    for index, raw in enumerate(raw_blocks):
        if not isinstance(raw, dict):
            raise ValueError(f"blocks[{index}] must be an object")
        library = str(raw.get("library", "")).strip()
        if library not in SAFE_BASIC_BLOCKS:
            raise ValueError(f"blocks[{index}].library is not in the safe basic registry")
        name = _identifier(raw.get("name", ""), f"blocks[{index}].name")
        if name in seen:
            raise ValueError(f"duplicate block name: {name}")
        seen.add(name)
        position = raw.get("position")
        if position is not None and (not isinstance(position, list) or len(position) != 4 or not all(isinstance(item, (int, float)) for item in position)):
            raise ValueError(f"blocks[{index}].position must contain four numbers")
        parameters = raw.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError(f"blocks[{index}].parameters must be an object")
        blocks.append({"library": library, "name": name, "position": position, "parameters": parameters})
    connections = []
    for index, raw in enumerate(specification.get("connections") or []):
        if not isinstance(raw, dict) or not raw.get("src") or not raw.get("dst"):
            raise ValueError(f"connections[{index}] requires src and dst")
        connections.append({"src": str(raw["src"]), "dst": str(raw["dst"])})
    model_parameters = specification.get("model_parameters") or {}
    variables = specification.get("variables") or {}
    if not isinstance(model_parameters, dict) or not isinstance(variables, dict):
        raise ValueError("model_parameters and variables must be objects")
    return {
        "project_root": str(project_root),
        "model": model,
        "blocks": blocks,
        "connections": connections,
        "model_parameters": model_parameters,
        "variables": variables,
        "simulate": bool(specification.get("simulate", False)),
        "overwrite": bool(specification.get("overwrite", False)),
        "timeout_seconds": int(specification.get("timeout_seconds", 180)),
    }


def normalize_advanced_model_spec(specification):
    if not isinstance(specification, dict):
        raise ValueError("specification must be a JSON object")
    project_root = specification.get("project_root")
    if not project_root:
        raise ValueError("project_root is required")
    model = _relative_path(specification.get("model", ""), "model")
    _identifier(PurePath(model).stem, "model name")
    data_dictionary = specification.get("data_dictionary")
    if data_dictionary is not None:
        if not isinstance(data_dictionary, dict):
            raise ValueError("data_dictionary must be an object")
        data_dictionary = {
            "path": _relative_path(data_dictionary.get("path", ""), "data_dictionary.path"),
            "entries": dict(data_dictionary.get("entries") or {}),
        }
        if not data_dictionary["path"].lower().endswith(".sldd"):
            raise ValueError("data_dictionary.path must end with .sldd")
        for name in data_dictionary["entries"]:
            _identifier(name, "data_dictionary entry")
    buses = []
    for bus_index, raw in enumerate(specification.get("buses") or []):
        if not isinstance(raw, dict):
            raise ValueError(f"buses[{bus_index}] must be an object")
        name = _identifier(raw.get("name", ""), f"buses[{bus_index}].name")
        elements = []
        for element_index, element in enumerate(raw.get("elements") or []):
            if not isinstance(element, dict):
                raise ValueError(f"buses[{bus_index}].elements[{element_index}] must be an object")
            elements.append({
                "name": _identifier(element.get("name", ""), "bus element name"),
                "data_type": str(element.get("data_type", "double")),
                "dimensions": element.get("dimensions", [1]),
            })
        if not elements:
            raise ValueError(f"buses[{bus_index}] requires elements")
        buses.append({"name": name, "elements": elements})
    model_references = []
    for index, raw in enumerate(specification.get("model_references") or []):
        if not isinstance(raw, dict):
            raise ValueError(f"model_references[{index}] must be an object")
        position = raw.get("position")
        if position is not None and (not isinstance(position, list) or len(position) != 4):
            raise ValueError(f"model_references[{index}].position must contain four numbers")
        model_references.append({
            "name": _identifier(raw.get("name", ""), f"model_references[{index}].name"),
            "model": _relative_path(raw.get("model", ""), f"model_references[{index}].model"),
            "position": position,
            "parameters": dict(raw.get("parameters") or {}),
        })
    variant_controls = []
    for index, raw in enumerate(specification.get("variant_controls") or []):
        if not isinstance(raw, dict):
            raise ValueError(f"variant_controls[{index}] must be an object")
        condition = str(raw.get("condition", "")).strip()
        if not condition or len(condition) > 200 or not re.fullmatch(r"[A-Za-z0-9_ <>=&|~().+\-*/]+", condition):
            raise ValueError(f"variant_controls[{index}].condition is unsafe")
        variant_controls.append({
            "name": _identifier(raw.get("name", ""), f"variant_controls[{index}].name"),
            "condition": condition,
        })
    sample_times = []
    for index, raw in enumerate(specification.get("sample_times") or []):
        if not isinstance(raw, dict) or not raw.get("block"):
            raise ValueError(f"sample_times[{index}] requires block")
        block = str(raw["block"]).replace("\\", "/").strip("/")
        if ".." in PurePath(block).parts:
            raise ValueError(f"sample_times[{index}].block is unsafe")
        sample_times.append({"block": block, "sample_time": raw.get("sample_time")})
    connections = []
    for index, raw in enumerate(specification.get("connections") or []):
        if not isinstance(raw, dict) or not raw.get("src") or not raw.get("dst"):
            raise ValueError(f"connections[{index}] requires src and dst")
        connections.append({"src": str(raw["src"]), "dst": str(raw["dst"])})
    return {
        "project_root": str(project_root),
        "model": model,
        "data_dictionary": data_dictionary,
        "buses": buses,
        "model_references": model_references,
        "variant_controls": variant_controls,
        "sample_times": sample_times,
        "connections": connections,
        "simulate": bool(specification.get("simulate", False)),
        "timeout_seconds": int(specification.get("timeout_seconds", 300)),
    }
