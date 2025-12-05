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

