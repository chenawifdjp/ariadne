#!/usr/bin/env python3
"""
Ariadne Memory Router (AMR) — Lite Edition
==========================================
AGENTS.md 自存储路由表引擎。零外部依赖。

用法:
  python ariadne.py compile              # 重新编译 AGENTS.md 路由表
  python ariadne.py ingest "规则内容"     # 添加新规则
         --tags "编码,gbk" --importance 4
  python ariadne.py routes               # 查看当前路由表
  python ariadne.py hit "编码"            # 标记某条规则被命中（hit_count+1）

设计:
  所有规则存储在 AGENTS.md 的隐藏 JSON 块中。
  编译器从 JSON 读取 → 生成路由表+热缓存+回退 → 写回 AGENTS.md。
  不需要 Obsidian, vault_index.json, 或任何外部依赖。
"""

import json
import os
import re
import sys
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 路径 ──────────────────────────────────────────────
AGENTS_MD = Path("D:/hermes/AGENTS.md")
SKILLS_DIR = Path("D:/hermes/skills")

# AGENTS.md 标记 — Ariadne 独立，不和 B6 COMPILED:RULES 冲突
BLOCK_START = "<!-- COMPILED:ARIADNE_START -->"
BLOCK_END = "<!-- COMPILED:ARIADNE_END -->"
STORE_MARKER = "ARIADNE_STORE"

# ── Mini 回退（硬编码，永不删除）────────────────────
MINI_FALLBACK = [
    "所有文件读写 → encoding='utf-8' + 子进程编码 fallback",
    "外网访问 → 一律走系统代理",
    "Chrome 操作 → 由浏览器工具自动管理，不手动杀进程",
    "搜索结果 → 双源交叉验证，单源不采纳",
    "UI/方案 → 不简化，每行对齐，一次做对",
    "用户纠正 → 立刻改，不辩解",
]

# ── 技能触发词映射 — 留空，由 scan_skills() 自动发现用户本机 skills ──
SKILL_TRIGGER_MAP = {}

# ── 通用触发词映射（非技能路由）─────────────────────
CATEGORY_TRIGGERS = {
    "编码": ["编码", "gbk", "utf8", "utf-8", "乱码", "中文路径", "encoding"],
    "浏览器": ["浏览器", "CDP", "Chrome", "cdp", "chrome", "browser"],
    "代理": ["代理", "翻墙", "proxy", "7897", "网络"],
    "配置": ["配置", "安装", "hermes", "MCP", "config", "install"],
    "UI": ["UI", "对齐", "HTML", "布局", "报告", "CSS", "layout"],
    "文件": ["文件", "路径", "file", "path", "not found"],
    "记忆": ["记忆", "保存", "存储", "记住", "memory", "export"],
    "Git": ["git", "commit", "push", "pull", "clone", "分支"],
    "验证": ["验证", "交叉", "信源", "搜索验证", "双源", "crosscheck"],
    "预测": ["预测", "泊松", "lambda", "poisson", "xG"],
    "Python": ["python", "pip", "venv", "import", "package", "模块"],
    "Windows": ["windows", "cmd", "powershell", "msys", "bash路径"],
}

# ── 默认种子规则（全新安装时的初始规则）─────────────
SEED_RULES = [
    {
        "id": "seed_gbk",
        "content": "所有 open() 调用带 encoding='utf-8'；子进程输出先试 utf-8 后 gbk",
        "tags": ["编码", "gbk", "utf8"],
        "importance": 5,
    },
    {
        "id": "seed_proxy",
        "content": "外网访问一律走系统代理；git clone 境外仓库加代理参数",
        "tags": ["代理", "proxy", "网络"],
        "importance": 5,
    },
    {
        "id": "seed_browser",
        "content": "Chrome 由浏览器工具自动管理，不手动杀进程",
        "tags": ["浏览器", "Chrome"],
        "importance": 5,
    },
    {
        "id": "seed_crosscheck",
        "content": "搜索结果双源交叉验证；单源标注警告；野鸡站跳过",
        "tags": ["验证", "搜索"],
        "importance": 4,
    },
    {
        "id": "seed_nosimplify",
        "content": "方案不许简化；UI 每行对齐一次做对；用户说算了就放弃",
        "tags": ["UI", "偏好"],
        "importance": 4,
    },
]


# ══════════════════════════════════════════════════════
# 原子写入
# ══════════════════════════════════════════════════════

