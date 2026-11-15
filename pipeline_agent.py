from prompt_agent import correct_and_refine_prompt
from code_agent import generate_code, classify_prompt, save_code
from test_agent import test_and_improve_code
from evaluator import analyze_code_quality

import os

OUTPUT_DIR = "results/generated"


def run_localization(issue, repo_root, base_commit, **kwargs):
    """Task 1 handoff: returns a plan for a future repository Coder."""
    from prompt_agent import plan_repair
    return plan_repair(issue, repo_root, base_commit, **kwargs)

RAW_PROMPTS = [
    "给定一个包含非负整数的 m x n 网格 grid ，请找出一条从左上角到右下角的路径，使得路径上的数字总和为最小。"  # 示例有错别字
]


def run_pipeline(prompts):
    for i, raw_prompt in enumerate(prompts):
        print(f"\n=== 📝 原始 Prompt {i+1}: {raw_prompt} ===")

        # ✅ Step 1: 修正/优化任务描述
        refined_prompt = correct_and_refine_prompt(raw_prompt)
        print(f"✅ 修正后的任务描述:\n{refined_prompt}")

        # ✅ Step 2: 算法类型检测
        algo_type = classify_prompt(refined_prompt)
        print(f"🧠 检测到的算法类型: {algo_type}")

        # ✅ Step 3: 代码生成
        code = generate_code(refined_prompt, algo_type)
        code_path = os.path.join(OUTPUT_DIR, f"task_{i+1}.py")
        save_code(code, code_path)

        # ✅ Step 4: 代码质量分析
        print("📊 代码质量分析:")
        print(analyze_code_quality(code))

        # ✅ Step 5: 检测代码 + 判别器评分 + 自动改进
        print("🛡️ 代码检测 + 评分 + 自动改进...")
        print(test_and_improve_code(code, refined_prompt))


if __name__ == "__main__":
    run_pipeline(RAW_PROMPTS)
