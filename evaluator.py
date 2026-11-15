import ast
import re

def analyze_code_quality(code: str) -> dict:
    lines = code.splitlines()
    num_lines = len(lines)
    num_comments = sum(1 for l in lines if l.strip().startswith("#"))
    num_functions = len(re.findall(r'^\s*def\s', code, re.MULTILINE))
    avg_line_length = round(sum(len(l) for l in lines) / num_lines, 2) if num_lines else 0
    num_loops = len(re.findall(r'\b(for|while)\b', code))
    num_conditionals = len(re.findall(r'\bif\b', code))
    try:
        tree = ast.parse(code)
        contains_recursion = any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == function.name
            for function in ast.walk(tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for call in ast.walk(function)
        )
    except SyntaxError:
        contains_recursion = False
    libraries_used = re.findall(r'^\s*import\s+(\w+)', code, re.MULTILINE) +                      re.findall(r'^\s*from\s+(\w+)', code, re.MULTILINE)
    time_complexity = "N/A"
    match = re.search(r'#\s*Time complexity\s*:\s*(O\([^)]+\))', code)
    if match:
        time_complexity = match.group(1)

    return {
        "lines": num_lines,
        "comments": num_comments,
        "functions": num_functions,
        "comment_ratio": round(num_comments / num_lines, 2) if num_lines else 0,
        "avg_line_length": avg_line_length,
        "num_loops": num_loops,
        "num_conditionals": num_conditionals,
        "contains_recursion": contains_recursion,
        "libraries_used": sorted(set(libraries_used)),
        "time_complexity": time_complexity
    }
