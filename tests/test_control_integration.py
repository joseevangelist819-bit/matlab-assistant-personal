import unittest
from unittest.mock import Mock, patch

from workflow_engine.matlab_agent import MatlabAgent
from workflow_engine.matlab_agent_mcp import McpServer


class ControlIntegrationTests(unittest.TestCase):
    @patch("workflow_engine.control_benchmarks.load_control_benchmark_result")
    @patch("workflow_engine.control_benchmarks.prepare_control_benchmark")
    def test_agent_runs_prepared_benchmark_through_existing_executor(self, prepare, load):
        prepare.return_value = {"script": "bench/run_pid.m", "required_products": ["MATLAB"], "parameters": {}, "acceptance": {}}
        load.return_value = {"benchmark": "pid_tracking", "status": "succeeded"}
        agent = MatlabAgent.__new__(MatlabAgent)
        agent.execute = Mock(return_value={"status": "succeeded", "attempt_id": "a"})
        result = agent.run_control_benchmark({"project_root": "D:/p", "benchmark": "pid_tracking", "backend": "batch"})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["execution"]["attempt_id"], "a")
        self.assertEqual(agent.execute.call_args.args[0]["action"], "run_script")

    def test_mcp_lists_and_routes_control_benchmarks(self):
        agent = Mock()
        agent.run_control_benchmark.return_value = {"benchmark": "pid_tracking", "status": "succeeded"}
        server = McpServer(agent)
        listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "matlab_list_control_benchmarks", "arguments": {}}})
        run = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "matlab_run_control_benchmark", "arguments": {"project_root": "D:/p", "benchmark": "pid_tracking"}}})
        self.assertFalse(listed["result"]["isError"])
        self.assertFalse(run["result"]["isError"])
        agent.run_control_benchmark.assert_called_once()


if __name__ == "__main__":
    unittest.main()
