---
name: wechat-db-reader
description: 微信本地数据库读取与分析技能。读取微信 macOS 版本地数据库（WCDB），通过账号目录下的凭据文件将数据库导出为明文 SQLite，并按需进行聊天数据分析（群聊/私聊/时间分布）和完整 HTML 报告生成。触发场景：用户提到"微信数据库"、"微信本地数据库"、"读取微信聊天记录"、"微信聊天数据分析"、"查看微信数据"、"wechat db"等。技能提供三级能力：export（仅导出17库）、export+analyze（导出+聊天分析JSON）、export+report（导出+分析+文件扫描+完整HTML报告）。
name_cn: 微信数据库读取
description_cn: 一键读取微信本地数据库，可选生成聊天分析和完整 HTML 报告
create_source: super-agent-skill-creator
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'daca575d-911c-4665-a3b5-9d36a5df63a7'
  PropagateID: 'daca575d-911c-4665-a3b5-9d36a5df63a7'
  ReservedCode1: '1c8cff84-a759-4733-876b-e2b565a41dae'
  ReservedCode2: '1c8cff84-a759-4733-876b-e2b565a41dae'
---

# 微信数据库读取

## 概述

自动读取 macOS 微信本地数据库。凭据直接读取账号目录下的凭据文件（4.1.11+ 起微信明文存储），无需提权、无需重签名、无需退出微信。导出后可继续生成聊天分析 JSON 和完整 HTML 报告。

## 快速开始

统一入口 `scripts/run.py`，按模式执行：

```bash
# 1. 仅导出全部 17 个数据库（输出明文库到 ./exported_db_411/）
python3 scripts/run.py export --wxdir <微信数据目录>

# 2. 导出 + 聊天分析（群聊/私聊/时间分布 → analysis_result.json）
python3 scripts/run.py export+analyze --wxdir <微信数据目录>

# 3. 导出 + 分析 + 文件扫描 + 完整 HTML 报告（默认推荐）
python3 scripts/run.py export+report --wxdir <微信数据目录>
```

可选项：
- `--wxdir <目录>`：微信数据目录（必需，包含凭据文件和 `db_storage/`）
- `--outdir <目录>`：导出输出目录（默认 `./exported_db_411/`）

## 能力详解

### 1. 全量导出（export）

- 微信数据目录由 `--wxdir` 参数传入（AI agent 负责探测路径）
- 读取目录下的凭据文件，用数据库工具逐库导出
- 跳过 `sqlite_sequence` 和 FTS 索引对象，保留数据表
- 输出结构：`<outdir>/<分类>/<dbname>.db`
- 默认输出到当前工作目录 `exported_db_411/`

失败时提示：
- 凭据文件不存在 → 让用户退出并重启微信（凭据文件在微信运行时生成）
- 读取失败 → 检查微信版本是否为 4.1.11+，或凭据是否过期

### 2. 聊天分析（export+analyze）

复用 `chat_analysis.py`，输出 `analysis_result.json`：
- 总体统计（总消息数、群聊/私聊数、时间范围、消息类型分布）
- 群聊活跃度 Top50（含群内最活跃发送者）
- 私聊频次 Top50
- 跨群最活跃成员 Top30（附带最活跃群）
- 时间分布（24小时/星期/月份/日趋势）

发送者识别：群聊消息格式为 `wxid_xxx:\n实际内容`，通过 `split(":\n", 1)` 提取。

### 3. 完整报告（export+report）

在分析基础上追加：
- `filesystem_scan.py` 扫描微信数据目录（数据库/文件/附件/视频，含存储占比、月度趋势、工作主题分类）
- `gen_report.py` 生成微信绿色风格完整 HTML 报告（9 大章节）

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `run.py` | 统一入口，按模式串联（推荐直接用） |
| `db_export.py` | 批量导出全部数据库（支持 `--outdir`、`--wxdir`） |
| `chat_analysis.py` | 聊天数据分析（支持 `--start-date/--end-date` 日期过滤） |
| `filesystem_scan.py` | 文件系统扫描（`--data-dir` 微信目录、`--output`） |
| `gen_report.py` | 完整 HTML 报告生成器 |

## 环境依赖

- macOS + 微信 4.1.x（App Store 版）
- Python 3.10+，安装数据库工具和压缩工具
- 若数据库工具安装失败：安装 OpenSSL 后设置
  `export LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include"` 重试

## 常见问题

- **凭据文件为空**：退出微信重新打开（凭据文件由微信进程写入）
- **某库读取失败**：多为库当前被微信占用，可先退出微信再重试
- **消息内容乱码**：消息体为 WCDB zstd 压缩，`chat_analysis.py` 已内置自动解压
- **wxid 自动识别**：脚本从微信容器目录名自动推导自身 wxid，无需手动配置；多账号切换亦无需改代码

## 密钥轮换应对（重要）

微信在账期轮换时会更换消息库（`message_0.db`/`message_1.db`/`message_resource.db`）的密钥，
旧密钥立即失效，表现为"凭据文件存在但解密失败"。

**关键认知**：新版本微信密钥**不以明文驻留可读内存**，内存 dump 扫描、salt 邻近搜索等方法均失效；
且微信 WCDB 为静态链接 SQLCipher，hook `sqlite3_key` 系统符号不触发。

**有效方法**：微信加密最终必经系统 `libcommonCrypto.dylib` 的 `CCCryptorCreateWithMode`，
hook 其参数即可直接捕获密钥：

```js
var cc = Process.findModuleByName('libcommonCrypto.dylib');
var addr = cc.getExportByName('CCCryptorCreateWithMode');
Interceptor.attach(addr, {
  onEnter: function(args) {
    var keyLen = args[6].toInt32();   // arm64: args[5]=key, args[6]=keyLen
    if (keyLen === 32) {
      send({key: hexify(args[5].readByteArray(32))});
    }
  }
});
```

微信运行中打开聊天/收发消息即会触发（无需重启）。捕获后用 v411 HMAC 验证：

```
mac_key = PBKDF2-HMAC-SHA512(raw_key, salt^0x3a, iterations=2, dklen=32)
HMAC-SHA512(mac_key, page_body[16:4032] + LE32(page_no+1)) 匹配即密钥正确
```

> 注意：v411 加密首页解密后不含明文 SQLite 头（需手动拼接 `SQLite format 3\0`），
> 判断密钥正确性以 **HMAC 匹配**为准，不要用"解密后是否含 SQLite 头"判断。

完整实战记录见项目 `docs/key_extraction_success_20260911.md`。

## FTS 兜底口径说明

当消息库密钥轮换失效、降级到全文索引库（`message_fts.db`）时，消息类型分类存在口径差异：

- **主库口径**（`chat_analysis.py`）：49 型卡片消息可解析 XML `<type>` 子类型，精确定位为文件/链接/商品/视频号等
- **FTS 兜底口径**（`build_analysis_from_fts.py`）：全文索引只存文本、无 XML，改用文本启发式分类
  - 文件扩展名匹配 → 文件
  - 含"邀请你加入群聊" → 群邀请
  - 含"[聊天记录]" → 聊天记录
  - 含"视频号" → 视频号
  - 含"小程序" → 小程序
  - 其余 49 型 → 链接卡片
- FTS 口径只收录带文本的消息（文字/链接/文件名等），图片、语音、表情包等未入索引的消息不在统计内

## 安全提醒

- 导出产物含完整聊天记录，属于高度敏感数据
- 明文库/报告文件不要提交到 git、不要外发
- 使用完毕建议删除导出目录（或按 `.gitignore` 排除）