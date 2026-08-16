#!/usr/bin/env python3
"""
微信本地数据库解密技能 - 统一入口
================================
三级能力：
  1. decrypt          仅解密全部数据库（输出明文库）
  2. decrypt+analyze  解密 + 聊天分析（群聊/私聊/时间分布 JSON）
  3. decrypt+report   解密 + 分析 + 文件扫描 + 完整 HTML 报告

用法：
    python3 run.py decrypt                     # 仅解密
    python3 run.py decrypt+analyze             # 解密 + 分析
    python3 run.py decrypt+report              # 解密 + 完整报告（默认）

选项：
    --outdir <目录>     解密输出目录（默认 decrypted_db_411/）
    --report-dir <目录> 报告输出目录（默认项目根）
"""

import argparse
import os
import sys
import importlib

# 技能脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 默认输出目录：当前工作目录下的 decrypted_db_411
DEFAULT_OUTDIR = os.path.join(os.getcwd(), "decrypted_db_411")

MODES = ("decrypt", "decrypt+analyze", "decrypt+report")


def detect_wxdir():
    """自动探测微信容器目录：优先包含 all_keys.json 的目录"""
    base = os.path.expanduser("~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
    if not os.path.isdir(base):
        return None
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if os.path.isfile(os.path.join(p, "all_keys.json")):
            return p
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if os.path.isdir(p) and not name.startswith('.'):
            return p
    return None


def detect_my_wxid(wxdir):
    """从微信容器目录名推导自身 wxid（目录名格式: <wxid>_<hash>）"""
    if not wxdir:
        return None
    return os.path.basename(wxdir).split('_')[0] or None


def import_script(name):
    """从 SCRIPT_DIR 导入同名模块"""
    sys.path.insert(0, SCRIPT_DIR)
    return importlib.import_module(name)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(f"用法: python3 run.py [{'|'.join(MODES)}]")
        print("  示例:")
        print("    python3 run.py decrypt            # 仅解密 17 库")
        print("    python3 run.py decrypt+analyze    # 解密 + 聊天分析")
        print("    python3 run.py decrypt+report     # 解密 + 完整报告")
        sys.exit(1)

    mode = sys.argv[1]
    outdir = DEFAULT_OUTDIR
    if "--outdir" in sys.argv:
        idx = sys.argv.index("--outdir")
        if idx + 1 < len(sys.argv):
            outdir = os.path.expanduser(sys.argv[idx + 1])

    # 自动探测微信目录与自身 wxid
    wxdir = detect_wxdir()
    if not wxdir:
        print("❌ 未找到微信容器目录，请确认微信已安装并登录")
        sys.exit(1)
    my_wxid = detect_my_wxid(wxdir)
    print(f"微信目录: {wxdir}")
    print(f"账号 wxid: {my_wxid or '(未识别，分析时使用空值)'}")

    # 1. 解密
    print(f"\n== 解密全部数据库 → {outdir} ==")
    decrypt_mod = import_script("decrypt_with_keys")
    decrypt_mod.WXDIR = wxdir
    decrypt_mod.KEYFILE = os.path.join(wxdir, "all_keys.json")
    decrypt_mod.OUTDIR = outdir
    print(f"密钥文件: {decrypt_mod.KEYFILE}")
    print(f"输出目录: {outdir}")
    if not os.path.isfile(decrypt_mod.KEYFILE):
        print(f"❌ 密钥文件不存在: {decrypt_mod.KEYFILE}")
        print("   请先确认微信已登录并重启（all_keys.json 在账号目录下）")
        sys.exit(1)
    import json
    with open(decrypt_mod.KEYFILE) as f:
        keys = json.load(f)
    ok = fail = 0
    for dbname, info in keys.items():
        s, msg = decrypt_mod.export_db(dbname, info)
        print(f"[{'OK' if s else 'FAIL'}] {dbname}: {msg}")
        if s:
            ok += 1
        else:
            fail += 1
    print(f"\n成功 {ok}/{len(keys)}, 失败 {fail}")
    if fail:
        sys.exit(1)

    if mode == "decrypt":
        print("\n✅ 解密完成")
        return

    # 2. 分析
    msg_db = os.path.join(outdir, "message", "message_0.db")
    contact_db = os.path.join(outdir, "contact", "contact.db")
    analysis_json = os.path.join(os.getcwd(), "analysis_result.json")
    print(f"\n== 聊天数据分析 → {analysis_json} ==")
    chat_mod = import_script("chat_analysis")
    start_ts, end_ts = chat_mod.parse_date_range(None, None)
    print("构建联系人映射...")
    name_map = chat_mod.build_name_map(contact_db)
    print(f"  联系人: {len(name_map)}")
    print("构建会话映射...")
    sessions = chat_mod.build_session_map(msg_db)
    print(f"  会话: {len(sessions)}")
    print("\n计算总体统计...")
    overall = chat_mod.analyze_overall(msg_db, sessions, start_ts, end_ts)
    print(f"  总消息: {overall['total_messages']}")
    print("\n分析群聊活跃度...")
    chatroom_stats, sender_counter, sender_chatrooms = chat_mod.analyze_chatrooms(msg_db, sessions, name_map, start_ts, end_ts)
    top_senders_overall = []
    for s, c in sender_counter.most_common(30):
        if s == (my_wxid or ''):
            continue
        top_chatroom = sender_chatrooms[s].most_common(1)
        chatroom_name = top_chatroom[0][0] if top_chatroom else '未知'
        chatroom_count = top_chatroom[0][1] if top_chatroom else 0
        top_senders_overall.append({
            'name': name_map.get(s, s), 'username': s, 'count': c,
            'top_chatroom': chatroom_name, 'top_chatroom_count': chatroom_count
        })
    print("\n分析私聊频次...")
    private_stats = chat_mod.analyze_private_chats(msg_db, sessions, name_map, start_ts, end_ts)
    print("\n分析时间分布...")
    time_dist = chat_mod.analyze_time_distribution(msg_db, sessions, start_ts, end_ts)
    import datetime
    result = {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'overall': overall,
        'chatrooms': chatroom_stats[:50],
        'private_chats': private_stats[:50],
        'top_senders_in_chatrooms': top_senders_overall,
        'time_distribution': time_dist
    }
    with open(analysis_json, 'w', encoding='utf-8') as f:
        import json as _json
        _json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {analysis_json}")

    if mode == "decrypt+analyze":
        print("\n✅ 解密 + 分析完成")
        return

    # 3. 文件扫描 + 完整报告
    fs_json = os.path.join(os.getcwd(), "filesystem_scan.json")
    print(f"\n== 文件系统扫描 → {fs_json} ==")
    fs_mod = import_script("filesystem_scan")
    fs_result = fs_mod.run_scan(wxdir, fs_json)
    print(f"结果已保存: {fs_json}")

    report_html = os.path.join(os.getcwd(), "微信本地数据库分析报告.html")
    print(f"\n== 生成完整 HTML 报告 → {report_html} ==")
    report_mod = import_script("gen_report")
    report_mod.generate(chat_json=analysis_json, fs_json=fs_json, output_html=report_html)

    print("\n✅ 解密 + 完整报告完成")
    print(f"  解密库: {outdir}")
    print(f"  分析:   {analysis_json}")
    print(f"  报告:   {report_html}")


if __name__ == "__main__":
    main()
