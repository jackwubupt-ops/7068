from pathlib import Path
from config import get_client, OPENAI_MODEL

def classify_prompt(prompt: str) -> str:
    classification_prompt = (
        "Classify the following function description into one of the algorithm types: "
        "dynamic programming, greedy, divide and conquer, binary search, graph traversal, or other. "
        "Return ONLY the type name (e.g., dynamic programming).\n\n"
        "Function description: " + prompt
    )
    response = get_client().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": classification_prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content.strip()

def generate_code(prompt: str, algo_type: str = "default", model=OPENAI_MODEL) -> str:
    system_instruction = (
        f"You are a professional Python developer. You will write a clean, optimized, and well-documented Python function "
        f"using {algo_type} to solve the task provided by the user. "
        "Ensure your code STRICTLY follows Python's PEP8 style guide, including:\n"
        "- 4-space indentation\n"
        "- Clear and consistent naming conventions\n"
        "- Proper spacing around operators and after commas\n"
        "- Line width <= 79 characters\n"
        "- Reasonable blank lines (before/after function definitions, etc.)\n\n"
        "Make sure to use appropriate data structures and algorithmic patterns. "
        "Add meaningful inline comments to explain your logic. "
        "At the end of the code, add a single line estimating the time complexity (e.g., '# Time complexity: O(n log n)'). "
        "Output ONLY valid executable Python code. Do not include markdown or explanations."
    )

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    response = get_client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3
    )
    return response.choices[0].message.content.strip()


def save_code(code_str, filename="results/code_output.py"):
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code_str, encoding="utf-8")
