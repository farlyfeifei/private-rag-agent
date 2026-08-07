# -*- coding: utf-8 -*-
"""生成英文旁白（edge-tts 神经语音），每镜头一个音频文件。"""
import asyncio
import os
import sys

import edge_tts

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = "demo/narration"
os.makedirs(OUT, exist_ok=True)

VOICE = "en-US-AriaNeural"   # 自然美音女声

# 八镜头旁白（与 demo_video_EN.md 对应；顺序见 assemble_video.py 的 ORDER）
SHOTS = [
    ("shot1", "This is Private RAG Agent — a fully offline, local, private multi-agent assistant. Every document you import is processed right on this machine. Nothing ever leaves your device."),
    ("shot2", "Building a knowledge base is simple. Import individual documents, select a whole folder, or read every supported file on this machine — PDF, Word, Markdown, Excel, and PowerPoint. You decide exactly what the agent can see."),
    ("shot8", "The entire interface is bilingual. Open the settings panel, and switch between English and Chinese with a single click — every label, button, and status message updates instantly. English is the default, so international judges and users feel at home from the very first screen."),
    ("shot3", "Now let's ask a question. Before answering, the agent retrieves from the knowledge base using hybrid search — semantic vectors fused with BM25 keywords, then re-ranked by a cross-encoder for precision. The answer streams out in real time, and every sentence carries a citation. Click any source to jump straight to the original text, with the matched terms highlighted."),
    ("shot7", "But what happens when you ask something the knowledge base doesn't cover? Watch closely. We ask for a well-known fact together with tomorrow's weather. The agent answers the part it genuinely knows, and labels its source. Then, for the weather, it openly states that the information is not in the knowledge base, and points you to a live service instead. It never fabricates an answer. This honesty is the entire point of a trustworthy assistant — it would rather admit a gap than invent a fact."),
    ("shot4", "This is the core of the project — the multi-agent pipeline. A complex question is decomposed into independent sub-tasks, and several researcher agents search the knowledge base in parallel, each writing its own report. Then every report passes through a fact-checker, which scores each statement against the retrieved evidence. Only content that passes verification is synthesized into the final answer. The interface shows you exactly which sentence rests on which source, and the plan panel lets you follow every step of the reasoning as it unfolds."),
    ("shot5", "All inference runs locally on AMD Radeon hardware. The GPU monitor shows utilization, memory, and temperature in real time, updating live as the model works. On Radeon with ROCm, throughput is projected to improve five to ten times over a CPU baseline — which is exactly why the parallel researcher agents are scheduled onto the GPU together, turning that headroom into faster answers."),
    ("shot6", "Private RAG Agent: retrieval you can trace, answers you can verify, and data that never leaves this machine. Thank you for watching."),
]

async def gen(name, text):
    out = os.path.join(OUT, f"{name}.mp3")
    comm = edge_tts.Communicate(text, VOICE, rate="-6%")
    await comm.save(out)
    return out, os.path.getsize(out)

async def main():
    for name, text in SHOTS:
        out, size = await gen(name, text)
        print(f"{name}: {size} bytes -> {out}")

asyncio.run(main())
