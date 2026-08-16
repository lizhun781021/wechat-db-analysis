#!/usr/bin/env python3
"""
微信每日聊天报告 - 精简日报版生成器
===================================
基于 chat_analysis.py 生成的单日分析 JSON，生成轻量日报 HTML。
风格沿用完整版报告的微信绿色主题，仅包含核心指标：
- 头部概览（日期、消息量）
- 核心统计卡片（总消息、活跃群、活跃私聊、消息类型）
- 活跃群聊 Top10
- 活跃私聊 Top10
- 跨群活跃成员 Top10
- 24小时分布热力图
- 星期分布

用法：
    python3 gen_daily_report.py --chat-json <analysis_json> --output <output.html> --date 2026-08-15

示例：
    python3 gen_daily_report.py \
        --chat-json ./analysis_result_20260815.json \
        --output ./daily-reports/2026-08-15/微信聊天日报_2026-08-15.html \
        --date 2026-08-15
"""

import json
import datetime
import os
import argparse

# 消息类型配色
TYPE_COLORS = {
    "文字": "#07c160",
    "图片": "#576b95",
    "语音": "#fa9d3b",
    "视频": "#e15f63",
    "文件": "#8a6de9",
    "表情包": "#4cc4d4",
    "名片": "#d4a017",
    "位置": "#2c9f9f",
    "语音通话": "#e91e63",
    "系统消息": "#9e9e9e",
}
FALLBACK_COLOR = "#95a5a6"


def type_color(name):
    return TYPE_COLORS.get(name, FALLBACK_COLOR)


def rank_class(idx):
    if idx == 0:
        return "top1"
    if idx == 1:
        return "top2"
    if idx == 2:
        return "top3"
    return "other"


