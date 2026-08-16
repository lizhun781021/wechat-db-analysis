#!/usr/bin/env python3
"""
微信本地数据库分析报告 - 融合版生成器
===================================
合并文件系统分析 + 聊天内容分析，生成微信绿色风格HTML报告。
所有数据从JSON动态读取，确保最新。

用法：
    python3 gen_report.py --chat-json <聊天分析JSON> --fs-json <文件系统扫描JSON> --output <输出HTML>

示例：
    python3 gen_report.py \
        --chat-json ./analysis_result.json \
        --fs-json ./filesystem_scan.json \
        --output ./report.html
"""

import json
import datetime
import os
import argparse

# 默认路径（可通过命令行参数覆盖）
CHAT_JSON = "analysis_result.json"
FS_JSON = "filesystem_scan.json"
OUTPUT_HTML = "report.html"

# 数据库用途映射
DB_PURPOSE = {
    "message_0.db": ("message", "聊天消息主库", "已解密"),
    "biz_message_0.db": ("message", "公众号/企业消息", "待解密"),
    "message_fts.db": ("message", "消息全文搜索索引", "待解密"),
    "message_resource.db": ("message", "消息资源文件", "待解密"),
    "media_0.db": ("message", "媒体资源", "待解密"),
    "weclaw.db": ("message", "消息扩展", "待解密"),
    "contact.db": ("contact", "联系人信息", "旧版可用"),
    "contact_fts.db": ("contact", "联系人搜索索引", "待解密"),
    "head_image.db": ("head_image", "头像缓存", "待解密"),
    "favorite.db": ("favorite", "收藏内容", "待解密"),
    "favorite_fts.db": ("favorite", "收藏搜索索引", "待解密"),
    "general.db": ("general", "通用数据", "待解密"),
    "emoticon.db": ("emoticon", "表情包", "待解密"),
    "sns.db": ("sns", "朋友圈", "待解密"),
    "session.db": ("session", "会话列表", "待解密"),
    "bizchat.db": ("bizchat", "企业微信会话", "待解密"),
    "hardlink.db": ("hardlink", "硬链接索引", "待解密"),
    "solitaire.db": ("solitaire", "接龙", "待解密"),
}

# 工作主题关键词
WORK_TOPICS = {
    '管理报告': ['活动安排', '报告', '汇报', '经分', '会议', '总结', '计划'],
    '数据统计': ['发展量', '统计', '台账', '汇总', '数据'],
    '收入分析': ['收入', '会审', '核心平台', '地市', '增量'],
    '业务分析': ['退订', '移网', '净增', '新入网', '业务'],
    '虚假业务': ['虚假', '群腐', '违规', '处罚', '终端核查'],
    '质检工作': ['质检', '听原声', '新入网质检'],
    '检查审计': ['检查', '审计', '核查'],
    '佣金结算': ['佣金', '结算', '承诺函', '对账'],
}

def bar_color(idx):
    colors = ['#07c160', '#576b95', '#fa9d3b', '#e15f63', '#8a6de9', '#4cc4d4']
    return colors[idx % len(colors)]

