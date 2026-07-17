import json
import tempfile
import unittest
from pathlib import Path

from workflow_engine.control_benchmarks import (
    BENCHMARK_NAMES,
    list_control_benchmarks,
    load_control_benchmark_result,
    prepare_control_benchmark,
)


class ControlBenchmarkTests(unittest.TestCase):
    def test_registry_is_complete_and_stable(self):
        items = list_control_benchmarks()
        self.assertEqual([item["benchmark"] for item in items], list(BENCHMARK_NAMES))
        for item in items:
            for key in ("model", "parameters", "seed", "required_products", "metrics", "acceptance", "artifacts", "limitations"):
                self.assertIn(key, item)

    def test_prepare_stays_under_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for benchmark in BENCHMARK_NAMES:
                prepared = prepare_control_benchmark(tmp, benchmark)
                script = root / prepared["script"]
                self.assertTrue(script.is_file())
                self.assertEqual(Path(prepared["script"]).drive, "")
                self.assertIn(str(prepared["seed"]), script.read_text(encoding="utf-8"))
                self.assertEqual(load_control_benchmark_result(prepared)["status"], "needs_verification")

    def test_unknown_and_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                prepare_control_benchmark(tmp, "../../escape")
            prepared = prepare_control_benchmark(tmp, "pid_tracking")
            prepared["result"] = "../outside.json"
            with self.assertRaises(ValueError):
                load_control_benchmark_result(prepared)

    def test_loads_structured_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = prepare_control_benchmark(tmp, "kalman_estimation")
            result_path = Path(tmp) / prepared["result"]
            result_path.write_text(json.dumps({"status": "succeeded", "metrics": {"estimate_rmse": 0.1}}), encoding="utf-8")
            loaded = load_control_benchmark_result(prepared)
            self.assertEqual(loaded["benchmark"], "kalman_estimation")
            self.assertEqual(loaded["status"], "succeeded")
            self.assertEqual(loaded["metrics"]["estimate_rmse"], 0.1)


if __name__ == "__main__":
    unittest.main()
