import math
import tempfile
import unittest
from pathlib import Path

from workflow_engine.dynamic_validation import classify_function_case, normalize_validation_spec, validate_function_cases


class MockAgent:
    def execute(self, request):
        function = request["parameters"]["function"]
        args = [item["value"] for item in request["parameters"]["arguments"]]
        values = args[0] if args else None
        if function == "sum": value = sum(values)
        elif function == "mean": value = sum(values) / len(values)
        elif function == "size": value = [len(values), len(values[0])]
        elif function == "abs": value = [abs(item) for item in values]
        elif function == "min": value = min(values)
        elif function == "max": value = max(values)
        elif function == "prod": value = math.prod(values)
        elif function == "length": value = len(values)
        elif function == "numel": value = sum(len(row) for row in values) if values and isinstance(values[0], list) else len(values)
        elif function == "ndims": value = 2 if values and isinstance(values[0], list) else 2
        elif function == "cumsum":
            total = 0; value = []
            for item in values: total += item; value.append(total)
        elif function == "diff": value = [values[index + 1] - values[index] for index in range(len(values) - 1)]
        elif function == "sort": value = sorted(values)
        elif function == "unique": value = sorted(set(values))
        elif function == "trace": value = sum(values[index][index] for index in range(min(len(values), len(values[0]))))
        elif function == "det": value = values[0][0] * values[1][1] - values[0][1] * values[1][0]
        elif function == "norm": value = math.sqrt(sum(item * item for item in values))
        elif function == "strlength": value = len(values)
        elif function == "lower": value = values.lower()
        elif function == "upper": value = values.upper()
        elif function == "strcmp": value = args[0] == args[1]
        elif function == "reshape": value = [[1, 2], [3, 4]]
        else: value = values
        return {"status": "succeeded", "result": {"outputs": value}}


class FailingMockAgent(MockAgent):
    def execute(self, request):
        if request["parameters"]["function"] == "mean":
            raise RuntimeError("intentional failure")
        return super().execute(request)


class DynamicValidationTests(unittest.TestCase):
    def test_normalize_and_classify(self):
        spec = normalize_validation_spec([{"function": "sum", "fixture": "vector"}])
        self.assertEqual(spec["schema_version"], "dynamic-validation.v1")
        self.assertEqual(classify_function_case(spec["cases"][0])["status"], "safe")
        self.assertEqual(classify_function_case({"function": "plot"})["status"], "classified_skip")

    def test_batch_continues_and_summary_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_function_cases(MockAgent(), Path(tmp), [
                {"function": "sum", "fixture": "vector", "expected": 6},
                {"function": "mean", "fixture": "vector", "expected": 2},
                {"function": "plot", "fixture": "vector"},
                {"function": "size", "fixture": "matrix", "expected": {"equals": [2, 2]}},
            ], {"backend": "mock", "seed": 7})
            self.assertEqual(report["summary"]["total"], len(report["cases"]))
            self.assertEqual(report["summary"]["dynamic_pass"], 3)
            self.assertEqual(report["summary"]["classified_skip"], 1)
            self.assertTrue(Path(report["evidence_paths"][0]).is_file())
            self.assertTrue(Path(report["evidence_paths"][1]).is_file())

    def test_one_failure_does_not_abort_remaining_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_function_cases(FailingMockAgent(), tmp, [
                {"function": "mean", "fixture": "vector"},
                {"function": "sum", "fixture": "vector", "expected": 6},
            ], {"backend": "mock"})
            self.assertEqual([case["status"] for case in report["cases"]], ["dynamic_failed", "dynamic_pass"])
            self.assertEqual(report["summary"]["total"], 2)

    def test_expanded_safe_registry_and_fixtures(self):
        expected_safe = {"abs", "cumsum", "det", "diff", "length", "max", "min", "norm", "numel", "prod", "trace", "strlength", "lower", "upper", "strcmp"}
        self.assertTrue(expected_safe.issubset({name for name in expected_safe if classify_function_case({"function": name})["status"] == "safe"}))
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_function_cases(MockAgent(), tmp, [
                {"function": "abs", "fixture": "signed_vector", "expected": [3, 1, 2]},
                {"function": "cumsum", "fixture": "vector", "expected": [3, 4, 6]},
                {"function": "diff", "fixture": "vector", "expected": [-2, 1]},
                {"function": "min", "fixture": "vector", "expected": 1},
                {"function": "max", "fixture": "vector", "expected": 3},
                {"function": "prod", "fixture": "vector", "expected": 6},
                {"function": "length", "fixture": "vector", "expected": 3},
                {"function": "numel", "fixture": "matrix", "expected": 4},
                {"function": "trace", "fixture": "matrix", "expected": 5},
                {"function": "det", "fixture": "matrix", "expected": -2},
                {"function": "strlength", "fixture": "string", "expected": 5},
                {"function": "lower", "fixture": "string", "expected": "codex"},
                {"function": "upper", "fixture": "string", "expected": "CODEX"},
                {"function": "strcmp", "arguments": ["codex", "codex"], "expected": True},
            ], {"backend": "mock", "seed": 9})
            self.assertEqual(report["summary"]["dynamic_pass"], 14)
            self.assertGreaterEqual(report["summary"]["safe_registry_size"], 20)
            self.assertIn("safe_registry", report)


if __name__ == "__main__":
    unittest.main()
