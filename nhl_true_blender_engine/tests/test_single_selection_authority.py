"""Regression checks: only the integrated engine may select the Core.

These tests intentionally inspect the public CLI and scorer execution boundary
rather than accepting a dashboard PASS label as proof of execution.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_cli_delegates_without_independent_selection():
    source = (ROOT / "run_daily.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {alias.name for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert "run_slate" not in imports
    assert "execute_gate_matrix" not in imports
    assert "publish_verified_core" not in imports
    assert "run_true_blender.py" in source
    assert "subprocess.run" in source
    assert "check=True" in source


def test_postgame_audit_cannot_veto_scorer_selection():
    source = (ROOT / "nhl_true_blender_engine" / "engine.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    execute = next(node for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == "execute")
    calls = {node.func.id for node in ast.walk(execute)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "apply_active_guards" not in calls
    assert "active_guards" not in calls


def test_all_master_and_overlay_positions_remain_distinct():
    from nhl_true_blender_engine.engine import MASTER, OVERLAY, EXECUTION_ORDER
    assert MASTER == (["G0"] + [f"G{i}" for i in range(1, 11)] +
                      ["G10.5"] + [f"G{i}" for i in range(11, 19)])
    assert OVERLAY == ([f"Step{i}" for i in range(11)] +
                       ["Step10.5"] + [f"Step{i}" for i in range(11, 15)])
    assert len(EXECUTION_ORDER) == 36
    assert len(set(EXECUTION_ORDER)) == 36
    assert EXECUTION_ORDER[-1] == "G18"
