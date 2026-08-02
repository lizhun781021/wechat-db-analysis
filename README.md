---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '346bae97-5b04-4dac-a2f9-54d524125778'
  PropagateID: '346bae97-5b04-4dac-a2f9-54d524125778'
  ReservedCode1: '72a0554b-e2bd-4bfa-994d-8dc18bdb6ed0'
  ReservedCode2: '72a0554b-e2bd-4bfa-994d-8dc18bdb6ed0'
---

# 微信 4.x 本地数据库解密与分析工具

macOS 上微信 4.1.x（App Store 版）本地 WCDB 加密数据库的解密、分析与可视化报告生成工具。

## 背景

微信 4.x 使用 WCDB（SQLCipher 4 兼容）对本地 SQLite 数据库进行 AES-256-CBC 加密。本项目通过从微信进程内存中提取 Data Key，结合对 4.1.11 版本加密参数变更的逆向发现，实现了本地数据库的完整解密，并在此基础上进行聊天数据分析与可视化报告生成。

## 核心发现

微信 4.1.11 相比之前版本改变了加密参数：

| 参数 | 旧版（4.1.7 等） | 4.1.11 |
|------|------------------|--------|
| enc_key 派生 | PBKDF2-SHA512 256000 次迭代 | **直接使用 raw key，不做迭代** |
| mac_key 派生 | PBKDF2-SHA512 256000 次迭代 | PBKDF2-SHA512 **2 次**迭代 |
| 验证方式 | salt + PBKDF2 | salt XOR 0x3a + PBKDF2 |

> 注意：此参数变更已确认适用于 `message_0.db`。其他数据库可能使用不同的 per-db 密钥或参数。

## 项目结构

```
wechat-db-analysis/
├── scripts/
│   ├── decrypt_v411.py      # WCDB 数据库解密器（4.1.11 参数）
│   ├── chat_analysis.py     # 聊天数据分析（群聊/私聊/时间分布）
│   ├── filesystem_scan.py   # 文件系统扫描器（数据库/文件/附件/视频）
│   └── gen_report.py        # HTML 报告生成器（微信绿色风格）
├── docs/
│   └── encryption_notes.md  # 加密技术细节笔记
├── .gitignore
└── README.md
```

## 快速开始

### 环境要求

- macOS（需禁用 SIP 提取密钥）
- Python 3.10+
- Go 1.21+（编译 chatlog 提取密钥）
- 微信 4.1.x（App Store 版）

### 安装依赖

```bash
pip install pycryptodome zstandard
```

### 步骤一：提取密钥

> 需要禁用 SIP（System Integrity Protection），因为要从微信进程内存中读取数据。

1. 禁用 SIP：关机 → 按住电源键进入恢复模式 → 终端 → `csrutil disable` → 重启
2. 对微信进行 adhoc 重签名（移除 Hardened Runtime）：
   ```bash
   codesign --force --sign - --remove-signature /Applications/WeChat.app
   ```
3. 编译并运行 [chatlog](https://github.com/any35/chatlog)（Go 版）提取密钥：
   ```bash
   git clone https://github.com/any35/chatlog.git
   cd chatlog
   go build -o chatlog .
   ./chatlog
   ```
4. 密钥会保存在 `~/.chatlog/chatlog.json` 的 `data_key` 字段中

### 步骤二：解密数据库

```bash
python3 scripts/decrypt_v411.py \
    --key <你的32字节Data Key hex> \
    --input ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<your_account>/db_storage \
    --output ./decrypted_db
```

### 步骤三：分析聊天数据

```bash
python3 scripts/chat_analysis.py \
    --msg-db ./decrypted_db/message/message_0.db \
    --contact-db ./decrypted_db/contact/contact.db \
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

### 步骤六：重新开启 SIP

```bash
# 恢复模式 → 终端
csrutil enable
# 重启
```

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

- **SIP 禁用有安全风险**，仅在实际操作期间禁用，完成后立即重新开启
- 解密后的数据库包含所有聊天记录，注意数据安全
- 密钥提取后缓存在 `~/.chatlog/chatlog.json`，无需重复提取
- 微信大版本更新可能更换密钥，需要重新提取

## 依赖工具

| 工具 | 用途 | 安装 |
|------|------|------|
| [chatlog](https://github.com/any35/chatlog) | 从内存提取 WCDB Data Key | `go install` |
| pycryptodome | AES-CBC 解密 | `pip install pycryptodome` |
| zstandard | WCDB zstd 压缩消息解压 | `pip install zstandard` |

## 参考项目

- [chatlog](https://github.com/any35/chatlog) - Go 版微信密钥提取与数据库解密工具
- [wechat-decrypt-macos](https://github.com/walnut-a/wechat-decrypt-macos) - macOS 微信解密参考

## License

MIT