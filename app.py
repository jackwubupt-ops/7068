from flask import Flask, render_template, request
from prompt_agent import correct_and_refine_prompt
from code_agent import generate_code, classify_prompt
from test_agent import test_and_improve_code
from evaluator import analyze_code_quality

import json

from pipeline_agent import run_localization

app = Flask(__name__)


@app.route('/localize', methods=['GET', 'POST'])
def localize():
    result, error = None, None
    if request.method == 'POST':
        try:
            result = json.dumps(run_localization(
                request.form.get('issue', ''), request.form.get('repo_root', ''),
                request.form.get('base_commit', '')), ensure_ascii=False, indent=2)
        except Exception as exc:
            error = str(exc)
    return render_template('localize.html', result=result, error=error), 400 if error else 200

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None

    if request.method == 'POST':
        user_input = request.form['prompt']

        if user_input.strip():
            # Step 1: 修正描述
            refined_prompt = correct_and_refine_prompt(user_input)

            # Step 2: 算法类型检测
            algo_type = classify_prompt(refined_prompt)

            # Step 3: 代码生成
            code = generate_code(refined_prompt, algo_type)

            # Step 4: 代码质量分析
            quality_report = analyze_code_quality(code)

            # Step 5: 检测 & 改进
            detect_result = test_and_improve_code(code, refined_prompt)

            result = {
                'original_prompt': user_input,
                'refined_prompt': refined_prompt,
                'algo_type': algo_type,
                'generated_code': code,
                'quality_report': quality_report,
                'detect_result': detect_result
            }

    return render_template('index.html', result=result)


if __name__ == '__main__':
    app.run(debug=True)
