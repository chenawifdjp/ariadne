#!/usr/bin/env python3
"""
Ariadne 一键安装脚本
用法: python setup.py
"""
import subprocess, sys, os

print("🧵 Ariadne Memory Router 安装中...")
print(f"   Hermes 目录: D:\\hermes")
print(f"   AGENTS.md: {'存在' if os.path.exists('D:/hermes/AGENTS.md') else '不存在'}")

# 跑一次 compile
result = subprocess.run(
    [sys.executable, "ariadne.py", "compile"],
    capture_output=True, text=True, timeout=30
)
print(result.stdout)
if result.returncode == 0:
    print("[Ariadne] ✅ 安装完成")
    print("   下次 Hermes 会话自动加载路由表")
    print("   当用户纠正错误时，AI 调 ingest → compile 即可")
else:
    print(f"[Ariadne] ❌ 失败: {result.stderr}")
