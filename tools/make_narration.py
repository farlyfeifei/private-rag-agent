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

# 六镜头旁白（与 demo_video_EN.md 对应）
SHOTS = [
    ("shot1", "This is Private RAG Agent — a fully offline, local, private multi-agent assistant. Every document you import is processed right on this machine. Nothing ever leaves your device."),
    ("shot2", "Building a knowledge base is simple. Import individual documents, select a whole folder, or read every supported file on this machine — PDF, Word, Markdown, Excel, and PowerPoint."),
    ("shot3", "Now let's ask a question. Before answering, the agent retrieves from the knowledge base using hybrid search — semantic vectors fused with BM25 keywords, then re-ranked by a cross-encoder for precision. The answer streams out in real time, and every sentence carries a citation. Click any source to jump straight to the original text, with the matched terms highlighted."),
    ("shot4", "This is the core of the project — the multi-agent pipeline. A complex question is decomposed into independent sub-tasks, and several researcher agents search the knowledge base in parallel, each writing its own report. Then every report passes through a fact-checker, which scores each statement against the retrieved evidence. Only content that passes verification is synthesized into the final answer — and the interface shows you exactly which sentence rests on which source."),
    ("shot5", "All inference runs locally on AMD Radeon hardware. The GPU monitor shows utilization, memory, and temperature in real time. On Radeon with ROCm, throughput is projected to improve five to ten times over CPU — which is why the parallel researchers are scheduled onto the GPU at once."),
    ("shot6", "Private RAG Agent: retrieval you can trace, answers you can verify, and data that never leaves this machine. Thank you."),
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
