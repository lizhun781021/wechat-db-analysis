#!/usr/bin/env python3
"""
微信本地数据库解密技能 - 统一入口
=================================
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
import subprocess
import sys
import re

# 技能脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 默认输出目录：当前工作目录下的 decrypted_db_411
DEFAULT_OUTDIR = os.path.join(os.getcwd(), "decrypted_db_411")
# 微信容器目录（自动探测，无硬编码）
WXDIR = None
MY_WXID = None

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


def run(cmd, desc):
    print(f"\n== {desc} ==")
    print("  " + " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"❌ {desc} 失败 (exit={r.returncode})")
        sys.exit(r.returncode)
    return True


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(f"用法: python3 run.py [{'|'.join(MODES)}]")
        print("  示例:")
        print("    python3 run.py decrypt            # 仅解密 17 库")
        print("    python3 run.py decrypt+analyze    # 解密 + 聊天分析")
        print("    python3 run.py decrypt+report     # 解密 + 完整报告")
        sys.exit(1)

    mode = sys.argv[1]
    args = sys.argv[2:]
    outdir = DEFAULT_OUTDIR
    if "--outdir" in args:
        outdir = os.path.expanduser(args[args.index("--outdir") + 1])

    # 自动探测微信目录与自身 wxid
    global WXDIR, MY_WXID
    WXDIR = detect_wxdir()
    if not WXDIR:
        print("❌ 未找到微信容器目录，请确认微信已安装并登录")
        sys.exit(1)
    MY_WXID = detect_my_wxid(WXDIR)
    print(f"微信目录: {WXDIR}")
    print(f"账号 wxid: {MY_WXID or '(未识别，分析时使用空值)'}")

    py = sys.executable
    scripts = SCRIPT_DIR

    # 1. 解密
    run([py, os.path.join(scripts, "decrypt_with_keys.py"), "--outdir", outdir],
        f"解密全部数据库 → {outdir}")

    if mode == "decrypt":
        print("\n✅ 解密完成")
        return

    # 2. 分析
    msg_db = os.path.join(outdir, "message", "message_0.db")
    contact_db = os.path.join(outdir, "contact", "contact.db")
    analysis_json = os.path.join(os.getcwd(), "analysis_result.json")
    run([py, os.path.join(scripts, "chat_analysis.py"),
         "--msg-db", msg_db,
         "--contact-db", contact_db,
         "--my-wxid", MY_WXID,
         "--output", analysis_json],
        f"聊天数据分析 → {analysis_json}")

    if mode == "decrypt+analyze":
        print("\n✅ 解密 + 分析完成")
        return

    # 3. 文件扫描 + 完整报告
    fs_json = os.path.join(os.getcwd(), "filesystem_scan.json")
    run([py, os.path.join(scripts, "filesystem_scan.py"),
         "--data-dir", WXDIR,
         "--output", fs_json],
        f"文件系统扫描 → {fs_json}")

    report_html = os.path.join(os.getcwd(), "微信本地数据库分析报告.html")
    run([py, os.path.join(scripts, "gen_report.py"),
         "--chat-json", analysis_json,
         "--fs-json", fs_json,
         "--output", report_html],
        f"生成完整 HTML 报告 → {report_html}")

    print("\n✅ 解密 + 完整报告完成")
    print(f"  解密库: {outdir}")
    print(f"  分析:   {analysis_json}")
    print(f"  报告:   {report_html}")


if __name__ == "__main__":
    main()