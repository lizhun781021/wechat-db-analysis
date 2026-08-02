#!/usr/bin/env python3
"""
微信本地数据文件系统扫描器
========================
扫描微信本地数据目录，统计：
- 加密数据库文件清单（大小、分类、用途）
- 聊天文件消息（按类型/月份/小时/星期统计）
- 视频消息统计
- 图片/语音附件统计
- 缓存文件统计
- 工作主题关键词分类
- 高频迭代文件检测
- 存储占用汇总

用法：
    python3 filesystem_scan.py --data-dir <微信数据目录> --output <输出JSON路径>

示例：
    python3 filesystem_scan.py \
        --data-dir ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<your_account> \
        --output ./filesystem_scan.json

无第三方依赖，仅使用标准库。
"""

import os
import json
import argparse
import datetime
from collections import defaultdict, Counter

# 数据库用途映射
DB_PURPOSE = {
    "message_0.db": ("message", "聊天消息主库"),
    "biz_message_0.db": ("message", "公众号/企业消息"),
    "message_fts.db": ("message", "消息全文搜索索引"),
    "message_resource.db": ("message", "消息资源文件"),
    "media_0.db": ("message", "媒体资源"),
    "weclaw.db": ("message", "消息扩展"),
    "contact.db": ("contact", "联系人信息"),
    "contact_fts.db": ("contact", "联系人搜索索引"),
    "head_image.db": ("head_image", "头像缓存"),
    "favorite.db": ("favorite", "收藏内容"),
    "favorite_fts.db": ("favorite", "收藏搜索索引"),
    "general.db": ("general", "通用数据"),
    "emoticon.db": ("emoticon", "表情包"),
    "sns.db": ("sns", "朋友圈"),
    "session.db": ("session", "会话列表"),
    "bizchat.db": ("bizchat", "企业微信会话"),
    "hardlink.db": ("hardlink", "硬链接索引"),
    "solitaire.db": ("solitaire", "接龙"),
}

# 文件分类关键词
FILE_CATEGORIES = {
    'Excel': ['.xlsx', '.xls', '.csv'],
    'PDF': ['.pdf'],
    'Word': ['.doc', '.docx'],
    'PPT': ['.ppt', '.pptx'],
    '压缩包': ['.zip', '.rar', '.7z', '.gz', '.tar'],
    '图片': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.heic', '.webp'],
    '其他': []
}

# 工作主题关键词（可根据自身行业自定义）
WORK_TOPICS = {
    '管理报告': ['报告', '汇报', '会议', '总结', '计划', '安排'],
    '数据统计': ['统计', '台账', '汇总', '数据'],
    '业务分析': ['业务', '退订', '净增', '新入网'],
    '检查审计': ['检查', '审计', '核查'],
}


def categorize_file(filename):
    """根据扩展名分类文件"""
    ext = os.path.splitext(filename)[1].lower()
    for category, exts in FILE_CATEGORIES.items():
        if ext in exts:
            return category
    return '其他'


def classify_work_topic(filename):
    """根据文件名关键词分类工作主题"""
    topics = []
    for topic, keywords in WORK_TOPICS.items():
        if any(kw in filename for kw in keywords):
            topics.append(topic)
    return topics


def scan_db_files(data_dir):
    """扫描数据库文件"""
    db_storage = os.path.join(data_dir, "db_storage")
    db_files = []
    total_size = 0

    if not os.path.exists(db_storage):
        return [], 0

    for root, dirs, files in os.walk(db_storage):
        for f in files:
            if f.endswith(".db") and not f.endswith("-shm") and not f.endswith("-wal"):
                path = os.path.join(root, f)
                size = os.path.getsize(path)
                cat, purpose = DB_PURPOSE.get(f, ("unknown", "未知"))
                db_files.append({
                    'name': f,
                    'path': os.path.relpath(path, db_storage),
                    'size_mb': size / (1024 * 1024),
                    'category': cat,
                    'purpose': purpose
                })
                total_size += size

    db_files.sort(key=lambda x: x['size_mb'], reverse=True)
    return db_files, total_size


def scan_files_by_type(data_dir, subdir, file_types=None):
    """扫描指定子目录的文件统计"""
    target = os.path.join(data_dir, "msg", subdir)
    if not os.path.exists(target):
        target = os.path.join(data_dir, subdir)

    stats = {
        'total_count': 0,
        'total_size_gb': 0,
        'by_type': defaultdict(lambda: {'count': 0, 'size_mb': 0}),
        'by_month': defaultdict(lambda: {'count': 0, 'size_mb': 0}),
        'by_hour': defaultdict(int),
        'by_weekday': defaultdict(int),
        'top_days': [],
    }

    if not os.path.exists(target):
        return normalize_stats(stats)

    file_counter = Counter()
    day_counter = defaultdict(int)

    for root, dirs, files in os.walk(target):
        for f in files:
            path = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(path)
                size = os.path.getsize(path)
            except:
                continue

            dt = datetime.datetime.fromtimestamp(mtime)
            month = dt.strftime('%Y-%m')
            day = dt.strftime('%Y-%m-%d')
            hour = str(dt.hour)
            weekday = str(dt.weekday())

            stats['total_count'] += 1
            stats['total_size_gb'] += size / (1024**3)

            category = categorize_file(f) if file_types is None else 'file'
            stats['by_type'][category]['count'] += 1
            stats['by_type'][category]['size_mb'] += size / (1024 * 1024)

            stats['by_month'][month]['count'] += 1
            stats['by_month'][month]['size_mb'] += size / (1024 * 1024)

            stats['by_hour'][hour] += 1
            stats['by_weekday'][weekday] += 1

            file_counter[f] += 1
            day_counter[day] += 1

    # Top迭代文件（出现次数最多的文件名）
    stats['top_iterated_files'] = [
        {'name': name, 'count': cnt}
        for name, cnt in file_counter.most_common(20) if cnt > 1
    ]

    # Top活跃日期
    stats['top_days'] = sorted(day_counter.items(), key=lambda x: x[1], reverse=True)[:10]

    # 工作主题
    work_topics = Counter()
    for name, cnt in file_counter.items():
        for topic in classify_work_topic(name):
            work_topics[topic] += cnt
    stats['work_topics'] = dict(work_topics)

    return normalize_stats(stats)


