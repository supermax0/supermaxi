"""Read-only AST inventory. Does not import the app or connect to a database."""
import ast
from pathlib import Path


def inventory():
    for path in sorted(Path("modules/clinics").glob("*routes*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes, guards = [], []
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if isinstance(decorator.func, ast.Name) and decorator.func.id == "require_clinics":
                    guards.append(ast.unparse(decorator.args[0]) if decorator.args else "authenticated clinics user")
                if isinstance(decorator.func, ast.Attribute) and decorator.func.attr in {"route", "get", "post", "put", "patch", "delete"}:
                    route = ast.literal_eval(decorator.args[0])
                    methods = next((ast.literal_eval(k.value) for k in decorator.keywords if k.arg == "methods"), None)
                    methods = methods or (["GET"] if decorator.func.attr == "route" else [decorator.func.attr.upper()])
                    routes.append((route, methods))
            for route, methods in routes:
                yield path, node, route, methods, guards


if __name__ == "__main__":
    print("# Clinics Authorization Route Inventory\n")
    print("Generated from route decorators. This is an inventory, NOT a completed security audit. Public routes use a separate trust model. Dynamic dispatch and service-level checks need manual review.\n")
    print("| Source | Handler | Route | Methods | Declared permission | Review status |")
    print("|---|---|---|---|---|---|")
    for path, node, route, methods, guards in inventory():
        print(f"| {path.as_posix()}:{node.lineno} | {node.name} | `{route}` | {', '.join(methods)} | {', '.join(guards) or 'No require_clinics decorator - inspect'} | Pending full review |")
