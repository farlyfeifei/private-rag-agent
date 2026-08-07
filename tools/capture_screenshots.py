# -*- coding: utf-8 -*-
"""截图 6 张关键功能图，输出到 docs/screenshots/。"""
import os, sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

OUT = "docs/screenshots"
os.makedirs(OUT, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 860})

    # 1) 空状态首页
    page.goto("http://127.0.0.1:7860", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    page.screenshot(path=f"{OUT}/01_empty_state.png")
    print("1/6 empty_state")

    # 2) 知识库（打开设置面板）
    page.evaluate("() => document.getElementById('settings-btn').click()")
    time.sleep(1.5)
    page.screenshot(path=f"{OUT}/02_knowledge_base.png")
    print("2/6 knowledge_base")
    page.evaluate("() => document.getElementById('modal-close').click()")
    time.sleep(0.5)

    # 3) 单Agent问答
    page.fill("#input", "What is the technical architecture of this project?")
    page.evaluate("() => document.getElementById('send-btn').click()")
    for _ in range(60):
        time.sleep(0.5)
        ln = page.evaluate("() => { const m=document.querySelector('.msg.assistant:last-of-type .md.stream'); return m ? m.textContent.length : 0; }")
        if ln > 200:
            break
    time.sleep(3)
    page.screenshot(path=f"{OUT}/03_single_agent_qa.png")
    print("3/6 single_agent_qa")

    # 4) 多Agent
    page.evaluate("() => { const b=document.querySelector('.new-chat-btn'); if(b) b.click(); }")
    time.sleep(2)
    page.evaluate("() => { const b=document.querySelector('.mode-btn[data-mode=multi]'); if(b) b.click(); }")
    time.sleep(0.5)
    page.fill("#input", "Explain the project architecture, key features, and deployment options.")
    page.evaluate("() => document.getElementById('send-btn').click()")
    time.sleep(8)
    for _ in range(40):
        hp = page.evaluate("() => !!document.querySelector('.plan-panel')")
        if hp:
            break
        time.sleep(1)
    time.sleep(15)
    page.screenshot(path=f"{OUT}/04_multi_agent.png")
    print("4/6 multi_agent")

    # 5) GPU监控
    page.evaluate("""() => {
        const t = Array.from(document.querySelectorAll('.panel-tab'))
            .find(x => x.textContent.includes('GPU'));
        if (t) t.click();
    }""")
    time.sleep(2)
    page.screenshot(path=f"{OUT}/05_gpu_monitor.png")
    print("5/6 gpu_monitor")

    # 6) 中文界面
    page.evaluate("() => { try{localStorage.setItem('privrag_lang','zh')}catch(e){} }")
    page.goto("http://127.0.0.1:7860", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    page.screenshot(path=f"{OUT}/06_chinese_ui.png")
    print("6/6 chinese_ui")
    page.evaluate("() => { try{localStorage.setItem('privrag_lang','en')}catch(e){} }")

    browser.close()
print("all done")