# -*- coding: utf-8 -*-
"""采集两个新镜头：
  shot7 = 库外诚实回答（问库外问题，展示"知识库中没有相关信息"、不编造）
  shot8 = 中英界面切换（设置面板 EN -> 切 ZH -> 展示中文界面）
输出 demo/frames/shot7 与 demo/frames/shot8。
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7860"
ROOT = "demo/frames"


def grab_seq(page, folder, count, interval=1.0):
    os.makedirs(folder, exist_ok=True)
    # 清旧帧
    for f in os.listdir(folder):
        if f.endswith(".png"):
            os.remove(os.path.join(folder, f))
    for i in range(count):
        page.screenshot(path=os.path.join(folder, f"frame_{i:04d}.png"))
        time.sleep(interval)
    print(f"  {folder}: {count} frames")


def capture_shot7(page):
    """库外诚实回答。"""
    print("[shot7] out-of-KB honesty")
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    time.sleep(2.5)
    folder = f"{ROOT}/shot7"
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        if f.endswith(".png"):
            os.remove(os.path.join(folder, f))

    q = "What is the capital of France, and what is the weather there tomorrow?"
    page.fill("#input", q)
    idx = 0
    # 输入后停一下（展示问题）
    for _ in range(3):
        page.screenshot(path=os.path.join(folder, f"frame_{idx:04d}.png")); idx += 1
        time.sleep(1.0)
    # 发送
    page.evaluate("() => { document.getElementById('send-btn').click(); }")
    # 流式期间连续截帧（约 30 帧覆盖全过程 + 停留）
    last, stable = -1, 0
    for _ in range(34):
        page.screenshot(path=os.path.join(folder, f"frame_{idx:04d}.png")); idx += 1
        time.sleep(1.0)
        ln = page.evaluate("() => { const m=document.querySelector('.msg.assistant:last-of-type .md.stream'); return m ? m.textContent.length : 0; }")
        if ln == last:
            stable += 1
        else:
            stable = 0; last = ln
        # 回答稳定后再多停 8 帧展示最终"诚实"结果即可
        if stable >= 8 and idx >= 30:
            break
    print(f"  shot7: {idx} frames")


def capture_shot8(page):
    """中英界面切换：EN 设置面板 -> 切 ZH -> 中文界面。"""
    print("[shot8] bilingual toggle")
    folder = f"{ROOT}/shot8"
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        if f.endswith(".png"):
            os.remove(os.path.join(folder, f))
    idx = 0

    def snap(n=1, dt=1.0):
        nonlocal idx
        for _ in range(n):
            page.screenshot(path=os.path.join(folder, f"frame_{idx:04d}.png")); idx += 1
            time.sleep(dt)

    # 1) 确保英文
    page.evaluate("() => { try{localStorage.setItem('privrag_lang','en')}catch(e){} }")
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    time.sleep(2.5)
    snap(3)  # 英文主界面
    # 2) 打开设置面板
    page.evaluate("() => { document.getElementById('settings-btn').click(); }")
    time.sleep(1.0)
    snap(4)  # 英文设置面板（含语言下拉）
    # 3) 高亮语言下拉
    page.evaluate("() => { const s=document.getElementById('lang-select'); if(s){s.focus(); s.style.outline='3px solid #22c55e';} }")
    snap(3)
    # 4) 切到中文（会 reload）
    page.evaluate("() => { try{localStorage.setItem('privrag_lang','zh')}catch(e){} }")
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    time.sleep(2.5)
    snap(3)  # 中文主界面
    # 5) 打开中文设置面板
    page.evaluate("() => { document.getElementById('settings-btn').click(); }")
    time.sleep(1.0)
    snap(5)  # 中文设置面板
    # 复位为英文（默认）
    page.evaluate("() => { try{localStorage.setItem('privrag_lang','en')}catch(e){} }")
    print(f"  shot8: {idx} frames")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 860})
        capture_shot7(page)
        capture_shot8(page)
        browser.close()
    print("done new shots")


if __name__ == "__main__":
    main()

