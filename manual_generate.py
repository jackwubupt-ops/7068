from code_agent import generate_code, save_code
from evaluator import analyze_code_quality

prompt = "请用Python写一个函数，判断一个字符串是否是回文。"
code = generate_code(prompt)
save_code(code)

print("=== Code Generated ===")
print(code)

print("\n=== Quality Analysis ===")
print(analyze_code_quality(code))
