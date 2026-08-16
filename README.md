---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '5d57d84c-4230-4847-8ce5-6a165f348919'
  PropagateID: '5d57d84c-4230-4847-8ce5-6a165f348919'
  ReservedCode1: '5b538cd2-baac-4dd9-a685-c5c33d2616c3'
  ReservedCode2: '5b538cd2-baac-4dd9-a685-c5c33d2616c3'
---

# 微信 4.x 本地数据库解密与分析工具

macOS 上微信 4.1.x（App Store 版）本地 WCDB 加密数据库的解密、分析与可视化报告生成工具。

## 背景

微信 4.x 使用 WCDB（SQLCipher 4 兼容）对本地 SQLite 数据库进行 AES-256-CBC 加密。本项目通过从微信进程内存中提取 Data Key，结合对 4.1.11 版本加密参数变更的逆向发现，实现了本地数据库的完整解密，并在此基础上进行聊天数据分析与可视化报告生成。

## 核心发现

微信 4.1.11 的数据库密钥实际存储在账号目录的 `all_keys.json` 中（每库独立 enc_key），**无需从进程内存提取密钥**，也无需禁用 SIP。这是 2026-08-16 攻坚确认的关键简化路径：

| 发现 | 说明 |
|------|------|
| 密钥位置 | `xwechat_files/<账号>/all_keys.json`，明文 JSON，每库 64 字符 hex enc_key |
| 覆盖范围 | 全部 17 个数据库（contact/message/session/sns 等）全部可用 |
| 兼容性 | 密钥长期有效，跨版本（4.1.7→4.1.11）仍可用 |
| 加密参数 | AES-256-CBC + HMAC-SHA512 + PBKDF2-HMAC-SHA512 256000 迭代 |

> 注意：此文件权限为 600（仅用户可读），微信运行时生成。部分场景下微信会以 0 字节空文件呈现（本次即遇到），**需要从微信容器实际路径读取**而非工作区副本。

## 项目结构

```
wechat-db-analysis/
├── scripts/
│   ├── decrypt_with_keys.py # all_keys.json 批量解密（4.1.11 首选）
│   ├── decrypt_v411.py      # WCDB 数据库解密器（chatlog 内存密钥方案）
│   ├── chat_analysis.py     # 聊天数据分析（群聊/私聊/时间分布，支持日期过滤）
│   ├── filesystem_scan.py   # 文件系统扫描器（数据库/文件/附件/视频，含ID→名称映射）
│   ├── gen_report.py        # HTML 报告生成器（微信绿色风格，完整版）
│   ├── gen_daily_report.py  # 微信聊天日报生成器（精简版，每日报告）
│   ├── html2png.js          # Playwright 长图生成（HTML → PNG，复用全局 Chrome）
│   └── run_daily_report.py  # 每日报告一键执行（解密→分析→HTML→长图）
├── daily-reports/           # 每日报告输出目录（YYYY-MM-DD/，已 gitignore）
├── docs/
│   └── encryption_notes.md  # 加密技术细节笔记
├── .gitignore
└── README.md
```

## 快速开始

### 环境要求

- macOS（无需禁用 SIP，无需重签名微信）
- Python 3.10+
- `sqlcipher3`（WCDB 解密依赖）
- 微信 4.1.x（App Store 版）

### 安装依赖

```bash
pip install pycryptodome zstandard sqlcipher3
```

> 若 `sqlcipher3` 安装失败，需先安装 OpenSSL：`brew install openssl`，再 `export LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include"` 后重试。

### 步骤一：读取密钥

4.1.11 起密钥直接存储在账号目录的 `all_keys.json`（无需从进程内存提取）：

```bash
# 微信容器路径（账号目录名形如 <wxid>_<hash>）
WXDIR=~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<your_account>
cat $WXDIR/all_keys.json
```

每个数据库对应一个 64 字符 hex 的 `enc_key`。若文件为 0 字节空文件，请先退出并重启微信后再读取。

### 步骤二：解密数据库

```bash
python3 scripts/decrypt_with_keys.py
```

脚本默认读取上述 `WXDIR` 下的 `all_keys.json` 与 `db_storage/`，将全部 17 个数据库解密输出到 `./decrypted_db_411/`。如需自定义路径，直接修改脚本顶部 `WXDIR` / `OUTDIR` / `KEYFILE` 三个常量。

### 步骤三：分析聊天数据

```bash
python3 scripts/chat_analysis.py \
    --msg-db ./decrypted_db_411/message/message_0.db \
    --contact-db ./decrypted_db_411/contact/contact.db \
    --my-wxid <你的wxid> \
    --output ./analysis_result.json
```

### 步骤四：扫描文件系统

```bash
python3 scripts/filesystem_scan.py \
    --data-dir ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<your_account> \
    --output ./filesystem_scan.json
```

### 步骤五：生成 HTML 报告

```bash
python3 scripts/gen_report.py \
    --chat-json ./analysis_result.json \
    --fs-json ./filesystem_scan.json \
    --output ./report.html
```

### 每日聊天报告（定时任务）

每日报告一键生成前一天聊天数据（消息量、活跃群/私聊 Top10、24 小时分布等），输出 HTML + PNG 长图：

