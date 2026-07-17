def diagnose_execution(payload):
    process = payload.get("process") or {}
    result = payload.get("result") or {}
    error = result.get("error") or process.get("error_detail") or {}
    if isinstance(error, str):
        message, identifier = error, ""
    else:
        message = str(error.get("message", ""))
        identifier = str(error.get("identifier", error.get("type", "")))
    combined = (identifier + " " + message + " " + str(process.get("error_type", ""))).lower()
    category, retryable, action, fallback = "matlab_runtime", True, "inspect_error_and_modify_code", None
    if "syntax" in combined or "parse" in combined or "语法" in combined or "表达式无效" in combined or "运算符的使用不正确" in combined:
        category, retryable, action = "syntax_error", True, "modify_code"
    elif "cancel" in combined:
        category, retryable, action = "cancelled", False, "stop"
    elif process.get("error_type") == "process_timed_out" or identifier.lower() in {"timeouterror", "timeout"}:
        category, retryable, action = "timeout", True, "increase_timeout_or_optimize"
    elif "nosupportedcompiler" in combined or "compiler" in combined and ("not" in combined or "未" in combined):
        category, retryable, action = "missing_compiler", False, "configure_supported_cpp_compiler"
    elif "license" in combined or "许可证" in combined:
        category, retryable, action = "license_unavailable", False, "check_matlab_license"
    elif "toolbox" in combined or "产品" in combined and "缺" in combined:
        category, retryable, action = "toolbox_unavailable", False, "install_or_replace_toolbox_dependency"
    elif "undefinedfunction" in combined or "unrecognized function" in combined or "无法识别" in combined:
        category, retryable, action = "missing_function", True, "fix_function_or_path"
    elif "filenotfound" in combined or "missingpath" in combined or "path not found" in combined or "文件" in combined and "不存在" in combined:
        category, retryable, action = "missing_file", True, "fix_project_path"
    elif "simulink" in combined:
        category, retryable, action = "simulink_error", True, "inspect_model_solver_and_parameters"
    elif "engine" in combined or "module not found" in combined:
        category, retryable, action, fallback = "engine_unavailable", True, "retry_with_batch", "batch"
    return {"category": category, "identifier": identifier or None, "message": message, "retryable": retryable, "recommended_action": action, "fallback_backend": fallback}
