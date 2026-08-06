# -*- coding: utf-8 -*-
"""英文配音演示视频 - 分镜画面采集（playwright 驱动真实 UI）。

每个镜头按旁白时长采集帧，输出 demo/frames/<shot>/frame_NNNN.png。
shot4（多 Agent）单独采集完整运行，后期提速。
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7860"
ROOT = "demo/frames"
os.makedirs(ROOT, exist_ok=True)

# 每镜头目标时长（与旁白对齐，秒）
DUR = {"shot1": 14, "shot2": 14, "shot3": 26, "shot5": 22, "shot6": 10}
FPS = 1.0  # 非多 Agent 镜头按 1fps 采集


def grab(page, folder, count):
    os.makedirs(folder, exist_ok=True)
    for i in range(count):
        page.screenshot(path=os.path.join(folder, f"frame_{i:04d}.png"))
        time.sleep(1 / FPS)
    print(f"  {folder}: {count} frames")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 860})
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # ---- 镜头 1：开场（空状态）----
        print("[shot1] opening empty state")
        grab(page, f"{ROOT}/shot1", int(DUR["shot1"] * FPS))

        # ---- 镜头 2：知识库与三种导入 ----
        print("[shot2] knowledge base + import modes")
        # 切到英文、悬停导入按钮展示三种方式
        for btn_sel in ["#folder-btn", "#scan-all-btn", "#import-btn"]:
            try:
                page.locator(btn_sel).hover()
                time.sleep(0.8)
            except Exception:
                pass
        grab(page, f"{ROOT}/shot2", int(DUR["shot2"] * FPS))

        # ---- 镜头 3：单 Agent 问答 ----
        print("[shot3] single-agent Q&A")
        page.fill("textarea", "这个项目的技术栈是什么？")
        page.evaluate("() => { document.querySelector('.send-btn').click(); }")
        # 等回答完成（流式停止）
        last, stable = -1, 0
        for _ in range(60):
            time.sleep(0.5)
            ln = page.evaluate("() => { const m = document.querySelector('.msg.assistant:last-of-type .md.stream'); return m ? m.textContent.length : 0; }")
            if ln == last: stable += 1
            else: stable = 0; last = ln
            if stable >= 3: break
        grab(page, f"{ROOT}/shot3", int(DUR["shot3"] * FPS))

        # ---- 镜头 5：GPU 监控面板 ----
        print("[shot5] GPU monitor")
        page.evaluate("() => { const t = Array.from(document.querySelectorAll('.panel-tab')).find(x => x.textContent.includes('GPU')); if (t) t.click(); }")
        grab(page, f"{ROOT}/shot5", int(DUR["shot5"] * FPS))
        page.evaluate("() => { const t = Array.from(document.querySelectorAll('.panel-tab')).find(x => x.textContent.includes('Activity')); if (t) t.click(); }")

        # ---- 镜头 6：收尾（点击引用打开来源抽屉 = "可追溯"）----
        print("[shot6] closing - source drawer")
        page.evaluate("() => { const c = document.querySelector('.cite-chip'); if (c) c.click(); }")
        time.sleep(1.5)
        grab(page, f"{ROOT}/shot6", int(DUR["shot6"] * FPS))
        page.evaluate("() => { const m = document.getElementById('doc-drawer-mask'); if (m) m.classList.add('hidden'); }")

        browser.close()
    print("done live shots")


if __name__ == "__main__":
    main()
