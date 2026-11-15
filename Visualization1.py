from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 读取数据
df = pd.read_csv(Path(__file__).with_name("experiment_results_extreme.csv"))

# 指标名称
metrics = ["correctness", "readability", "efficiency", "style"]

# 计算平均值
raw_means = [df[f"raw_{m}"].mean() for m in metrics]
agent_means = [df[f"agent_{m}"].mean() for m in metrics]

# 闭合数据和角度
labels = [m.capitalize() for m in metrics]
angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
angles += angles[:1]
raw_means += raw_means[:1]
agent_means += agent_means[:1]

# 创建图形
fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

# 绘制曲线
ax.plot(angles, raw_means, label='Direct GPT-3.5', linewidth=2, linestyle='solid')
ax.fill(angles, raw_means, alpha=0.25)

ax.plot(angles, agent_means, label='CodeNexus', linewidth=2, linestyle='dashed')
ax.fill(angles, agent_means, alpha=0.25)

# 设置角度标签
ax.set_xticks(angles[:-1])
ax.set_xticklabels(labels, fontsize=13)

# 设置标题与图例
ax.set_title("Average Performance by Metric", size=16, weight='bold', position=(0.5, 1.1))
ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1.1))

# 显示图形
plt.tight_layout()
plt.show()
