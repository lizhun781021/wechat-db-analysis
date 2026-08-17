#!/usr/bin/env python3
"""
微信本地数据库读取技能 - 统一入口
================================
三级能力：
  1. export          仅导出全部数据库（输出明文库）
  2. export+analyze  导出 + 聊天分析（群聊/私聊/时间分布 JSON）
  3. export+report   导出 + 分析 + 文件扫描 + 完整 HTML 报告

用法：
    python3 run.py export --wxdir <微信目录> --outdir <输出目录>
    python3 run.py export+analyze --wxdir <微信目录> --outdir <输出目录>
    python3 run.py export+report --wxdir <微信目录> --outdir <输出目录>

所有路径由参数传入，脚本不硬编码任何系统路径。
"""

import os
import sys
import json
import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import db_export
import chat_analysis
import filesystem_scan
import gen_report

MODES = ("export", "export+analyze", "export+report")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(f"用法: python3 run.py [{'|'.join(MODES)}] --wxdir <微信目录> [--outdir <输出目录>]")
        print("  示例:")
        print("    python3 run.py export --wxdir /path/to/wechat --outdir ./out")
        print("    python3 run.py export+analyze --wxdir /path/to/wechat --outdir ./out")
        print("    python3 run.py export+report --wxdir /path/to/wechat --outdir ./out")
        sys.exit(1)

    mode = sys.argv[1]

    # 解析参数
    wxdir = None
    outdir = os.path.join(os.getcwd(), "exported_db_411")
    args = sys.argv[2:]
    if "--wxdir" in args:
        idx = args.index("--wxdir")
        if idx + 1 < len(args):
            wxdir = os.path.expanduser(args[idx + 1])
    if "--outdir" in args:
        idx = args.index("--outdir")
        if idx + 1 < len(args):
            outdir = os.path.expanduser(args[idx + 1])

    if not wxdir:
        print("❌ 请用 --wxdir 指定微信数据目录")
        sys.exit(1)

    cred_file = os.path.join(wxdir, "all_keys.json")
    db_storage_dir = os.path.join(wxdir, "db_storage")
    print(f"微信目录: {wxdir}")
    print(f"输出目录: {outdir}")

    # 1. 导出
    print(f"\n== 导出全部数据库 → {outdir} ==")
    db_export.run_export(cred_file, db_storage_dir, outdir)

    if mode == "export":
        print("\n✅ 导出完成")
        return

    # 2. 分析
    msg_db = os.path.join(outdir, "message", "message_0.db")
    contact_db = os.path.join(outdir, "contact", "contact.db")
    analysis_json = os.path.join(os.getcwd(), "analysis_result.json")
    print(f"\n== 聊天数据分析 → {analysis_json} ==")
    start_ts, end_ts = chat_analysis.parse_date_range(None, None)
    print("构建联系人映射...")
    name_map = chat_analysis.build_name_map(contact_db)
    print(f"  联系人: {len(name_map)}")
    print("构建会话映射...")
    sessions = chat_analysis.build_session_map(msg_db)
    print(f"  会话: {len(sessions)}")
    print("\n计算总体统计...")
    overall = chat_analysis.analyze_overall(msg_db, sessions, start_ts, end_ts)
    print(f"  总消息: {overall['total_messages']}")
    print("\n分析群聊活跃度...")
    chatroom_stats, sender_counter, sender_chatrooms = chat_analysis.analyze_chatrooms(msg_db, sessions, name_map, start_ts, end_ts)
    top_senders_overall = []
    for s, c in sender_counter.most_common(30):
        top_chatroom = sender_chatrooms[s].most_common(1)
        chatroom_name = top_chatroom[0][0] if top_chatroom else '未知'
        chatroom_count = top_chatroom[0][1] if top_chatroom else 0
        top_senders_overall.append({
            'name': name_map.get(s, s), 'username': s, 'count': c,
            'top_chatroom': chatroom_name, 'top_chatroom_count': chatroom_count
        })
    print("\n分析私聊频次...")
    private_stats = chat_analysis.analyze_private_chats(msg_db, sessions, name_map, start_ts, end_ts)
    print("\n分析时间分布...")
    time_dist = chat_analysis.analyze_time_distribution(msg_db, sessions, start_ts, end_ts)
    result = {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'overall': overall,
        'chatrooms': chatroom_stats[:50],
        'private_chats': private_stats[:50],
        'top_senders_in_chatrooms': top_senders_overall,
        'time_distribution': time_dist
    }
    with open(analysis_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {analysis_json}")

    if mode == "export+analyze":
        print("\n✅ 导出 + 分析完成")
        return

    # 3. 文件扫描 + 完整报告
    fs_json = os.path.join(os.getcwd(), "filesystem_scan.json")
    print(f"\n== 文件系统扫描 → {fs_json} ==")
    filesystem_scan.run_scan(wxdir, fs_json)
    print(f"结果已保存: {fs_json}")

    report_html = os.path.join(os.getcwd(), "微信本地数据库分析报告.html")
    print(f"\n== 生成完整 HTML 报告 → {report_html} ==")
    gen_report.generate(analysis_json, fs_json, report_html)

    print("\n✅ 导出 + 完整报告完成")
    print(f"  导出库: {outdir}")
    print(f"  分析:   {analysis_json}")
    print(f"  报告:   {report_html}")


if __name__ == "__main__":
    main()
