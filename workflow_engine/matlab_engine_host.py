import json
import io
import os
import sys
import traceback
import uuid

import matlab.engine


def normalize(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if hasattr(value, "tolist"):
        try: return normalize(value.tolist())
        except Exception: pass
    if hasattr(value, "_data"):
        try: return {"matlab_type": type(value).__name__, "size": list(value.size), "data": [normalize(item) for item in value._data]}
        except Exception: pass
    return {"matlab_type": type(value).__name__, "repr": repr(value)}


def response(command_id, *, result=None, error=None):
    payload = {"id": command_id, "ok": error is None}
    if error is None: payload["result"] = normalize(result)
    else: payload["error"] = error
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n"); sys.stdout.flush()


def main():
    engine = matlab.engine.start_matlab("-nodesktop -noFigureWindows")
    engine.cd(os.getcwd(), nargout=0)
    futures = {}
    response("startup", result={"version": engine.version(), "release": "R" + engine.eval("version('-release')", nargout=1), "session": "started"})
    try:
        for line in sys.stdin:
            if not line.strip(): continue
            request = json.loads(line); command_id = request.get("id", str(uuid.uuid4()))
            try:
                command = request["command"]
                if command == "call":
                    outputs = int(request.get("nargout", 1)); args = request.get("arguments", [])
                    result = engine.feval(request["function"], *args, nargout=outputs)
                elif command == "run_script":
                    engine.run(request["path"], nargout=0)
                    result = {"path": request["path"]}
                elif command == "run_tests":
                    path = str(request["path"]).replace("'", "''")
                    console = io.StringIO()
                    errors = io.StringIO()
                    engine.eval("agent_test_results=runtests('" + path + "');", nargout=0, stdout=console, stderr=errors)
                    result = {
                        "test_count": int(engine.eval("numel(agent_test_results)", nargout=1, stdout=console, stderr=errors)),
                        "passed": int(engine.eval("sum([agent_test_results.Passed])", nargout=1, stdout=console, stderr=errors)),
                        "failed": int(engine.eval("sum([agent_test_results.Failed])", nargout=1, stdout=console, stderr=errors)),
                        "incomplete": int(engine.eval("sum([agent_test_results.Incomplete])", nargout=1, stdout=console, stderr=errors)),
                        "console_output": console.getvalue(),
                        "console_error": errors.getvalue(),
                    }
                    engine.eval("clear agent_test_results", nargout=0, stdout=console, stderr=errors)
                elif command == "check_code":
                    path = str(request["path"]).replace("'", "''")
                    encoded = engine.eval("jsonencode(checkcode('" + path + "','-id'))", nargout=1)
                    result = json.loads(encoded)
                elif command == "start_call":
                    token = str(uuid.uuid4()); args = request.get("arguments", [])
                    futures[token] = engine.feval(request["function"], *args, nargout=int(request.get("nargout", 1)), background=True)
                    result = {"token": token}
                elif command == "cancel":
                    token = request["token"]
                    future = futures[token]; cancelled = bool(future.cancel())
                    if cancelled: futures.pop(token, None)
                    result = {"cancelled": cancelled}
                elif command == "future_result":
                    future = futures.pop(request["token"]); result = future.result(timeout=request.get("timeout"))
                elif command == "workspace_set":
                    engine.workspace[request["name"]] = request["value"]; result = {"name": request["name"]}
                elif command == "workspace_get":
                    result = engine.workspace[request["name"]]
                elif command == "toolbox_info":
                    result = engine.eval("ver", nargout=1)
                elif command == "cd":
                    engine.cd(request["path"], nargout=0)
                    result = {"path": request["path"]}
                elif command == "requirements":
                    path = str(request["path"]).replace("'", "''")
                    console = io.StringIO(); errors = io.StringIO()
                    engine.eval("[agent_req_files,agent_req_products]=matlab.codetools.requiredFilesAndProducts('" + path + "');", nargout=0, stdout=console, stderr=errors)
                    encoded = engine.eval("jsonencode(struct('files',{agent_req_files},'products',agent_req_products))", nargout=1, stdout=console, stderr=errors)
                    engine.eval("clear agent_req_files agent_req_products", nargout=0, stdout=console, stderr=errors)
                    result = json.loads(encoded)
                elif command == "eval":
                    if not request.get("allow_eval", False): raise PermissionError("eval requires allow_eval=true")
                    result = engine.eval(request["expression"], nargout=int(request.get("nargout", 0)))
                elif command == "ping":
                    result = {"version": engine.version(), "future_count": len(futures)}
                elif command == "quit":
                    response(command_id, result={"session": "closing"}); break
                else: raise ValueError(f"unsupported command: {command}")
                response(command_id, result=result)
            except Exception as error:
                response(command_id, error={"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
    finally:
        for future in futures.values():
            try: future.cancel()
            except Exception: pass
        engine.quit()


if __name__ == "__main__": main()
