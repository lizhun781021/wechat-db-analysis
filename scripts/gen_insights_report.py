#!/usr/bin/env python3
"""
微信聊天深度分析报告生成器
===========================
基于 deep_analysis.py 输出的 JSON，生成多区块综合 HTML 报告。
包含 12 个分析维度的可视化展示。

用法：
    python3 gen_insights_report.py --analysis-json deep_result.json --output report.html
"""

import json
import datetime
import os
import argparse


def esc(text):
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def rank_class(i):
    return ["top1", "top2", "top3", "other"][min(i, 3)]


def generate_report(data, generated_at):
    overall = data.get('overall', {})
    trend = data.get('trend', {})
    chatrooms = data.get('chatrooms', [])
    private_chats = data.get('private_chats', [])
    top_senders = data.get('top_senders', [])
    dormant = data.get('dormant_contacts', [])
    unreplied = data.get('unreplied_chats', [])
    group_topics = data.get('group_topics', [])
    commitments = data.get('commitments', [])
    opportunities = data.get('business_opportunities', [])
    profiles = data.get('contact_profiles', [])
    group_cls = data.get('group_classification', {})
    date_range = data.get('date_range', ['', ''])

    # 对话摘要
    conv_summaries = data.get('conversation_summaries', [])

    # 扩展分析数据
    response_times = data.get('response_times', [])
    relationships = data.get('relationship_temperature', [])
    best_times = data.get('best_contact_times', [])
    directions = data.get('conversation_directions', [])
    repeated_q = data.get('repeated_questions', [])
    links = data.get('link_sharing', [])
    file_flow = data.get('file_flow', [])
    meetings = data.get('meetings', [])
    influence = data.get('influence_map', [])
    bridges = data.get('bridge_persons', [])
    circles = data.get('circle_discovery', [])
    sensitive = data.get('sensitive_info', [])
    anomalies = data.get('anomaly_detection', [])
    commit_track = data.get('commitment_tracking', {})
    voice_ratios = data.get('voice_ratio', [])
    night_contacts = data.get('late_night_contacts', [])
    one_time = data.get('one_time_contacts', [])

    total = overall.get('total_messages', 0)
    dr_text = f"{date_range[0]} ~ {date_range[1]}" if date_range[0] else "全量"

    # --- 概览卡片 ---
    overview_cards = []
    cards = [
        ("总消息", total, "#07c160"),
        ("活跃群聊", overall.get('total_chatrooms', 0), "#576b95"),
        ("活跃私聊", overall.get('total_private_chats', 0), "#fa9d3b"),
        ("沉寂联系人", len(dormant), "#e15f63"),
        ("未回复私聊", len(unreplied), "#ff7043"),
        ("商机线索", len(opportunities), "#ff6b6b"),
        ("承诺待办", len(commitments), "#8a6de9"),
        ("消息类型", len(overall.get('type_breakdown', {})), "#4cc4d4"),
    ]
    for label, num, color in cards:
        overview_cards.append(f"""
        <div class="stat-card">
          <div class="stat-num" style="color:{color}">{num}</div>
          <div class="stat-label">{label}</div>
        </div>""")

    # --- 日趋势图 ---
    daily = trend.get('daily', [])
    daily_bars = ""
    if daily:
        max_daily = max(d['count'] for d in daily) or 1
        for d in daily:
            h = d['count'] / max_daily * 100
            label = d['date'][5:]  # MM-DD
            daily_bars += f"""
            <div class="trend-bar">
              <div class="trend-bar-fill" style="height:{h:.1f}%"></div>
              <div class="trend-bar-label">{label}</div>
              <div class="trend-bar-count">{d['count']}</div>
            </div>"""

    # --- 小时分布 ---
    hourly = trend.get('hourly', [])
    hour_cells = ""
    if hourly:
        max_h = max(h['count'] for h in hourly) or 1
        for h in hourly:
            intensity = h['count'] / max_h
            if h['count'] == 0: bg, fg = "#f0f2f5", "#bbb"
            elif intensity > 0.8: bg, fg = "#07c160", "#fff"
            elif intensity > 0.5: bg, fg = "#4fd08d", "#fff"
            elif intensity > 0.2: bg, fg = "#9ae3b8", "#fff"
            else: bg, fg = "#cdeeda", "#666"
            hour_cells += f'<div class="hour-cell" style="background:{bg};color:{fg}">{h["count"]}</div>'
    hour_labels = "".join(f'<div>{h:02d}</div>' for h in range(24))

    # --- 群聊 Top 10 ---
    chatroom_html = ""
    max_cc = max((c['message_count'] for c in chatrooms[:10]), default=1)
    for i, c in enumerate(chatrooms[:10]):
        pct = c['message_count'] / max_cc * 100
        chatroom_html += f"""
        <div class="rank-item">
          <div class="rank-num {rank_class(i)}">{i+1}</div>
          <div class="rank-info">
            <div class="rank-name">{esc(c['name'])}</div>
            <div class="rank-meta">{c.get('sender_count',0)}人发言</div>
            <div class="bar-track"><div class="bar-fill green" style="width:{pct:.1f}%"></div></div>
          </div>
          <div class="rank-count">{c['message_count']}</div>
        </div>"""

    # --- 私聊 Top 10 ---
    private_html = ""
    max_pc = max((p['message_count'] for p in private_chats[:10]), default=1)
    for i, p in enumerate(private_chats[:10]):
        pct = p['message_count'] / max_pc * 100
        private_html += f"""
        <div class="rank-item">
          <div class="rank-num {rank_class(i)}">{i+1}</div>
          <div class="rank-info">
            <div class="rank-name">{esc(p['name'])}</div>
            <div class="rank-meta">最后联系 {esc(p.get('last_time','')[:10] or '')}</div>
            <div class="bar-track"><div class="bar-fill blue" style="width:{pct:.1f}%"></div></div>
          </div>
          <div class="rank-count">{p['message_count']}</div>
        </div>"""

    # --- 跨群活跃成员 ---
    sender_html = ""
    max_sc = max((s['count'] for s in top_senders[:10]), default=1)
    for i, s in enumerate(top_senders[:10]):
        pct = s['count'] / max_sc * 100
        sender_html += f"""
        <div class="rank-item">
          <div class="rank-num {rank_class(i)}">{i+1}</div>
          <div class="rank-info">
            <div class="rank-name">{esc(s['name'])}</div>
            <div class="rank-meta">主要活跃于：{esc(s.get('top_chatroom',''))}</div>
            <div class="bar-track"><div class="bar-fill orange" style="width:{pct:.1f}%"></div></div>
          </div>
          <div class="rank-count">{s['count']}</div>
        </div>"""

    # --- 群话题热点 ---
    topics_html = ""
    for t in group_topics:
        kws = " · ".join(f'<span class="topic-tag">{esc(kw["keyword"])}<span class="topic-count">{kw["count"]}</span></span>'
                         for kw in t.get('keywords', [])[:8])
        topics_html += f"""
        <div class="topic-card">
          <div class="topic-group">{esc(t['group'])} <span class="topic-msg">({t['message_count']}条)</span></div>
          <div class="topic-keywords">{kws}</div>
        </div>"""

    # --- 商机挖掘 ---
    opp_html = ""
    opp_type_colors = {
        "需求意向": "#ff6b6b", "产品咨询": "#4cc4d4", "采购招标": "#fa9d3b",
        "竞品线索": "#e15f63", "合作意向": "#07c160", "流失预警": "#ff7043",
    }
    for o in opportunities[:30]:
        type_tags = "".join(
            f'<span class="opp-type" style="background:{opp_type_colors.get(t, "#999")}">{esc(t)}</span>'
            for t in o.get('opportunity_types', []))
        kw_tags = " ".join(f'<span class="opp-kw">{esc(kw)}</span>' for kw in o.get('keywords', [])[:5])
        mine_tag = '<span class="mine-tag">我发的</span>' if o.get('is_mine') else ""
        opp_html += f"""
        <div class="opp-item">
          <div class="opp-header">
            <span class="opp-sender">{esc(o['sender'])}</span>
            <span class="opp-context">@ {esc(o['context'])}</span>
            <span class="opp-time">{esc(o['time'])}</span>
            {mine_tag}
          </div>
          <div class="opp-types">{type_tags}</div>
          <div class="opp-content">{esc(o['content'])}</div>
          <div class="opp-keywords">{kw_tags}</div>
        </div>"""

    # --- 承诺与待办 ---
    commit_html = ""
    for c in commitments[:30]:
        mine_tag = '<span class="mine-tag">我的承诺</span>' if c.get('is_mine') else ""
        commit_html += f"""
        <div class="commit-item">
          <div class="commit-header">
            <span class="commit-sender">{esc(c['sender'])}</span>
            <span class="commit-context">@ {esc(c['context'])}</span>
            <span class="commit-time">{esc(c['time'])}</span>
            {mine_tag}
          </div>
          <div class="commit-content">{esc(c['content'])}</div>
        </div>"""

    # --- 未回复私聊 ---
    unreplied_html = ""
    for u in unreplied:
        urgency = "高" if u['hours_ago'] >= 24 else "中" if u['hours_ago'] >= 6 else "低"
        urgency_color = "#e15f63" if urgency == "高" else "#fa9d3b" if urgency == "中" else "#4cc4d4"
        unreplied_html += f"""
        <div class="alert-item">
          <div class="alert-badge" style="background:{urgency_color}">{urgency}</div>
          <div class="alert-info">
            <div class="alert-name">{esc(u['name'])}</div>
            <div class="alert-meta">{u['hours_ago']}小时前 · {esc(u.get('last_content','')[:60])}</div>
          </div>
        </div>"""

    # --- 沉寂联系人 ---
    dormant_html = ""
    for d in dormant[:20]:
        level = "严重" if d['days_since'] >= 30 else "较高" if d['days_since'] >= 14 else "一般"
        level_color = "#e15f63" if level == "严重" else "#fa9d3b" if level == "较高" else "#4cc4d4"
        dormant_html += f"""
        <div class="alert-item">
          <div class="alert-badge" style="background:{level_color}">{level}</div>
          <div class="alert-info">
            <div class="alert-name">{esc(d['name'])}</div>
            <div class="alert-meta">{d['days_since']}天未联系 · 共{d['total_messages']}条 · 最后：{esc(d['last_message_date'])}</div>
          </div>
        </div>"""

    # --- 联系人画像 ---
    profile_html = ""
    for p in profiles[:15]:
        type_chips = " ".join(f'<span class="profile-type">{esc(k)}</span>' for k in list(p.get('type_breakdown',{}).keys())[:4])
        profile_html += f"""
        <div class="profile-item">
          <div class="profile-name">{esc(p['name'])}</div>
          <div class="profile-stats">
            <span>共{p['total_messages']}条</span>
            <span>日均{p['avg_daily']}条</span>
            <span>活跃{p['active_days']}天</span>
            <span>{esc(p['first_contact'])} → {esc(p['last_contact'])}</span>
          </div>
          <div class="profile-types">{type_chips}</div>
        </div>"""

    # --- 群分类 ---
    cls_labels = {"work": "工作群", "shopping": "购物群", "family": "家庭群", "social": "社交群", "other": "其他群"}
    cls_colors = {"work": "#07c160", "shopping": "#fa9d3b", "family": "#e15f63", "social": "#8a6de9", "other": "#95a5a6"}
    cls_html = ""
    for cat, label in cls_labels.items():
        groups = group_cls.get(cat, [])
        if not groups:
            continue
        total_msgs = sum(g['message_count'] for g in groups)
        group_chips = " ".join(
            f'<span class="cls-chip" style="border-color:{cls_colors[cat]}">{esc(g["name"])} ({g["message_count"]})</span>'
            for g in groups[:15])
        cls_html += f"""
        <div class="cls-section">
          <div class="cls-title" style="color:{cls_colors[cat]}">{label}（{len(groups)}个群 · {total_msgs}条消息）</div>
          <div class="cls-chips">{group_chips}</div>
        </div>"""

    # --- 消息类型分布 ---
    type_items = list(overall.get('type_breakdown', {}).items())[:8]
    type_colors_map = {"文字":"#07c160","图片":"#576b95","语音":"#fa9d3b","视频":"#e15f63",
                        "文件":"#8a6de9","表情包":"#4cc4d4","名片":"#d4a017","位置":"#2c9f9f",
                        "语音通话":"#e91e63","系统消息":"#9e9e9e","链接卡片":"#576b95"}
    type_chips_html = ""
    for name, cnt in type_items:
        pct = cnt / total * 100 if total else 0
        color = type_colors_map.get(name, "#95a5a6")
        type_chips_html += f"""
        <div class="type-chip">
          <span class="type-dot" style="background:{color}"></span>
          <span class="type-name">{esc(name)}</span>
          <span class="type-count">{cnt}</span>
          <span class="type-pct">{pct:.1f}%</span>
        </div>"""

    # --- 组装 HTML ---

    # --- 对话摘要 HTML ---
    conv_summary_html = ""
    for cs in conv_summaries:
        chat_type = "群聊" if cs.get('is_group') else "私聊"
        type_color = "#07c160" if cs.get('is_group') else "#576b95"
        seg_html = ""
        for seg in cs.get('summaries', []):
            s = seg.get('summary', {})
            raw = seg.get('raw', '')
            seg_html += f"""
            <div class="conv-seg">
              <div class="conv-seg-time">{esc(seg['time_range'])} · {seg['message_count']}条消息</div>
              <div class="conv-seg-body">{esc(raw)}</div>
            </div>"""
        conv_summary_html += f"""
        <div class="conv-card">
          <div class="conv-header">
            <span class="conv-type" style="background:{type_color}">{chat_type}</span>
            <span class="conv-name">{esc(cs['chat_name'])}</span>
            <span class="conv-meta">{cs['total_messages']}条消息 · {cs.get('segment_count',0)}段对话</span>
          </div>
          {seg_html}
        </div>"""

    # === 扩展分析 HTML 生成 ===

    # 13. 响应时长
    response_html = ""
    for r in response_times[:15]:
        my_min = r.get('my_avg_reply_min')
        their_min = r.get('their_avg_reply_min')
        response_html += f"""
        <div class="rank-item">
          <div class="rank-info">
            <div class="rank-name">{esc(r['name'])}</div>
            <div class="rank-meta">我回复平均 {my_min or '—'}分钟 · 对方回复平均 {their_min or '—'}分钟</div>
          </div>
        </div>"""

    # 14. 关系温度计
    temp_colors = {"升温": "#07c160", "降温": "#e15f63", "稳定": "#576b95", "停滞": "#fa9d3b"}
    temp_emojis = {"升温": "↑", "降温": "↓", "稳定": "→", "停滞": "—"}
    relation_html = ""
    for r in relationships[:15]:
        trend = r['trend']
        color = temp_colors.get(trend, "#999")
        emoji = temp_emojis.get(trend, "?")
        weekly = " · ".join(f"第{i+1}周:{c}" for i, c in enumerate(r.get('weekly_counts', [])))
        relation_html += f"""
        <div class="rank-item">
          <div class="rank-num other" style="background:{color};color:#fff">{emoji}</div>
          <div class="rank-info">
            <div class="rank-name">{esc(r['name'])} <span style="color:{color};font-size:12px;font-weight:600">{trend}</span></div>
            <div class="rank-meta">{weekly} · 4周共{r['total_4w']}条</div>
          </div>
        </div>"""

    # 15. 最佳联系时段
    best_time_html = ""
    for b in best_times[:15]:
        best_time_html += f"""
        <div class="rank-item">
          <div class="rank-info">
            <div class="rank-name">{esc(b['name'])}</div>
            <div class="rank-meta">最佳时段：{b['best_hour']:02d}:00-{b['best_hour']+1:02d}:00（对方发{b['best_hour_count']}条）</div>
          </div>
        </div>"""

    # 16. 对话方向
    direction_html = ""
    for d in directions[:15]:
        my_pct = d['my_ratio']
        their_pct = d['their_ratio']
        who_dominant = "我主动" if my_pct > 60 else "对方主动" if their_pct > 60 else "双向均衡"
        direction_html += f"""
        <div class="rank-item">
          <div class="rank-info">
            <div class="rank-name">{esc(d['name'])} <span style="font-size:12px;color:#999">（{who_dominant}）</span></div>
            <div class="rank-meta">我发起{d['my_initiated']}次({my_pct}%) · 对方发起{d['their_initiated']}次({their_pct}%)</div>
            <div class="bar-track" style="display:flex;height:8px">
              <div style="height:100%;background:#07c160;width:{my_pct}%;border-radius:4px 0 0 4px"></div>
              <div style="height:100%;background:#576b95;width:{their_pct}%;border-radius:0 4px 4px 0"></div>
            </div>
          </div>
        </div>"""

    # 17. 重复问题
    repeated_html = ""
    for r in repeated_q[:10]:
        kws = " ".join(f'<span class="topic-tag">{esc(kw["keyword"])}<span class="topic-count">{kw["count"]}</span></span>' for kw in r.get('keywords', [])[:5])
        repeated_html += f"""
        <div class="topic-card">
          <div class="topic-group">{esc(r['group'])} <span class="topic-msg">({r['count']}次提及)</span></div>
          <div class="topic-keywords">{kws}</div>
          <div style="font-size:13px;color:#666;margin-top:6px">{esc(r['sample'])}</div>
        </div>"""

    # 18. 链接分享
    link_html = ""
    for l in links[:20]:
        link_html += f"""
        <div class="rank-item">
          <div class="rank-info">
            <div class="rank-name" style="font-size:12px;white-space:normal">{esc(l['url'][:80])}</div>
            <div class="rank-meta">{esc(l['sender'])} @ {esc(l['context'])} · {esc(l['time'])}</div>
          </div>
        </div>"""

    # 19. 文件流转
    file_html = ""
    ext_colors = {"pdf":"#e15f63","docx":"#576b95","xlsx":"#07c160","pptx":"#fa9d3b","zip":"#8a6de9"}
    for f in file_flow[:20]:
        color = ext_colors.get(f['ext'], "#95a5a6")
        file_html += f"""
        <div class="rank-item">
          <div class="rank-num other" style="background:{color};color:#fff;font-size:9px">{esc(f['ext'].upper()[:3])}</div>
          <div class="rank-info">
            <div class="rank-name">{esc(f['filename'][:50])}</div>
            <div class="rank-meta">{esc(f['sender'])} → {esc(f['context'])} · {esc(f['time'])}</div>
          </div>
        </div>"""

    # 20. 会议日程
    meeting_html = ""
    for m in meetings[:15]:
        meeting_html += f"""
        <div class="commit-item" style="border-left-color:#07c160;background:#f0faf3">
          <div class="commit-header">
            <span class="commit-sender">{esc(m['sender'])}</span>
            <span class="commit-context">@ {esc(m['context'])}</span>
            <span class="commit-time">{esc(m['time'])}</span>
          </div>
          <div class="commit-content">{esc(m['content'])}</div>
        </div>"""

    # 21. 影响力图谱
    influence_html = ""
    for i in influence[:15]:
        influence_html += f"""
        <div class="rank-item">
          <div class="rank-info">
            <div class="rank-name">{esc(i['name'])}</div>
            <div class="rank-meta">引发{i['triggered_count']}次讨论 · 平均{i['avg_followers']}人跟帖 · 共{i['follow_ups']}次跟帖</div>
          </div>
        </div>"""

    # 22. 桥梁人物
    bridge_html = ""
    for b in bridges[:15]:
        groups = " · ".join(esc(g) for g in b['groups'][:5])
        bridge_html += f"""
        <div class="rank-item">
          <div class="rank-num other" style="background:#8a6de9;color:#fff">桥</div>
          <div class="rank-info">
            <div class="rank-name">{esc(b['name'])} <span style="font-size:12px;color:#999">({b['group_count']}个群)</span></div>
            <div class="rank-meta">{groups}</div>
          </div>
        </div>"""

    # 23. 圈子发现
    circle_html = ""
    for c in circles[:8]:
        members = " · ".join(esc(m) for m in c['members'][:6])
        groups = " · ".join(esc(g) for g in c.get('common_groups', [])[:3])
        circle_html += f"""
        <div class="topic-card">
          <div class="topic-group">圈子（{c['member_count']}人） <span class="topic-msg">共同群：{esc(groups or '—')}</span></div>
          <div style="font-size:13px;color:#333;margin-top:4px">{members}</div>
        </div>"""

    # 24. 敏感信息
    sensitive_html = ""
    type_colors_s = {"手机号":"#e15f63","身份证号":"#ff4444","IP地址":"#fa9d3b","密码/口令":"#8a6de9"}
    for s in sensitive[:15]:
        color = type_colors_s.get(s['type'], "#999")
        sensitive_html += f"""
        <div class="alert-item">
          <div class="alert-badge" style="background:{color}">{esc(s['type'][:2])}</div>
          <div class="alert-info">
            <div class="alert-name">{esc(s['sender'])} @ {esc(s['context'])}</div>
            <div class="alert-meta">类型：{esc(s['type'])} · 内容：{esc(s['match'])} · {esc(s['time'])}</div>
          </div>
        </div>"""

    # 25. 异常行为
    anomaly_html = ""
    for a in anomalies[:10]:
        anomaly_html += f"""
        <div class="alert-item">
          <div class="alert-badge" style="background:#fa9d3b">!</div>
          <div class="alert-info">
            <div class="alert-name">{esc(a['name'])}</div>
            <div class="alert-meta">{esc(a['change'])} · 上周{a['prev_count']}条 → 本周{a['recent_count']}条</div>
          </div>
        </div>"""

    # 26. 承诺追踪
    ct = commit_track or {}
    ct_total = ct.get('total_prev_commitments', 0)
    ct_fulfilled = ct.get('fulfilled', [])
    ct_untracked = ct.get('untracked', 0)
    commitment_track_html = ""
    for f in ct_fulfilled[:10]:
        commitment_track_html += f'<div class="rank-item"><div class="rank-info"><div class="rank-name" style="font-size:13px">{esc(f["content"])}</div><div class="rank-meta">{esc(f["context"])}</div></div></div>'

    # 27. 语音占比
    voice_html = ""
    for v in voice_ratios[:15]:
        voice_html += f"""
        <div class="rank-item">
          <div class="rank-info">
            <div class="rank-name">{esc(v['name'])}</div>
            <div class="rank-meta">语音{v['voice']}条 / 总{v['total']}条 · 占比{v['voice_ratio']}%</div>
            <div class="bar-track"><div class="bar-fill orange" style="width:{v['voice_ratio']}%"></div></div>
          </div>
        </div>"""

    # 28. 深夜沟通
    night_html = ""
    for n in night_contacts[:10]:
        night_html += f"""
        <div class="rank-item">
          <div class="rank-num other" style="background:#2c2c3a;color:#aaa">夜</div>
          <div class="rank-info">
            <div class="rank-name">{esc(n['name'])}</div>
            <div class="rank-meta">深夜消息 {n['count']} 条（23:00-05:00）</div>
          </div>
        </div>"""

    # 29. 一次性联系人
    one_time_html = ""
    for o in one_time[:15]:
        one_time_html += f"""
        <div class="alert-item">
          <div class="alert-badge" style="background:#95a5a6">—</div>
          <div class="alert-info">
            <div class="alert-name">{esc(o['name'])}</div>
            <div class="alert-meta">{o['days_since']}天前 · 活跃{o['active_days']}天 · 共{o['total_messages']}条 · {esc(o['last_contact'])}</div>
          </div>
        </div>"""

    # --- 组装 HTML ---
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>微信聊天深度分析报告 - {dr_text}</title>
<style>
  :root {{
    --primary: #07c160; --bg: #f5f7fa; --card: #fff;
    --text: #1a1a1a; --text2: #666; --border: #e8e8e8;
    --accent: #576b95; --shadow: 0 2px 12px rgba(0,0,0,0.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
    background:var(--bg); color:var(--text); line-height:1.7; -webkit-font-smoothing:antialiased; }}
  .container {{ max-width:980px; margin:0 auto; padding:0 20px 60px; }}

  .header {{ background:linear-gradient(135deg,#07c160,#06ad56); color:#fff;
    padding:40px 0 32px; border-radius:0 0 24px 24px; margin-bottom:30px; text-align:center; }}
  .header h1 {{ font-size:26px; font-weight:700; margin-bottom:8px; }}
  .header .sub {{ font-size:15px; opacity:0.9; }}
  .header .meta {{ font-size:13px; opacity:0.8; margin-top:6px; }}

  .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
    gap:14px; margin-bottom:32px; }}
  .stat-card {{ background:var(--card); border-radius:12px; padding:20px 14px; text-align:center; box-shadow:var(--shadow); }}
  .stat-num {{ font-size:26px; font-weight:700; }}
  .stat-label {{ font-size:12px; color:var(--text2); margin-top:4px; }}

  .section {{ margin-bottom:32px; }}
  .section-title {{ font-size:19px; font-weight:700; margin-bottom:14px;
    padding-left:12px; border-left:4px solid var(--primary); }}
  .section-title .badge {{ font-size:12px; font-weight:400; color:var(--text2); margin-left:8px;
    background:#f0f2f5; padding:2px 10px; border-radius:10px; }}

  .card {{ background:var(--card); border-radius:12px; padding:22px; box-shadow:var(--shadow); margin-bottom:14px; }}

  .rank-item {{ display:flex; align-items:center; padding:9px 0; border-bottom:1px solid var(--border); }}
  .rank-item:last-child {{ border-bottom:none; }}
  .rank-num {{ width:30px; height:30px; border-radius:50%; display:flex; align-items:center;
    justify-content:center; font-weight:700; font-size:0.85em; flex-shrink:0; margin-right:10px; }}
  .rank-num.top1 {{ background:linear-gradient(135deg,#FFD700,#FFA500); color:#fff; }}
  .rank-num.top2 {{ background:linear-gradient(135deg,#C0C0C0,#A0A0A0); color:#fff; }}
  .rank-num.top3 {{ background:linear-gradient(135deg,#CD7F32,#B87333); color:#fff; }}
  .rank-num.other {{ background:#f0f2f5; color:#999; }}
  .rank-info {{ flex:1; min-width:0; }}
  .rank-name {{ font-weight:600; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .rank-meta {{ font-size:12px; color:var(--text2); margin-top:1px; }}
  .rank-count {{ font-weight:700; color:var(--primary); margin-left:10px; font-size:15px; }}
  .bar-track {{ height:7px; background:#f0f2f5; border-radius:4px; overflow:hidden; margin-top:5px; }}
  .bar-fill {{ height:100%; border-radius:4px; }}
  .bar-fill.green {{ background:var(--primary); }}
  .bar-fill.blue {{ background:#576b95; }}
  .bar-fill.orange {{ background:#fa9d3b; }}

  .trend-chart {{ display:flex; align-items:flex-end; gap:4px; height:160px; padding:10px 0; }}
  .trend-bar {{ flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; height:100%; position:relative; }}
  .trend-bar-fill {{ width:80%; background:linear-gradient(180deg,#07c160,#4fd08d); border-radius:4px 4px 0 0; min-height:2px; }}
  .trend-bar-label {{ font-size:9px; color:var(--text2); margin-top:4px; }}
  .trend-bar-count {{ font-size:9px; color:var(--primary); font-weight:600; position:absolute; top:-14px; }}

  .hour-grid {{ display:grid; grid-template-columns:repeat(24,1fr); gap:3px; margin:10px 0; }}
  .hour-cell {{ aspect-ratio:1.4; border-radius:3px; display:flex; align-items:center; justify-content:center; font-size:10px; font-weight:600; }}
  .hour-labels {{ display:grid; grid-template-columns:repeat(24,1fr); gap:3px; font-size:9px; color:var(--text2); text-align:center; margin-top:3px; }}

  .topic-card {{ background:#f8faf9; border:1px solid var(--border); border-radius:10px; padding:14px; margin-bottom:10px; }}
  .topic-group {{ font-weight:600; font-size:14px; margin-bottom:8px; }}
  .topic-msg {{ font-weight:400; color:var(--text2); font-size:12px; }}
  .topic-keywords {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .topic-tag {{ background:#e8f5e9; color:#07c160; padding:3px 10px; border-radius:12px; font-size:13px; font-weight:600; }}
  .topic-count {{ font-size:11px; color:var(--text2); margin-left:3px; }}

  .opp-item {{ border-left:3px solid #ff6b6b; background:#fff5f5; border-radius:0 8px 8px 0; padding:12px 14px; margin-bottom:10px; }}
  .opp-header {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:6px; }}
  .opp-sender {{ font-weight:600; font-size:14px; }}
  .opp-context {{ font-size:12px; color:var(--text2); }}
  .opp-time {{ font-size:12px; color:var(--text2); margin-left:auto; }}
  .opp-types {{ display:flex; gap:5px; flex-wrap:wrap; margin-bottom:6px; }}
  .opp-type {{ color:#fff; padding:2px 8px; border-radius:8px; font-size:11px; font-weight:600; }}
  .opp-content {{ font-size:13px; line-height:1.6; color:#333; margin-bottom:5px; }}
  .opp-keywords {{ display:flex; gap:4px; flex-wrap:wrap; }}
  .opp-kw {{ background:#fff0f0; color:#e15f63; padding:2px 6px; border-radius:4px; font-size:11px; }}

  .commit-item {{ border-left:3px solid #8a6de9; background:#f5f0ff; border-radius:0 8px 8px 0; padding:12px 14px; margin-bottom:10px; }}
  .commit-header {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:5px; }}
  .commit-sender {{ font-weight:600; font-size:14px; }}
  .commit-context {{ font-size:12px; color:var(--text2); }}
  .commit-time {{ font-size:12px; color:var(--text2); margin-left:auto; }}
  .commit-content {{ font-size:13px; line-height:1.6; color:#333; }}

  .mine-tag {{ background:#e8f5e9; color:#07c160; padding:1px 8px; border-radius:8px; font-size:11px; }}

  .alert-item {{ display:flex; align-items:center; padding:10px 0; border-bottom:1px solid var(--border); }}
  .alert-item:last-child {{ border-bottom:none; }}
  .alert-badge {{ width:36px; height:24px; border-radius:6px; color:#fff; display:flex; align-items:center;
    justify-content:center; font-size:11px; font-weight:600; flex-shrink:0; margin-right:10px; }}
  .alert-info {{ flex:1; min-width:0; }}
  .alert-name {{ font-weight:600; font-size:14px; }}
  .alert-meta {{ font-size:12px; color:var(--text2); margin-top:2px; }}

  .profile-item {{ background:#f8faf9; border:1px solid var(--border); border-radius:10px; padding:14px; margin-bottom:10px; }}
  .profile-name {{ font-weight:600; font-size:15px; margin-bottom:6px; }}
  .profile-stats {{ display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--text2); margin-bottom:6px; }}
  .profile-types {{ display:flex; gap:4px; flex-wrap:wrap; }}
  .profile-type {{ background:#e8f0fa; color:#576b95; padding:2px 8px; border-radius:6px; font-size:11px; }}

  .cls-section {{ margin-bottom:16px; }}
  .cls-title {{ font-weight:600; font-size:15px; margin-bottom:8px; }}
  .cls-chips {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .cls-chip {{ border:1px solid; padding:3px 10px; border-radius:12px; font-size:12px; }}

  .type-chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
  .type-chip {{ display:flex; align-items:center; gap:5px; background:#f8faf9; border:1px solid var(--border);
    border-radius:18px; padding:5px 12px; font-size:13px; }}
  .type-dot {{ width:9px; height:9px; border-radius:50%; flex-shrink:0; }}
  .type-name {{ font-weight:600; }}
  .type-count {{ color:var(--text2); }}
  .type-pct {{ color:var(--primary); font-weight:600; }}

  .callout {{ background:#f0faf3; border:1px solid #c8f0d6; border-radius:10px; padding:12px 16px; margin:10px 0; font-size:14px; }}

  .conv-card {{ background:var(--card); border-radius:12px; padding:18px; box-shadow:var(--shadow); margin-bottom:14px; border-left:4px solid #07c160; }}
  .conv-header {{ display:flex; align-items:center; gap:8px; margin-bottom:10px; flex-wrap:wrap; }}
  .conv-type {{ color:#fff; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:600; }}
  .conv-name {{ font-weight:700; font-size:15px; }}
  .conv-meta {{ font-size:12px; color:var(--text2); }}
  .conv-seg {{ background:#f8faf9; border-radius:8px; padding:12px; margin-bottom:8px; }}
  .conv-seg-time {{ font-size:12px; color:var(--text2); margin-bottom:6px; font-weight:600; }}
  .conv-seg-body {{ font-size:13px; line-height:1.8; color:#333; white-space:pre-wrap; }}
  .footer {{ text-align:center; font-size:12px; color:var(--text2); margin-top:40px; }}
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  @media(max-width:680px) {{ .two-col {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>微信聊天深度分析报告</h1>
  <div class="sub">{dr_text}</div>
  <div class="meta">报告生成：{generated_at} · 数据已解密 · 30项深度分析</div>
</div>

<div class="stats-grid">
  {"".join(overview_cards)}
</div>

<div class="section">
  <div class="section-title">AI 对话摘要 <span class="badge">大模型理解 · {len(conv_summaries)}个会话</span></div>
  {conv_summary_html or '<div class="card" style="text-align:center;color:#999">暂无对话摘要（需大模型服务运行中）</div>'}
</div>

<div class="section">
  <div class="section-title">消息类型分布 <span class="badge">维度1</span></div>
  <div class="card"><div class="type-chips">{type_chips_html}</div></div>
</div>

<div class="section">
  <div class="section-title">趋势分析 <span class="badge">维度2</span></div>
  <div class="card">
    <div class="trend-chart">{daily_bars}</div>
  </div>
</div>

<div class="section">
  <div class="section-title">24小时活跃分布 <span class="badge">维度2</span></div>
  <div class="card">
    <div class="hour-grid">{hour_cells}</div>
    <div class="hour-labels">{hour_labels}</div>
  </div>
</div>

<div class="two-col">
  <div class="section">
    <div class="section-title">活跃群聊 Top 10 <span class="badge">维度3</span></div>
    <div class="card">{chatroom_html}</div>
  </div>
  <div class="section">
    <div class="section-title">活跃私聊 Top 10 <span class="badge">维度4</span></div>
    <div class="card">{private_html}</div>
  </div>
</div>

<div class="section">
  <div class="section-title">跨群活跃成员 Top 10 <span class="badge">维度3</span></div>
  <div class="card">{sender_html}</div>
</div>

<div class="section">
  <div class="section-title">群话题热点 <span class="badge">维度7</span></div>
  {topics_html or '<div class="card" style="text-align:center;color:#999">暂无数据</div>'}
</div>

<div class="section">
  <div class="section-title">商机挖掘 <span class="badge">维度9 · 共{len(opportunities)}条线索</span></div>
  {opp_html or '<div class="card" style="text-align:center;color:#999">本周期内未检测到商机线索</div>'}
</div>

<div class="section">
  <div class="section-title">承诺与待办 <span class="badge">维度8 · 共{len(commitments)}条</span></div>
  {commit_html or '<div class="card" style="text-align:center;color:#999">暂无承诺/待办</div>'}
</div>

<div class="two-col">
  <div class="section">
    <div class="section-title">未回复私聊 <span class="badge">维度6 · {len(unreplied)}条</span></div>
    <div class="card">{unreplied_html or '<div style="text-align:center;color:#999">暂无未回复</div>'}</div>
  </div>
  <div class="section">
    <div class="section-title">沉寂联系人 <span class="badge">维度5 · {len(dormant)}人</span></div>
    <div class="card">{dormant_html or '<div style="text-align:center;color:#999">暂无沉寂联系人</div>'}</div>
  </div>
</div>

<div class="section">
  <div class="section-title">联系人画像 <span class="badge">维度10</span></div>
  {profile_html or '<div class="card" style="text-align:center;color:#999">暂无数据</div>'}
</div>

<div class="section">
  <div class="section-title">群分类分析 <span class="badge">维度11</span></div>
  <div class="card">{cls_html or '<div style="text-align:center;color:#999">暂无数据</div>'}</div>
</div>

<!-- ===== 扩展分析（18项）===== -->

<div class="section">
  <div class="section-title">响应时长分析 <span class="badge">维度13 · 谁秒回谁要催</span></div>
  <div class="card">{response_html or '<div style="text-align:center;color:#999">暂无数据</div>'}</div>
</div>

<div class="section">
  <div class="section-title">关系温度计 <span class="badge">维度14 · 升温/降温趋势</span></div>
  <div class="card">{relation_html or '<div style="text-align:center;color:#999">暂无数据</div>'}</div>
</div>

<div class="two-col">
  <div class="section">
    <div class="section-title">最佳联系时段 <span class="badge">维度15</span></div>
    <div class="card">{best_time_html or '<div style="text-align:center;color:#999">暂无数据</div>'}</div>
  </div>
  <div class="section">
    <div class="section-title">对话方向分析 <span class="badge">维度16 · 谁在主动</span></div>
    <div class="card">{direction_html or '<div style="text-align:center;color:#999">暂无数据</div>'}</div>
  </div>
</div>

<div class="section">
  <div class="section-title">重复问题/痛点挖掘 <span class="badge">维度17 · 反复出现的问题</span></div>
  {repeated_html or '<div class="card" style="text-align:center;color:#999">暂无重复问题</div>'}
</div>

<div class="section">
  <div class="section-title">链接分享追踪 <span class="badge">维度18 · 共{len(links)}条</span></div>
  <div class="card">{link_html or '<div style="text-align:center;color:#999">暂无链接</div>'}</div>
</div>

<div class="section">
  <div class="section-title">文件流转图谱 <span class="badge">维度19 · 共{len(file_flow)}个文件</span></div>
  <div class="card">{file_html or '<div style="text-align:center;color:#999">暂无文件</div>'}</div>
</div>

<div class="section">
  <div class="section-title">会议/日程提取 <span class="badge">维度20 · 共{len(meetings)}条</span></div>
  {meeting_html or '<div class="card" style="text-align:center;color:#999">暂无会议信息</div>'}
</div>

<div class="section">
  <div class="section-title">影响力图谱 <span class="badge">维度21 · 群内话题引爆力</span></div>
  <div class="card">{influence_html or '<div style="text-align:center;color:#999">暂无数据</div>'}</div>
</div>

<div class="section">
  <div class="section-title">桥梁人物 <span class="badge">维度22 · 跨群信息中间人</span></div>
  <div class="card">{bridge_html or '<div style="text-align:center;color:#999">暂无桥梁人物</div>'}</div>
</div>

<div class="section">
  <div class="section-title">社交圈子发现 <span class="badge">维度23</span></div>
  {circle_html or '<div class="card" style="text-align:center;color:#999">暂无圈子数据</div>'}
</div>

<div class="section">
  <div class="section-title">敏感信息检测 <span class="badge">维度24 · 共{len(sensitive)}条 · 注意安全</span></div>
  <div class="card">{sensitive_html or '<div style="text-align:center;color:#999">未检测到敏感信息</div>'}</div>
</div>

<div class="two-col">
  <div class="section">
    <div class="section-title">异常行为预警 <span class="badge">维度25 · {len(anomalies)}人异常</span></div>
    <div class="card">{anomaly_html or '<div style="text-align:center;color:#999">暂无异常</div>'}</div>
  </div>
  <div class="section">
    <div class="section-title">承诺追踪 <span class="badge">维度26 · 上期{ct_total}条/疑似兑现{len(ct_fulfilled)}条</span></div>
    <div class="card">{commitment_track_html or '<div style="text-align:center;color:#999">暂无追踪数据</div>'}</div>
  </div>
</div>

<div class="two-col">
  <div class="section">
    <div class="section-title">语音消息占比榜 <span class="badge">维度27 · 谁爱发语音</span></div>
    <div class="card">{voice_html or '<div style="text-align:center;color:#999">暂无语音数据</div>'}</div>
  </div>
  <div class="section">
    <div class="section-title">深夜沟通对象 <span class="badge">维度28 · 23-5点</span></div>
    <div class="card">{night_html or '<div style="text-align:center;color:#999">暂无深夜沟通</div>'}</div>
  </div>
</div>

<div class="section">
  <div class="section-title">一次性联系人 <span class="badge">维度29 · {len(one_time)}人</span></div>
  <div class="card">{one_time_html or '<div style="text-align:center;color:#999">暂无一次性联系人</div>'}</div>
</div>

<div class="callout">
  本报告由本地脚本自动生成，数据仅存于本机，未上传任何外部服务。<br>
  生成时间：{generated_at} · 作者：李准的星小辰
</div>

</div>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description="微信深度分析报告生成器")
    parser.add_argument("--analysis-json", required=True, help="深度分析JSON路径")
    parser.add_argument("--output", required=True, help="输出HTML路径")
    args = parser.parse_args()

    with open(os.path.expanduser(args.analysis_json), 'r', encoding='utf-8') as f:
        data = json.load(f)

    generated_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    html = generate_report(data, generated_at)

    out_path = os.path.expanduser(args.output)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"深度分析报告已生成: {out_path}")
    print(f"文件大小: {os.path.getsize(out_path) / 1024:.1f} KB")


if __name__ == '__main__':
    main()
