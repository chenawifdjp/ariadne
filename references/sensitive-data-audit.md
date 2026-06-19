# 敏感数据审计清单

公开发布 Hermes Skill 前，逐项检查以下内容。

## 代码中

| 检查项 | 示例 | 动作 |
|--------|------|------|
| 内网 IP / 端口 | `127.0.0.1:7897`, `192.168.x.x`, `10.x.x.x` | 泛化为"系统代理"或"浏览器工具自动管理" |
| API key / token / secret | `sk-xxx`, `Bearer xxx` | 删除，用环境变量占位符代替 |
| 用户特定 skill 名 | `football-prediction`, `betting-post-match` | 如果硬编码在 TRIGGER_MAP 里 → 清空，靠 scan_skills() 自动发现 |
| 第三方服务 URL | `ql2peo.vip:7382`, 特定 API 端点 | 删除或泛化 |
| 私人称呼 | "主人", 特定人名 | 改为"用户" |
| CDP URL / Chrome 路径 | `cdp_url=http://127.0.0.1:9222` | 泛化 |

## SKILL.md 中

| 检查项 | 动作 |
|--------|------|
| "主人" 等私人称呼 | 全文替换为"用户" |
| 和用户本机 B6 的对比表 | 去掉——这是开源项目，不是个人文档 |
| 提到用户特定环境配置 | 泛化或删除 |
| 安装说明假设特定路径 | 确认路径是 Hermes 标准路径（D:\hermes\skills\） |

## 正则扫描命令

```bash
# 扫描所有文件中的敏感模式
python -c "
import re, os
patterns = [
    (r'127\.0\.0\.1:\d+', '本地代理端口'),
    (r'主人', '私人称呼'),
    (r'api[_-]?key|token|secret|password', '凭证关键词'),
    (r'192\.168\.|10\.\d+\.|172\.(1[6-9]|2\d|3[01])\.', '内网IP'),
]
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if f.endswith(('.py','.md','.sh','.json','.yaml','.yml')):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as fh:
                content = fh.read()
            for pat, label in patterns:
                if re.search(pat, content, re.IGNORECASE):
                    print(f'⚠️  {path}: {label}')
print('✅ 扫描完成')
"
```

## 本 skill 审计记录

- 2026-06-19: 首次审计 → 发现 6 项（本地代理端口、CDP端口、硬编码 skill 名、私人称呼），全部修复后通过。
