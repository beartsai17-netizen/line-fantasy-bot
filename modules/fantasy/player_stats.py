# modules/fantasy/player_stats.py

"""
負責處理 Yahoo Fantasy API 回傳的原始資料，
例如：本季 stats、recent stats（7/14/30 天）、
統一格式化 stat。
"""

def get_season_stats(player_key):
    """從 app.py 的 yahoo_get_player_season_avg 呼叫"""
    from app import yahoo_get_player_season_avg
    return yahoo_get_player_season_avg(player_key)


def get_recent_stats(player_key, days):
    """從 app.py 的 yahoo_get_player_stats_by_date_range 呼叫"""
    from app import yahoo_get_player_stats_by_date_range
    return yahoo_get_player_stats_by_date_range(player_key, days)


# modules/fantasy/player_stats.py

def format_stats_for_llm(stats_dict):
    """
    將 Yahoo API 回傳的 stats dict，整理成 GPT 能讀懂的格式。
    """
    if not stats_dict:
        return "沒有可用的數據"

    lines = []
    for k, v in stats_dict.items():
        lines.append(f"{k}: {v}")

    return "\n".join(lines)

def format_injury_status(raw_detail):
    """
    將 Yahoo API 回傳的傷病資料格式化成固定模板。
    raw_detail 來自 yahoo_get_player_detail()
    """
    if not raw_detail:
        return "沒有傷病資訊。"

    status = raw_detail.get("status") or "無資料"
    injury = raw_detail.get("injury") or "—"

    # 可擴充 mapping（你之後可補充更多）
    status_map = {
        "GTD": "🟡 今日出賽成疑 (GTD)",
        "O":   "🔴 缺席 (O)",
        "OUT": "🔴 缺席中 (OUT)",
        "INJ": "🔴 受傷（可放 IR）(INJ)",
        "DL":  "🔴 長期缺席 (DL)",
        "NA":  "⚪ 非激活 (NA)",
    }

    status_text = status_map.get(status, f"⚪ 狀態：{status}")

    return f"{status_text}\n傷病：{injury}"
