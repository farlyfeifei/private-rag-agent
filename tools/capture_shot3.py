# -*- coding: utf-8 -*-
"""shot3 v2：捕捉单 Agent 流式打字过程（发消息即刻开始逐帧拍）。"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7860"
FOLDER = "demo/frames/shot3"
os.makedirs(FOLDER, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 860})
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        time.sleep(3)
        page.fill("textarea", "这个项目的技术栈是什么？")
        page.evaluate("() => { document.querySelector('.send-btn').click(); }")
        # 发送后立即开始逐帧拍（0.5s/帧），直到回答完成 + 定格
        last, stable = -1, 0
        idx = 0
        t0 = time.time()
        while time.time() - t0 < 120:
            time.sleep(0.5)
            page.screenshot(path=os.path.join(FOLDER, f"frame_{idx:04d}.png"))
            idx += 1
            ln = page.evaluate("() => { const a = document.querySelectorAll('.msg.assistant'); const m = a[a.length-1]; return m && m.querySelector('.md.stream') ? m.querySelector('.md.stream').textContent.length : 0; }")
            if ln == last: stable += 1
            else: stable = 0; last = ln
            if stable >= 6: break   # 回答稳定约 3s 后停
        # 定格几帧（引用卡片/校验面板）
        for _ in range(6):
            page.screenshot(path=os.path.join(FOLDER, f"frame_{idx:04d}.png"))
            idx += 1
            time.sleep(0.5)
        print(f"shot3 v2 captured {idx} frames in {time.time()-t0:.0f}s")
        browser.close()


if __name__ == "__main__":
    main()
