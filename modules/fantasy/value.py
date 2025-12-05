# modules/fantasy/value.py
from modules.fantasy.yahoo_api import (
    yahoo_search_player_by_name,
    yahoo_get_player_season_avg
)
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def summarize_season_stats(stats: dict):
    """
    將 Yahoo season stats → 精簡 summary
    """
    label_map = {
        "points": "得分",
        "reboundsTotal": "籃板",
        "assists": "助攻",
        "steals": "抄截",
        "blocks": "火鍋",
        "fgPct": "命中率",
        "ftPct": "罰球命中率",
        "threePct": "三分命中率",
        "turnovers": "失誤",
    }

    lines = []
    for k, label in label_map.items():
        if k in stats:
            v = stats[k]
            if isinstance(v, float) and v <= 1:
                v = round(v * 100, 1)
                lines.append(f"{label}: {v}%")
            else:
                lines.append(f"{label}: {v}")
    return "\n".join(lines)


def analyze_value(player_name: str):
    p = yahoo_search_player_by_name(player_name)
    if not p:
        return f"找不到球員：{player_name}"

    stats = yahoo_get_player_season_avg(p["player_key"])
    if not stats:
        return "查無球季數據"

    summary = summarize_season_stats(stats)

    prompt = f"""
你是 Yahoo Fantasy 的專家。
請用以下球季數據 summary，提供「球員價值分析」：

球員：{p['name']}
球季 summary：
{summary}

請分析：
- 該球員在 Yahoo Fantasy 中屬於哪一型（高 usage、大防守、全能型…）
- 他最強的項目、明顯弱點
- 健康風險 or 角色風險
- 未來價值趨勢：買進 / 持有 / 賣出
- 用 5 行左右講完即可
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        max_tokens=350,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    analysis = res.choices[0].message.content

    return f"📈 {p['name']} — Fantasy 價值分析\n{analysis}"
