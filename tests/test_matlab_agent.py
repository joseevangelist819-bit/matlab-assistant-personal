import io
import json
import unittest
from unittest.mock import Mock

from workflow_engine.matlab_agent_mcp import McpServer


class McpServerTests(unittest.TestCase):
    def test_initialize_and_tool_discovery(self):
        server = McpServer(Mock())
        initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "matlab-agent")
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertTrue({"matlab_status", "matlab_execute", "matlab_list_control_benchmarks", "matlab_run_control_benchmark", "matlab_validate_functions"}.issubset(names))

    def test_execute_tool_forwards_request(self):
        agent = Mock()
        agent.execute.return_value = {"status": "succeeded", "attempt_id": "a"}
        response = McpServer(agent).handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "matlab_execute", "arguments": {"project_root": "D:/p", "action": "run_script"}}})
        self.assertFalse(response["result"]["isError"])
        agent.execute.assert_called_once()

    def test_tool_error_is_structured(self):
        agent = Mock()
        agent.execute.side_effect = ValueError("bad request")
        response = McpServer(agent).handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "matlab_execute", "arguments": {"project_root": "D:/p", "action": "run_script"}}})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("bad request", response["result"]["content"][0]["text"])

    def test_stdio_uses_json_lines(self):
        source = io.StringIO("\ufeff" + json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"}) + "\n")
        sink = io.StringIO()
        McpServer(Mock()).serve(source, sink)
        self.assertEqual(json.loads(sink.getvalue())["id"], 5)

    def test_dynamic_validation_route(self):
        agent = Mock()
        agent.validate_functions.return_value = {"summary": {"total": 1}}
        response = McpServer(agent).handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "matlab_validate_functions", "arguments": {"project_root": "D:/p", "cases": []}}})
        self.assertFalse(response["result"]["isError"])
        agent.validate_functions.assert_called_once()

    def test_new_tool_schema_rejects_missing_and_extra_arguments(self):
        server = McpServer(Mock())
        missing = server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "matlab_validate_functions", "arguments": {"project_root": "D:/p"}}})
        extra = server.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "matlab_validate_functions", "arguments": {"project_root": "D:/p", "cases": [], "unsafe": True}}})
        self.assertTrue(missing["result"]["isError"])
        self.assertTrue(extra["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