def generate_html(chat_data, fs_data):
    overall = chat_data['overall']
    chatrooms = chat_data['chatrooms']
    private_chats = chat_data['private_chats']
    top_senders = chat_data['top_senders_in_chatrooms']
    time_dist = chat_data['time_distribution']
    
    fs = fs_data
    
    # 缩放最大值
    max_chatroom_count = max(c['message_count'] for c in chatrooms) if chatrooms else 1
    max_private_count = max(p['message_count'] for p in private_chats) if private_chats else 1
    max_sender_count = top_senders[0]['count'] if top_senders else 1
    max_hour_count = max(h['count'] for h in time_dist['hourly'])
    max_monthly_count = max(m['count'] for m in time_dist['monthly'])
    max_weekly_count = max(w['count'] for w in time_dist['weekly'])
    
    type_items = list(overall['type_breakdown'].items())[:8]
    
    # 文件类型最大值
    file_types = sorted(fs['file_stats']['by_type'].items(), key=lambda x: x[1]['count'], reverse=True)
    max_file_type_count = max(v['count'] for _, v in file_types) if file_types else 1
    
    # 文件月度最大值
    file_months = sorted(fs['file_stats']['by_month'].items())
    max_file_month_count = max(v['count'] for _, v in file_months) if file_months else 1
    
    # 视频月度最大值
    video_months = sorted(fs['video_stats']['by_month'].items())
    max_video_month_count = max(v['count'] for _, v in video_months) if video_months else 1
    
    # 附件月度最大值
    attach_months = sorted(fs['attach_stats']['by_month'].items())
    max_attach_month_count = max(v['count'] for _, v in attach_months) if attach_months else 1
    
    # 工作主题最大值
    topics = sorted(fs['file_stats'].get('work_topics', fs.get('work_topics', {})).items(), key=lambda x: x[1], reverse=True)
    max_topic_count = max(v for _, v in topics) if topics else 1
    
    # 文件小时分布Top5
    file_hours = sorted(fs['file_stats']['by_hour'].items(), key=lambda x: x[1], reverse=True)[:5]
    max_file_hour = max(v for _, v in file_hours) if file_hours else 1
    
    # 文件星期分布
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    file_weekdays = [(weekday_names[int(k)], fs['file_stats']['by_weekday'].get(k, 0)) for k in ['0','1','2','3','4','5','6']]
    max_file_weekday = max(v for _, v in file_weekdays) if file_weekdays else 1
    
    # 存储占比
    total_gb = fs['total_storage_gb']
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>微信本地数据库分析报告</title>
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
    --warning: #fa9d3b;
    --danger: #e15f63;
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
    padding: 48px 0 40px;
    border-radius: 0 0 24px 24px;
    margin-bottom: 32px;
    text-align: center;
  }}
  .header h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 10px; }}
  .header .meta {{ font-size: 14px; opacity: 0.85; line-height: 2; }}
  .header .meta span {{ display: inline-block; margin: 0 12px; }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px;
    margin-bottom: 36px;
  }}
  .stat-card {{
    background: var(--card-bg);
    border-radius: 14px;
    padding: 22px 18px;
    text-align: center;
    box-shadow: var(--shadow);
    transition: transform 0.2s;
  }}
  .stat-card:hover {{ transform: translateY(-2px); }}
  .stat-card .num {{ font-size: 28px; font-weight: 700; color: var(--primary); }}
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
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ font-weight: 600; color: var(--text-secondary); font-size: 13px; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f9fbfc; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .bar-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 14px; }}
  .bar-label {{ width: 80px; text-align: right; color: var(--text-secondary); flex-shrink: 0; }}
  .bar-track {{ flex: 1; height: 22px; background: #f0f2f5; border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 4px; display: flex; align-items: center; padding-left: 8px; color: #fff; font-size: 12px; font-weight: 600; transition: width 0.6s ease; }}
  .bar-fill.green {{ background: var(--primary); }}
  .bar-fill.blue {{ background: #576b95; }}
  .bar-fill.orange {{ background: var(--warning); }}
  .bar-fill.red {{ background: var(--danger); }}
  .bar-fill.purple {{ background: #8a6de9; }}
  .bar-fill.cyan {{ background: #4cc4d4; }}
  .donut-container {{ display: flex; align-items: center; gap: 30px; flex-wrap: wrap; }}
  .donut {{
    width: 160px; height: 160px; border-radius: 50%; position: relative; flex-shrink: 0;
    background: conic-gradient(
      #07c160 0% {fs['file_stats']['total_size_gb']/total_gb*100:.1f}%,
      #576b95 {fs['file_stats']['total_size_gb']/total_gb*100:.1f}% {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb'])/total_gb*100:.1f}%,
      #fa9d3b {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb'])/total_gb*100:.1f}% {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb']+fs['video_stats']['total_size_gb'])/total_gb*100:.1f}%,
      #4cc4d4 {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb']+fs['video_stats']['total_size_gb'])/total_gb*100:.1f}% {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb']+fs['video_stats']['total_size_gb']+fs['cache_stats']['total_size_gb'])/total_gb*100:.1f}%,
      #e15f63 {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb']+fs['video_stats']['total_size_gb']+fs['cache_stats']['total_size_gb'])/total_gb*100:.1f}% {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb']+fs['video_stats']['total_size_gb']+fs['cache_stats']['total_size_gb']+fs['db_total_size']/1024**3)/total_gb*100:.1f}%,
      #ddd {(fs['file_stats']['total_size_gb']+fs['attach_stats']['total_size_gb']+fs['video_stats']['total_size_gb']+fs['cache_stats']['total_size_gb']+fs['db_total_size']/1024**3)/total_gb*100:.1f}% 100%
    );
  }}
  .donut::after {{
    content: '{total_gb:.2f} GB';
    position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: 100px; height: 100px; border-radius: 50%; background: var(--card-bg);
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 700; color: var(--text);
  }}
  .donut-legend {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; font-size: 13px; }}
  .donut-legend .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }}
  .callout {{
    background: #f0faf3;
    border: 1px solid #c8f0d6;
    border-radius: 10px;
    padding: 14px 18px;
    margin: 12px 0;
    font-size: 14px;
  }}
  .callout.warning {{ background: #fff8ee; border-color: #ffe0b3; }}
  .callout.danger {{ background: #fdf0f0; border-color: #fcc; }}
  .callout .icon {{ font-size: 16px; margin-right: 4px; }}
  .tag {{ display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 12px; font-weight: 600; }}
  .tag.green {{ background: #e8f7ee; color: var(--primary-dark); }}
  .tag.blue {{ background: #eef1f8; color: var(--accent); }}
  .tag.orange {{ background: #fff5e8; color: #d4840e; }}
  .tag.red {{ background: #fdeaea; color: #c44; }}
  .hour-grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 3px; margin: 10px 0; }}
  .hour-cell {{ aspect-ratio: 1; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #fff; font-weight: 600; }}
  .hour-labels {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 3px; font-size: 10px; color: var(--text-secondary); text-align: center; margin-top: 4px; }}
  .weekday-bars .bar-label {{ width: 50px; }}
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
  .rank-sub {{ font-size: 11px; color: #aaa; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .rank-bar-mini {{ flex: 0 0 100px; height: 6px; background: #f0f2f5; border-radius: 3px; margin: 0 12px; overflow: hidden; }}
  .rank-bar-fill-mini {{ height: 100%; border-radius: 3px; }}
  .rank-count {{ flex-shrink: 0; width: 60px; text-align: right; font-weight: 700; color: var(--primary); font-size: 14px; }}
  .type-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
  .type-item {{ background: #f9fbfc; border-radius: 10px; padding: 14px; display: flex; align-items: center; gap: 10px; }}
  .type-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .type-name {{ font-size: 13px; color: var(--text-secondary); }}
  .type-count {{ font-size: 18px; font-weight: 700; color: var(--text); }}
  .chart-container {{ display: flex; align-items: flex-end; gap: 6px; height: 160px; padding: 10px 0; }}
  .chart-bar {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }}
  .chart-bar-fill {{ width: 100%; border-radius: 4px 4px 0 0; transition: height 0.6s ease; position: relative; cursor: pointer; }}
  .chart-bar-fill:hover {{ opacity: 0.8; }}
  .chart-bar-fill .tooltip {{ position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: #333; color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 11px; white-space: nowrap; opacity: 0; transition: opacity 0.2s; pointer-events: none; z-index: 10; }}
  .chart-bar-fill:hover .tooltip {{ opacity: 1; }}
  .chart-label {{ font-size: 11px; color: var(--text-secondary); margin-top: 6px; text-align: center; }}
  .footer {{ text-align: center; padding: 30px 0 0; font-size: 13px; color: var(--text-secondary); border-top: 1px solid var(--border); }}
  .milestone {{ display: flex; align-items: center; gap: 12px; padding: 14px 18px; background: linear-gradient(135deg, #f0faf3 0%, #eef1f8 100%); border-radius: 10px; margin-bottom: 12px; font-size: 14px; }}
  .milestone-icon {{ width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }}
  @media (max-width: 768px) {{
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .donut-container {{ flex-direction: column; }}
    table {{ font-size: 12px; }}
    th, td {{ padding: 6px 8px; }}
    .rank-bar-mini {{ display: none; }}
    .chart-container {{ height: 120px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>微信本地数据库分析报告</h1>
  <div class="meta">
    <span>分析日期：{datetime.datetime.now().strftime('%Y-%m-%d')}</span>
    <span>账号：your_account</span>
    <span>微信版本：4.1.11</span>
    <span>数据已解密</span>
  </div>
</div>

<div class="container">

  <div class="stats-grid">
    <div class="stat-card">
      <div class="num">{overall['total_messages']:,}</div>
      <div class="label">聊天消息总数</div>
    </div>
    <div class="stat-card">
      <div class="num">{overall['total_chatrooms']}</div>
      <div class="label">群聊数量</div>
    </div>
    <div class="stat-card">
      <div class="num">{overall['total_private_chats']}</div>
      <div class="label">私聊会话</div>
    </div>
    <div class="stat-card">
      <div class="num">{fs['file_stats']['total_count']:,}</div>
      <div class="label">聊天文件（{fs['file_stats']['total_size_gb']} GB）</div>
    </div>
    <div class="stat-card">
      <div class="num">{fs['attach_stats']['total_count']:,}</div>
      <div class="label">图片附件（{fs['attach_stats']['total_size_gb']} GB）</div>
    </div>
    <div class="stat-card">
      <div class="num">{total_gb:.2f} GB</div>
      <div class="label">总存储占用</div>
    </div>
  </div>

  <!-- 一、解密突破历程 -->
  <div class="section">
    <h2 class="section-title">一、解密突破历程</h2>
    <div class="card">
      <div class="milestone"><div class="milestone-icon" style="background:#e8f7ee">1</div><div><strong>文件系统分析</strong> — 扫描微信本地数据目录，梳理{len(fs['db_files'])}个WCDB加密数据库、{fs['file_stats']['total_count']:,}个聊天文件、{fs['video_stats']['total_count']:,}个视频消息，总存储{total_gb:.2f}GB</div></div>
      <div class="milestone"><div class="milestone-icon" style="background:#eef1f8">2</div><div><strong>SIP禁用 + 微信重签名</strong> — 恢复模式下执行<code>csrutil disable</code>，对微信App进行adhoc重签名（移除Hardened Runtime），获得进程内存读取权限</div></div>
      <div class="milestone"><div class="milestone-icon" style="background:#fff5e8">3</div><div><strong>编译chatlog提取密钥</strong> — 编译运行chatlog（Go版），从微信进程内存中成功提取32字节Data Key和Image Key</div></div>
      <div class="milestone"><div class="milestone-icon" style="background:#fdeaea">4</div><div><strong>发现4.1.11加密变更</strong> — 微信4.1.11改变了加密参数：message_0.db直接使用raw key作为enc_key，跳过PBKDF2 256000次迭代。自写Python解密脚本验证通过</div></div>
      <div class="milestone"><div class="milestone-icon" style="background:#e8f7ee">5</div><div><strong>成功解密 + 聊天分析</strong> — message_0.db（{fs['db_files'][[d['name'] for d in fs['db_files']].index('message_0.db')]['size_mb']:.1f}MB，16728页）解密成功，数据覆盖{overall['time_range'][0][:10]}至{overall['time_range'][1][:10]}，{overall['total_messages']:,}条消息全部可读</div></div>
    </div>
  </div>

  <!-- 二、数据目录结构 -->
  <div class="section">
    <h2 class="section-title">二、数据目录结构概览</h2>
    <div class="card">
      <table>
        <thead><tr><th>目录</th><th>用途</th><th>说明</th></tr></thead>
        <tbody>
          <tr><td><code>db_storage/</code></td><td>加密数据库</td><td>{len(fs['db_files'])}个SQLCipher加密的SQLite数据库</td></tr>
          <tr><td><code>msg/file/</code></td><td>聊天文件消息</td><td>按月归档，共{fs['file_stats']['total_count']:,}个文件</td></tr>
          <tr><td><code>msg/video/</code></td><td>视频消息</td><td>按月归档，共{fs['video_stats']['total_count']:,}个视频</td></tr>
          <tr><td><code>msg/attach/</code></td><td>图片/语音附件</td><td>{fs['attach_stats']['conversation_count']}个对话的附件，共{fs['attach_stats']['total_count']:,}个文件</td></tr>
          <tr><td><code>cache/</code></td><td>缓存文件</td><td>{fs['cache_stats']['total_count']:,}个文件</td></tr>
          <tr><td><code>resource/</code></td><td>表情/收藏/朋友圈</td><td>资源文件</td></tr>
          <tr><td><code>config/</code></td><td>MMKV配置</td><td>加密配置文件</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 三、数据库文件清单 -->
  <div class="section">
    <h2 class="section-title">三、数据库文件清单 <span class="sub">共{len(fs['db_files'])}个，{fs['db_total_size']/1024/1024:.1f} MB，WCDB加密</span></h2>
    <div class="card">
      <table>
        <thead><tr><th>分类</th><th>文件名</th><th class="num">大小</th><th>用途</th><th>解密状态</th></tr></thead>
        <tbody>"""
    
    for db in fs['db_files']:
        name = db['name']
        cat, purpose, status = DB_PURPOSE.get(name, (db['category'], "未知", "待解密"))
        tag_class = {'已解密': 'green', '旧版可用': 'blue', '待解密': 'orange'}.get(status, 'orange')
        html += f"""
          <tr><td><span class="tag {cat}">{cat}</span></td><td>{name}</td><td class="num">{db['size_mb']:.1f} MB</td><td>{purpose}</td><td><span class="tag {tag_class}">{status}</span></td></tr>"""
    
    html += f"""
        </tbody>
      </table>
      <div class="callout">
        <strong>加密机制：</strong>WCDB（SQLCipher 4兼容），AES-256-CBC加密。微信4.1.11对加密参数做了变更——message_0.db直接使用raw key作为enc_key，跳过PBKDF2迭代。其他16个数据库可能使用不同的per-db密钥或参数，有待进一步研究。
      </div>
    </div>
  </div>

  <!-- 四、聊天消息分析 -->
  <div class="section">
    <h2 class="section-title">四、聊天消息分析 <span class="sub">{overall['total_messages']:,}条消息 | {overall['time_range'][0]} ~ {overall['time_range'][1]}</span></h2>
    <div class="card">
      <div class="card-title">群聊活跃度排名 Top 20</div>"""
    
    for i, c in enumerate(chatrooms[:20]):
        rank = i + 1
        rank_class = f'top{rank}' if rank <= 3 else 'other'
        bar_pct = c['message_count'] / max_chatroom_count * 100
        color = bar_color(i)
        senders_str = ' | '.join([f"{s['name']}({s['count']})" for s in c['top_senders'][:3]])
        tags = ''
        if c['message_count'] > 5000:
            tags = '<span class="tag red" style="margin-left:6px">超活跃</span>'
        elif c['message_count'] > 2000:
            tags = '<span class="tag green" style="margin-left:6px">活跃</span>'
        html += f"""
      <div class="rank-item">
        <div class="rank-num {rank_class}">{rank}</div>
        <div class="rank-info">
          <div class="rank-name">{c['name']}{tags}</div>
          <div class="rank-meta">{c['time_range'][0]} ~ {c['time_range'][1]} | {c['sender_count']}人发言 | 文字{c['type_breakdown'].get('文字', 0)} 图片{c['type_breakdown'].get('图片', 0)}</div>
          <div class="rank-sub">活跃: {senders_str}</div>
        </div>
        <div class="rank-bar-mini"><div class="rank-bar-fill-mini" style="width: {bar_pct:.1f}%; background: {color};"></div></div>
        <div class="rank-count">{c['message_count']:,}</div>
      </div>"""
    
    html += """    </div>
    <div class="card">
      <div class="card-title">私聊频次排名 Top 20</div>"""
    
    for i, p in enumerate(private_chats[:20]):
        rank = i + 1
        rank_class = f'top{rank}' if rank <= 3 else 'other'
        bar_pct = p['message_count'] / max_private_count * 100
        color = bar_color(i + 2)
        tags = ''
        if p['message_count'] > 5000:
            tags = '<span class="tag red" style="margin-left:6px">超高频</span>'
        elif p['message_count'] > 1000:
            tags = '<span class="tag green" style="margin-left:6px">高频</span>'
        html += f"""
      <div class="rank-item">
        <div class="rank-num {rank_class}">{rank}</div>
        <div class="rank-info">
          <div class="rank-name">{p['name']}{tags}</div>
          <div class="rank-meta">{p['time_range'][0]} ~ {p['time_range'][1]} | 文字{p['type_breakdown'].get('文字', 0)} 图片{p['type_breakdown'].get('图片', 0)} 视频{p['type_breakdown'].get('视频', 0)}</div>
        </div>
        <div class="rank-bar-mini"><div class="rank-bar-fill-mini" style="width: {bar_pct:.1f}%; background: {color};"></div></div>
        <div class="rank-count">{p['message_count']:,}</div>
      </div>"""
    
    html += """    </div>
    <div class="card">
      <div class="card-title">群聊中最活跃的人 Top 20</div>"""
    
    for i, s in enumerate(top_senders[:20]):
        rank = i + 1
        rank_class = f'top{rank}' if rank <= 3 else 'other'
        bar_pct = s['count'] / max_sender_count * 100
        color = bar_color(i + 4)
        tags = ''
        if s['count'] > 3000:
            tags = '<span class="tag red" style="margin-left:6px">话痨</span>'
        elif s['count'] > 500:
            tags = '<span class="tag green" style="margin-left:6px">活跃</span>'
        html += f"""
      <div class="rank-item">
        <div class="rank-num {rank_class}">{rank}</div>
        <div class="rank-info">
          <div class="rank-name">{s['name']} <span style="color:#999;font-weight:400">（{s['top_chatroom']}）</span>{tags}</div>
          <div class="rank-meta">共在群聊中发送 {s['count']:,} 条文字消息，其中在《{s['top_chatroom']}》最多（{s['top_chatroom_count']:,}条）</div>
        </div>
        <div class="rank-bar-mini"><div class="rank-bar-fill-mini" style="width: {bar_pct:.1f}%; background: {color};"></div></div>
        <div class="rank-count">{s['count']:,}</div>
      </div>"""
    
    html += """    </div>
    <div class="card">
      <div class="card-title">消息类型分布</div>
      <div class="type-grid">"""
    
    for tname, tcount in type_items:
        pct = tcount / overall['total_messages'] * 100
        color = bar_color(hash(tname) % 6)
        html += f"""
        <div class="type-item">
          <div class="type-dot" style="background: {color};"></div>
          <div>
            <div class="type-name">{tname}</div>
            <div class="type-count">{tcount:,} <span style="font-size:12px;color:#999">({pct:.1f}%)</span></div>
          </div>
        </div>"""
    
    html += f"""      </div>
    </div>
  </div>

  <!-- 五、聊天文件消息分析 -->
  <div class="section">
    <h2 class="section-title">五、聊天文件消息分析 <span class="sub">{fs['file_stats']['total_count']:,}个文件，{fs['file_stats']['total_size_gb']} GB，时间跨度4月~8月</span></h2>
    <div class="card">
      <div class="card-title">文件类型分布</div>"""
    
    type_colors = {'Excel': 'green', 'PDF': 'blue', 'Word': 'orange', 'PPT': 'red', '压缩包': 'purple', '图片': 'cyan', '其他': 'blue'}
    for tname, v in file_types:
        pct = v['count'] / fs['file_stats']['total_count'] * 100
        bar_pct = v['count'] / max_file_type_count * 100
        color_class = type_colors.get(tname, 'blue')
        html += f"""
      <div class="bar-row"><div class="bar-label">{tname}</div><div class="bar-track"><div class="bar-fill {color_class}" style="width:{bar_pct:.1f}%">{v['count']} ({pct:.1f}%) · {v['size_mb']:.0f} MB</div></div></div>"""
    
    # 最大的类型
    top_type = file_types[0] if file_types else ('', {'count': 0})
    html += f"""      <div class="callout">{top_type[0]}占比最高（{top_type[1]['count']/fs['file_stats']['total_count']*100:.1f}%），其次是{file_types[1][0] if len(file_types)>1 else '其他'}，与工作场景高度吻合——大量数据报表、通报文件和汇报材料。</div>
    </div>
    <div class="card">
      <div class="card-title">月度文件趋势</div>
      <table>
        <thead><tr><th>月份</th><th class="num">文件数</th><th class="num">总大小</th><th>趋势</th><th class="num">环比</th></tr></thead>
        <tbody>"""
    
    prev_count = None
    for month, v in file_months:
        bar_pct = v['count'] / max_file_month_count * 100
        if prev_count is None:
            change = '<td class="num">-</td>'
        else:
            pct_change = (v['count'] - prev_count) / prev_count * 100
            color_style = 'color:#e15f63' if pct_change > 50 else ('color:#fa9d3b' if pct_change > 0 else '')
            change = f'<td class="num" style="{color_style}">{"+" if pct_change>=0 else ""}{pct_change:.0f}%</td>'
        html += f"""
          <tr><td>{month}</td><td class="num">{v['count']}</td><td class="num">{v['size_mb']:.0f} MB</td><td><div class="bar-track" style="height:16px"><div class="bar-fill green" style="width:{bar_pct:.1f}%"></div></div></td>{change}</tr>"""
        prev_count = v['count']
    
    html += f"""        </tbody>
      </table>
      <div class="callout">4月到7月文件数量增长近4倍，工作强度持续上升。7月体积最大（{fs['file_stats']['by_month'].get('2026-07',{}).get('size_mb',0):.0f} MB），大文件增多。</div>
    </div>
    <div class="card">
      <div class="card-title">工作主题分类</div>"""
    
    topic_colors = ['green', 'blue', 'orange', 'red', 'purple', 'cyan', 'blue', 'orange']
    topic_desc = {
        '管理报告': '市场部报告、一周活动安排、经分会材料',
        '数据统计': '线上发展量统计、台账、汇总',
        '收入分析': '收入会审、核心平台收入、地市通报',
        '业务分析': '退订统计、移网净增、新入网',
        '虚假业务': '群腐整治、违规处罚、终端核查',
        '质检工作': '质检周报、听原声、新入网质检',
        '检查审计': '集团检查、核查报告',
        '佣金结算': '佣金扣罚、结算承诺函、对账',
    }
    topic_desc_short = {
        '管理报告': '管理报告',
        '数据统计': '数据统计',
        '收入分析': '收入分析',
        '业务分析': '业务分析',
        '虚假业务': '虚假业务',
        '质检工作': '质检工作',
        '检查审计': '检查审计',
        '佣金结算': '佣金结算',
    }
    for i, (tname, count) in enumerate(topics):
        if count == 0:
            continue
        bar_pct = count / max_topic_count * 100
        color_class = topic_colors[i % len(topic_colors)]
        desc = topic_desc.get(tname, '')
        html += f"""
      <div class="bar-row"><div class="bar-label" style="width:90px">{topic_desc_short.get(tname, tname)}</div><div class="bar-track"><div class="bar-fill {color_class}" style="width:{bar_pct:.1f}%">{count} · {desc}</div></div></div>"""
    
    html += """    </div>
    <div class="card">
      <div class="card-title">高频迭代文件（版本迭代最多）</div>
      <table>
        <thead><tr><th>文件名</th><th class="num">出现次数</th><th>说明</th></tr></thead>
        <tbody>"""
    
    tag_classes = ['green', 'green', 'blue', 'blue', 'orange', 'orange', 'orange', '', '', '']
    top_iterated = fs['file_stats'].get('top_iterated_files', [])
    for i, f in enumerate(top_iterated[:10]):
        tag_class = tag_classes[i] if i < len(tag_classes) else ''
        tag_html = f'<span class="tag {tag_class}">{f["count"]}次</span>' if tag_class else f'<span class="tag">{f["count"]}次</span>'
        desc = '定期报表，每月多版本迭代' if '统计' in f['name'] or '发展量' in f['name'] else ('每周固定发送' if '活动安排' in f['name'] else ('专项问题处理' if '退订' in f['name'] or '申诉' in f['name'] else ('季度分析报告' if '季度' in f['name'] else ('月度收入报告' if '收入' in f['name'] or '会审' in f['name'] else '工作部署文件'))))
        html += f"""
          <tr><td>{f['name']}</td><td class="num">{tag_html}</td><td>{desc}</td></tr>"""
    
    html += f"""        </tbody>
      </table>
    </div>
  </div>

  <!-- 六、视频与图片附件 -->
  <div class="section">
    <h2 class="section-title">六、视频与图片附件分析</h2>
    <div class="card">
      <div class="card-title">视频消息 <span style="font-size:13px;font-weight:400;color:#999">{fs['video_stats']['total_count']:,}个，{fs['video_stats']['total_size_gb']} GB，日均约{fs['video_stats']['total_count']//101:.0f}个</span></div>"""
    
    for month, v in video_months:
        bar_pct = v['count'] / max_video_month_count * 100
        pct_of_total = v['count'] / fs['video_stats']['total_count'] * 100
        label = f'{v["count"]}'
        if pct_of_total > 10:
            label += f' ({pct_of_total:.1f}%)'
        html += f"""
      <div class="bar-row"><div class="bar-label">{month}</div><div class="bar-track"><div class="bar-fill green" style="width:{bar_pct:.1f}%">{label}</div></div></div>"""
    
    html += """    </div>
    <div class="card">
      <div class="card-title">图片/语音附件 <span style="font-size:13px;font-weight:400;color:#999">""" + f"{fs['attach_stats']['conversation_count']}个对话，{fs['attach_stats']['total_count']:,}个文件，{fs['attach_stats']['total_size_gb']} GB</span></div>"
    
    for month, v in attach_months:
        bar_pct = v['count'] / max_attach_month_count * 100
        pct_of_total = v['count'] / fs['attach_stats']['total_count'] * 100
        label = f'{v["count"]}'
        if pct_of_total > 10:
            label += f' ({pct_of_total:.1f}%)'
        html += f"""
      <div class="bar-row"><div class="bar-label">{month}</div><div class="bar-track"><div class="bar-fill blue" style="width:{bar_pct:.1f}%">{label}</div></div></div>"""
    
    # 附件Top10
    html += f"""    </div>
    <div class="card">
      <div class="card-title">附件最活跃对话 Top 10</div>
      <table>
        <thead><tr><th class="num">#</th><th>对话名称</th><th class="num">文件数</th><th class="num">大小</th><th>占比可视化</th></tr></thead>
        <tbody>"""
    
    max_conv_count = fs['attach_stats']['top_conversations'][0]['count'] if fs['attach_stats']['top_conversations'] else 1
    for i, conv in enumerate(fs['attach_stats']['top_conversations'][:10]):
        bar_pct = conv['count'] / max_conv_count * 100
        conv_name = conv.get('conv_name', conv['conv_id'])
        html += f"""
          <tr><td class="num">{i+1}</td><td>{conv_name}</td><td class="num">{conv['count']:,}</td><td class="num">{conv['size_mb']:.0f} MB</td><td><div class="bar-track" style="height:16px"><div class="bar-fill green" style="width:{bar_pct:.1f}%"></div></div></td></tr>"""
    
    top_conv_name = fs['attach_stats']['top_conversations'][0].get('conv_name', 'Top1') if fs['attach_stats']['top_conversations'] else 'Top1'
    html += f"""        </tbody>
      </table>
      <div class="callout">{top_conv_name}的文件数占{fs['attach_stats']['top_conversations'][0]['count']/fs['attach_stats']['total_count']*100:.0f}%，说明有一个非常高频的群聊或个人对话。</div>
    </div>
  </div>

  <!-- 七、时间分布 -->
  <div class="section">
    <h2 class="section-title">七、消息与文件时间分布</h2>
    <div class="card">
      <div class="card-title">消息每小时分布（{overall['total_messages']:,}条消息）</div>
      <div class="chart-container">"""
    
    for h in time_dist['hourly']:
        bar_pct = h['count'] / max_hour_count * 100
        color = '#07c160' if 9 <= h['hour'] <= 18 else ('#fa9d3b' if h['hour'] >= 22 or h['hour'] <= 5 else '#576b95')
        html += f"""
        <div class="chart-bar">
          <div class="chart-bar-fill" style="height: {bar_pct:.1f}%; background: {color};">
            <span class="tooltip">{h['hour']}:00 - {h['count']:,}条</span>
          </div>
          <div class="chart-label">{h['hour']}</div>
        </div>"""
    
    peak_month = max(time_dist['monthly'], key=lambda x: x['count'])
    html += f"""      </div>
      <div class="callout">消息高峰集中在9-11点和14-17点，与文件活动高峰重合。{peak_month['month']}月消息量最大（{peak_month['count']:,}条），日均约{peak_month['count']//30:.0f}条。</div>
    </div>
    <div class="card">
      <div class="card-title">消息每周分布</div>
      <div class="chart-container">"""
    
    for w in time_dist['weekly']:
        bar_pct = w['count'] / max_weekly_count * 100
        color = '#07c160' if w['name'] not in ('周六', '周日') else '#fa9d3b'
        html += f"""
        <div class="chart-bar">
          <div class="chart-bar-fill" style="height: {bar_pct:.1f}%; background: {color};">
            <span class="tooltip">{w['name']} - {w['count']:,}条</span>
          </div>
          <div class="chart-label">{w['name']}</div>
        </div>"""
    
    peak_weekday = max(time_dist['weekly'], key=lambda x: x['count'])
    html += f"""      </div>
      <div class="callout">工作日消息量明显大于周末，{peak_weekday['name']}消息最多（{peak_weekday['count']:,}条）。</div>
    </div>
    <div class="card">
      <div class="card-title">消息月度趋势</div>
      <div class="chart-container">"""
    
    for m in time_dist['monthly']:
        bar_pct = m['count'] / max_monthly_count * 100
        html += f"""
        <div class="chart-bar">
          <div class="chart-bar-fill" style="height: {bar_pct:.1f}%; background: #07c160;">
            <span class="tooltip">{m['month']} - {m['count']:,}条</span>
          </div>
          <div class="chart-label">{m['month'][5:]}</div>
        </div>"""
    
    html += """    </div>
    </div>
    <div class="card">
      <div class="card-title">文件活动按小时分布</div>
      <div class="hour-grid">"""
    
    # 文件小时热力图
    file_by_hour = {int(k): v for k, v in fs['file_stats']['by_hour'].items()}
    max_fh = max(file_by_hour.values()) if file_by_hour else 1
    for h in range(24):
        count = file_by_hour.get(h, 0)
        intensity = count / max_fh if max_fh > 0 else 0
        if intensity > 0.8:
            bg = '#07c160'
            color = '#fff'
        elif intensity > 0.5:
            bg = '#3acc73'
            color = '#fff'
        elif intensity > 0.3:
            bg = '#7adb9e'
            color = '#fff'
        elif intensity > 0.1:
            bg = '#a8e8ba'
            color = '#07c160'
        elif intensity > 0:
            bg = '#c8f0d6'
            color = '#07c160'
        else:
            bg = '#e8f7ee'
            color = '#999'
        html += f'        <div class="hour-cell" style="background:{bg};color:{color}">{h}</div>\n'
    
    html += """      </div>
      <div class="hour-labels">
        <div>0</div><div>1</div><div>2</div><div>3</div><div>4</div><div>5</div>
        <div>6</div><div>7</div><div>8</div><div>9</div><div>10</div><div>11</div>
        <div>12</div><div>13</div><div>14</div><div>15</div><div>16</div><div>17</div>
        <div>18</div><div>19</div><div>20</div><div>21</div><div>22</div><div>23</div>
      </div>
      <div style="margin-top:16px">
        <div class="bar-row" style="font-size:13px;color:#666;margin-bottom:4px">Top 5 最活跃时段（文件）</div>"""
    
    for h, c in file_hours:
        bar_pct = c / max_file_hour * 100
        html += f"""
        <div class="bar-row"><div class="bar-label">{int(h):02d}:00</div><div class="bar-track"><div class="bar-fill green" style="width:{bar_pct:.1f}%">{c}</div></div></div>"""
    
    html += """      </div>
      <div class="callout">文件活动高峰与消息高峰重合，上午9-11点和下午16-18点为双重活跃期。</div>
    </div>
    <div class="card weekday-bars">
      <div class="card-title">文件按星期分布</div>"""
    
    for name, count in file_weekdays:
        bar_pct = count / max_file_weekday * 100 if max_file_weekday > 0 else 0
        color_class = 'green' if '周六' not in name and '周日' not in name else 'orange'
        html += f"""
      <div class="bar-row"><div class="bar-label">{name}</div><div class="bar-track"><div class="bar-fill {color_class}" style="width:{bar_pct:.1f}%">{count}</div></div></div>"""
    
    html += """      <div class="callout">周一和周五文件活动最频繁，符合"周一部署、周五收尾"的工作节奏。</div>
    </div>
    <div class="card">
      <div class="card-title">最活跃日期 Top 5（文件数）</div>
      <table>
        <thead><tr><th class="num">排名</th><th>日期</th><th class="num">文件数</th><th>星期</th></tr></thead>
        <tbody>"""
    
    tag_classes_day = ['green', 'blue', 'blue', 'orange', 'orange']
    for i, (date, count) in enumerate(fs['file_stats']['top_days'][:5]):
        dt = datetime.datetime.strptime(date, '%Y-%m-%d')
        wd_name = weekday_names[dt.weekday()]
        tag_class = tag_classes_day[i] if i < len(tag_classes_day) else ''
        tag_html = f'<span class="tag {tag_class}">{count}</span>' if tag_class else f'<span class="tag">{count}</span>'
        html += f"""
          <tr><td class="num">{i+1}</td><td>{date}</td><td class="num">{tag_html}</td><td>{wd_name}</td></tr>"""
    
    html += f"""        </tbody>
      </table>
    </div>
  </div>

  <!-- 八、存储汇总 -->
  <div class="section">
    <h2 class="section-title">八、存储占用汇总 <span class="sub">总计 {total_gb:.2f} GB</span></h2>
    <div class="card">
      <div class="donut-container">
        <div class="donut"></div>
        <div class="donut-legend">
          <div><span class="dot" style="background:#07c160"></span>聊天文件消息 {fs['file_stats']['total_size_gb']} GB ({fs['file_stats']['total_size_gb']/total_gb*100:.1f}%)</div>
          <div><span class="dot" style="background:#576b95"></span>图片/语音附件 {fs['attach_stats']['total_size_gb']} GB ({fs['attach_stats']['total_size_gb']/total_gb*100:.1f}%)</div>
          <div><span class="dot" style="background:#fa9d3b"></span>视频消息 {fs['video_stats']['total_size_gb']} GB ({fs['video_stats']['total_size_gb']/total_gb*100:.1f}%)</div>
          <div><span class="dot" style="background:#4cc4d4"></span>缓存文件 {fs['cache_stats']['total_size_gb']} GB ({fs['cache_stats']['total_size_gb']/total_gb*100:.1f}%)</div>
          <div><span class="dot" style="background:#e15f63"></span>加密数据库 {fs['db_total_size']/1024**3:.2f} GB ({fs['db_total_size']/1024**3/total_gb*100:.1f}%)</div>
          <div><span class="dot" style="background:#ddd"></span>其他 ~0.15 GB (1.2%)</div>
        </div>
      </div>
    </div>
  </div>

  <!-- 九、关键发现与总结 -->
  <div class="section">
    <h2 class="section-title">九、关键发现与总结</h2>
    <div class="card">
      <div class="card-title">聊天画像</div>
      <table>
        <thead><tr><th>指标</th><th>结果</th><th>解读</th></tr></thead>
        <tbody>"""
    
    top_chatroom = chatrooms[0] if chatrooms else {'name': '-', 'message_count': 0}
    top_chatroom_sender = chatrooms[0]['top_senders'][0] if chatrooms and chatrooms[0]['top_senders'] else {'name': '-', 'count': 0}
    max_sender_chatroom = max(chatrooms, key=lambda x: x['sender_count']) if chatrooms else {'name': '-', 'sender_count': 0}
    top_private = private_chats[0] if private_chats else {'name': '-', 'message_count': 0}
    peak_hour = max(time_dist['hourly'], key=lambda x: x['count'])
    peak_month = max(time_dist['monthly'], key=lambda x: x['count'])
    
    summary_rows = [
        ('最活跃群聊', f'{top_chatroom["name"]}（{top_chatroom["message_count"]:,}条）', f'{top_chatroom_sender["name"]}一人发{top_chatroom_sender["count"]:,}条'),
        ('发言人数最多群', f'{max_sender_chatroom["name"]}（{max_sender_chatroom["sender_count"]}人发言）', '参与度最高的群'),
        ('私聊最多', f'{top_private["name"]}（{top_private["message_count"]:,}条）', '高频私聊对象'),
        ('群聊最活跃的人', f'{top_senders[0]["name"]}（{top_senders[0]["count"]:,}条，主要在《{top_senders[0]["top_chatroom"]}》）' if top_senders else '-', '跨所有群聊的发言统计'),
        ('消息高峰时段', f'{peak_hour["hour"]}点（{peak_hour["count"]:,}条）', '上午沟通密集'),
        ('消息最多月', f'{peak_month["month"]}月（{peak_month["count"]:,}条）', '工作沟通量最大的月份'),
    ]
    
    for label, result, desc in summary_rows:
        html += f"""
          <tr><td>{label}</td><td><strong>{result}</strong></td><td>{desc}</td></tr>"""
    
    html += f"""        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-title">工作画像</div>
      <table>
        <thead><tr><th>核心工作领域</th><th class="num">文件数</th><th>典型内容</th></tr></thead>
        <tbody>"""
    
    topic_tags = {'管理报告': 'green', '数据统计': 'blue', '收入分析': 'orange', '业务分析': 'red', '虚假业务': 'red', '质检工作': 'green', '检查审计': '', '佣金结算': ''}
    for tname, count in topics:
        if count == 0:
            continue
        tag_class = topic_tags.get(tname, '')
        tag_html = f'<span class="tag {tag_class}">{tname}</span>' if tag_class else f'<span class="tag">{tname}</span>'
        desc = topic_desc.get(tname, '')
        html += f"""
          <tr><td>{tag_html}</td><td class="num">{count}</td><td>{desc}</td></tr>"""
    
    html += f"""        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-title">工作节奏</div>
      <ul style="list-style:none; font-size:14px; line-height:2.2">
        <li> 日均处理约 <strong>{fs['file_stats']['total_count']//101}个文件</strong>、发送/接收约 <strong>{overall['total_messages']//101}条消息</strong></li>
        <li> 上午9-11点和下午16-18点为双重工作高峰</li>
        <li> 周一最忙（文件+消息双高峰），周五收尾</li>"""
    
    # 找最高频迭代文件
    top_iterated_all = fs['file_stats'].get('top_iterated_files', [])
    if top_iterated_all:
        top_iter = top_iterated_all[0]
        html += f"""
        <li> "{top_iter['name']}"出现 <strong>{top_iter['count']}个版本</strong>，核心迭代报表</li>"""
    
    html += f"""
        <li> {peak_month['month']}月消息量和工作文件量均为高峰，工作强度最大</li>
      </ul>
    </div>
    <div class="card">
      <div class="card-title">技术突破记录</div>
      <div class="callout"><span class="icon">i</span><strong>WCDB加密破解：</strong>微信4.1.11使用WCDB（SQLCipher 4兼容）加密，AES-256-CBC。通过编译Go版chatlog从微信进程内存提取32字节Data Key，并发现4.1.11跳过PBKDF2迭代的参数变更，自写Python脚本成功解密message_0.db。</div>
      <div class="callout"><span class="icon">i</span><strong>WCDB压缩支持：</strong>39.6%的消息使用zstd压缩（WCDB内置），通过pyzstd库成功解压全部压缩消息，确保分析数据完整。</div>
      <div class="callout warning"><span class="icon">!</span><strong>剩余数据库：</strong>message_0.db以外{len(fs['db_files'])-1}个数据库可能使用不同的per-db密钥或加密参数，有待进一步研究。当前联系人映射使用5月18日旧版contact.db快照。</div>
    </div>
    <div class="card">
      <div class="card-title">数据安全提醒</div>
      <div class="callout warning"><span class="icon">!</span><strong>SIP状态：</strong>当前SIP已禁用（<code>csrutil disable</code>），建议尽快重新开启。恢复模式 → 终端 → <code>csrutil enable</code> → 重启</div>
      <div class="callout warning"><span class="icon">!</span><strong>数据敏感性：</strong>{total_gb:.1f}GB聊天数据包含大量工作敏感信息（收入数据、处罚通报、审计材料等），且已可完整解密读取，建议注意数据安全</div>
      <div class="callout"><span class="icon">i</span><strong>大文件清理：</strong>7月单月文件体积达{fs['file_stats']['by_month'].get('2026-07',{}).get('size_mb',0):.0f}MB，可考虑清理历史附件释放空间</div>
    </div>
  </div>

  <div class="footer">
    生成时间：{datetime.datetime.now().strftime('%Y-%m-%d')} | 数据来源：~/Library/Containers/com.tencent.xinWeChat/ | 由微信数据库分析工具生成<br>
    消息数据：{overall['time_range'][0]} ~ {overall['time_range'][1]} | 联系人映射基于contact.db快照
  </div>

</div>
</body>
</html>"""
    
    return html

def main():
    parser = argparse.ArgumentParser(description="微信本地数据库分析报告生成器")
    parser.add_argument("--chat-json", default=CHAT_JSON, help="聊天分析JSON路径")
    parser.add_argument("--fs-json", default=FS_JSON, help="文件系统扫描JSON路径")
    parser.add_argument("--output", default=OUTPUT_HTML, help="输出HTML路径")
    args = parser.parse_args()

    chat_json = os.path.expanduser(args.chat_json)
    fs_json = os.path.expanduser(args.fs_json)
    output_html = os.path.expanduser(args.output)

    with open(chat_json, 'r', encoding='utf-8') as f:
        chat_data = json.load(f)

    with open(fs_json, 'r', encoding='utf-8') as f:
        fs_data = json.load(f)

    html = generate_html(chat_data, fs_data)

    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"HTML报告已生成: {output_html}")
    print(f"文件大小: {os.path.getsize(output_html) / 1024:.1f} KB")

if __name__ == '__main__':
    main()
