# -*- coding: utf-8 -*-
"""多 Agent 协作编排：研究者 → 事实核查者 → 汇总者。

角色分工（对标工业级 multi-agent RAG，是本项目"严谨性"叙事的关键）：
  1. 分解器 (Decomposer)    —— 把复杂问题拆成 n 个相互独立的子问题
  2. 研究者 (Researchers)    —— n 个并行的子 Agent，各自检索知识库产出子报告
  3. 事实核查者 (Fact-Checker)—— 对每份子报告做 groundedness 校验，
                                 检查"回答是否被检索原文支撑、引用是否真实存在"
  4. 汇总者 (Synthesizer)   —— 只依据"通过核查"的内容综合成最终答案

流程：decompose → parallel research → fact-check → synthesize
并行动机（AMD 特色）：本地 GPU 上多个推理并发排队，串行→并行的墙钟时间大幅下降。

事件流（供 UI 渲染活动时间线）：
  {"type":"plan","steps":[...]}
  {"type":"plan_step_start"/"plan_step_done", ...}    # 每个子任务
  {"type":"verify","sub_q":...,"grounding":...,"cites":[...]}
  {"type":"delta","text":...}
  {"type":"done","verification":...,"trace":...,"sub_reports":[...]}
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from .agent import Agent
from .verify import groundedness, verify_citations

DECOMPOSE_PROMPT = """你是任务分解器。用户有一个复杂问题，请把它拆解为 **{n} 个相互独立的子问题**。
要求：
1. 每个子问题能独立回答（可以各自检索知识库的不同部分）。
2. 子问题之间不要有依赖（这样才能并行）。
3. 子问题要有代表性，覆盖原问题的不同方面。
4. 输出 JSON 数组，如：["子问题1", "子问题2", ...]
只输出 JSON，不要多余文字。
"""

SYNTHESIZE_PROMPT = """你是一名资深分析师。下面是针对同一问题并行调研得到的多个子报告（每个子报告已经过事实核查，标注了支撑情况）：

<user_question>
{question}
</user_question>

<sub_reports>
{sub_reports}
</sub_reports>

请综合这些子报告，产出一份**结构化、有逻辑、完整**的最终答案。
要求：
1. 组织清晰：用标题/分点/列表。
2. 综合而非罗列：把各子报告的信息整合成连贯叙述。
3. 标注来源（用 [来源:文档名] 格式）。**只引用子报告"来源"字段里真实存在的文档名**（例如 [来源:技术白皮书.md]），不要臆造文件名。
4. 如果某个子报告被标注为"部分/无证据支撑"，要如实说明该部分可信度有限。
5. 最后用一段话总结核心结论。
请用中文回答。
"""

JUDGE_PROMPT = """你是事实核查员。下面是一份 AI 子报告及其检索到的原文来源。请逐条判断报告中每个事实性陈述是否被来源支撑。

<report>
{answer}
</report>

<sources>
{sources}
</sources>