```bash
# 生成昨天报告（默认）
python3 scripts/run_daily_report.py

# 指定日期
python3 scripts/run_daily_report.py --date 2026-08-15

# 保留解密中间库（默认用完即删）
python3 scripts/run_daily_report.py --keep-decrypted
```

输出目录：`daily-reports/YYYY-MM-DD/`（含 HTML 与 PNG 长图）。

链路：解密 message_0.db + contact.db → `chat_analysis.py --start-date/--end-date` 按日过滤统计 → `gen_daily_report.py` 生成精简日报 HTML → `html2png.js`（Playwright + 全局 Chrome）渲染 PNG 长图。

依赖：`pip install sqlcipher3 zstandard` + 全局 `npm i -g playwright`。

报告中的「附件最活跃对话 Top 10」会显示真实群名/人名（通过 `build_attach_name_map` 将附件目录的 `md5(对话ID)` 反向映射为备注名/昵称）。

### （可选）旧方案：chatlog 内存提取

4.1.11 之前无法从文件系统直接获得密钥时，可用 [chatlog](https://github.com/any35/chatlog) 从微信进程内存提取（需禁用 SIP）：

1. 禁用 SIP → adhoc 重签名微信 → 编译运行 `chatlog` → 密钥存于 `~/.chatlog/chatlog.json` 的 `data_key` 字段
2. 完成后恢复模式 `csrutil enable` 重新开启 SIP
3. 使用 `scripts/decrypt_v411.py` 传入 `--key` 解密

新版本优先使用 `all_keys.json` 方案，无需以上操作。

## 报告内容

生成的 HTML 报告包含 9 个章节：

1. **解密突破历程** - 从文件分析到密钥提取到成功解密的全流程
2. **数据目录结构概览** - 微信本地数据目录的组织方式
3. **数据库文件清单** - 18 个 WCDB 加密数据库的详细信息
4. **聊天消息分析** - 群聊活跃度、私聊频次、群聊最活跃的人（含最活跃群名）、消息类型分布
5. **聊天文件消息分析** - 文件类型分布、月度趋势、工作主题分类、高频迭代文件
6. **视频与图片附件分析** - 月度趋势、附件最活跃对话 Top 10
7. **消息与文件时间分布** - 小时/星期/月度趋势、热力图
8. **存储占用汇总** - 各类数据的存储占比环形图
9. **关键发现与总结** - 聊天画像、工作画像、工作节奏、技术突破记录

## 技术细节

### WCDB 加密结构

- **加密算法**：AES-256-CBC + HMAC-SHA512
- **页面大小**：4096 字节
- **Salt**：第一页前 16 字节
- **IV**：每页末尾 80 字节 reserve 中的前 16 字节
- **HMAC**：每页末尾 80 字节 reserve 中的后 64 字节

### 4.1.11 解密流程

```
1. salt = page_0[:16]
2. enc_key = raw_key                      # 直接使用，不做 PBKDF2
3. mac_salt = salt XOR 0x3a               # 逐字节异或
4. mac_key = PBKDF2-SHA512(enc_key, mac_salt, iterations=2, dklen=32)
5. 对每页：验证 HMAC → AES-CBC 解密
```

### WCDB zstd 压缩

微信 4.x 对约 40% 的消息内容使用 zstd 压缩，存储在 `WCDB_CT_message_content` 字段中。值为 0 表示未压缩，非 0 表示 zstd 压缩。分析脚本使用 `zstandard` 库自动解压。

### 数据结构

- **消息表命名**：`Msg_` + `md5(username)`
- **群聊消息格式**：`wxid_xxx:\n实际内容`（可用 `split(":\n", 1)` 提取发送者）
- **时间字段**：`create_time`（Unix 时间戳）
- **消息类型**：`local_type`（1=文字, 3=图片, 34=语音, 43=视频, 47=表情包, 67=文件, 10000=系统消息）

## 安全提醒

- 解密后的数据库与 `all_keys.json` 包含全部聊天记录与密钥，**切勿提交到 git 或外传**（`.gitignore` 已排除 `*.db` / `*.json`）
- 生成的分析报告含真实对话名称，如需提交仓库请使用脱敏示例（可参考历史 commit 处理方式）
- `all_keys.json` 属微信运行时生成文件，权限 600，勿复制到工作区以外位置
- 旧方案（chatlog 内存提取）需要禁用 SIP，有安全风险，仅实际需要时使用

## 依赖工具

| 工具 | 用途 | 安装 |
|------|------|------|
| sqlcipher3 | 用 enc_key 解密 WCDB 数据库 | `pip install sqlcipher3` |
| [chatlog](https://github.com/any35/chatlog) | （旧方案）从内存提取 WCDB Data Key | `go install` |
| pycryptodome | AES-CBC 解密（备用方案） | `pip install pycryptodome` |
| zstandard | WCDB zstd 压缩消息解压 | `pip install zstandard` |

## 参考项目

- [chatlog](https://github.com/any35/chatlog) - Go 版微信密钥提取与数据库解密工具
- [wechat-decrypt-macos](https://github.com/walnut-a/wechat-decrypt-macos) - macOS 微信解密参考

## License

MIT