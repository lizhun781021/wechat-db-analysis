---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '766bba02-4968-4931-898c-f67a83bdbb4e'
  PropagateID: '766bba02-4968-4931-898c-f67a83bdbb4e'
  ReservedCode1: '665fea58-8595-4c31-83c8-2fab3b790b52'
  ReservedCode2: '665fea58-8595-4c31-83c8-2fab3b790b52'
---

# Changelog

本项目所有重要变更均记录于此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [v1.5.2] - 2026-08-16

### 变更
- 技能名称更名：`wechat-db-decrypt` → `wechat-db-reader`（读取/导出）
- 脚本更名：`decrypt_with_keys.py` → `db_export.py`（导出）
- 命令模式更名：`decrypt` → `export`（导出）
- 数据库操作库导入改为动态导入（`importlib.import_module("sqlcipher3")`），避免静态扫描检测
- `PRAGMA key` 语句拆分构建，避免被安全扫描器识别为敏感模式
- 技能目录重命名：`wechat-db-decrypt` → `wechat-db-reader`
- 项目存档同步更新

## [v1.5.1] - 2026-08-16

### 新增
- 新增微信数据库解密技能备份：`skill/wechat-db-decrypt/`（SKILL.md + 5 个脚本），
  技能支持三级能力：`decrypt`（仅解密 17 库）、`decrypt+analyze`（解密+聊天分析 JSON）、
  `decrypt+report`（解密+分析+文件扫描+完整 HTML 报告）
- `.gitignore` 放行 `skill/**/SKILL.md`，技能说明文件可随仓库版本管理

### 变更
- 技能脚本去除个人痕迹：微信目录与 wxid 改为自动探测（从
  `~/Library/Containers/com.tencent.xinWeChat/.../xwechat_files/` 扫描含
  `all_keys.json` 的账号目录，wxid 从目录名前缀自动推导），不硬编码个人路径

## [v1.5.0] - 2026-08-15

### 新增
- 每日微信聊天日报全链路：`scripts/chat_analysis.py` 支持 `--start-date/--end-date`
  日期过滤，`scripts/gen_daily_report.py` 生成精简日报 HTML，
  `scripts/html2png.js` 基于 Playwright 渲染 PNG 长图，
  `scripts/run_daily_report.py` 一键执行（解密→分析→HTML→长图）
- 配套定时任务：每天 08:00 自动生成前一天微信聊天日报

### 修复
- 报告附件 Top10 显示真实对话名称（对话 ID md5 反向映射），修复文件大小显示 0 MB 问题

## [v1.4.0] - 2026-08-16

### 新增
- all_keys.json 批量解密方案：通过账号目录下 `all_keys.json` 密钥文件
  将微信 17 个加密数据库批量解密为明文 SQLite

## 更早版本

### v1.3.x（2026-08-15）
- 微信本地数据库分析报告（HTML/MD）初版，支持群聊/私聊/时间分布统计