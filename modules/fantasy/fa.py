# modules/fantasy/fa.py

"""
FA 推薦模組：
1. 從 Yahoo Fantasy API 抓取 FA 清單。
2. 計算本季 / 近 7 天的 stats。
3. 排序後送給 LLM 做自然語言分析。
"""

from modules.llm import client


def llm_rank_fa(fa_list, categories=None):
    """
    categories = ['reb', 'ast', '3pm'] 等 → 用來客製排序重點
    fa_list = [
       {'name': 'XX', 'team': 'YYY', 'stats_text': 'PTS:...' },
       {...}
    ]
    """

    cat_text = ", ".join(categories) if categories else "all categories"

    prompt = f"""
你是一位 Yahoo Fantasy 的 FA 推薦專家。

以下是自由球員的統計資料（本季 + 最近 7 天）：

{fa_list}

請根據以下需求排序（若無指定，就是全類別綜合排序）：
{cat_text}

輸出格式請如下：

1. <球員> — 最重要的理由（例如：三分爆量 / 助攻穩定）
2. <球員> — 理由
3. <球員> — 理由
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content
