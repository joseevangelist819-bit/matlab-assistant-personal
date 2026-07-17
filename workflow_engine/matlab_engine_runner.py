import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow_engine.matlab_engine_client import MatlabEngineClient


def main(request_path, result_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8")); params = request["parameters"]
    result = {"protocol_version":"1.0","action":request["action"],"backend":"engine","status":"failed","error":None}
    try:
        runtime = request.get("runtime", {})
        with MatlabEngineClient(request["project_root"], engine_python=sys.executable, expected_release=runtime.get("release")) as client:
            if request["action"] == "call_function":
                arguments = [item["value"] for item in params.get("arguments", [])]
                result["outputs"] = client.call(params["function"], *arguments, nargout=int(params.get("nargout",1)))
            elif request["action"] == "toolbox_info":
                result["outputs"] = client.eval("ver", nargout=1, allow_eval=True)
            else: raise ValueError(f"engine backend action not supported: {request['action']}")
            result["matlab_version"] = client.startup["version"]; result["status"] = "succeeded"
    except Exception as error:
        result["error"] = {"type":type(error).__name__,"message":str(error)}
    Path(result_path).parent.mkdir(parents=True, exist_ok=True)
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__": raise SystemExit(main(sys.argv[1], sys.argv[2]))
