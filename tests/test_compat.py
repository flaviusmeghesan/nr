"""Garda de compatibilitate cu Python 3.9 (Python-ul de sistem de pe macOS).

`int | None` intr-o semnatura se evalueaza la definirea functiei si crapa pe 3.9,
exceptand cazul in care fisierul are `from __future__ import annotations`. Testele
ruleaza de obicei pe un Python mai nou, unde greseala asta nu se vede - de aceea o
cautam static, in sursa.
"""

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def source_files():
    files = [ROOT / "run.py"]
    files += sorted((ROOT / "tracker").rglob("*.py"))
    return files


def annotations_of(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in (args.posonlyargs + args.args + args.kwonlyargs
                        + [a for a in (args.vararg, args.kwarg) if a]):
                if arg.annotation is not None:
                    yield arg.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def uses_union_operator(annotation):
    return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)
               for n in ast.walk(annotation))


def postpones_annotations(tree):
    return any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(alias.name == "annotations" for alias in n.names)
               for n in tree.body)


class Python39CompatibilityTests(unittest.TestCase):
    def test_union_annotations_need_the_future_import(self):
        offenders = []
        for path in source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(uses_union_operator(a) for a in annotations_of(tree)) \
                    and not postpones_annotations(tree):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            offenders, [],
            "Aceste fisiere folosesc `X | Y` in adnotari fara `from __future__ import "
            "annotations` si crapa pe Python 3.9: " + ", ".join(offenders))

    def test_guard_actually_detects_the_problem(self):
        """Verifica garda in sine: pe un exemplu stricat trebuie sa dea alarma."""
        broken = ast.parse("def f(x: int | None = None): pass")
        fixed = ast.parse("from __future__ import annotations\n"
                          "def f(x: int | None = None): pass")
        self.assertTrue(any(uses_union_operator(a) for a in annotations_of(broken)))
        self.assertFalse(postpones_annotations(broken))
        self.assertTrue(postpones_annotations(fixed))


if __name__ == "__main__":
    unittest.main()
