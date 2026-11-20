"""Make the historical comparison engine callable with current G10.5 context.

Only the archived BASELINE copy is changed. The legacy scorer deliberately
ignores the new opponent_coverage input, preserving its historical method;
the authoritative current engine and all selection rules remain untouched.
Fail closed if the pinned legacy version no longer matches this signature.
"""
import argparse
import ast
from pathlib import Path

LEGACY = ("def challenger_proof(candidate, challengers, goalie_weak_zones, "
          "defense_weak_zones=None):")
COMPAT = ("def challenger_proof(candidate, challengers, goalie_weak_zones, "
          "defense_weak_zones=None, opponent_coverage=None):")


def adapt_baseline_source(source: str) -> str:
    if source.count(LEGACY) != 1 or COMPAT in source:
        raise ValueError("Pinned legacy G10.5 signature changed; refuse automatic adaptation")
    tree = ast.parse(source)
    functions = [item for item in tree.body
                 if isinstance(item, ast.FunctionDef) and item.name == "challenger_proof"]
    if len(functions) != 1:
        raise ValueError("Pinned baseline must expose exactly one challenger_proof")
    fn = functions[0]
    parameters = [arg.arg for arg in fn.args.args]
    if parameters != ["candidate", "challengers", "goalie_weak_zones", "defense_weak_zones"]:
        raise ValueError("Pinned baseline G10.5 inputs do not match the known old contract")
    if any(node.id == "opponent_coverage" for node in ast.walk(fn)
           if isinstance(node, ast.Name)):
        raise ValueError("Legacy baseline already uses new opponent coverage evidence")
    result = source.replace(LEGACY, COMPAT, 1)
    ast.parse(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_engine", type=Path)
    path = parser.parse_args().baseline_engine
    original = path.read_text(encoding="utf-8")
    updated = adapt_baseline_source(original)
    path.write_text(updated, encoding="utf-8")
    print("Historical-only baseline G10.5 call compatibility applied; old scoring logic unchanged")


if __name__ == "__main__":
    main()
