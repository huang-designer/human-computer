/* 三条件实验前端。只消费 /api/session 返回的归一化 Session。 */

const S = {
  pid: "",
  taskId: "",
  cond: "C",
  spec: {},
  session: null,
  catalog: [],
  t0: 0,
  expanded: new Set(),
  flags: new Set(),
  events: 0,
};

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);

/* ---------------- 日志 ---------------- */
function log(event, payload = {}) {
  S.events++;
  $("logCount").textContent = `${S.events} events`;
  fetch("/api/log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pid: S.pid || "anonymous",
      task_id: S.taskId,
      condition: S.cond,
      event,
      elapsed_ms: S.t0 ? Date.now() - S.t0 : 0,
      payload,
    }),
  }).catch(() => {});
}

/* ---------------- 计时 ---------------- */
function startTimer() {
  S.t0 = Date.now();
  clearInterval(S.timerId);
  S.timerId = setInterval(() => {
    const s = Math.floor((Date.now() - S.t0) / 1000);
    $("timer").textContent =
      `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 500);
}

/* ---------------- 初始化 ---------------- */
async function boot() {
  S.pid = params.get("pid") || "";
  $("pid").value = S.pid;
  $("pid").addEventListener("change", (e) => { S.pid = e.target.value.trim(); });

  const [taskData, catalogData] = await Promise.all([
    fetch("/api/tasks").then((r) => r.json()),
    fetch("/api/catalog").then((r) => r.json()),
  ]);
  S.spec = taskData.condition_spec || {};
  S.catalog = catalogData.products || [];

  const sel = $("taskSel");
  sel.innerHTML = "";
  for (const t of taskData.tasks) {
    const o = document.createElement("option");
    o.value = t.task_id;
    o.textContent = `${t.demo ? "示例" : t.task_id} · ${(t.title || t.query).slice(0, 26)}${t.has_fixture ? "" : "（未生成）"}`;
    o.disabled = !t.has_fixture;
    sel.appendChild(o);
  }

  const tabs = $("condTabs");
  tabs.innerHTML = "";
  for (const c of ["A", "B", "C"]) {
    const b = document.createElement("button");
    b.textContent = `${c} · ${(S.spec[c] || {}).label || c}`;
    b.dataset.cond = c;
    b.onclick = () => { S.cond = c; syncUrl(); loadSession(); };
    tabs.appendChild(b);
  }

  S.taskId = params.get("task") || (taskData.tasks.find((t) => t.has_fixture) || {}).task_id || "";
  S.cond = params.get("cond") || "C";
  sel.value = S.taskId;
  sel.onchange = () => { S.taskId = sel.value; syncUrl(); loadSession(); };

  // 「换成别的机型」下拉
  $("otherSel").innerHTML = S.catalog
    .map((p) => `<option value="${p.id}">${p.name} · ¥${p.price}</option>`).join("");
  document.querySelectorAll('input[name="decide"]').forEach((r) => {
    r.onchange = () => {
      $("otherSel").disabled = r.value !== "other" || !r.checked;
      log("choose_option", { option: r.value });
    };
  });

  if (S.taskId) loadSession();
}

function syncUrl() {
  const p = new URLSearchParams();
  if (S.pid) p.set("pid", S.pid);
  p.set("task", S.taskId);
  p.set("cond", S.cond);
  history.replaceState(null, "", `?${p}`);
}

/* ---------------- 加载 ---------------- */
async function loadSession() {
  for (const b of $("condTabs").children) b.classList.toggle("active", b.dataset.cond === S.cond);
  $("content").innerHTML = `<p class="muted center">加载中…</p>`;
  $("actionCard").hidden = true;
  $("surveyCard").hidden = true;

  const r = await fetch(`/api/session?task_id=${encodeURIComponent(S.taskId)}&condition=${S.cond}`);
  if (!r.ok) {
    const e = await r.json();
    $("content").innerHTML = `<p class="muted center">${e.error || "加载失败"}</p>`;
    $("query").textContent = "—";
    return;
  }
  S.session = await r.json();
  S.expanded.clear();
  S.flags.clear();
  render();
  startTimer();
  log("view_task", {});
}

/* ---------------- 渲染 ---------------- */
function esc(t) {
  return String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function render() {
  const s = S.session;
  const spec = S.spec[s.condition] || { label: s.condition, description: "" };

  $("levelPill").textContent = s.task.level === "decision" ? "购买决策" : `L${s.task.level}`;
  $("condPill").textContent = `条件 ${s.condition} · ${spec.label}`;
  $("taskTitle").textContent = s.task.title || "";
  $("query").textContent = s.task.query;
  $("chips").innerHTML = constraintChips(s.task.constraints);

  const parts = [renderRecommendation(s, spec)];
  if ((spec.show || []).includes("agents")) parts.push(renderAgents(s));
  if ((spec.show || []).includes("disagreements") && (s.disagreements || []).length) parts.push(renderDisagreements(s));
  if ((spec.show || []).includes("steps")) parts.push(renderSteps(s));
  $("content").innerHTML = parts.join("");
  bindDynamic();

  $("actionCard").hidden = false;
  $("actionHint").textContent =
    s.condition === "C"
      ? "可以展开每一步查看证据来源；发现某一步有问题，点该步的「标记有误」。"
      : "如果不同意系统建议，可以换成别的机型，或直接判定没有机型满足条件。";

  const rec = s.recommendation || {};
  const acceptLabel = document.querySelector('label.opt span');
  if (acceptLabel) acceptLabel.textContent = rec.name ? `采纳系统建议（${rec.name}）` : "采纳系统建议";
  if (rec.id) $("otherSel").value = rec.id;
}

function constraintChips(c) {
  if (!c) return "";
  const map = [
    ["budget_max", (v) => `预算 ≤ ¥${v}`],
    ["require_discrete_gpu", () => "必须独显"],
    ["min_ram_gb", (v) => `内存 ≥ ${v}GB`],
    ["min_storage_gb", (v) => `存储 ≥ ${v}GB`],
    ["max_weight_kg", (v) => `重量 ≤ ${v}kg`],
    ["require_official", () => "必须自营售后"],
    ["min_pos_rate", (v) => `好评率 ≥ ${Math.round(v * 100)}%`],
  ];
  return map
    .filter(([k]) => c[k] !== undefined && c[k] !== false)
    .map(([k, f]) => `<span class="chip">${esc(f(c[k]))}</span>`)
    .join("");
}

function renderRecommendation(s, spec) {
  const r = s.recommendation || { name: s.final_answer, price: "", reason: "" };
  return `
    <div class="card">
      <div class="answer-card">
        <h3>系统给出的建议</h3>
        <div class="answer-line">
          <span class="answer-value">${esc(r.name || "（无）")}</span>
          ${r.price ? `<span class="price">¥${r.price}</span>` : ""}
        </div>
        ${r.reason ? `<p class="reason">${esc(r.reason)}</p>` : ""}
      </div>
      <p class="hint">${esc(spec.description || "")}</p>
    </div>`;
}

function renderAgents(s) {
  const cards = (s.agents || []).map((a) => `
    <div class="agent ${esc(a.status)}">
      <span class="ms">${a.elapsed_ms ? (a.elapsed_ms / 1000).toFixed(1) + "s" : ""}</span>
      <div class="name">${esc(a.name)}${a.status !== "ok" ? `<span class="badge">${esc(a.status)}</span>` : ""}</div>
      <div class="role">${esc(a.role)}</div>
      <div class="sum">${esc(a.summary)}</div>
    </div>`).join("");
  return `
    <div class="card">
      <h3 class="block-title">参与本次任务的 Agent</h3>
      <div class="agents">${cards}</div>
    </div>`;
}

function agentName(s, id) {
  const a = (s.agents || []).find((x) => x.id === id);
  return a ? a.name : id;
}

function renderDisagreements(s) {
  const items = s.disagreements.map((d, k) => `
    <div class="dis">
      <h4>分歧 ${k + 1}：${esc(d.topic)}</h4>
      ${(d.options || []).map((o) => `
        <div class="dis-opt"><div class="who">${esc(agentName(s, o.agent_id))}</div>
        <div>${esc(o.claim)}</div></div>`).join("")}
      ${d.resolution ? `<div class="dis-res">主控采纳：<b>${esc(agentName(s, d.resolution.chosen_agent))}</b> —— ${esc(d.resolution.reason)}</div>` : ""}
    </div>`).join("");
  return `<div class="card">${items}</div>`;
}

function renderSteps(s) {
  const items = s.steps.map((st) => {
    const open = S.expanded.has(st.i);
    const flagged = S.flags.has(st.i);
    const ev = (st.evidence || []).length
      ? `<ul class="evidence">${st.evidence.map((e) => `
          <li><b>${esc(e.label)}</b><div class="src">${esc(e.source)}</div>
          <div class="snip">${esc(e.snippet)}</div></li>`).join("")}</ul>`
      : "";
    return `
      <li class="step ${esc(st.kind)}" data-step="${st.i}">
        <div class="step-head">
          <span class="step-title">${st.i}. ${esc(st.title)}</span>
          <span class="step-agent">${esc(agentName(s, st.agent_id))}</span>
          ${st.elapsed_ms ? `<span class="step-agent">${(st.elapsed_ms / 1000).toFixed(1)}s</span>` : ""}
          ${st.confidence != null ? `<span class="step-agent">置信度 ${(st.confidence * 100).toFixed(0)}%</span>` : ""}
          <button class="toggle" data-toggle="${st.i}">${open ? "收起" : "展开"}</button>
          <button class="flag-btn ${flagged ? "on" : ""}" data-flag="${st.i}">${flagged ? "已标记有误" : "标记有误"}</button>
        </div>
        ${open ? `<div class="step-body"><div class="step-detail">${esc(st.detail)}</div>${ev}</div>` : ""}
      </li>`;
  }).join("");
  return `
    <div class="card">
      <h3 class="block-title">执行时间线</h3>
      <ul class="timeline">${items}</ul>
    </div>`;
}

function bindDynamic() {
  document.querySelectorAll("[data-toggle]").forEach((b) => {
    b.onclick = () => {
      const i = Number(b.dataset.toggle);
      S.expanded.has(i) ? S.expanded.delete(i) : S.expanded.add(i);
      log("expand_step", { step: i, expanded: S.expanded.has(i) });
      render();
    };
  });
  document.querySelectorAll("[data-flag]").forEach((b) => {
    b.onclick = () => {
      const i = Number(b.dataset.flag);
      S.flags.has(i) ? S.flags.delete(i) : S.flags.add(i);
      log("flag_error", { step: i, on: S.flags.has(i) });
      render();
    };
  });
}

/* ---------------- 提交 ---------------- */
function currentChoice() {
  const v = (document.querySelector('input[name="decide"]:checked') || {}).value || "accept";
  if (v === "accept") return (S.session.recommendation || {}).id || S.session.final_answer;
  if (v === "other") return $("otherSel").value;
  return "无合适机型";
}

function submit() {
  const s = S.session;
  const mode = (document.querySelector('input[name="decide"]:checked') || {}).value;
  const userAnswer = currentChoice();
  const elapsed = Date.now() - S.t0;

  log("submit", {
    mode,
    user_answer: userAnswer,
    note: $("note").value.trim(),
    expanded_steps: [...S.expanded],
    flagged_steps: [...S.flags],
  });

  fetch("/api/response", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pid: S.pid || "anonymous",
      task_id: s.task.task_id,
      condition: s.condition,
      ai_answer: (s.recommendation || {}).id || s.final_answer,
      user_answer: userAnswer,
      gold: s.task.answer,
      mode,
      note: $("note").value.trim(),
      elapsed_ms: elapsed,
      expanded_steps: [...S.expanded],
      flagged_steps: [...S.flags],
    }),
  }).catch(() => {});

  clearInterval(S.timerId);
  $("actionCard").hidden = true;
  showSurvey();
}

const SURVEY = [
  ["trust", "我愿意采纳这个系统的建议"],
  ["control", "我觉得自己掌控着整个任务"],
  ["load", "刚才的任务让我感觉很费脑力"],
  ["usability", "这个界面容易使用"],
];

function showSurvey() {
  $("surveyGrid").innerHTML = SURVEY.map(([k, q]) => `
    <div class="survey-item">
      <span class="q">${esc(q)}</span>
      <div class="scale">
        ${[1, 2, 3, 4, 5, 6, 7].map((n) => `
          <input type="radio" name="${k}" id="${k}${n}" value="${n}" />
          <label for="${k}${n}">${n}</label>`).join("")}
      </div>
    </div>`).join("");
  $("surveyCard").hidden = false;
  $("surveyCard").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function saveSurvey() {
  const out = {};
  for (const [k] of SURVEY) {
    const el = document.querySelector(`input[name="${k}"]:checked`);
    out[k] = el ? Number(el.value) : null;
  }
  log("survey", out);
  $("surveyCard").hidden = true;
  $("content").innerHTML = `<p class="muted center">已保存。可以换下一个任务（右上角下拉框）。</p>`;
  $("actionCard").hidden = true;
}

/* ---------------- 绑定 ---------------- */
$("submitBtn").onclick = submit;
$("nextBtn").onclick = saveSurvey;
window.addEventListener("beforeunload", () => { if (S.session) log("leave_task", {}); });

boot();
