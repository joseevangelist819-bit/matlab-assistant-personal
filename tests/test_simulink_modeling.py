import unittest
from unittest.mock import Mock

from workflow_engine.matlab_agent import MatlabAgent
from workflow_engine.matlab_agent_mcp import McpServer
from workflow_engine.simulink_modeling import normalize_advanced_model_spec, normalize_basic_model_spec


SPEC = {
    "project_root": "D:/project",
    "model": "models/basic_gain.slx",
    "blocks": [
        {"library": "simulink/Sources/Constant", "name": "Input", "position": [30, 50, 60, 80], "parameters": {"Value": "2"}},
        {"library": "simulink/Math Operations/Gain", "name": "Gain", "parameters": {"Gain": "3"}},
    ],
    "connections": [{"src": "Input/1", "dst": "Gain/1"}],
    "model_parameters": {"StopTime": "1"},
    "simulate": True,
}


class SimulinkModelingTests(unittest.TestCase):
    def test_normalizes_safe_basic_spec(self):
        spec = normalize_basic_model_spec(SPEC)
        self.assertEqual(spec["model"], "models/basic_gain.slx")
        self.assertEqual(len(spec["blocks"]), 2)
        self.assertTrue(spec["simulate"])

    def test_rejects_unsafe_library_and_path(self):
        unsafe = {**SPEC, "model": "../outside.slx"}
        with self.assertRaises(ValueError): normalize_basic_model_spec(unsafe)
        unsafe = {**SPEC, "blocks": [{"library": "built-in/MATLABSystem", "name": "Unsafe"}]}
        with self.assertRaises(ValueError): normalize_basic_model_spec(unsafe)

    def test_agent_routes_basic_model_through_batch_action(self):
        agent = MatlabAgent.__new__(MatlabAgent)
        agent.execute = Mock(return_value={"status": "succeeded"})
        result = agent.create_simulink_model(SPEC)
        self.assertEqual(result["status"], "succeeded")
        request = agent.execute.call_args.args[0]
        self.assertEqual(request["action"], "create_simulink_model")
        self.assertEqual(request["parameters"]["backend"], "batch")

    def test_mcp_discovers_and_routes_basic_model_tool(self):
        agent = Mock()
        agent.create_simulink_model.return_value = {"status": "succeeded"}
        server = McpServer(agent)
        listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertIn("matlab_create_simulink_model", {tool["name"] for tool in listed["result"]["tools"]})
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "matlab_create_simulink_model", "arguments": SPEC}})
        self.assertFalse(response["result"]["isError"])
        agent.create_simulink_model.assert_called_once()

    def test_normalizes_advanced_spec(self):
        spec = normalize_advanced_model_spec({
            "project_root": "D:/project",
            "model": "models/parent.slx",
            "data_dictionary": {"path": "data/design.sldd", "entries": {"VariantMode": 1}},
            "buses": [{"name": "ControlBus", "elements": [{"name": "command"}, {"name": "measurement", "dimensions": [2]}]}],
            "model_references": [{"name": "Plant", "model": "models/plant.slx"}],
            "variant_controls": [{"name": "ChoiceA", "condition": "VariantMode == 1"}],
            "sample_times": [{"block": "InputFast", "sample_time": 0.1}],
        })
        self.assertEqual(spec["data_dictionary"]["path"], "data/design.sldd")
        self.assertEqual(spec["buses"][0]["elements"][1]["dimensions"], [2])

    def test_advanced_spec_rejects_unsafe_condition(self):
        with self.assertRaises(ValueError):
            normalize_advanced_model_spec({"project_root": "D:/p", "model": "m.slx", "variant_controls": [{"name": "Choice", "condition": "system('bad')"}]})

    def test_agent_and_mcp_route_advanced_model_tool(self):
        spec = {"project_root": "D:/project", "model": "models/parent.slx"}
        agent = MatlabAgent.__new__(MatlabAgent)
        agent.execute = Mock(return_value={"status": "succeeded"})
        agent.configure_simulink_model(spec)
        self.assertEqual(agent.execute.call_args.args[0]["action"], "configure_simulink_model")
        mcp_agent = Mock()
        mcp_agent.configure_simulink_model.return_value = {"status": "succeeded"}
        server = McpServer(mcp_agent)
        listed = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        self.assertIn("matlab_configure_simulink_model", {tool["name"] for tool in listed["result"]["tools"]})
        response = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "matlab_configure_simulink_model", "arguments": spec}})
        self.assertFalse(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
