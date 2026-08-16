---
name: wechat-db-decrypt
description: 微信本地数据库解密与分析技能。读取微信 macOS 版本地加密数据库（WCDB），通过账号目录下的 all_keys.json 密钥文件解密为明文 SQLite，并按需进行聊天数据分析（群聊/私聊/时间分布）和完整 HTML 报告生成。触发场景：用户提到"微信解密"、"微信数据库"、"微信本地数据库"、"解密微信聊天记录"、"微信聊天数据分析"、"查看微信数据"、"wechat decrypt"等。技能提供三级能力：decrypt（仅解密17库）、decrypt+analyze（解密+聊天分析JSON）、decrypt+report（解密+分析+文件扫描+完整HTML报告）。
name_cn: 微信数据库解密
description_cn: 一键解密微信本地数据库，可选生成聊天分析和完整 HTML 报告
create_source: super-agent-skill-creator
---

# 微信数据库解密

## 概述

自动解密 macOS 微信本地数据库。密钥直接读取账号目录下的 `all_keys.json`（4.1.11+ 起微信明文存储密钥），无需提权、无需重签名、无需退出微信。解密后可继续生成聊天分析 JSON 和完整 HTML 报告。

## 快速开始

统一入口 `scripts/run.py`，按模式执行：

```bash
# 1. 仅解密全部 17 个数据库（输出明文库到 ./decrypted_db_411/）
python3 scripts/run.py decrypt

# 2. 解密 + 聊天分析（群聊/私聊/时间分布 → analysis_result.json）
python3 scripts/run.py decrypt+analyze

# 3. 解密 + 分析 + 文件扫描 + 完整 HTML 报告（默认推荐）
python3 scripts/run.py decrypt+report
```

可选项：
- `--outdir <目录>`：解密输出目录（默认 `./decrypted_db_411/`）

## 能力详解

### 1. 全量解密（decrypt）

- 自动探测微信容器目录（`~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<账号>/`）
- 读取 `all_keys.json`，对每个库用 `sqlcipher3` 执行 `PRAGMA key = "x'<enc_key>'"` 解密
- 跳过 `sqlite_sequence` 和 FTS 索引对象，保留数据表
- 输出结构：`<outdir>/<分类>/<dbname>.db`（如 `message/message_0.db`、`contact/contact.db`）
- 默认输出到当前工作目录 `decrypted_db_411/`

失败时提示：
- `all_keys.json` 不存在 → 让用户退出并重启微信（密钥文件在微信运行时生成）
- 解密失败 → 检查微信版本是否为 4.1.11+，或密钥是否过期

### 2. 聊天分析（decrypt+analyze）

复用 `chat_analysis.py`，输出 `analysis_result.json`：
- 总体统计（总消息数、群聊/私聊数、时间范围、消息类型分布）
- 群聊活跃度 Top50（含群内最活跃发送者）
- 私聊频次 Top50
- 跨群最活跃成员 Top30（附带最活跃群）
- 时间分布（24小时/星期/月份/日趋势）

发送者识别：群聊消息格式为 `wxid_xxx:\n实际内容`，通过 `split(":\n", 1)` 提取。

### 3. 完整报告（decrypt+report）

在分析基础上追加：
- `filesystem_scan.py` 扫描微信数据目录（数据库/文件/附件/视频，含存储占比、月度趋势、工作主题分类）
- `gen_report.py` 生成微信绿色风格完整 HTML 报告（9 大章节）

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `run.py` | 统一入口，按模式串联（推荐直接用） |
| `decrypt_with_keys.py` | 批量解密全部数据库（支持 `--outdir`、`--wxdir`） |
| `chat_analysis.py` | 聊天数据分析（支持 `--start-date/--end-date` 日期过滤） |
| `filesystem_scan.py` | 文件系统扫描（`--data-dir` 微信目录、`--output`） |
| `gen_report.py` | 完整 HTML 报告生成器 |

## 环境依赖

- macOS + 微信 4.1.x（App Store 版）
- Python 3.10+，`pip install sqlcipher3 zstandard`
- 若 `sqlcipher3` 安装失败：`brew install openssl` 后设置
  `export LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include"` 重试

## 常见问题

- **all_keys.json 为空**：退出微信重新打开（密钥文件由微信进程写入）
- **某库解密失败**：多为库当前被微信占用，可先退出微信再重试
- **消息内容乱码**：消息体为 WCDB zstd 压缩，`chat_analysis.py` 已内置自动解压
- **wxid 自动识别**：脚本从微信容器目录名（格式 `<wxid>_<hash>`）自动推导自身 wxid，无需手动配置；多账号切换亦无需改代码

## 安全提醒

- 解密产物含完整聊天记录，属于高度敏感数据
- 明文库/报告文件不要提交到 git、不要外发
- 使用完毕建议删除解密目录（或按 `.gitignore` 排除）