def atomic_write(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ══════════════════════════════════════════════════════
# 规则存储（AGENTS.md 内嵌 JSON）
# ══════════════════════════════════════════════════════

def load_store() -> dict:
    """从 AGENTS.md 读取 ARIADNE_STORE"""
    if not AGENTS_MD.exists():
        return {"rules": [], "version": 0}
    content = AGENTS_MD.read_text(encoding="utf-8")
    # 匹配 <!-- ARIADNE_STORE {...} ARIADNE_STORE -->
    m = re.search(rf"<!--\s*{STORE_MARKER}\s*({{.+?}})\s*{STORE_MARKER}\s*-->", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return {"rules": [], "version": 0}


def save_store(store: dict, agents_content: str) -> str:
    """将 store 写入 AGENTS.md 内容中，返回新内容"""
    store_json = json.dumps(store, ensure_ascii=False, separators=(",", ":"))
    marker_line = f"<!-- {STORE_MARKER} {store_json} {STORE_MARKER} -->"
    
    if BLOCK_START in agents_content and BLOCK_END in agents_content:
        # 替换已有的 ARIADNE_STORE（如果有）
        if STORE_MARKER in agents_content:
            agents_content = re.sub(
                rf"<!--\s*{STORE_MARKER}\s*{{.+?}}\s*{STORE_MARKER}\s*-->",
                marker_line,
                agents_content,
                flags=re.DOTALL,
            )
            return agents_content
        else:
            # 插入到 BLOCK_END 之前
            before = agents_content.split(BLOCK_END)[0]
            after = BLOCK_END + agents_content.split(BLOCK_END, 1)[-1] if BLOCK_END in agents_content.split(BLOCK_END, 1)[-1] else ""
            if len(agents_content.split(BLOCK_END)) > 1:
                after = BLOCK_END + agents_content.split(BLOCK_END, 1)[-1]
            else:
                after = BLOCK_END + "\n"
            return before.rstrip() + "\n" + marker_line + "\n" + after
    else:
        # 无编译块 → 创建新块
        new_block = generate_block(store)
        return agents_content.rstrip() + "\n\n" + new_block + "\n"
    
    return agents_content


def add_rule(store: dict, content: str, tags: List[str], importance: int = 4) -> dict:
    """添加新规则到 store"""
    rule_id = hashlib.md5(content.encode()).hexdigest()[:8]
    now = datetime.now().isoformat()
    
    # 去重：相同内容已存在则只更新
    for r in store["rules"]:
        if r.get("content", "").strip() == content.strip():
            r["hit_count"] = r.get("hit_count", 0) + 1
            r["last_hit"] = now
            r["importance"] = max(r.get("importance", 3), importance)
            r["tags"] = list(set(r.get("tags", []) + tags))
            return store
    
    store["rules"].append({
        "id": rule_id,
        "content": content,
        "tags": tags,
        "importance": importance,
        "hit_count": 1,
        "created": now,
        "last_hit": now,
        "source": "user_correction",
    })
    return store


# ══════════════════════════════════════════════════════
# 技能自动发现
# ══════════════════════════════════════════════════════

def scan_skills() -> Dict[str, str]:
    skills_map = {}
    if not SKILLS_DIR.exists():
        return skills_map
    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.exists():
            continue
        try:
            content = skill_path.read_text(encoding="utf-8")
        except Exception:
            continue
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue
        name_match = re.search(r"name:\s*(.+)", parts[1])
        desc_match = re.search(r"description:\s*(.+)", parts[1])
        if name_match:
            skills_map[name_match.group(1).strip()] = desc_match.group(1).strip() if desc_match else ""
    return skills_map


# ══════════════════════════════════════════════════════
# 编译：规则 → 路由表 + 热缓存
# ══════════════════════════════════════════════════════

def compile_routes(store: dict, skills_map: Dict[str, str]) -> Tuple[List, List]:
    """从 store 和 skills 生成路由表和热缓存"""
    rules = store.get("rules", [])
    now = datetime.now()
    
    # ── 热缓存：hit_count 最高 8 条，衰减 ≥ 2.0 ──
    cached = []
    for r in sorted(rules, key=lambda x: x.get("hit_count", 0), reverse=True)[:8]:
        hit_count = r.get("hit_count", 0)
        # 简单衰减：age > 7 天 → ×0.7
        created = r.get("created", "")
        try:
            dt = datetime.fromisoformat(created.replace("Z", ""))
            days = (now.replace(tzinfo=None) - dt.replace(tzinfo=None)).days
        except:
            days = 0
        decay = hit_count * (0.70 ** max(days - 7, 0) / 7) if days > 7 else hit_count
        if decay >= 2.0:
            r["decay"] = round(decay, 1)
            cached.append(r)
    
    # ── 路由表 ──
    routes = []
    
    # Skill 覆盖
    for skill_name, keywords in SKILL_TRIGGER_MAP.items():
        if skill_name.lower() in skills_map:
            action = f"skill_view(name='{skill_name}')"
            routes.append(("|".join(keywords[:4]), True, action, "skill已加载"))
    
    # 规则触发词 → 归类
    category_rules = {}
    for r in rules:
        if r.get("importance", 3) < 3:
            continue
        tags = r.get("tags", [])
        matched = False
        for cat, triggers in CATEGORY_TRIGGERS.items():
            if any(t.lower() in " ".join(tags).lower() for t in triggers):
                category_rules.setdefault(cat, []).append(r)
                matched = True
                break
        if not matched:
            category_rules.setdefault("其他", []).append(r)
    
    for cat, items in sorted(category_rules.items(), key=lambda x: -len(x[1])):
        # 检查是否已被 skill 覆盖
        if any(cat.lower() in kw.lower() for kw_list in SKILL_TRIGGER_MAP.values() for kw in kw_list):
            continue
        # "其他" 也在路由表显示（作为通用回退）
        action = f"# 读取 AGENTS.md 热缓存段中 '{cat}' 相关规则"
        cache_n = min(len(items), 3)
        routes.append((", ".join([cat]), False, action, f"cache:{cache_n}"))
    
    routes.append(("无匹配", False, "# 读取 AGENTS.md 热缓存 + Mini回退", "—"))
    
    return routes, cached


def generate_block(store: dict) -> str:
    """生成完整 AGENTS.md 编译块"""
    skills_map = scan_skills()
    routes, cached = compile_routes(store, skills_map)
    now = datetime.now().isoformat()[:16]
    store_json = json.dumps(store, ensure_ascii=False, separators=(",", ":"))
    
    lines = [BLOCK_START]
    lines.append(f"## 🔀 Ariadne 记忆路由（编译: {now} · 活跃规则: {len(store.get('rules', []))}条）")
    lines.append("")
    
    # 路由表
    lines.append("### 触发路由表")
    lines.append("| 触发词 | Skill? | 动作 | 期望 | 降级 |")
    lines.append("|--------|:--:|------|------|------|")
    for kw, covered, action, cache in routes:
        skill_mark = "✅" if covered else "❌"
        fallback = "—" if covered else "热缓存→Mini回退"
        lines.append(f"| {kw} | {skill_mark} | {action} | {cache} | {fallback} |")
    lines.append("")
    
    # 热缓存
    lines.append("### 🔥 热缓存")
    lines.append("*以下规则可直接使用，无需查询。命中次数越高越优先。*")
    lines.append("")
    for r in cached:
        title = r.get("content", "?")[:60]
        hit = r.get("hit_count", 0)
        decay = r.get("decay", hit)
        lines.append(f"#### {title} [命中:{hit}·衰减:{decay}]")
        # 完整内容
        full = r.get("content", "")
        for para in full.split("；"):
            para = para.strip()
            if para:
                lines.append(f"- {para}")
        lines.append("")
    
    if not cached:
        lines.append("*（暂无热缓存规则——多纠正我几次就会有了）*")
        lines.append("")
    
    # Mini 回退
    lines.append("### 🛡️ Mini 回退（所有层炸了的底线）")
    for i, rule in enumerate(MINI_FALLBACK, 1):
        lines.append(f"{i}. {rule}")
    lines.append("")
    
    # 隐藏 JSON 存储
    lines.append(f"<!-- {STORE_MARKER} {store_json} {STORE_MARKER} -->")
    lines.append(BLOCK_END)
    
    return "\n".join(lines)


# ══════════════════════════════════════════════════════
# 命令行
# ══════════════════════════════════════════════════════

def cmd_compile():
    """编译：读 AGENTS.md → 解析 store → 生成新块 → 写回"""
    store = load_store()
    
    # 如果 store 为空 → 注入种子规则
    if not store.get("rules"):
        store["rules"] = [dict(r) for r in SEED_RULES]
        for r in store["rules"]:
            r["hit_count"] = 1
            r["created"] = datetime.now().isoformat()
            r["last_hit"] = datetime.now().isoformat()
        store["version"] = 1
        print(f"[ariadne] 注入 {len(SEED_RULES)} 条种子规则")
    
    store["version"] = store.get("version", 0) + 1
    store["compiled"] = datetime.now().isoformat()
    
    # 读现有 AGENTS.md
    if AGENTS_MD.exists():
        content = AGENTS_MD.read_text(encoding="utf-8")
    else:
        content = ""
    
    # 生成新块
    new_block = generate_block(store)
    
    # 替换或追加
    if BLOCK_START in content and BLOCK_END in content:
        before = content.split(BLOCK_START)[0]
        after_parts = content.split(BLOCK_END)
        after = after_parts[-1] if len(after_parts) > 1 else ""
        new_content = before + new_block + after
    else:
        new_content = content.rstrip() + "\n\n" + new_block + "\n"
    
    atomic_write(AGENTS_MD, new_content)
    print(f"[ariadne] ✅ 编译完成 · 路由:{len([r for r in compile_routes(store, scan_skills())[0] if not r[1]])}条 · 缓存:{len(compile_routes(store, scan_skills())[1])}条 · 规则:{len(store['rules'])}条")


def cmd_ingest():
    """添加新规则"""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("content", help="规则内容")
    p.add_argument("--tags", default="", help="逗号分隔的标签")
    p.add_argument("--importance", type=int, default=4, help="重要度 1-5")
    args = p.parse_args()
    
    store = load_store()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    store = add_rule(store, args.content, tags, args.importance)
    store["version"] = store.get("version", 0) + 1
    
    # 写回
    if AGENTS_MD.exists():
        content = AGENTS_MD.read_text(encoding="utf-8")
    else:
        content = ""
    new_content = save_store(store, content)
    atomic_write(AGENTS_MD, new_content)
    
    print(f"[ariadne] ✅ 已添加规则 (tags: {tags}, imp: {args.importance})")


def cmd_routes():
    """显示当前路由表"""
    store = load_store()
    skills_map = scan_skills()
    routes, cached = compile_routes(store, skills_map)
    
    print(f"=== Ariadne 路由表 · {len(store.get('rules', []))} 条规则 ===\n")
    for kw, covered, action, cache in routes:
        print(f"  {'✅' if covered else '❌'} {kw:25s} → {action}")
    
    print(f"\n=== 热缓存 ({len(cached)} 条) ===")
    for r in cached:
        print(f"  [{r.get('importance',3)}★] {r.get('content','?')[:60]} (命中:{r.get('hit_count',0)})")


def cmd_hit():
    """标记规则命中"""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("tag", help="要标记命中的标签")
    args = p.parse_args()
    
    store = load_store()
    hit_count = 0
    for r in store.get("rules", []):
        if args.tag.lower() in " ".join(r.get("tags", [])).lower():
            r["hit_count"] = r.get("hit_count", 0) + 1
            r["last_hit"] = datetime.now().isoformat()
            hit_count += 1
    
    if AGENTS_MD.exists():
        content = AGENTS_MD.read_text(encoding="utf-8")
    else:
        content = ""
    new_content = save_store(store, content)
    atomic_write(AGENTS_MD, new_content)
    
    print(f"[ariadne] ✅ 命中 {hit_count} 条规则 (tag: {args.tag})")


def cmd_status():
    """状态"""
    store = load_store()
    print(f"规则总数: {len(store.get('rules', []))}")
    print(f"版本: {store.get('version', 0)}")
    print(f"最后编译: {store.get('compiled', '从未')}")
    if AGENTS_MD.exists():
        content = AGENTS_MD.read_text(encoding="utf-8")
        has_block = BLOCK_START in content
        print(f"AGENTS.md: {'已有编译块' if has_block else '无编译块'}")
        has_store = STORE_MARKER in content
        print(f"ARIADNE_STORE: {'已有' if has_store else '无'}（规则存储在 AGENTS.md 内嵌 JSON）")


# ══════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    cmd = sys.argv[1]
    # 允许子命令带自己的参数
    sys.argv = [sys.argv[0]] + sys.argv[2:] if len(sys.argv) > 2 else [sys.argv[0]]
    
    if cmd == "compile":
        cmd_compile()
    elif cmd == "ingest":
        cmd_ingest()
    elif cmd == "routes":
        cmd_routes()
    elif cmd == "hit":
        cmd_hit()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"未知命令: {cmd}")
        print("可用: compile, ingest, routes, hit, status")


if __name__ == "__main__":
    main()