def generate_daily_html(chat_data, report_date, generated_at):
    overall = chat_data['overall']
    chatrooms = chat_data['chatrooms']
    private_chats = chat_data['private_chats']
    top_senders = chat_data['top_senders_in_chatrooms']
    time_dist = chat_data['time_distribution']

    total_messages = overall['total_messages']
    active_chatrooms = len(chatrooms)
    active_private = len(private_chats)
    type_items = list(overall['type_breakdown'].items())[:8]

    # 时间范围
    time_range = overall['time_range']
    if time_range and time_range[0] != time_range[1]:
        range_text = f"{time_range[0]} ~ {time_range[1]}"
    else:
        range_text = report_date

    # 群聊 Top10
    chatroom_rows = ""
    max_cc = max(c['message_count'] for c in chatrooms[:10]) if chatrooms else 1
    for i, c in enumerate(chatrooms[:10]):
        pct = c['message_count'] / max_cc * 100
        chatroom_rows += f"""
        <div class="rank-item">
          <div class="rank-num {rank_class(i)}">{i + 1}</div>
          <div class="rank-info">
            <div class="rank-name">{escape_html(c['name'])}</div>
            <div class="rank-meta">{c['sender_count']}人发言 · {','.join(list(c['type_breakdown'].keys())[:3])}</div>
            <div class="bar-track"><div class="bar-fill green" style="width:{pct:.1f}%"></div></div>
          </div>
          <div class="rank-count">{c['message_count']}</div>
        </div>"""

    # 私聊 Top10
    private_rows = ""
    max_pc = max(p['message_count'] for p in private_chats[:10]) if private_chats else 1
    for i, p in enumerate(private_chats[:10]):
        pct = p['message_count'] / max_pc * 100
        private_rows += f"""
        <div class="rank-item">
          <div class="rank-num {rank_class(i)}">{i + 1}</div>
          <div class="rank-info">
            <div class="rank-name">{escape_html(p['name'])}</div>
            <div class="rank-meta">{' · '.join(list(p['type_breakdown'].keys())[:3])}</div>
            <div class="bar-track"><div class="bar-fill blue" style="width:{pct:.1f}%"></div></div>
          </div>
          <div class="rank-count">{p['message_count']}</div>
        </div>"""

    # 跨群活跃成员 Top10
    sender_rows = ""
    max_sc = top_senders[0]['count'] if top_senders else 1
    for i, s in enumerate(top_senders[:10]):
        pct = s['count'] / max_sc * 100
        sender_rows += f"""
        <div class="rank-item">
          <div class="rank-num {rank_class(i)}">{i + 1}</div>
          <div class="rank-info">
            <div class="rank-name">{escape_html(s['name'])}</div>
            <div class="rank-meta">主要活跃于：{escape_html(s['top_chatroom'])}（{s['top_chatroom_count']}条）</div>
            <div class="bar-track"><div class="bar-fill orange" style="width:{pct:.1f}%"></div></div>
          </div>
          <div class="rank-count">{s['count']}</div>
        </div>"""

    # 消息类型分布
    type_chips = ""
    for name, cnt in type_items:
        pct = cnt / total_messages * 100 if total_messages else 0
        type_chips += f"""
        <div class="type-chip">
          <span class="type-dot" style="background:{type_color(name)}"></span>
          <span class="type-name">{name}</span>
          <span class="type-count">{cnt}</span>
          <span class="type-pct">{pct:.1f}%</span>
        </div>"""

    # 小时分布热力图
    hourly = time_dist['hourly']
    max_hour = max(h['count'] for h in hourly) if any(h['count'] for h in hourly) else 1
    hour_cells = []
    for h in hourly:
        intensity = h['count'] / max_hour
        if h['count'] == 0:
            bg = "#f0f2f5"
            fg = "#bbb"
        elif intensity > 0.8:
            bg = "#07c160"
            fg = "#fff"
        elif intensity > 0.5:
            bg = "#4fd08d"
            fg = "#fff"
        elif intensity > 0.2:
            bg = "#9ae3b8"
            fg = "#fff"
        else:
            bg = "#cdeeda"
            fg = "#666"
        hour_cells.append(f'<div class="hour-cell" style="background:{bg};color:{fg}">{h["count"]}</div>')
    hour_grid = "".join(hour_cells)
    hour_labels = "".join(f'<div>{h:02d}</div>' for h in range(24))

    # 星期分布
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    max_wd = max(w['count'] for w in time_dist['weekly']) if any(w['count'] for w in time_dist['weekly']) else 1
    weekday_rows = ""
    for w in time_dist['weekly']:
        pct = w['count'] / max_wd * 100
        weekday_rows += f"""
        <div class="bar-row weekday-bars">
          <div class="bar-label">{w['name']}</div>
          <div class="bar-track"><div class="bar-fill cyan" style="width:{pct:.1f}%"></div></div>
          <div class="bar-count">{w['count']}</div>
        </div>"""

    # 深夜时段（23-05点）统计
    night_total = sum(h['count'] for h in hourly if h['hour'] >= 23 or h['hour'] <= 5)
    night_pct = night_total / total_messages * 100 if total_messages else 0

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>微信聊天日报 - {report_date}</title>
<style>
  :root {{
    --primary: #07c160;
    --primary-dark: #06ad56;
    --bg: #f5f7fa;
    --card-bg: #ffffff;
    --text: #1a1a1a;
    --text-secondary: #666;
    --border: #e8e8e8;
    --accent: #576b95;
    --shadow: 0 2px 12px rgba(0,0,0,0.06);
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.7;
    -webkit-font-smoothing: antialiased;
  }}
  .container {{ max-width: 980px; margin: 0 auto; padding: 0 20px 60px; }}
  .header {{
    background: linear-gradient(135deg, #07c160 0%, #06ad56 100%);
    color: #fff;
    padding: 44px 0 36px;
    border-radius: 0 0 24px 24px;
    margin-bottom: 32px;
    text-align: center;
  }}
  .header h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 10px; }}
  .header .sub {{ font-size: 14px; opacity: 0.9; margin-bottom: 8px; }}
  .header .meta {{ font-size: 13px; opacity: 0.85; line-height: 2; }}
  .header .meta span {{ display: inline-block; margin: 0 12px; }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 16px;
    margin-bottom: 36px;
  }}
  .stat-card {{
    background: var(--card-bg);
    border-radius: 14px;
    padding: 22px 18px;
    text-align: center;
    box-shadow: var(--shadow);
  }}
  .stat-card .num {{ font-size: 28px; font-weight: 700; color: var(--primary); }}
  .stat-card .num.small {{ font-size: 20px; }}
  .stat-card .label {{ font-size: 13px; color: var(--text-secondary); margin-top: 4px; }}
  .section {{ margin-bottom: 36px; }}
  .section-title {{
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 16px;
    padding-left: 14px;
    border-left: 4px solid var(--primary);
    color: var(--text);
  }}
  .section-title .sub {{ font-size: 13px; font-weight: 400; color: var(--text-secondary); margin-left: 8px; }}
  .card {{
    background: var(--card-bg);
    border-radius: 12px;
    padding: 24px;
    box-shadow: var(--shadow);
    margin-bottom: 16px;
  }}
  .card-title {{ font-size: 16px; font-weight: 600; margin-bottom: 14px; color: var(--accent); }}
  .rank-item {{
    display: flex; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border);
  }}
  .rank-item:last-child {{ border-bottom: none; }}
  .rank-num {{ width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.85em; flex-shrink: 0; margin-right: 12px; }}
  .rank-num.top1 {{ background: linear-gradient(135deg, #FFD700, #FFA500); color: #fff; }}
  .rank-num.top2 {{ background: linear-gradient(135deg, #C0C0C0, #A0A0A0); color: #fff; }}
  .rank-num.top3 {{ background: linear-gradient(135deg, #CD7F32, #B87333); color: #fff; }}
  .rank-num.other {{ background: #f0f2f5; color: #999; }}
  .rank-info {{ flex: 1; min-width: 0; }}
  .rank-name {{ font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .rank-meta {{ font-size: 12px; color: var(--text-secondary); margin-top: 2px; }}
  .rank-count {{ font-weight: 700; color: var(--primary); margin-left: 12px; font-size: 15px; }}
  .bar-track {{ height: 8px; background: #f0f2f5; border-radius: 4px; overflow: hidden; margin-top: 6px; }}
  .bar-fill {{ height: 100%; border-radius: 4px; }}
  .bar-fill.green {{ background: var(--primary); }}
  .bar-fill.blue {{ background: #576b95; }}
  .bar-fill.orange {{ background: var(--warning); }}
  .bar-fill.cyan {{ background: #4cc4d4; }}
  .bar-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 14px; }}
  .bar-label {{ width: 50px; text-align: right; color: var(--text-secondary); flex-shrink: 0; }}
  .bar-count {{ width: 40px; text-align: right; font-weight: 600; }}
  .type-chips {{ display: flex; flex-wrap: wrap; gap: 10px; }}
  .type-chip {{
    display: flex; align-items: center; gap: 6px;
    background: #f8faf9; border: 1px solid var(--border); border-radius: 20px;
    padding: 6px 14px; font-size: 13px;
  }}
  .type-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .type-name {{ font-weight: 600; }}
  .type-count {{ color: var(--text-secondary); }}
  .type-pct {{ color: var(--primary); font-weight: 600; }}
  .hour-grid {{ display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; margin: 10px 0; }}
  .hour-cell {{ aspect-ratio: 1.4; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; }}
  .hour-labels {{ display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; font-size: 9px; color: var(--text-secondary); text-align: center; margin-top: 4px; }}
  .callout {{
    background: #f0faf3;
    border: 1px solid #c8f0d6;
    border-radius: 10px;
    padding: 14px 18px;
    margin: 12px 0;
    font-size: 14px;
  }}
  .footer {{ text-align: center; font-size: 12px; color: var(--text-secondary); margin-top: 40px; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>微信聊天日报</h1>
  <div class="sub">{report_date}</div>
  <div class="meta">
    <span>报告生成：{generated_at}</span>
    <span>数据已解密</span>
  </div>
</div>

<div class="stats-grid">
  <div class="stat-card">
    <div class="num">{total_messages}</div>
    <div class="label">总消息数</div>
  </div>
  <div class="stat-card">
    <div class="num small">{active_chatrooms}</div>
    <div class="label">活跃群聊</div>
  </div>
  <div class="stat-card">
    <div class="num small">{active_private}</div>
    <div class="label">活跃私聊</div>
  </div>
  <div class="stat-card">
    <div class="num small">{len(type_items)}</div>
    <div class="label">消息类型</div>
  </div>
  <div class="stat-card">
    <div class="num small">{night_pct:.1f}%</div>
    <div class="label">深夜消息占比</div>
  </div>
</div>

<div class="section">
  <div class="section-title">消息类型分布</div>
  <div class="card">
    <div class="type-chips">
      {type_chips}
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">活跃群聊 Top 10</div>
  <div class="card">
    {chatroom_rows}
  </div>
</div>

<div class="section">
  <div class="section-title">活跃私聊 Top 10</div>
  <div class="card">
    {private_rows}
  </div>
</div>

<div class="section">
  <div class="section-title">跨群活跃成员 Top 10</div>
  <div class="card">
    {sender_rows}
  </div>
</div>

<div class="section">
  <div class="section-title">24 小时活跃分布</div>
  <div class="card">
    <div class="hour-grid">{hour_grid}</div>
    <div class="hour-labels">{hour_labels}</div>
  </div>
  <div class="card">
    <div class="card-title">星期分布</div>
    {weekday_rows}
  </div>
</div>

<div class="callout">
  深夜时段（23:00 - 05:00）共 {night_total} 条消息，占比 {night_pct:.1f}%。
</div>

<div class="footer">
  本报告由本地脚本自动生成 · 数据仅存于本机 · 生成时间 {generated_at}
</div>

</div>
</body>
</html>"""

    return html


def escape_html(text):
    """HTML转义，防止特殊字符破坏页面"""
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def main():
    parser = argparse.ArgumentParser(description="微信聊天日报生成器（精简版）")
    parser.add_argument("--chat-json", required=True, help="聊天分析JSON路径")
    parser.add_argument("--output", required=True, help="输出HTML路径")
    parser.add_argument("--date", required=True, help="报告日期 YYYY-MM-DD")
    args = parser.parse_args()

    chat_json = os.path.expanduser(args.chat_json)
    output_html = os.path.expanduser(args.output)

    with open(chat_json, 'r', encoding='utf-8') as f:
        chat_data = json.load(f)

    generated_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    html = generate_daily_html(chat_data, args.date, generated_at)

    os.makedirs(os.path.dirname(output_html) or '.', exist_ok=True)
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"日报HTML已生成: {output_html}")
    print(f"文件大小: {os.path.getsize(output_html) / 1024:.1f} KB")


if __name__ == '__main__':
    main()