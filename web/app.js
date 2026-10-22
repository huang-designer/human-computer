/* 三条件实验前端。只消费 /api/session 返回的归一化 Session。 */

const S = {
  pid: "",
  taskId: "",
  cond: "C",
  spec: {},
  session: null,
  t0: 0,
  expanded: new Set(),   // 展开过的步骤序号
  flags: new Set(),      // 被标记为「有误」的步骤序号
  events: 0,
};

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);

/* ---------------- 日志 ---------------- */
function log(event, payload = {}) {
  S.events++;
  $("logCount").textContent = `${S.events} events`;
  const body = {
    pid: S.pid || "anonymous",
    task_id: S.taskId,
    condition: S.cond,
    event,
    elapsed_ms: S.t0 ? Date.now() - S.t0 : 0,
    payload,
  };
  // 日志失败不应打断被试，静默忽略
  fetch("/api/log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
  $("pid").addEventListener("change", (e) => (S.pid = e.target.value.trim()));

  const data = await (await fetch("/api/tasks")).json();
  S.spec = data.condition_spec || {};

  const sel = $("taskSel");
  sel.innerHTML = "";
  for (const t of data.tasks) {
    const o = document.createElement("option");
    o.value = t.task_id;
    o.textContent = `${t.demo ? "示例" : "L" + t.level} · ${t.query.slice(0, 34)}${t.has_fixture ? "" : "（无结果）"}`;
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

  S.taskId = params.get("task") || (data.tasks.find((t) => t.has_fixture) || {}).task_id || "";
  S.cond = params.get("cond") || "C";
  sel.value = S.taskId;
  sel.onchange = () => { S.taskId = sel.value; syncUrl(); loadSession(); };

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
  log("view_task", { level: S.session.task.level });
}

/* ---------------- 渲染 ---------------- */
function render() {
  const s = S.session;
  const spec = S.spec[s.condition] || { label: s.condition, description: "" };

  $("levelPill").textContent = `L${s.task.level}`;
  $("condPill").textContent = `条件 ${s.condition} · ${spec.label}`;
  $("taskMeta").textContent = "";
  $("query").textContent = s.task.query;

  const parts = [];
  parts.push(renderAnswer(s, spec));
  if ((spec.show || []).includes("agents")) parts.push(renderAgents(s));
  if ((spec.show || []).includes("disagreements") && (s.disagreements || []).length) parts.push(renderDisagreements(s));
  if ((spec.show || []).includes("steps")) parts.push(renderSteps(s));

  $("content").innerHTML = parts.join("");
  bindDynamic();

  $("actionCard").hidden = false;
  $("answerBox").value = s.final_answer || "";
  $("actionHint").textContent =
    s.condition === "C"
      ? "你可以展开每一步的证据；如果发现某一步有错，点该步的「标记有误」。"
      : "如果你认为系统答案不对，可以直接改成你判断的答案。";
}

function esc(t) {
  return String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function renderAnswer(s, spec) {
  return `
    <div class="card">
      <div class="answer-card">
        <h3>系统给出的答案</h3>
        <div class="answer-value">${esc(s.final_answer) || '<span class="muted">（无）</span>'}</div>
      </div>
      <p class="hint">${esc(spec.description || "")}</p>
    </div>`;
}

function renderAgents(s) {
  const cards = (s.agents || []).map((a) => `
    <div class="agent ${esc(a.status)}">
      <span class="ms">${a.elapsed_ms ? (a.elapsed_ms / 1000).toFixed(1) + "s" : ""}</span>
      <div class="name">${esc(a.name)}
        ${a.status !== "ok" ? `<span class="badge">${esc(a.status)}</span>` : ""}</div>
      <div class="role">${esc(a.role)}</div>
      <div class="sum">${esc(a.summary)}</div>
    </div>`).join("");
  return `
    <div class="card">
      <h3 style="margin:0 0 10px;font-size:13px;color:#7a8291;letter-spacing:.04em">参与本次任务的 Agent</h3>
      <div class="agents">${cards}</div>
    </div>`;
}

function renderDisagreements(s) {
  const items = s.disagreements.map((d, k) => `
    <div class="dis" style="margin-bottom:10px">
      <h4>分歧 ${k + 1}：${esc(d.topic)}</h4>
      ${(d.options || []).map((o) => `
        <div class="dis-opt">
          <div class="who">${esc(agentName(s, o.agent_id))}</div>
          <div>${esc(o.claim)}</div>
        </div>`).join("")}
      ${d.resolution ? `<div class="dis-res">主控采纳：<b>${esc(agentName(s, d.resolution.chosen_agent))}</b> —— ${esc(d.resolution.reason)}</div>` : ""}
    </div>`).join("");
  return `<div class="card" data-block="disagreements">${items}</div>`;
}

function agentName(s, id) {
  const a = (s.agents || []).find((x) => x.id === id);
  return a ? a.name : id;
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
      <h3 style="margin:0 0 12px;font-size:13px;color:#7a8291;letter-spacing:.04em">执行时间线</h3>
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
function submit(accepted) {
  const s = S.session;
  const userAnswer = accepted ? s.final_answer : $("answerBox").value.trim();
  if (!userAnswer) { $("answerBox").focus(); return; }
  const elapsed = Date.now() - S.t0;
  log("submit", {
    accepted_ai: accepted,
    user_answer: userAnswer,
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
      ai_answer: s.final_answer,
      user_answer: userAnswer,
      gold: s.task.answer,
      accepted_ai: accepted,
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
$("acceptBtn").onclick = () => submit(true);
$("submitBtn").onclick = () => submit(false);
$("nextBtn").onclick = saveSurvey;
window.addEventListener("beforeunload", () => { if (S.session) log("leave_task", {}); });

boot();
