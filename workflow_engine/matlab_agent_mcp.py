import json
import sys

from workflow_engine.matlab_agent import MatlabAgent


TOOLS = [
    {
        "name": "matlab_status",
        "description": "Detect MATLAB, the selected release, available interfaces, and supported actions.",
        "inputSchema": {"type": "object", "properties": {"refresh": {"type": "boolean"}}, "additionalProperties": False},
    },
    {
        "name": "matlab_execute",
        "description": "Execute a safe project-local MATLAB action and return structured results and artifacts.",
        "inputSchema": {
            "type": "object", "required": ["project_root", "action"],
            "properties": {
                "project_root": {"type": "string"}, "action": {"type": "string"},
                "parameters": {"type": "object"}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
            }, "additionalProperties": False,
        },
    },
    {"name":"matlab_task_start","description":"Start a MATLAB request asynchronously and return a task id.","inputSchema":{"type":"object","required":["project_root","action"],"properties":{"project_root":{"type":"string"},"action":{"type":"string"},"parameters":{"type":"object"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_task_status","description":"Get asynchronous MATLAB task status and result.","inputSchema":{"type":"object","required":["task_id"],"properties":{"task_id":{"type":"string"}},"additionalProperties":False}},
    {"name":"matlab_task_logs","description":"Read task stdout and stderr logs.","inputSchema":{"type":"object","required":["task_id"],"properties":{"task_id":{"type":"string"},"offset":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_task_cancel","description":"Cancel a queued or running Batch task.","inputSchema":{"type":"object","required":["task_id"],"properties":{"task_id":{"type":"string"}},"additionalProperties":False}},
    {"name":"matlab_task_retry","description":"Retry an asynchronous task using its original request.","inputSchema":{"type":"object","required":["task_id"],"properties":{"task_id":{"type":"string"}},"additionalProperties":False}},
    {"name":"matlab_run_script","description":"Run a project-local MATLAB script.","inputSchema":{"type":"object","required":["project_root","script"],"properties":{"project_root":{"type":"string"},"script":{"type":"string"},"backend":{"type":"string","enum":["auto","engine","batch"]},"export_figures":{"type":"boolean"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_call_function","description":"Call a MATLAB function with structured arguments and outputs.","inputSchema":{"type":"object","required":["project_root","function"],"properties":{"project_root":{"type":"string"},"function":{"type":"string"},"arguments":{"type":"array"},"nargout":{"type":"integer"},"backend":{"type":"string","enum":["auto","engine","batch"]},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_run_tests","description":"Run MATLAB tests in a project path.","inputSchema":{"type":"object","required":["project_root","path"],"properties":{"project_root":{"type":"string"},"path":{"type":"string"},"backend":{"type":"string","enum":["auto","engine","batch"]},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_check_code","description":"Run MATLAB code analysis for a project file.","inputSchema":{"type":"object","required":["project_root","path"],"properties":{"project_root":{"type":"string"},"path":{"type":"string"},"backend":{"type":"string","enum":["auto","engine","batch"]},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_run_simulink","description":"Run a project-local Simulink model using Batch MATLAB.","inputSchema":{"type":"object","required":["project_root","model"],"properties":{"project_root":{"type":"string"},"model":{"type":"string"},"variables":{"type":"object"},"model_parameters":{"type":"object"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_workspace_set","description":"Set a variable in the persistent MATLAB Engine workspace.","inputSchema":{"type":"object","required":["project_root","name","value"],"properties":{"project_root":{"type":"string"},"name":{"type":"string"},"value":{},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_workspace_get","description":"Get a variable from the persistent MATLAB Engine workspace.","inputSchema":{"type":"object","required":["project_root","name"],"properties":{"project_root":{"type":"string"},"name":{"type":"string"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_collect_artifacts","description":"Get collected file changes and artifacts for an asynchronous task.","inputSchema":{"type":"object","required":["task_id"],"properties":{"task_id":{"type":"string"}},"additionalProperties":False}},
    {"name":"matlab_toolbox_requirements","description":"Analyze a MATLAB project file and report required files, products, installation and license status.","inputSchema":{"type":"object","required":["project_root","path"],"properties":{"project_root":{"type":"string"},"path":{"type":"string"}},"additionalProperties":False}},
    {"name":"matlab_project_run","description":"Run a complete MATLAB project loop: dependencies, code check, execution, tests and artifact acceptance.","inputSchema":{"type":"object","required":["project_root","script"],"properties":{"project_root":{"type":"string"},"script":{"type":"string"},"test_path":{"type":"string"},"required_artifacts":{"type":"array","items":{"type":"string"}},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_compiler_status","description":"Detect selected MATLAB C/C++ compilers and Coder availability.","inputSchema":{"type":"object","required":["project_root"],"properties":{"project_root":{"type":"string"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_build_mex","description":"Compile project-local C or C++ sources into a MEX binary.","inputSchema":{"type":"object","required":["project_root","sources"],"properties":{"project_root":{"type":"string"},"sources":{"type":"array","items":{"type":"string"}},"language":{"type":"string","enum":["C","C++"]},"output_dir":{"type":"string"},"output_name":{"type":"string"},"mex_arguments":{"type":"array","items":{"type":"string"}},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_run_rapid_accelerator","description":"Build and run a project-local Simulink model in Rapid Accelerator mode.","inputSchema":{"type":"object","required":["project_root","model"],"properties":{"project_root":{"type":"string"},"model":{"type":"string"},"variables":{"type":"object"},"model_parameters":{"type":"object"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_codegen","description":"Generate and compile code from a project-local MATLAB entry-point using MATLAB Coder.","inputSchema":{"type":"object","required":["project_root","entry_point","arguments"],"properties":{"project_root":{"type":"string"},"entry_point":{"type":"string"},"arguments":{"type":"array"},"configuration":{"type":"string","enum":["mex","lib","dll","exe"]},"output_dir":{"type":"string"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_simulink_codegen","description":"Generate and compile code from a project-local Simulink model using Simulink Coder.","inputSchema":{"type":"object","required":["project_root","model"],"properties":{"project_root":{"type":"string"},"model":{"type":"string"},"system_target_file":{"type":"string"},"generate_code_only":{"type":"string","enum":["on","off"]},"output_dir":{"type":"string"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_list_control_benchmarks","description":"List the registered MATLAB control engineering benchmarks.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}},
    {"name":"matlab_run_control_benchmark","description":"Prepare and run one registered control engineering benchmark.","inputSchema":{"type":"object","required":["project_root","benchmark"],"properties":{"project_root":{"type":"string"},"benchmark":{"type":"string","enum":["pid_tracking","lqr_regulation","kalman_estimation","mpc_constraints","system_identification","robustness_sweep"]},"backend":{"type":"string","enum":["auto","engine","batch"]},"timeout_seconds":{"type":"integer","minimum":1,"maximum":900},"options":{"type":"object"}},"additionalProperties":False}},
    {"name":"matlab_validate_functions","description":"Run safe deterministic MATLAB function dynamic validation cases.","inputSchema":{"type":"object","required":["project_root","cases"],"properties":{"project_root":{"type":"string"},"cases":{"type":"array"},"backend":{"type":"string","enum":["auto","engine","batch","mock"]},"seed":{"type":"integer"},"timeout_seconds":{"type":"integer"}},"additionalProperties":False}},
    {"name":"matlab_create_simulink_model","description":"Create, configure, save, and optionally simulate a project-local basic Simulink model from a structured specification.","inputSchema":{"type":"object","required":["project_root","model","blocks"],"properties":{"project_root":{"type":"string"},"model":{"type":"string"},"blocks":{"type":"array"},"connections":{"type":"array"},"model_parameters":{"type":"object"},"variables":{"type":"object"},"simulate":{"type":"boolean"},"overwrite":{"type":"boolean"},"timeout_seconds":{"type":"integer","minimum":1,"maximum":900}},"additionalProperties":False}},
    {"name":"matlab_configure_simulink_model","description":"Apply project-local advanced Simulink configuration including buses, data dictionaries, model references, variant controls, connections, and sample times.","inputSchema":{"type":"object","required":["project_root","model"],"properties":{"project_root":{"type":"string"},"model":{"type":"string"},"data_dictionary":{"type":"object"},"buses":{"type":"array"},"model_references":{"type":"array"},"variant_controls":{"type":"array"},"sample_times":{"type":"array"},"connections":{"type":"array"},"simulate":{"type":"boolean"},"timeout_seconds":{"type":"integer","minimum":1,"maximum":900}},"additionalProperties":False}},
]
TOOL_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _validate_tool_arguments(name, arguments):
    tool = TOOL_BY_NAME.get(name)
    if tool is None:
        raise ValueError(f"unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    schema = tool["inputSchema"]
    missing = [key for key in schema.get("required", []) if key not in arguments]
    if missing:
        raise ValueError("missing required arguments: " + ", ".join(missing))
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            raise ValueError("unexpected arguments: " + ", ".join(extra))


class McpServer:
    def __init__(self, agent=None):
        self.agent = agent or MatlabAgent()

    def handle(self, message):
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "matlab-agent", "version": "0.1.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params") or {}
            name, arguments = params.get("name"), params.get("arguments") or {}
            try:
                _validate_tool_arguments(name, arguments)
                payload = self._call_tool(name, arguments)
                if payload is None:
                    raise ValueError(f"unknown tool: {name}")
                result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}], "isError": False}
            except Exception as error:
                result = {"content": [{"type": "text", "text": json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False)}], "isError": True}
        elif method and method.startswith("notifications/"):
            return None
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _request(self, arguments, action, parameters, *, backend=None):
        payload = {"project_root": arguments["project_root"], "action": action, "parameters": dict(parameters), "timeout_seconds": arguments.get("timeout_seconds", 120)}
        if backend is not None:
            payload["parameters"]["backend"] = backend
        return self.agent.execute(payload)

    def _call_tool(self, name, arguments):
        if name == "matlab_status": return self.agent.doctor(bool(arguments.get("refresh")))
        if name == "matlab_list_control_benchmarks":
            from workflow_engine.control_benchmarks import list_control_benchmarks
            return {"status": "succeeded", "benchmarks": list_control_benchmarks()}
        if name == "matlab_run_control_benchmark":
            return self.agent.run_control_benchmark(arguments)
        if name == "matlab_validate_functions": return self.agent.validate_functions(arguments)
        if name == "matlab_create_simulink_model": return self.agent.create_simulink_model(arguments)
        if name == "matlab_configure_simulink_model": return self.agent.configure_simulink_model(arguments)
        if name == "matlab_execute": return self.agent.execute(arguments)
        if name == "matlab_task_start": return self.agent.submit(arguments)
        if name == "matlab_task_status": return self.agent.task_status(arguments["task_id"])
        if name == "matlab_task_logs": return self.agent.task_logs(arguments["task_id"], arguments.get("offset", 0))
        if name == "matlab_task_cancel": return self.agent.task_cancel(arguments["task_id"])
        if name == "matlab_task_retry": return self.agent.task_retry(arguments["task_id"])
        if name == "matlab_collect_artifacts":
            status = self.agent.task_status(arguments["task_id"])
            return {"task_id": arguments["task_id"], "status": status["status"], "file_changes": (status.get("result") or {}).get("file_changes")}
        if name == "matlab_toolbox_requirements": return self.agent.requirements(arguments["project_root"], arguments["path"])
        if name == "matlab_project_run": return self.agent.run_project(arguments)
        if name == "matlab_run_script": return self._request(arguments,"run_script",{"script":arguments["script"],"export_figures":arguments.get("export_figures",False)},backend=arguments.get("backend","auto"))
        if name == "matlab_call_function": return self._request(arguments,"call_function",{"function":arguments["function"],"arguments":arguments.get("arguments",[]),"nargout":arguments.get("nargout",1)},backend=arguments.get("backend","auto"))
        if name == "matlab_run_tests": return self._request(arguments,"run_tests",{"path":arguments["path"]},backend=arguments.get("backend","auto"))
        if name == "matlab_check_code": return self._request(arguments,"check_code",{"path":arguments["path"]},backend=arguments.get("backend","auto"))
        if name == "matlab_run_simulink": return self._request(arguments,"run_simulink",{"model":arguments["model"],"variables":arguments.get("variables",{}),"model_parameters":arguments.get("model_parameters",{}),"backend":"batch"})
        if name == "matlab_workspace_set": return self._request(arguments,"workspace_set",{"name":arguments["name"],"value":arguments["value"]},backend="engine")
        if name == "matlab_workspace_get": return self._request(arguments,"workspace_get",{"name":arguments["name"]},backend="engine")
        if name == "matlab_compiler_status": return self._request(arguments,"compiler_status",{"backend":"batch"})
        if name == "matlab_build_mex": return self._request(arguments,"build_mex",{"sources":arguments["sources"],"language":arguments.get("language","C"),"output_dir":arguments.get("output_dir","build/mex"),"output_name":arguments.get("output_name",""),"mex_arguments":arguments.get("mex_arguments",[]),"backend":"batch"})
        if name == "matlab_run_rapid_accelerator": return self._request(arguments,"run_rapid_accelerator",{"model":arguments["model"],"variables":arguments.get("variables",{}),"model_parameters":arguments.get("model_parameters",{}),"backend":"batch"})
        if name == "matlab_codegen": return self._request(arguments,"matlab_codegen",{"entry_point":arguments["entry_point"],"arguments":arguments["arguments"],"configuration":arguments.get("configuration","mex"),"output_dir":arguments.get("output_dir","build/matlab_coder"),"backend":"batch"})
        if name == "matlab_simulink_codegen": return self._request(arguments,"simulink_codegen",{"model":arguments["model"],"system_target_file":arguments.get("system_target_file","grt.tlc"),"generate_code_only":arguments.get("generate_code_only","off"),"output_dir":arguments.get("output_dir","build/simulink_coder"),"backend":"batch"})
        return None

    def serve(self, input_stream=None, output_stream=None):
        source, sink = input_stream or sys.stdin, output_stream or sys.stdout
        try:
            for line in source:
                line = line.lstrip("\ufeff")
                if not line.strip():
                    continue
                try:
                    response = self.handle(json.loads(line))
                except Exception as error:
                    response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}}
                if response is not None:
                    sink.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sink.flush()
        finally:
            close = getattr(self.agent, "close", None)
            if close is not None:
                close()
