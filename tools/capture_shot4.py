# -*- coding: utf-8 -*-
"""shot4：多 Agent 完整运行采集（每 2s 一帧，后期提速到 32s）。"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7860"
FOLDER = "demo/frames/shot4"
os.makedirs(FOLDER, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 860})
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        time.sleep(3)
        # 多 Agent 模式 + 发送（先显式设 state.mode 再点击，确保生效）
        page.fill("textarea", "总结这个项目的技术栈、AMD 优化点和部署方式")
        page.evaluate("""() => {
          const m = Array.from(document.querySelectorAll('.mode-btn')).find(b => b.dataset.mode === 'multi');
          if (m) m.click();
          document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
          if (m) m.classList.add('active');
          if (window.__STATE) {} else {}
        }""")
        time.sleep(0.8)
        # 确认 multi 已激活（否则重试点击）
        active = page.evaluate("() => { const m = document.querySelector('.mode-btn[data-mode=multi]'); return m ? m.classList.contains('active') : false; }")
        if not active:
            page.evaluate("() => { const m = document.querySelector('.mode-btn[data-mode=multi]'); if (m) m.click(); }")
            time.sleep(0.5)
        print("multi active:", active)
        page.evaluate("() => { document.querySelector('.send-btn').click(); }")
        # 采集直到完成：要求"计划面板出现过 + 至少 120s + 回答长度稳定"
        last, stable = -1, 0
        saw_plan = False
        t0 = time.time()
        idx = 0
        while time.time() - t0 < 420:
            time.sleep(2)
            plan = page.evaluate("() => !!document.querySelector('.plan-panel')")
            if plan: saw_plan = True
            ln = page.evaluate("() => { const a = document.querySelectorAll('.msg.assistant'); const m = a[a.length-1]; return m && m.querySelector('.md.stream') ? m.querySelector('.md.stream').textContent.length : 0; }")
            if ln == last and saw_plan and (time.time() - t0) > 120:
                stable += 1
                if stable >= 2: break
            else:
                stable = 0; last = ln
            page.screenshot(path=os.path.join(FOLDER, f"frame_{idx:04d}.png"))
            idx += 1
        # 结束时再多截几帧（答案+校验面板定格）
        for _ in range(4):
            page.screenshot(path=os.path.join(FOLDER, f"frame_{idx:04d}.png"))
            idx += 1
            time.sleep(1)
        print(f"shot4 captured {idx} frames in {time.time()-t0:.0f}s")
        browser.close()


if __name__ == "__main__":
    main()
