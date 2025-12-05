# modules/fantasy/last14.py
from modules.fantasy.yahoo_api import yahoo_search_player_by_name, yahoo_get_player_stats_by_date_range
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def summarize_stats(stats: dict):
    """
    將 Yahoo 大量 stats → 壓縮成精簡 summary
    （避免 LLM timeout）
    """
    keys = {
        "points": "得分",
        "reboundsTotal": "籃板",
        "assists": "助攻",
        "steals": "抄截",
        "blocks": "火鍋",
        "turnovers": "失誤",
        "fgPct": "命中率",
        "ftPct": "罰球命中率",
        "threePct": "三分命中率",
    }

    lines = []
    for k, label in keys.items():
        if k in stats:
            val = stats[k]
            if isinstance(val, float) and val <= 1:
                val = round(val * 100, 1)
                lines.append(f"{label}: {val}%")
            else:
                lines.append(f"{label}: {val}")
    return "\n".join(lines)


def analyze_last14(player_name: str):
    """
    主入口：抓 14 天資料 → summary → 丟 LLM 做自然語言分析
    """
    p = yahoo_search_player_by_name(player_name)
    if not p:
        return f"找不到球員：{player_name}"

    stats14 = yahoo_get_player_stats_by_date_range(p["player_key"], days=14)
    if not stats14:
        return "查無最近 14 天數據"

    summary = summarize_stats(stats14)

    prompt = f"""
你是 Yahoo Fantasy 專家。
以下是 {p['name']} 最近 14 天的壓縮後 summary：

{summary}

請用 4～6 行自然語言分析：
- 最近表現趨勢
- 哪些數據變好或變差
- 是否值得關注或買進
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        max_tokens=350,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    analysis = res.choices[0].message.content

    return f"📆 {p['name']} — 最近 14 天分析\n{analysis}"
