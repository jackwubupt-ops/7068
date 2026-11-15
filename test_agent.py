from config import get_client, OPENAI_MODEL
import json

# 评分函数：判别器逻辑
def score_code(code: str, prompt: str = "") -> dict:
    scoring_prompt = (
        "Please rate the following Python code on a scale of 1 to 10 in the following aspects:\n"
        "1. Correctness: Does it solve the task properly?\n"
        "2. Readability: Code clarity, comments, and clean structure.\n"
        "3. Efficiency: Use of optimal algorithm and data structures.\n"
        "4. Style: PEP8 and Python best practices.\n\n"
        f"Task description:\n{prompt}\n\nCode:\n{code}\n\n"
        "Provide a JSON object like: {\"correctness\": 9, \"readability\": 8, \"efficiency\": 7, \"style\": 8}."
    )

    response = get_client().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": scoring_prompt}],
        temperature=0.0
    )
    return json.loads(response.choices[0].message.content)

# 改进代码
def improve_code(code: str, scores: dict) -> str:
    improvement_prompt = (
        f"Your code was rated low in quality: {scores}. Please refactor the code to improve "
        "correctness, readability, efficiency, and style. "
        "Ensure the code strictly adheres to Python's PEP8 style guide, including proper indentation, naming conventions, spacing, and structure. "
        "Provide only clean Python code, no extra explanation."
    )
    response = get_client().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "user", "content": improvement_prompt},
            {"role": "user", "content": code}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content.strip()


# 检查代码是否为合法 Python 代码
def is_code_valid(code: str) -> bool:
    # 清洗代码块
    code = code.replace("```python", "").replace("```Python", "").replace("```", "").strip()
    try:
        compile(code, "<string>", "exec")
        return True
    except SyntaxError:
        return False


# 核心逻辑：检测 + 判别器 + 改进
def test_and_improve_code(code_str: str, prompt: str) -> str:
    """Return a report; callers choose where to display it."""
    valid = is_code_valid(code_str)
    scores = score_code(code_str, prompt)
    report = [
        "Syntax check: " + ("valid Python" if valid else "invalid Python"),
        "Quality scores: " + json.dumps(scores),
    ]
    if not valid or scores["correctness"] < 7 or scores["readability"] < 7:
        report.append("Suggested improvement:\n" + improve_code(code_str, scores))
    else:
        report.append("Code quality is good; no improvement is needed.")
    return "\n\n".join(report)