def scan_attach(data_dir):
    """扫描附件目录"""
    target = os.path.join(data_dir, "msg", "attach")
    if not os.path.exists(target):
        target = os.path.join(data_dir, "attach")

    stats = {
        'total_count': 0,
        'total_size_gb': 0,
        'conversation_count': 0,
        'by_month': defaultdict(lambda: {'count': 0, 'size_mb': 0}),
        'top_conversations': [],
    }

    if not os.path.exists(target):
        stats = normalize_stats(stats)
        stats['conversation_count'] = 0
        return stats

    conv_counter = Counter()
    for root, dirs, files in os.walk(target):
        # 附件目录结构: attach/<conv_id>/<month>/<files>
        parts = os.path.relpath(root, target).split(os.sep)
        if len(parts) >= 1 and parts[0] != '.':
            conv_id = parts[0]
            conv_counter[conv_id] += len(files)

        for f in files:
            path = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(path)
                size = os.path.getsize(path)
            except:
                continue

            dt = datetime.datetime.fromtimestamp(mtime)
            month = dt.strftime('%Y-%m')

            stats['total_count'] += 1
            stats['total_size_gb'] += size / (1024**3)
            stats['by_month'][month]['count'] += 1
            stats['by_month'][month]['size_mb'] += size / (1024 * 1024)

    stats['conversation_count'] = len(conv_counter)
    stats['top_conversations'] = [
        {'conv_id': cid[:16], 'count': cnt, 'size_mb': 0}
        for cid, cnt in conv_counter.most_common(10)
    ]

    return normalize_stats(stats)


def scan_cache(data_dir):
    """扫描缓存目录"""
    target = os.path.join(data_dir, "cache")
    stats = {'total_count': 0, 'total_size_gb': 0}

    if not os.path.exists(target):
        return stats

    for root, dirs, files in os.walk(target):
        for f in files:
            try:
                size = os.path.getsize(os.path.join(root, f))
                stats['total_count'] += 1
                stats['total_size_gb'] += size / (1024**3)
            except:
                pass

    return stats


def normalize_stats(stats):
    """将defaultdict转为普通dict以便JSON序列化"""
    result = {}
    for k, v in stats.items():
        if isinstance(v, defaultdict):
            if isinstance(v, dict) and v and isinstance(list(v.values())[0], dict):
                result[k] = {kk: vv for kk, vv in v.items()}
            else:
                result[k] = dict(v)
        else:
            result[k] = v
    return result


def main():
    parser = argparse.ArgumentParser(description="微信本地数据文件系统扫描器")
    parser.add_argument("--data-dir", required=True, help="微信数据目录路径")
    parser.add_argument("--output", default="filesystem_scan.json", help="输出JSON路径")
    args = parser.parse_args()

    data_dir = os.path.expanduser(args.data_dir)
    output_path = os.path.expanduser(args.output)

    print("=== 微信数据文件系统扫描 ===")
    print(f"数据目录: {data_dir}")
    print()

    # 扫描数据库
    print("扫描数据库文件...")
    db_files, db_total_size = scan_db_files(data_dir)
    print(f"  数据库: {len(db_files)}个, {db_total_size/1024/1024:.1f} MB")

    # 扫描聊天文件
    print("扫描聊天文件...")
    file_stats = scan_files_by_type(data_dir, "file")
    print(f"  文件: {file_stats['total_count']}个, {file_stats['total_size_gb']:.2f} GB")

    # 扫描视频
    print("扫描视频消息...")
    video_stats = scan_files_by_type(data_dir, "video")
    print(f"  视频: {video_stats['total_count']}个, {video_stats['total_size_gb']:.2f} GB")

    # 扫描附件
    print("扫描图片附件...")
    attach_stats = scan_attach(data_dir)
    print(f"  附件: {attach_stats['total_count']}个, {attach_stats['total_size_gb']:.2f} GB")

    # 扫描缓存
    print("扫描缓存...")
    cache_stats = scan_cache(data_dir)
    print(f"  缓存: {cache_stats['total_count']}个, {cache_stats['total_size_gb']:.2f} GB")

    # 汇总
    total_storage = (
        file_stats['total_size_gb'] +
        video_stats['total_size_gb'] +
        attach_stats['total_size_gb'] +
        cache_stats['total_size_gb'] +
        db_total_size / (1024**3)
    )

    result = {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_dir': data_dir,
        'db_files': db_files,
        'db_total_size': db_total_size,
        'file_stats': file_stats,
        'video_stats': video_stats,
        'attach_stats': attach_stats,
        'cache_stats': cache_stats,
        'total_storage_gb': round(total_storage + 0.15, 2),  # +其他资源
    }

    print(f"\n总存储: {result['total_storage_gb']:.2f} GB")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {output_path}")


if __name__ == '__main__':
    main()
