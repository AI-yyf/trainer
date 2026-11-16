"""Read literal Python checks tied to the current practice file without running tests."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def project_python_checks(root: Path, file_path: str, request: str) -> list[str]:
    root = root.resolve()
    target = (root / file_path).resolve()
    if target.suffix != ".py" or not target.is_relative_to(root) or not target.is_file():
        return []
    checks: list[str] = []
    seen: set[str] = set()
    for folder in dict.fromkeys((target.parent, root, root / "tests")):
        if not folder.is_dir() or not folder.resolve().is_relative_to(root):
            continue
        for candidate in sorted(folder.glob("test_*.py"))[:24]:
            try:
                test_file = candidate.resolve()
                if test_file == target or not test_file.is_relative_to(root) or not test_file.is_file():
                    continue
                if test_file.stat().st_size > 64_000:
                    continue
                tree = ast.parse(test_file.read_bytes())
            except (OSError, RuntimeError, SyntaxError, ValueError):
                continue
            for line, assertion in _assertions(tree, test_file, target, root, request):
                if assertion in seen:
                    continue
                seen.add(assertion)
                checks.append(f"`{assertion}` · `{test_file.relative_to(root)}:{line}`")
                if len(checks) == 6:
                    return checks
    return checks


def _assertions(
    tree: ast.Module, test_file: Path, target: Path, root: Path, request: str,
) -> list[tuple[int, str]]:
    imports: dict[str, str] = {}
    run_paths: set[str] = set()
    imports_path = False
    for statement in tree.body:
        if not isinstance(statement, ast.ImportFrom) or statement.level or not statement.module:
            continue
        if statement.module == "runpy":
            run_paths.update(item.asname or item.name for item in statement.names if item.name == "run_path")
        if statement.module == "pathlib":
            imports_path = any(item.name == "Path" and (not item.asname or item.asname == "Path")
                               for item in statement.names)
        module_file = Path(*statement.module.split(".")).with_suffix(".py")
        candidates = {item.resolve() for item in (root / module_file, test_file.parent / module_file)
                      if item.is_file()}
        for item in statement.names:
            name = item.asname or item.name
            imports.pop(name, None)
            if candidates == {target}:
                imports[name] = item.name
    if not imports_path:
        run_paths.clear()

    result: list[tuple[int, str]] = []
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith("test_"):
            continue
        if function.decorator_list or any(
            not isinstance(statement, (ast.Assign, ast.Assert, ast.Expr))
            for statement in function.body
        ):
            continue
        aliases = dict(imports)
        for statement in function.body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target_name = statement.targets[0]
                if isinstance(target_name, ast.Name):
                    aliases.pop(target_name.id, None)
                    symbol = _run_path_symbol(statement.value, run_paths, test_file, target)
                    if symbol:
                        aliases[target_name.id] = symbol
            elif isinstance(statement, ast.Assert):
                check = _literal_check(statement.test, aliases, request)
                if check:
                    result.append((statement.lineno, check))
    return result


def _run_path_symbol(value: ast.expr, run_paths: set[str], test_file: Path, target: Path) -> str:
    match value:
        case ast.Subscript(value=ast.Call(func=ast.Name(id=runner), args=[path], keywords=[]),
                           slice=ast.Constant(value=str(symbol))) if runner in run_paths:
            name = _sibling_path_name(path)
            if name and symbol.isidentifier() and (test_file.parent / name).resolve() == target:
                return symbol
    return ""


def _sibling_path_name(path: ast.expr) -> str:
    match path:
        case ast.Call(func=ast.Name(id="str"), args=[argument], keywords=[]):
            path = argument
    match path:
        case ast.Call(func=ast.Attribute(value=reference, attr="with_name"),
                      args=[ast.Constant(value=str(name))], keywords=[]):
            match reference:
                case ast.Call(func=ast.Name(id="Path"), args=[ast.Name(id="__file__")], keywords=[]):
                    return name if name == Path(name).name else ""
    return ""


def _literal_check(expression: ast.expr, aliases: dict[str, str], request: str) -> str:
    prefix = "assert "
    suffix = ""
    match expression:
        case ast.UnaryOp(op=ast.Not(), operand=ast.Call() as call):
            prefix += "not "
        case ast.Compare(left=ast.Call() as call, ops=[ast.Eq()], comparators=[ast.Constant() as expected]):
            suffix = f" == {ast.unparse(expected)}"
        case ast.Call() as call:
            pass
        case _:
            return ""
    if not isinstance(call.func, ast.Name) or not (symbol := aliases.get(call.func.id)):
        return ""
    if not re.search(rf"\b{re.escape(symbol)}\b", request):
        return ""
    if not all(isinstance(value, ast.Constant) for value in call.args):
        return ""
    if not all(keyword.arg and isinstance(keyword.value, ast.Constant) for keyword in call.keywords):
        return ""
    call_text = ast.unparse(call)
    check = prefix + symbol + call_text[len(call.func.id):] + suffix
    return check if len(check) <= 180 and "`" not in check else ""
