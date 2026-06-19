# Hermes Ariadne — AI 自愈记忆引擎

> **用户纠正过的事情，绝不再犯第二遍。**

Ariadne 是一个运行在 AGENTS.md 里的轻量记忆路由引擎。它把用户对 AI 的每一次纠正，自动转换成可检索的规则，并在每次对话开始时注入 LLM 的上下文——让 AI 像有长期记忆一样，不再重复犯错。

---

## 问题

AI 助手每次对话都从零开始。用户纠正了 100 次"搜索结果要双源验证"，第 101 次还是凭第一眼就信了。每次都靠用户手动提醒，这是**记忆断层**。

## 方案

**AGENTS.md 自存储热缓存。** 零外部依赖，不装数据库，不需要 Obsidian。

```
用户纠正 → Ariadne 自动提炼规则 → 写入 AGENTS.md JSON → 每次对话自动加载
```

## 架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  用户纠正    │ ──▶ │  ariadne.py  │ ──▶ │  AGENTS.md       │
│ "下次别忘了" │     │  ingest命令   │     │  ├ 路由索引      │
└─────────────┘     └──────────────┘     │  ├ 热缓存块      │
                                          │  └ Mini回退       │
                                          └─────────────────┘
                                                 │
                                                 ▼
                                          ┌─────────────────┐
                                          │  下次对话        │
                                          │  LLM 自动加载    │
                                          │  按路由表决策    │
                                          └─────────────────┘
```

---

## 功能

| 功能 | 说明 |
|------|------|
| 🔁 **纠正即存储** | 检测"记住/别再犯/肯定是"等信号词 → 自动提炼规则 |
| 🏷️ **自动分类路由** | 规则按领域打标签（编码/搜索/UI/配置…）→ 下次精确匹配 |
| 📊 **热缓存命中统计** | 每条规则被成功使用一次 +1，自动淘汰冷规则 |
| ⚡ **Mini 回退** | 新装用户还没积累规则时，6 条通用底线规则兜底 |
| 🔌 **零外部依赖** | 纯 Python 标准库，不装数据库，不依赖 Obsidian |

---

## 技术栈

- **语言：** Python 3（标准库 only — `json`, `re`, `datetime`, `hashlib`）
- **存储：** AGENTS.md（LLM 原生读取的 Markdown 文件，内嵌 JSON 块）
- **编译：** 增量路由表 + 热缓存 Top-N + 自动去重
- **分发：** `SKILL.md`（给 LLM 的 SOP）+ `ariadne.py`（引擎）+ `setup.py`（一键注入）

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/chenawifdjp/hermes-ariadne.git
cd hermes-ariadne

# 2. 放到你的 Hermes skills 目录
#    Windows: 复制整个 ariadne 文件夹到 D:\hermes\skills\
#    macOS/Linux: 复制整个 ariadne 文件夹到 ~/.hermes/skills/

# 3. 一键安装（写入 AGENTS.md）
cd scripts
python setup.py
```

装完即刻生效——下次对话，AGENTS.md 里的 Ariadne 块就会被 LLM 自动加载。

---

## 文件结构

```
ariadne/
├── SKILL.md              # LLM 操作手册（4 条铁律 + 场景 + 陷阱）
├── scripts/
│   ├── ariadne.py        # 核心引擎（ingest/compile/routes/status/hit）
│   └── setup.py          # 一键安装脚本（注入 AGENTS.md）
└── references/
    └── sensitive-data-audit.md  # 公开发布前敏感数据审计清单
```

---

## 命令

| 命令 | 作用 |
|------|------|
| `python ariadne.py ingest "规则" --tags "X,Y"` | 存入一条规则 |
| `python ariadne.py compile` | 编译路由表到 AGENTS.md |
| `python ariadne.py routes` | 查看当前路由索引 |
| `python ariadne.py status` | 自检编译块状态 |
| `python ariadne.py hit "标签"` | 记录一次热缓存命中 |

---

## 常见问题

**Q: 需要 Obsidian 吗？**  
A: 不需要。Ariadne 完全独立，只依赖 AGENTS.md。

**Q: 和其他规则系统冲突吗？**  
A: 不会。Ariadne 编译块用 `COMPILED:ARIADNE` 标记，与其他系统完全隔离。

**Q: 规则太多会爆炸吗？**  
A: 编译块只展示路由索引 + Top-N 热缓存，不会把所有规则都塞进上下文。

**Q: 能跨设备同步吗？**  
A: AGENTS.md 是纯文本文件，随便用 git / Dropbox / iCloud 同步就行。

---

## 许可

MIT License