对报告中每一个事实陈述，输出 JSON 数组：
[{{"claim": "陈述原文", "supported": true/false, "reason": "简短理由"}}]
只输出 JSON。
"""


class MultiAgentOrchestrator:
    def __init__(self, agent: Agent, n_workers: int = 3):
        self.agent = agent
        self.n_workers = n_workers
        self.sub_traces: dict = {}
        self.sub_reports: list = []
        self.verification = None
        self.sub_count = 0

    # ------------------------------------------------------------- 分解
    def decompose(self, question: str, n: int = 3) -> List[str]:
        llm = self.agent.llm
        resp = llm.chat([
            {"role": "system", "content": DECOMPOSE_PROMPT.format(n=n)},
            {"role": "user", "content": question},
        ], temperature=0.1, max_tokens=1024)
        text = resp["content"].strip().strip("```").strip()
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return [question]
        try:
            subs = json.loads(m.group(0))
            subs = self._normalize_subs(subs)
            return [str(s) for s in subs if str(s).strip()][:n]
        except Exception:
            return [question]

    @staticmethod
    def _normalize_subs(subs):
        """模型常把子问题输出为各种 JSON 形态，统一规整成字符串列表。
        已见形态：纯数组 / 单个 dict / [dict] / [{"子问题1":..},{"子问题2":..}]"""
        if isinstance(subs, dict):
            return list(subs.values())
        if isinstance(subs, list):
            out = []
            for s in subs:
                if isinstance(s, dict):
                    out.extend(str(v) for v in s.values())
                else:
                    out.append(s)
            return out
        return [subs]

    # --------------------------------------------------------- 研究者
    def _run_researcher(self, sub_q: str, emit=None) -> dict:
        """单个子 Agent：独立处理一个子问题，返回子报告 + 证据 + 校验。
        emit: 可选回调，把子 Agent 的工具事件实时转发给主流程（供 UI 活动面板展示）。"""
        try:
            sub = Agent(llm=self.agent.llm, rag=self.agent.rag)
            sub.memory.long = self.agent.memory.long
            text = ""
            # 子问题已由分解器拆成单点问题，无需再规划二次拆分；
            # 单遍"检索→回答"更快、聚焦，避免小模型在多层规划里重复调用工具
            for ev in sub.ask_events(sub_q, use_planning=False):
                if ev["type"] == "delta":
                    text += ev["text"]
                elif emit and ev["type"] in ("tool", "verify"):
                    # 转发工具/核查事件（给子事件加来源前缀，避免与主流程事件混淆）
                    ev = dict(ev)
                    ev["tag"] = "sub"
                    emit(ev)
            self.sub_traces[sub_q] = sub.trace
            return {
                "sub_q": sub_q,
                "answer": text,
                "sources": list(sub._retrieved_sources),
                "verification": sub.verification,
            }
        except Exception as e:
            return {"sub_q": sub_q, "answer": f"（子 Agent 执行失败: {e}）",
                    "sources": [], "verification": None}

    # ------------------------------------------------------ 事实核查者
    def _resolve_sources(self, src_names: list) -> list:
        """把来源文件名解析成文档全文（与单 Agent 校验路径一致），
        否则 groundedness 会用文件名去比对，分数会趋近 0。"""
        out = []
        for s in src_names:
            try:
                text = self.agent.rag.get_document(s, limit=6000)
                out.append(text if text else s)
            except Exception:
                out.append(s)
        return out

    def _fact_check(self, report: dict) -> dict:
        """对子报告做两级核查：确定性 groundedness + LLM-as-judge。"""
        answer = report["answer"]
        sources = report["sources"]
        if not sources:
            return {"grounding": None, "cite_precision": None, "cites": [],
                    "flag": "（该子任务未检索到来源，结论基于模型常识，可信度有限）"}
        g_score, sents = groundedness(answer, self._resolve_sources(sources))
        cite_p, cites = verify_citations(answer, set(sources))
        # LLM-as-judge：逐 claim 判定（best-effort，失败不影响主流程）
        flag = ""
        try:
            judge = self.agent.llm.chat([
                {"role": "system", "content": JUDGE_PROMPT.format(
                    answer=answer[:1800], sources="\n\n".join(sources)[:2500])},
                {"role": "user", "content": "请核查。"},
            ], temperature=0.1, max_tokens=900)
            jtext = judge["content"].strip().strip("`")
            jm = re.search(r"\[.*\]", jtext, re.S)
            arr = json.loads(jm.group(0)) if jm else None
            if isinstance(arr, list):
                unsupported = [x for x in arr if isinstance(x, dict) and not x.get("supported", True)]
                if unsupported:
                    flag = f"核查发现 {len(unsupported)} 处陈述缺支撑: " + \
                           "; ".join(str(x.get("claim", ""))[:50] for x in unsupported[:3])
        except Exception as e:
            print(f"[warn] fact-check judge: {e}")
        return {"grounding": g_score, "cite_precision": cite_p,
                "cites": cites, "flag": flag, "sentences": sents}

    # ------------------------------------------------------------- 主流程
    def run_events(self, question: str, n: int = 3):
        """富事件流：分解 → 并行研究 → 核查 → 汇总。"""
        self.sub_traces = {}
        self.sub_reports = []
        self.verification = None

        subs = self.decompose(question, n)
        self.sub_count = len(subs)
        yield {"type": "plan", "steps": [f"子任务 {i + 1}: {q}" for i, q in enumerate(subs)]}

        # 并行研究（轮询排空 live 事件 → 子 Agent 的工具/核查事件实时上屏）
        import time
        from collections import deque
        live: deque = deque()
        reports = [None] * self.sub_count
        with ThreadPoolExecutor(max_workers=min(self.n_workers, self.sub_count)) as pool:
            pending = {pool.submit(self._run_researcher, q, live.append): i
                       for i, q in enumerate(subs)}
            done = 0
            while pending:
                # 先把子 Agent 已产生的事件排空（实时活动面板）
                while live:
                    yield live.popleft()
                finished = [f for f in pending if f.done()]
                if not finished:
                    time.sleep(0.15)   # 让出给工作线程
                    continue
                for fut in finished:
                    idx = pending.pop(fut)
                    reports[idx] = fut.result()
                    done += 1
                    yield {"type": "plan_step_done", "step": idx + 1,
                           "task": subs[idx], "total": self.sub_count,
                           "progress": f"{done}/{self.sub_count}"}
            # 结束前最后一次排空
            while live:
                yield live.popleft()

        # 事实核查
        checked = []
        for i, r in enumerate(reports):
            if r is None:
                continue
            verdict = self._fact_check(r)
            r["verdict"] = verdict
            checked.append(r)
            yield {"type": "verify", "sub_q": r["sub_q"], "grounding": verdict["grounding"],
                   "flag": verdict.get("flag", "")}
        self.sub_reports = checked

        # 汇总
        yield {"type": "synthesize"}
        sub_reports = "\n\n---\n\n".join(
            f"【子问题】{r['sub_q']}\n{r['answer']}\n"
            f"[该子问题实际检索到的来源文档: {', '.join(r.get('sources', [])) or '无'}]\n"
            f"[核查: grounding={r['verdict'].get('grounding')} "
            f"引用={r['verdict'].get('cite_precision')}]\n{r['verdict'].get('flag', '')}"
            for r in checked)
        full = ""
        try:
            for ev in self.agent.llm.chat_stream_full([
                {"role": "system", "content": SYNTHESIZE_PROMPT.format(
                    question=question, sub_reports=sub_reports)},
                {"role": "user", "content": "请给出综合结论。"},
            ]):
                if ev["tool_calls"]:
                    continue
                if ev["delta"]:
                    full += ev["delta"]
                    yield {"type": "delta", "text": ev["delta"]}
        except Exception as e:
            print(f"[warn] multi-agent stream: {e}")
            summary = self.agent.llm.chat([
                {"role": "system", "content": SYNTHESIZE_PROMPT},
                {"role": "user", "content": sub_reports},
            ])
            full = summary["content"]
            yield {"type": "delta", "text": full}

        # 汇总后的总校验
        all_sources = set()
        for r in checked:
            all_sources.update(r.get("sources", []))
        if all_sources:
            g, sents = groundedness(full, self._resolve_sources(list(all_sources)))
            cp, cites = verify_citations(full, all_sources)
            self.verification = {"grounding": g, "sentences": sents,
                                 "cite_precision": cp, "cites": cites}
        yield {"type": "done", "verification": self.verification,
               "trace": self._flat_trace(), "sub_reports": self.sub_reports}

    def _flat_trace(self) -> list:
        flat = []
        for q, tr in self.sub_traces.items():
            for t in tr:
                flat.append(t)
        return flat

    # --------------------------------------------------------- 兼容接口
    def run_parallel(self, question: str, n: int = 3) -> str:
        text = ""
        for ev in self.run_events(question, n):
            if ev["type"] == "delta":
                text += ev["text"]
        return text

    def run_stream(self, question: str, n: int = 3):
        for ev in self.run_events(question, n):
            if ev["type"] == "delta":
                yield ev["text"]
            elif ev["type"] == "plan":
                yield f"🧩 已拆解为 {len(ev['steps'])} 个并行子任务：\n" + \
                      "".join(f"  {s}\n" for s in ev["steps"])
            elif ev["type"] == "verify":
                yield f"\n🔍 核查完成: {ev['sub_q'][:30]}… grounding={ev['grounding']}\n"


if __name__ == "__main__":
    from .agent import Agent
    agent = Agent()
    orch = MultiAgentOrchestrator(agent, n_workers=3)
    print("== 多 Agent 并行自测 ==")
    result = orch.run_parallel("分析这个项目的技术栈、优化点和部署方式", n=3)
    print(result)
    print(f"\n[并行信息] 拆解 {orch.sub_count} 个子任务")
    print(f"[总校验] {orch.verification}")
