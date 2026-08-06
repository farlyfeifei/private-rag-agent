# -*- coding: utf-8 -*-
"""Gradio 网页界面：本地私有 RAG Agent 的演示 UI。

AMD 红黑科技风 · 流式打字机输出 · Agent 推理过程可视化
功能：上传文档入库 + 智能对话（RAG 检索 / 工具调用 / 任务规划）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr

# ============ 主题：AMD 红黑科技风 ============
AMD_RED = "#ED1C24"
AMD_DARK = "#0D0D0D"
AMD_BG = "#121212"
AMD_PANEL = "#1A1A1A"
AMD_ACCENT = "#FF4D54"
AMD_TEXT = "#E8E8E8"
AMD_GRAY = "#9A9A9A"

CUSTOM_CSS = f"""
:root {{
  --amd-red: {AMD_RED};
  --amd-dark: {AMD_DARK};
  --amd-accent: {AMD_ACCENT};
}}

/* 全局深色背景 */
.gradio-container {{
  background: radial-gradient(ellipse at top, #1c1010 0%, {AMD_BG} 45%) !important;
  color: {AMD_TEXT} !important;
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif !important;
}}

/* 顶部渐变横幅 */
.hero-banner {{
  background: linear-gradient(135deg, {AMD_RED} 0%, #7a1015 35%, {AMD_DARK} 100%);
  border-radius: 16px;
  padding: 28px 24px;
  margin-bottom: 16px;
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 8px 32px rgba(237,28,36,0.18);
  position: relative;
  overflow: hidden;
}}
.hero-banner::after {{
  content: '';
  position: absolute;
  top: -50%; right: -10%;
  width: 300px; height: 300px;
  background: radial-gradient(circle, rgba(237,28,36,0.25), transparent 70%);
  pointer-events: none;
}}
.hero-banner h1 {{
  margin: 0;
  color: #fff;
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 0.5px;
  text-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}
.hero-banner .subtitle {{
  color: rgba(255,255,255,0.85);
  margin: 6px 0 0;
  font-size: 14px;
}}
.hero-badge {{
  display: inline-block;
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.25);
  color: #fff;
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 12px;
  margin-right: 6px;
  margin-top: 10px;
  backdrop-filter: blur(4px);
}}

/* 聊天气泡美化 */
.chat-bubble .message {{
  border-radius: 14px !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.3) !important;
  font-size: 14px !important;
  line-height: 1.6 !important;
}}
/* 用户消息 */
.chat-bubble .user {{
  background: linear-gradient(135deg, #2a2a2a, #1f1f1f) !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
}}
/* AI 消息 */
.chat-bubble .assistant {{
  background: linear-gradient(135deg, #241418, #161616) !important;
  border-left: 3px solid {AMD_RED} !important;
}}

/* 状态卡（入库结果 / 推理过程） */
.status-card {{
  background: rgba(26,26,26,0.9) !important;
  border: 1px solid rgba(255,77,84,0.3) !important;
  border-radius: 12px !important;
  padding: 10px 14px !important;
  color: {AMD_TEXT} !important;
  font-size: 13px;
}}
.trace-card {{
  background: rgba(18,18,18,0.95) !important;
  border: 1px solid rgba(255,77,84,0.25) !important;
  border-radius: 10px !important;
  padding: 12px 16px !important;
  margin-top: 10px;
}}
.trace-title {{
  color: {AMD_ACCENT};
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}}
.trace-step {{
  color: #ccc;
  font-size: 12px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
  padding: 3px 0;
  border-bottom: 1px dashed rgba(255,255,255,0.08);
}}
.trace-step .tool-name {{
  color: {AMD_ACCENT};
  font-weight: 600;
}}
.trace-step .tool-src {{
  color: #8fd18f;
}}

/* 输入框 */
#chat-input textarea {{
  background: rgba(30,30,30,0.9) !important;
  border: 1px solid rgba(255,77,84,0.25) !important;
  border-radius: 12px !important;
  color: {AMD_TEXT} !important;
  font-size: 14px !important;
  padding: 12px !important;
}}
#chat-input textarea:focus {{
  border-color: {AMD_RED} !important;
  box-shadow: 0 0 0 2px rgba(237,28,36,0.15) !important;
}}

