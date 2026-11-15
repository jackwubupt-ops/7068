from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# 读取数据
df = pd.read_csv(Path(__file__).with_name("experiment_results_extreme.csv"))

# 设置绘图风格
sns.set(style="whitegrid", context="talk")
colors = sns.color_palette("Set2", 2)

# 指标列表
metrics = ["correctness", "readability", "efficiency", "style"]

# 逐个指标绘图
for metric in metrics:
    plt.figure(figsize=(12, 6))
    plt.plot(df.index, df[f"raw_{metric}"], marker='o', linestyle='-', linewidth=2.5,
             label="Direct GPT-3.5", color=colors[0])
    plt.plot(df.index, df[f"agent_{metric}"], marker='s', linestyle='--', linewidth=2.5,
             label="CodeNexus", color=colors[1])
    plt.xlabel("Task number", fontsize=14)
    plt.ylabel(f"{metric.capitalize()} Score", fontsize=14)
    plt.title(f"{metric.capitalize()}: Direct GPT-3.5 vs CodeNexus", fontsize=16, weight='bold')

    # 设置 x 轴每隔 10 显示一个刻度
    plt.xticks(ticks=range(0, len(df)+1, 10), labels=range(0, len(df)+1, 10))

    plt.ylim(0, 11)
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.show()
