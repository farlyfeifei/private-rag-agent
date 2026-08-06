/* ============================================================
   Private RAG Agent — 前端逻辑
   SSE 流式对话 · 富事件渲染 · 运行轨迹面板 · GPU 监控
   ============================================================ */
(function () {
  'use strict';

  /* ---------- 全局状态 ---------- */
  const state = {
    sessionId: 'default',
    mode: 'single',
    toolsEnabled: true,
    busy: false,
    history: [],           // [{role, content(html), text, citations, verification}]
    trace: [],             // 当前消息的工具步骤
    currentMsgEl: null,    // 正在流式渲染的 assistant 消息气泡
    currentMsgText: '',
    currentCiteSeen: new Set(),
    planSteps: [],
    subCount: 0,
    lastQuery: '',          // 用户原始问题
    lastSearchQuery: '',    // 最近一次 rag_search 检索词（供来源抽屉高亮）
    abortCtrl: null,
    gpuHistory: [],        // [{util, vram, temp, power}]
  };

  /* ---------- DOM 引用 ---------- */
  const $ = (id) => document.getElementById(id);
  const chatList = $('chat-list');
  const chatScroll = $('chat-scroll');
  const emptyState = $('empty-state');
  const input = $('input');
  const sendBtn = $('send-btn');
  const traceList = $('trace-list');
  const traceEmpty = $('trace-empty');
  const sessionList = $('session-list');
  const sessionTitle = $('session-title');
  const kbList = $('kb-list');
  const kbStats = $('kb-stats');
  const gpuMetrics = $('gpu-metrics');
  const gpuChart = $('gpu-chart');
  const gpuNote = $('gpu-note');

  /* ---------- 工具函数 ---------- */
  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function escapeRegex(s) {
    return (s || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
  function queryMarkRanges(doc, raw) {
    /* 高亮定位：查询与文档共有的 2-gram 重叠区间。
       原理与 BM25 检索一致（中文 2-gram 窗口），因此任意口语化问法
       都能标出文档里真正相关的段落，而不是要求整句逐字出现。 */
    const clean = (raw || '').replace(/[^\p{L}\p{N}]/gu, '').toLowerCase();
    if (clean.length < 2 || !doc) return null;
    const d = doc.toLowerCase();
    const grams = new Set();
    for (let i = 0; i < clean.length - 1; i++) grams.add(clean.slice(i, i + 2));
    // 统计文档 2-gram 频次，太常见的（如“系统”“进行”）不作为高亮依据
    const freq = new Map();
    for (let i = 0; i < d.length - 1; i++) {
      const g = d.slice(i, i + 2);
      freq.set(g, (freq.get(g) || 0) + 1);
    }
    const cap = Math.max(6, d.length / 250);
    const ranges = [];
    let start = -1;
    for (let i = 0; i < d.length - 1; i++) {
      const g = d.slice(i, i + 2);
      const hit = grams.has(g) && (freq.get(g) || 0) <= cap;
      if (hit) { if (start < 0) start = i; }
      else if (start >= 0) { ranges.push([start, i + 2]); start = -1; }
    }
    if (start >= 0) ranges.push([start, d.length]);
    if (!ranges.length) return null;
    // 合并相距 ≤ 12 字符的相邻区间，避免高亮碎片化
    const merged = [ranges[0]];
    for (let i = 1; i < ranges.length; i++) {
      const last = merged[merged.length - 1];
      if (ranges[i][0] - last[1] <= 12) last[1] = ranges[i][1];
      else merged.push(ranges[i]);
    }
    return merged;
  }
  function debounce(fn, ms) {
    let t; return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
  }
  function fmtTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (d.toDateString() === now.toDateString()) return hm;
    if (d.getTime() > now.getTime() - 7 * 864e5) return `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
    return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
  }
  function toast(msg, isErr = false) {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'toast' + (isErr ? ' err' : '');
    t.classList.remove('hidden');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.add('hidden'), 3200);
  }
  function api(path, opts = {}) {
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    return fetch(path, opts).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || data.error || r.statusText);
      return data;
    });
  }

  /* ---------- Markdown 渲染 ---------- */
  function renderMarkdown(text) {
    try {
      let html = marked.parse(text || '', { breaks: true, gfm: true });
      html = DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true },
        ADD_ATTR: ['target'],
      });
      // 代码高亮
      const wrap = document.createElement('div');
      wrap.innerHTML = html;
      wrap.querySelectorAll('pre code').forEach(el => {
        try { hljs.highlightElement(el); } catch (e) {}
      });
      return wrap.innerHTML;
    } catch (e) {
      return escapeHtml(text);
    }
  }

  /* ---------- 引用提取（从 markdown 文本） ---------- */
  function extractCitations(text) {
    const set = new Set();
    const re = /\[来源[:：]?\s*([^\]\[]+?)\]/g;
    let m;
    while ((m = re.exec(text || '')) !== null) {
      let name = m[1].trim();
      name = name.replace(/[，。；,;）)\]].*$/, '');
      if (name) set.add(name);
    }
    return [...set];
  }

  /* ---------- 消息渲染 ---------- */
  function appendUserMsg(text) {
    emptyState.classList.add('hidden');
    const el = document.createElement('div');
    el.className = 'msg user';
    el.innerHTML = `
      <div class="avatar">我</div>
      <div class="bubble">${escapeHtml(text)}</div>`;
    chatList.appendChild(el);
    scrollBottom();
    return el;
  }

  function appendAssistantMsg() {
    emptyState.classList.add('hidden');
    const el = document.createElement('div');
    el.className = 'msg assistant';
    el.innerHTML = `
      <div class="avatar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 2 L21 7 L21 17 L12 22 L3 17 L3 7 Z"/></svg>
      </div>
      <div class="bubble">
        <div class="md stream"></div>
      </div>`;
    chatList.appendChild(el);
    scrollBottom();
    return el;
  }

  function renderCurrentStream() {
    if (!state.currentMsgEl) return;
    const md = state.currentMsgEl.querySelector('.md.stream');
    const cursor = state.currentMsgText.endsWith('\n') || !state.currentMsgText ? '' : '<span class="type-cursor"></span>';
    md.innerHTML = renderMarkdown(state.currentMsgText) + cursor;
    scrollBottom();
  }

  /* ---------- 运行轨迹面板 ---------- */
  function addTraceStep(name, args, status, dur) {
    traceEmpty.classList.add('hidden');
    const card = document.createElement('div');
    card.className = 'tool-step' + (status === 'running' ? '' : ' open');
    const argsJson = args ? escapeHtml(JSON.stringify(args, null, 1)) : '';
    const icon = toolIcon(name);
    card.innerHTML = `
      <div class="tool-step-head">
        ${icon}
        <span class="tool-name">${escapeHtml(name)}</span>
        <span class="tool-status">
          ${status === 'running'
            ? '<span class="st-running"></span><span class="tool-dur">运行中</span>'
            : status === 'ok'
              ? '<span class="dot st-ok"></span><span class="tool-dur">' + (dur || '') + '</span>'
              : '<span class="dot st-err"></span><span class="tool-dur">失败</span>'}
        </span>
      </div>
      <div class="tool-step-body">
        ${argsJson ? `<div class="tb-label">参数</div><pre>${argsJson}</pre>` : ''}
        <div class="tb-label">结果</div>
        <pre class="tb-result">${escapeHtml(resultPreview(status))}</pre>
      </div>`;
    card.querySelector('.tool-step-head').addEventListener('click', () => {
      card.classList.toggle('open');
    });
    traceList.appendChild(card);
    // 展开时滚动到底
    traceList.scrollTop = traceList.scrollHeight;

    function resultPreview(st) {
      if (st === 'running') return '…';
      if (st === 'err') return '执行出错';
      return '';
    }
    return card;
  }

  function toolIcon(name) {
    const common = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">`;
    const close = `</svg>`;
    if (name.includes('rag_search'))
      return common + `<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg>`;
    if (name.includes('read_doc') || name.includes('list_doc') || name.includes('summarize'))
      return common + `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>`;
    if (name.includes('web_search'))
      return common + `<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`;
    return common + `<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`;
  }

  /* ---------- 规划步骤展示（主区） ---------- */
  function renderPlan(panel, steps) {
    const inner = document.createElement('div');
    inner.className = 'plan-steps';
    steps.forEach((task, i) => {
      const row = document.createElement('div');
      row.className = 'plan-step';
      row.dataset.i = i;
      row.innerHTML = `<span class="step-num">${i + 1}</span><span class="step-text">${escapeHtml(task)}</span>`;
      inner.appendChild(row);
    });
    // 顶部进度条：completed/total
    const bar = document.createElement('div');
    bar.className = 'plan-bar';
    bar.innerHTML = `<div class="plan-bar-track"><div class="plan-bar-fill" style="width:0%"></div></div><span class="plan-bar-label mono">0/${steps.length}</span>`;
    panel.appendChild(bar);
    panel.appendChild(inner);
    panel._bar = bar;
    return inner;
  }
  function updatePlanStep(panel, index, status) {
    const rows = panel.querySelectorAll('.plan-step');
    if (rows[index]) {
      rows[index].classList.remove('running');
      rows[index].classList.add(status);
    }
    if (panel._bar) {
      const done = panel.querySelectorAll('.plan-step.done').length;
      const total = panel.querySelectorAll('.plan-step').length;
      panel._bar.querySelector('.plan-bar-fill').style.width = `${Math.round(done / total * 100)}%`;
      panel._bar.querySelector('.plan-bar-label').textContent = `${done}/${total}`;
    }
  }

  /* ---------- 可信度徽标 ---------- */
  function trustPill(verification) {
    if (!verification) return '';
    const g = verification.grounding;
    let level = 'low', label = '可信度待确认';
    if (g >= 0.6) { level = 'high'; label = `已支撑 · 证据强度 ${Math.round(g * 100)}%`; }
    else if (g >= 0.35) { level = 'med'; label = `部分支撑 · ${Math.round(g * 100)}%`; }
    else { level = 'low'; label = `证据不足 · ${Math.round(g * 100)}%`; }
    const icons = {
      high: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`,
      med: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 3v18M3 12h18" opacity=".8"/></svg>`,
      low: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>`,
    };
    return `<div class="trust-pill ${level}">${icons[level]}${label}</div>`;
  }

  /* 逐句校验面板：把 grounding 的每个句子支撑度可视化（✓ 已支撑 / △ 部分 / ✗ 无） */
  function renderSentenceVerify(msgEl, verification) {
    const sents = verification.sentences;
    if (!msgEl || !sents || !sents.length) return;
    let ok = 0, partial = 0, no = 0;
    const items = sents.map(s => {
      const lv = s.level || '';
      const cls = lv === '已支撑' ? 'ok' : lv === '部分支撑' ? 'partial' : 'no';
      if (cls === 'ok') ok++;
      else if (cls === 'partial') partial++;
      else no++;
      const mark = cls === 'ok' ? '✓' : cls === 'partial' ? '△' : '✗';
      const pct = Math.round((s.support || 0) * 100);
      return `<div class="sv-item">
        <span class="sv-badge ${cls}">${mark}</span>
        <span class="sv-text">${escapeHtml(s.text)}</span>
        <span class="sv-score">${pct}%</span>
      </div>`;
    }).join('');
    const el = document.createElement('div');
    el.className = 'sentence-verify';
    el.innerHTML = `
      <button class="sv-toggle" type="button">
        <span style="display:flex;align-items:center;gap:7px">
          <svg class="sv-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
          逐句校验
        </span>
        <span class="sv-count"><span class="ok">✓ ${ok}</span><span class="partial">△ ${partial}</span><span class="no">✗ ${no}</span></span>
      </button>
      <div class="sv-body">${items}</div>`;
    el.querySelector('.sv-toggle').addEventListener('click', () => el.classList.toggle('open'));
    msgEl.querySelector('.bubble').appendChild(el);
  }

  /* ---------- 引用来源卡片 ---------- */
  function renderCitations(msgEl, sources) {
    if (!sources || !sources.length) return;
    // 去重 + 相对归一化分数（最高分 → 100%，便于视觉比较）
    const seen = new Set();
    const uniq = sources.filter(s => !seen.has(s.doc) && seen.add(s.doc));
    const maxScore = Math.max(...uniq.map(s => s.score || 0), 0.0001);
    let chips = uniq.map(s => {
      const pct = Math.max(10, Math.round((s.score / maxScore) * 100));
      return `
      <div class="cite-chip" data-doc="${escapeHtml(s.doc)}">
        <span class="cite-ic"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></span>
        <span class="cite-name">${escapeHtml(s.doc)}</span>
        <span class="cite-relevance"><span class="rel-bar"><span class="rel-fill" style="width:${pct}%"></span></span>${pct}</span>
      </div>`;
    }).join('');
    const el = document.createElement('div');
    el.className = 'citations';
    el.innerHTML = `<div class="cite-head">引用来源</div>${chips}`;
    el.querySelectorAll('.cite-chip').forEach(chip => {
      chip.addEventListener('click', () => openDocDrawer(chip.dataset.doc));
    });
    msgEl.querySelector('.bubble').appendChild(el);
  }

  /* ---------- 来源抽屉（点击引用 → 查看原文 + 高亮） ---------- */
  async function openDocDrawer(doc) {
    const mask = $('doc-drawer-mask');
    const body = $('drawer-body');
    $('drawer-doc-name').textContent = doc;
    $('drawer-doc-meta').textContent = '正在读取原文…';
    body.innerHTML = '<div class="drawer-loading">加载原文…</div>';
    mask.classList.remove('hidden');
    try {
      const data = await api(`/api/documents/${encodeURIComponent(doc)}?limit=6000`);
      $('drawer-doc-meta').textContent = `${data.chars} 字符${data.truncated ? '（已截断）' : ''} · 本地知识库`;
      // 高亮：用「查询 2-gram ∩ 文档」重叠定位相关区间（与 BM25 检索同套 tokenization）。
      // 任意问法都能标出文档里语义相关的段落，而不是要求整句逐字匹配。
      const docText = data.content;
      const ranges = queryMarkRanges(docText,
        (state.lastSearchQuery || state.lastQuery || '').trim());
      let content;
      if (ranges) {
        let out = '', last = 0;
        for (const [s, e] of ranges) {
          out += escapeHtml(docText.slice(last, s));
          out += `<mark>${escapeHtml(docText.slice(s, e))}</mark>`;
          last = e;
        }
        out += escapeHtml(docText.slice(last));
        content = out;
      } else {
        content = escapeHtml(docText);
      }
      body.innerHTML = content || '<div class="drawer-loading">（文档内容为空）</div>';
    } catch (e) {
      body.innerHTML = `<div class="msg-error">无法读取文档：${escapeHtml(e.message)}</div>`;
    }
  }
  $('drawer-close').addEventListener('click', () => $('doc-drawer-mask').classList.add('hidden'));
  $('doc-drawer-mask').addEventListener('click', (e) => {
    if (e.target === $('doc-drawer-mask')) $('doc-drawer-mask').classList.add('hidden');
  });

  /* ---------- SSE 流式对话 ---------- */
  async function sendMessage() {
    const text = input.value.trim();
    if (!text || state.busy) return;
    if (!state.toolsEnabled) {
      // 关闭工具时仍走服务端，但事件里工具照常（服务端暂不支持停用），这里直接走完整流
    }
    state.busy = true;
    sendBtn.disabled = true;
    input.value = '';
    autoGrow();

    appendUserMsg(text);
    state.lastQuery = text;   // 供来源抽屉高亮
    state.currentMsgEl = appendAssistantMsg();
    state.currentMsgText = '';
    state.trace = [];
    state.planSteps = [];
    traceList.innerHTML = '';
    traceEmpty.classList.remove('hidden');
    // 清理当前消息的旧引用区（等 done 事件统一渲染）
    state.currentCiteSeen = new Set();

    // 取消上一个
    if (state.abortCtrl) state.abortCtrl.abort();
    state.abortCtrl = new AbortController();

    const url = `/api/chat`;
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: state.sessionId,
          mode: state.mode,
          n_workers: 3,
        }),
        signal: state.abortCtrl.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // 解析 SSE 事件（可能多条粘连）
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const part of parts) {
          const line = part.replace(/^data: ?/m, '').trim();
          if (!line) continue;
          try { handleEvent(JSON.parse(line)); } catch (e) { console.warn('bad event', e); }
        }
      }
      if (buf) {
        const line = buf.replace(/^data: ?/m, '').trim();
        if (line) { try { handleEvent(JSON.parse(line)); } catch (e) {} }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        if (state.currentMsgEl) {
          state.currentMsgEl.querySelector('.md.stream').innerHTML =
            `<div class="msg-error">请求失败：${escapeHtml(e.message)}</div>`;
        } else {
          toast('请求失败：' + e.message, true);
        }
      }
    } finally {
      state.busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  /* ---------- 事件处理 ---------- */
  function handleEvent(ev) {
    switch (ev.type) {
      case 'plan':
        state.planSteps = ev.steps || [];
        if (state.currentMsgEl) {
          const panel = document.createElement('div');
          panel.className = 'plan-panel';
          state.currentMsgEl.querySelector('.bubble').appendChild(panel);
          state.currentMsgEl._planPanel = panel;
          renderPlan(panel, state.planSteps);
          if (state.planSteps.length > 2) {
            state.currentMsgEl._subStatus = document.createElement('div');
            state.currentMsgEl._subStatus.className = 'status-row';
            state.currentMsgEl._subStatus.innerHTML = `<span class="status-spinner"></span><span class="status-text">并行执行 <em>${state.planSteps.length}</em> 个子任务…</span>`;
            state.currentMsgEl.querySelector('.bubble').appendChild(state.currentMsgEl._subStatus);
          }
        }
        break;

      case 'plan_step_start':
        if (state.currentMsgEl && state.currentMsgEl._planPanel) {
          updatePlanStep(state.currentMsgEl._planPanel, ev.step - 1, 'running');
        }
        break;
      case 'plan_step_done':
        if (state.currentMsgEl && state.currentMsgEl._planPanel) {
          updatePlanStep(state.currentMsgEl._planPanel, ev.step - 1, 'done');
        }
        if (state.currentMsgEl && state.currentMsgEl._subStatus && ev.progress) {
          const [d, t] = ev.progress.split('/');
          state.currentMsgEl._subStatus.querySelector('em').textContent = `${t} 个子任务`;
          state.currentMsgEl._subStatus.querySelector('.status-text').innerHTML =
            `已完成 <em>${d}/${t}</em> 个子任务…`;
        }
        break;

      case 'synthesize':
        // 汇总阶段：更新子任务状态条文案
        if (state.currentMsgEl && state.currentMsgEl._subStatus) {
          state.currentMsgEl._subStatus.querySelector('.status-text').innerHTML =
            `正在综合 <em>${state.planSteps.length}</em> 份子报告…`;
        }
        break;

      case 'verify':
        addTraceStep('fact_check', { sub: ev.sub_q, grounding: ev.grounding },
                     ev.flag ? 'err' : 'ok', ev.grounding != null ? `g=${ev.grounding}` : '');
        // 主对话流内也展示核查卡片（"可核查"是本项目核心卖点）。
        // 未通过核查（grounding 为 null 或低于阈值）的子报告标注"已排除"，清晰可见。
        if (state.currentMsgEl && (ev.grounding != null || ev.excluded)) {
          const vc = document.createElement('div');
          vc.className = 'verify-card' + (ev.excluded ? ' excluded' : '');
          const g = ev.grounding;
          let cls, label;
          if (ev.excluded) { cls = 'excluded'; label = '未通过核查 · 已排除'; }
          else if (g >= 0.6) { cls = 'high'; label = '已支撑'; }
          else if (g >= 0.35) { cls = 'med'; label = '部分支撑'; }
          else { cls = 'low'; label = '证据不足'; }
          vc.innerHTML = `
            <div class="verify-head">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 12l2 2 4-4M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/></svg>
              事实核查
            </div>
            <div class="verify-q">${escapeHtml(ev.sub_q)}</div>
            <div class="verify-result ${cls}">${label}${g != null ? ` · grounding ${g.toFixed(3)}` : ''}</div>
            ${ev.excluded ? `<div class="verify-flag">${escapeHtml(ev.excluded)}</div>` : ''}
            ${ev.flag ? `<div class="verify-flag">${escapeHtml(ev.flag)}</div>` : ''}`;
          state.currentMsgEl.querySelector('.bubble').appendChild(vc);
        }
        break;

      case 'tool':
        state.trace.push(ev);
        // 子 Agent 转发的事件加"研究"前缀，与主 Agent 动作区分
        addTraceStep(ev.tag === 'sub' ? `研究 · ${ev.name}` : ev.name,
                     ev.args, ev.status || 'ok', ev.dur || '');
        // 记录最近一次检索词，供来源抽屉高亮
        if (ev.name === 'rag_search' && ev.args && ev.args.query) {
          state.lastSearchQuery = ev.args.query;
        }
        // 收集工具里出现的来源
        if (ev.name === 'rag_search' && ev.result) {
          const re = /\[来源[:：]?\s*([^\]\[]+?)\]/g;
          let m;
          while ((m = re.exec(ev.result)) !== null) {
            let name = m[1].trim().split(/[\s，。；,;（）(]/)[0];
            if (name && !state.currentCiteSeen.has(name)) {
              state.currentCiteSeen.add(name);
            }
          }
        }
        break;

      case 'delta':
        state.currentMsgText += ev.text;
        renderCurrentStream();
        break;

      case 'error':
        if (state.currentMsgEl) {
          state.currentMsgEl.querySelector('.md.stream').innerHTML =
            `<div class="msg-error">服务错误：${escapeHtml(ev.error || '未知')}</div>`;
        }
        break;

      case 'done': {
        // 收尾：移除光标、补来源卡片 + 可信度徽标
        const md = state.currentMsgEl && state.currentMsgEl.querySelector('.md.stream');
        if (md) {
          md.innerHTML = renderMarkdown(state.currentMsgText);
          // 从最终文本提取引用
          const cites = extractCitations(state.currentMsgText);
          const sources = [...state.currentCiteSeen].map(doc => ({ doc, score: 0.8 }));
          // 并进去重（名称统一清洗）
          const seen = new Set(sources.map(s => s.doc));
          cites.forEach(c => {
            c = c.trim().split(/[\s，。；,;（）(]/)[0];
            if (c && !seen.has(c)) { seen.add(c); sources.push({ doc: c, score: 0.6 }); }
          });
          renderCitations(state.currentMsgEl, sources);
        }
        if (ev.verification) {
          const pill = trustPill(ev.verification);
          if (pill && state.currentMsgEl) {
            const wrap = document.createElement('div');
            wrap.innerHTML = pill;
            state.currentMsgEl.querySelector('.bubble').appendChild(wrap.firstChild);
          }
          renderSentenceVerify(state.currentMsgEl, ev.verification);
        }
        // 移除子任务状态条（"已完成 x/3 …" / "正在综合…"）
        if (state.currentMsgEl && state.currentMsgEl._subStatus) {
          state.currentMsgEl._subStatus.remove();
          state.currentMsgEl._subStatus = null;
        }
        // 清理引用当前消息对象
        state.currentMsgEl = null;
        break;
      }
    }
  }

  /* ---------- 输入框 ---------- */
  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 180) + 'px';
  }
  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  sendBtn.addEventListener('click', sendMessage);

  /* ---------- 模式切换 ---------- */
  $('mode-switch').querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $('mode-switch').querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.mode = btn.dataset.mode;
      // 多 Agent 模式时提示
      if (state.mode === 'multi') {
        toast('多 Agent 并行：分解 → 研究 → 核查 → 汇总');
      }
    });
  });
  $('tools-toggle').addEventListener('change', (e) => {
    state.toolsEnabled = e.target.checked;
  });

  /* ---------- 会话管理 ---------- */
  async function loadSessions() {
    try {
      const data = await api('/api/sessions');
      renderSessions(data.sessions || []);
    } catch (e) {}
  }
  function renderSessions(sessions) {
    sessionList.innerHTML = '';
    if (!sessions.length) {
      sessionList.innerHTML = '<div class="kb-empty" style="padding:8px">暂无历史会话</div>';
      return;
    }
    sessions.forEach(s => {
      const el = document.createElement('div');
      el.className = 'session-item' + (s.id === state.sessionId ? ' active' : '');
      const title = s.title && s.title !== '新会话' ? s.title : '新会话';
      el.innerHTML = `
        <span class="sess-title">${escapeHtml(title)}</span>
        <span class="sess-time">${fmtTime(s.created)}</span>
        <span class="sess-del" title="删除">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
        </span>`;
      el.querySelector('.sess-title').addEventListener('click', () => switchSession(s.id));
      el.querySelector('.sess-del').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteSession(s.id);
      });
      sessionList.appendChild(el);
    });
  }
  async function switchSession(sid) {
    state.sessionId = sid;
    state.history = [];
    state.currentMsgEl = null;
    chatList.innerHTML = '';
    emptyState.classList.remove('hidden');
    traceList.innerHTML = '';
    traceEmpty.classList.remove('hidden');
    // 标题
    const found = SESSIONS_CACHE.find(s => s.id === sid);
    sessionTitle.textContent = found && found.title !== '新会话' ? found.title : '新会话';
    loadSessions();
  }
  let SESSIONS_CACHE = [];
  async function newSession() {
    const data = await api('/api/sessions', { method: 'POST' });
    await switchSession(data.session_id);
  }
  async function deleteSession(sid) {
    // 当前简化：直接删除本地会话对象（后端内存），重建
    try {
      await api(`/api/sessions/${sid}/clear`, { method: 'POST' });
      if (sid === state.sessionId) {
        await newSession();
      } else {
        loadSessions();
      }
    } catch (e) {}
  }
  $('new-chat-btn').addEventListener('click', newSession);

  /* ---------- 知识库 ---------- */
  async function loadKB() {
    try {
      const data = await api('/api/documents');
      renderKB(data);
    } catch (e) {}
  }
  function renderKB(data) {
    const indexed = data.indexed || [];
    const pending = data.pending || [];
    kbList.innerHTML = '';
    indexed.forEach(d => {
      const el = document.createElement('div');
      el.className = 'kb-item';
      el.innerHTML = `
        <span class="kb-icon"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></span>
        <span class="kb-name" title="${escapeHtml(d.doc)}">${escapeHtml(d.doc)}</span>
        <span class="kb-chunks">${d.chunks}</span>
        <span class="kb-del" title="从知识库删除">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </span>`;
      el.querySelector('.kb-del').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm(`从知识库删除 ${d.doc}？`)) return;
        try {
          await api(`/api/documents/${encodeURIComponent(d.doc)}`, { method: 'DELETE' });
          toast(`已删除 ${d.doc}`);
          loadKB();
        } catch (err) { toast('删除失败：' + err.message, true); }
      });
      kbList.appendChild(el);
    });
    // 待导入
    pending.forEach(f => {
      const el = document.createElement('div');
      el.className = 'kb-item';
      el.style.opacity = '.6';
      el.innerHTML = `
        <span class="kb-icon"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg></span>
        <span class="kb-name" title="待导入">${escapeHtml(f)}</span>
        <span class="kb-chunks">待入库</span>`;
      el.addEventListener('click', () => ingestFileFromDir(f));
      kbList.appendChild(el);
    });
    if (!indexed.length && !pending.length) {
      kbList.innerHTML = '<div class="kb-empty">知识库为空，点击"导入文档"添加</div>';
    }
    kbStats.textContent = indexed.length ? `${indexed.length} 份文档 · ${indexed.reduce((a, b) => a + b.chunks, 0)} 片段` : '';
    if (data.error) kbStats.textContent = '⚠ ' + data.error;
  }
  async function ingestFileFromDir(fname) {
    // 对已存在于 docs 目录但未入库的文件，通过后端 ingest_dir 无法单独指定；
    // 简化：用 fetch 到 /api/ingest 需要文件体，改用专用接口
    try {
      const resp = await fetch('/api/ingest_dir', { method: 'POST' });
      const data = await resp.json();
      if (data.ok) {
        toast(`扫描目录完成，共入库 ${data.total_chunks} 片段`);
        loadKB();
      }
    } catch (e) { toast('扫描失败：' + e.message, true); }
  }

  // 上传文件
  const fileInput = $('file-input');
  $('import-btn').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async () => {
    const files = [...fileInput.files];
    fileInput.value = '';
    if (!files.length) return;
    for (const f of files) {
      const fd = new FormData();
      fd.append('file', f);
      try {
        const resp = await fetch('/api/ingest', { method: 'POST', body: fd });
        const data = await resp.json();
        if (data.ok) toast(`${data.file} → ${data.chunks} 片段已入库`);
        else toast(`${data.file}：${data.note || '入库失败'}`, true);
      } catch (e) {
        toast(`${f.name} 上传失败：${e.message}`, true);
      }
    }
    loadKB();
  });
  $('rescan-btn').addEventListener('click', () => ingestFileFromDir(''));

  /* ---------- GPU 监控 ---------- */
  const gpuCtx = gpuChart.getContext('2d');
  let gpuChartInit = false;
  function drawGpuChart() {
    if (gpuHistory.length < 2) {
      // 画空网格
      gpuCtx.clearRect(0, 0, gpuChart.width, gpuChart.height);
      gpuCtx.strokeStyle = '#1C2126';
      gpuCtx.lineWidth = 1;
      for (let i = 1; i < 4; i++) {
        gpuCtx.beginPath();
        gpuCtx.moveTo(0, gpuChart.height * i / 4);
        gpuCtx.lineTo(gpuChart.width, gpuChart.height * i / 4);
        gpuCtx.stroke();
      }
      return;
    }
    const w = gpuChart.width, h = gpuChart.height;
    gpuCtx.clearRect(0, 0, w, h);
    // 网格
    gpuCtx.strokeStyle = '#1C2126';
    gpuCtx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
      gpuCtx.beginPath();
      gpuCtx.moveTo(0, h * i / 4);
      gpuCtx.lineTo(w, h * i / 4);
      gpuCtx.stroke();
    }
    const draw = (key, color) => {
      const vals = gpuHistory.map(d => d[key] || 0);
      const max = Math.max(...vals, 100);
      gpuCtx.strokeStyle = color;
      gpuCtx.lineWidth = 1.6;
      gpuCtx.beginPath();
      vals.forEach((v, i) => {
        const x = (i / Math.max(1, vals.length - 1)) * w;
        const y = h - (v / max) * (h - 8) - 4;
        if (i === 0) gpuCtx.moveTo(x, y); else gpuCtx.lineTo(x, y);
      });
      gpuCtx.stroke();
    };
    draw('util', '#34D399');
    draw('vramPct', '#38BDF8');
  }

  async function refreshGpu() {
    try {
      const data = await api('/api/gpu');
      const g = data.gpus && data.gpus[0];
      if (g) {
        const util = Math.round(g.utilization || 0);
        const vramPct = Math.round(g.vram_util_pct != null ? g.vram_util_pct :
          (g.vram_used_mb / Math.max(1, g.vram_total_mb)) * 100);
        const temp = g.temperature != null ? Math.round(g.temperature) : null;
        const power = g.power_w != null ? Math.round(g.power_w) : null;
        const clock = g.core_clock != null ? Math.round(g.core_clock) : null;

        // 顶栏徽标
        const dot = $('gpu-dot');
        if (data.available) dot.className = 'gpu-dot ok';
        else if (data.demo) dot.className = 'gpu-dot warn';
        else dot.className = 'gpu-dot';
        $('gpu-chip-label').textContent = data.available ? 'AMD GPU' : '演示';
        $('gpu-metric-vram').textContent = `${vramPct}%`;
        $('gpu-metric-temp').textContent = temp != null ? `${temp}°C` : '—';

        // 右侧指标
        gpuMetrics.innerHTML = `
          <div class="gpu-metric-row">
            <span class="gm-label">GPU 名称</span>
            <span class="gm-value" style="font-size:12px;min-width:0;text-align:left;color:var(--text-tertiary)">${escapeHtml(g.name || '—')}</span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">利用率</span>
            <span class="gm-value">${util}%</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${util}%;background:var(--gpu-util)"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">显存占用</span>
            <span class="gm-value">${vramPct}%</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${vramPct}%;background:var(--gpu-vram)"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">温度</span>
            <span class="gm-value" style="color:${temp != null && temp > 80 ? 'var(--gpu-temp-hot)' : 'var(--text-primary)'}">${temp != null ? temp + '°C' : '—'}</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${temp != null ? Math.min(100, temp / 100 * 100) : 0}%;background:${temp != null && temp > 80 ? 'var(--gpu-temp-hot)' : 'var(--gpu-fan)'}"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">功耗</span>
            <span class="gm-value">${power != null ? power + 'W' : '—'}</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${power != null ? Math.min(100, power / 300 * 100) : 0}%;background:var(--gpu-power)"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">核心时钟</span>
            <span class="gm-value">${clock != null ? clock + 'MHz' : '—'}</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${clock != null ? Math.min(100, clock / 3500 * 100) : 0}%;background:var(--gpu-clock)"></span></span>
          </div>`;
        gpuNote.innerHTML = data.demo
          ? '<b>演示数据</b> — 本机未检测到 AMD GPU。部署到 Radeon Cloud 后显示真实 rocm-smi 指标。'
          : `来源：${data.source} · 实时刷新 2s`;

        // 历史数据
        gpuHistory.push({ util, vramPct: vramPct, temp: temp || 0, power: power || 0 });
        if (gpuHistory.length > 60) gpuHistory.shift();
        drawGpuChart();
      }
    } catch (e) {}
  }

  // 面板 Tab 切换
  document.querySelectorAll('.panel-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const which = tab.dataset.tab;
      $('panel-trace').classList.toggle('hidden', which !== 'trace');
      $('panel-gpu').classList.toggle('hidden', which !== 'gpu');
      if (which === 'gpu') setTimeout(() => drawGpuChart(), 50);
    });
  });

  /* ---------- 系统信息浮层 ---------- */
  $('settings-btn').addEventListener('click', async () => {
    $('modal-mask').classList.remove('hidden');
    try {
      const d = await api('/api/health');
      const fmt = (k, v) => `<div class="hi-row"><span>${k}</span><span class="hi-val">${escapeHtml(String(v))}</span></div>`;
      $('health-info').innerHTML = `
        <div class="hi-block">
          <div class="hi-label">模型</div>
          ${fmt('后端', d.model.backend)}${fmt('模型', d.model.name)}${fmt('服务地址', d.model.base_url)}
        </div>
        <div class="hi-block">
          <div class="hi-label">检索</div>
          ${fmt('混合检索', d.rag.hybrid ? 'BM25 + 向量' : '纯向量')}${fmt('重排', d.rag.rerank ? 'on' : 'off')}${fmt('Embedding', d.embedding)}
        </div>
        <div class="hi-block">
          <div class="hi-label">知识库</div>
          ${fmt('文档', d.rag.docs)}${fmt('片段', d.rag.chunks)}${fmt('目录', d.rag.docs_dir)}
        </div>
        <div class="hi-block">
          <div class="hi-label">AMD GPU</div>
          <div class="hi-row"><span>状态</span><span><span class="hi-badge ${d.gpu.available ? 'on' : 'off'}">${d.gpu.available ? '已连接' : '未检测到'}</span> ${d.gpu.source || ''}</span></div>
        </div>
        <div class="hi-row"><span>服务器时间</span><span class="hi-val mono">${d.time}</span></div>`;
    } catch (e) {
      $('health-info').textContent = '无法获取系统信息';
    }
  });
  $('modal-close').addEventListener('click', () => $('modal-mask').classList.add('hidden'));
  $('modal-mask').addEventListener('click', (e) => {
    if (e.target === $('modal-mask')) $('modal-mask').classList.add('hidden');
  });

  /* ---------- 建议示例 ---------- */
  function runSuggestion(q) {
    input.value = q;
    autoGrow();
    // 复杂问题自动切多 Agent 并行模式（分解→研究→核查→汇总）
    if (/分析|总结|解读|全景|盘点|评估|比较|怎么|如何/.test(q)) {
      const mb = $('mode-switch').querySelector('.mode-btn[data-mode="multi"]');
      $('mode-switch').querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      mb.classList.add('active');
      state.mode = 'multi';
    }
    sendMessage();
  }
  const suggestionBtns = [...document.querySelectorAll('.suggestion')];
  suggestionBtns.forEach(btn => {
    btn.addEventListener('click', () => runSuggestion(btn.dataset.q));
  });
  // 键盘快捷键 1-4 触发建议（空状态且未在输入时）
  window.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || document.activeElement === input) return;
    if (state.streaming || !emptyState || emptyState.classList.contains('hidden')) return;
    const idx = '1234'.indexOf(e.key);
    if (idx >= 0 && suggestionBtns[idx]) runSuggestion(suggestionBtns[idx].dataset.q);
  });

  /* ---------- 滚动 ---------- */
  let autoScroll = true;
  chatScroll.addEventListener('scroll', () => {
    const dist = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight;
    autoScroll = dist < 80;
  });
  function scrollBottom() {
    if (autoScroll) chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  /* ---------- 初始化 ---------- */
  (async function init() {
    await loadSessions();
    await loadKB();
    refreshGpu();
    // GPU 实时
    const gpuTimer = setInterval(refreshGpu, 2000);
    // 健康检查更新顶栏 GPU
    try {
      const h = await api('/api/health');
      if (h.gpu && h.gpu.available) $('gpu-chip-label').textContent = 'AMD GPU';
      else if (h.gpu && h.gpu.source === 'demo') $('gpu-chip-label').textContent = '演示';
    } catch (e) {}
    input.focus();
  })();
})();