/* 按钮 */
.gr-button-primary {{
  background: linear-gradient(135deg, {AMD_RED}, #b00f16) !important;
  border: none !important;
  border-radius: 10px !important;
  color: #fff !important;
  font-weight: 600 !important;
  padding: 10px 20px !important;
  transition: all 0.2s !important;
}}
.gr-button-primary:hover {{
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(237,28,36,0.35) !important;
}}

/* 快捷示例按钮 */
.example-chip {{
  background: rgba(255,77,84,0.1) !important;
  border: 1px solid rgba(255,77,84,0.3) !important;
  color: #ffb3b6 !important;
  border-radius: 20px !important;
  padding: 8px 16px !important;
  font-size: 13px !important;
  transition: all 0.2s !important;
  cursor: pointer;
}}
.example-chip:hover {{
  background: rgba(237,28,36,0.25) !important;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(237,28,36,0.25);
}}

/* 页脚 */
.footer {{
  color: {AMD_GRAY};
  font-size: 12px;
  text-align: center;
  padding: 16px 0;
  border-top: 1px solid rgba(255,255,255,0.06);
  margin-top: 16px;
}}

/* Tab 样式 */
.tabs {{
  background: rgba(26,26,26,0.7) !important;
  border-radius: 12px !important;
  padding: 8px !important;
}}
button.tab-button {{
  border-radius: 8px !important;
  color: {AMD_GRAY} !important;
  font-weight: 600;
}}
button.tab-button[aria-selected="true"] {{
  background: rgba(237,28,36,0.2) !important;
  color: {AMD_RED} !important;
}}
"""

HERO_HTML = """
<div class="hero-banner">
  <h1>🗂️ Private RAG Agent</h1>
  <p class="subtitle">本地私有 AI 智能体 · 完全离线 · 数据不出本机 · AMD Radeon GPU 推理</p>
  <div>
    <span class="hero-badge">🔒 100% 离线</span>
    <span class="hero-badge">🧠 Agent 工具调用</span>
    <span class="hero-badge">⚡ AMD ROCm 加速</span>
    <span class="hero-badge">📄 RAG 知识库</span>
  </div>
</div>
"""


def build_trace_html(trace: list) -> str:
    """把 Agent 工具调用过程渲染成可视化的推理时间线卡片。"""
    if not trace:
        return ""
    steps_html = []
    for i, (name, args, result) in enumerate(trace, 1):
        args_str = json.dumps(args, ensure_ascii=False)[:80]
        src = ""
        # 尝试从工具结果里提取来源文档名
        if "来源:" in result:
            for part in result.split("来源:")[1:]:
                src = part.strip().split()[0] if part.strip() else ""
                break
        src_html = f' → <span class="tool-src">📄 {src}</span>' if src else ""
        steps_html.append(
            f'<div class="trace-step">'
            f'<span class="tool-name">#{i} {name}</span>'
            f' <span style="color:#777">({args_str})</span>'
            f'{src_html}'
            f'</div>'
        )
    return (
        f'<div class="trace-card">'
        f'<div class="trace-title">🧠 Agent 推理过程</div>'
        + "".join(steps_html)
        + "</div>"
    )


def launch(agent, host="0.0.0.0", port=7860):
    theme = gr.themes.Base(
        primary_hue="red",
        neutral_hue="slate",
        radius_size=gr.themes.sizes.radius_lg,
        font=[gr.themes.GoogleFont("Segoe UI"), "Microsoft YaHei", "sans-serif"],
    ).set(
        body_background_fill="#121212",
        body_text_color="#E8E8E8",
        block_background_fill="#1A1A1A",
        block_border_color="rgba(255,255,255,0.08)",
        input_background_fill="#1E1E1E",
        button_primary_background_fill="#ED1C24",
        button_primary_text_color="#FFFFFF",
    )

    def do_ingest(file):
        if not file:
            return "请先选择要导入的文档"
        path = file.name
        n = agent.ingest(path)
        return f"✅ 导入完成：`{os.path.basename(path)}` → {n} 个片段已入库"

    # 多子 Agent 并行编排器
    from agent.multi_agent import MultiAgentOrchestrator
    orch = MultiAgentOrchestrator(agent, n_workers=3)

    def orch_sub_trace():
        """把并行子 Agent 的工具调用日志展平为单条列表，供 trace 卡片展示。"""
        flat = []
        for q, tr in orch.sub_traces.items():
            for name, args, result in tr:
                flat.append((name, args, result))
        return flat

    def do_ask(message, history, mode):
        """流式回答：单 Agent 或 多 Agent 并行，均打字机式输出。"""
        if not message.strip():
            return history
        history = history or []
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": ""})
        full = ""
        if mode == "⚡ 多 Agent 并行":
            for piece in orch.run_stream(message):
                full += piece
                history[-1] = {"role": "assistant", "content": full}
                yield history
        else:
            for piece in agent.ask_stream(message):
                full += piece
                history[-1] = {"role": "assistant", "content": full}
                yield history
        # 追加 Agent 推理过程可视化
        trace_html = build_trace_html(agent.trace if mode == "单 Agent" else orch_sub_trace())
        if trace_html:
            history[-1] = {"role": "assistant", "content": full}
            yield history
            # 用 HTML 组件展示推理过程（追加一条辅助消息）
            history.append({
                "role": "assistant",
                "content": trace_html,
                # Gradio 6 支持通过 content 里的 HTML 渲染（需 sanitize 关闭）
            })
            yield history

    def do_ask_nonstream(message, history):
        """非流式兜底（后端不支持流式时）。"""
        if not message.strip():
            return history
        history = history or []
        answer = agent.ask(message)
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": answer})
        return history

    with gr.Blocks(
        title="Private RAG Agent — 本地私有 AI 智能体",
        theme=theme,
        css=CUSTOM_CSS,
        fill_height=True,
    ) as demo:
        # ===== 顶部横幅 =====
        gr.HTML(HERO_HTML)

        with gr.Tabs():
            # ===== Tab 1: 对话 =====
            with gr.Tab("💬 智能对话"):
                chatbot = gr.Chatbot(
                    height=560,
                    layout="bubble",
                    avatar_images=[None, None],
                    render_markdown=True,
                    sanitize_html=True,
                    autoscroll=True,
                    placeholder="👋 欢迎！向我提问，我会先检索你的私有知识库再回答。",
                )
                with gr.Row():
                    msg = gr.Textbox(
                        elem_id="chat-input",
                        placeholder="输入问题，例如：我的项目用了什么技术栈？",
                        scale=6,
                        container=False,
                    )
                    send = gr.Button("发送", variant="primary", scale=1)
                with gr.Row():
                    mode = gr.Radio(
                        choices=["单 Agent", "⚡ 多 Agent 并行"],
                        value="⚡ 多 Agent 并行",
                        label="推理模式",
                        scale=2,
                    )
                    n_agents = gr.Slider(2, 6, value=3, step=1, label="并行子 Agent 数", scale=2)
                # 快捷示例
                gr.Markdown("**💡 试试这些示例：**")
                examples = gr.Examples(
                    examples=[
                        "📄 我的项目用了什么技术栈？",
                        "📚 知识库里有哪些文档？",
                        "🧠 帮我规划如何部署到 AMD GPU",
                        "👋 你好",
                    ],
                    inputs=msg,
                    label="",
                )

                clear = gr.Button("🗑️ 清空对话", size="sm")

                def _set_workers(n):
                    orch.n_workers = int(n)
                    return n
                n_agents.change(_set_workers, [n_agents], [n_agents])

                send.click(do_ask, [msg, chatbot, mode], [chatbot])
                msg.submit(do_ask, [msg, chatbot, mode], [chatbot])
                clear.click(lambda: [], None, chatbot)

            # ===== Tab 2: 知识库管理 =====
            with gr.Tab("📥 知识库管理"):
                gr.Markdown("### 📤 导入文档\n\n支持 **PDF / Word / Markdown / Excel / PPT**，上传后自动切片、向量化入库。")
                with gr.Column():
                    file = gr.File(
                        label="拖拽或点击上传文档",
                        file_types=[".pdf", ".docx", ".md", ".txt", ".csv", ".json", ".pptx", ".xlsx"],
                    )
                    with gr.Row():
                        ingest_btn = gr.Button("🚀 导入入库", variant="primary")
                        list_btn = gr.Button("📚 查看已有文档")
                    status = gr.Markdown(elem_classes=["status-card"])
                    doc_list = gr.Markdown()

                def do_list_docs():
                    try:
                        from agent.tools import build_tools
                        registry = build_tools(agent.rag)
                        result = registry.call("list_docs", {})
                        return f"**📚 知识库中的文档：**\n```\n{result}\n```"
                    except Exception as e:
                        return f"⚠️ {e}"

                ingest_btn.click(do_ingest, [file], [status])
                list_btn.click(do_list_docs, None, [doc_list])

        # ===== 页脚 =====
        gr.HTML(
            '<div class="footer">AMD AI DevMaster 2026 · 赛道 2 · 本地私有 AI 智能体 · '
            '完全离线运行 · 数据不出本机 · Powered by AMD Radeon / ROCm</div>'
        )

    demo.queue(default_concurrency_limit=4).launch(
        server_name=host, server_port=port, inbrowser=True
    )


if __name__ == "__main__":
    from agent.agent import Agent
    launch(Agent())
