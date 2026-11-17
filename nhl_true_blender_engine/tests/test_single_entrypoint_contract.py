"""Regression: old daily CLI must never independently choose or publish scorers."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SingleEntrypointContract(unittest.TestCase):
    def test_daily_runner_delegates_to_integrated_engine(self):
        tree = ast.parse((ROOT / "run_daily.py").read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertIn("run", imports)
        forbidden = {"run_slate", "execute_gate_matrix", "publish_verified_core"}
        self.assertFalse(imports & forbidden, imports & forbidden)
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(calls & forbidden)
        self.assertTrue(any(
            isinstance(node, ast.ImportFrom)
            and node.module == "run_true_blender"
            and any(alias.name == "run" for alias in node.names)
            for node in ast.walk(tree)
        ))

    def test_workflow_uses_integrated_entrypoint(self):
        workflow = (ROOT / ".github/workflows/nhl-true-blender.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("'run_true_blender.py'", workflow)
        self.assertNotIn("python run_daily.py", workflow)


if __name__ == "__main__":
    unittest.main()
