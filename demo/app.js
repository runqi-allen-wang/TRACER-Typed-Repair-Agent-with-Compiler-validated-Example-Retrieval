const data = window.TRACER_DEMO;
const $ = (selector) => document.querySelector(selector);
const all = (selector) => [...document.querySelectorAll(selector)];
const repository = "https://github.com/runqi-allen-wang/TRACER-Typed-Repair-Agent-with-Compiler-validated-Example-Retrieval";

const translations = {
  en: {
    eyebrow: "COMPILER-GROUNDED LEAN REPAIR",
    title: "Explore 24 failed proofs and their verified repairs.",
    lede: "Filter by failure mode, inspect the compiler signal, and switch from each frozen faulty proof to an independently recompiled solution. Everything runs in your browser—no API key required.",
    browse: "Browse 24 repairs", resultsLink: "See published results",
    evidence: "Evidence-backed · public release research-six-arm-313f437f",
    verifiedCases: "verified repair pairs", topics: "proof domains", categories: "diagnostic families",
    staticNote: "Interactive static replay · zero network requests",
    caseEyebrow: "VERIFIED REPAIR EXPLORER", caseTitle: "Different errors need different repair moves",
    caseBody: "Each left side is a frozen failing benchmark proof; each right side is a public solution that passed independent Lean recompilation.",
    filterError: "Error family", filterTopic: "Proof domain", examples: "Examples",
    firstCandidate: "Frozen faulty proof", compileFail: "Compiler rejects",
    feedbackRepair: "Verified repair", kernelPass: "Independent recompile passes",
    candidate: "Proof term", compiler: "Lean compiler", feedback: "TRACER structured signal",
    retrieved: "Evidence provenance", replay: "Replay repair", previous: "← Previous", next: "Next →",
    pipelineEyebrow: "WHERE TRACER INTERVENES", pipelineTitle: "The improvement is the repair loop—not a new Lean kernel",
    pipelineBody: "TRACER keeps the model replaceable and improves the engineering between generation and acceptance: diagnostics remain traceable, retrieval can react to the current error, and no proof is accepted without compilation.",
    p1Title: "Patch safely", p1Body: "Replace only the target proof region in an isolated temporary project; preserve imports and theorem headers.", p1Effect: "Effect: source files stay untouched.",
    p2Title: "Keep the compiler signal", p2Body: "Store raw diagnostics, normalized categories, structured goals, warnings, and timeouts together.", p2Effect: "Effect: compact feedback remains auditable.",
    p3Title: "React to the error", p3Body: "Feedback arms expose the latest diagnostic; adaptive retrieval arms rebuild the query from the current error state.", p3Effect: "Effect: R-E changed 90% of eligible Flash queries.",
    p4Title: "Bound the repair loop", p4Body: "Retry only within a declared round budget, recording every candidate, diagnostic, retrieved example, latency, and usage.", p4Effect: "Effect: 76/864 instances recovered after round one.",
    p5Title: "Verify, then publish", p5Body: "Reject incomplete proofs and unsafe constructs; save successful files and independently recompile public solutions.", p5Effect: "Effect: 811 released proofs recompiled independently.",
    pipelineBoundary: "<strong>Boundary:</strong> TRACER does not replace Lean, train a new model, or make every feedback arm better. It turns model output into a bounded, compiler-validated, inspectable repair process.",
    published: "PUBLISHED SIX-ARM RELEASE", resultsTitle: "What the bounded repair loop recovered",
    resultsBody: "Across every model/arm/repeat task instance, compare the first candidate with the final outcome after at most three rounds.",
    firstRound: "First candidate", threeRounds: "Within three rounds", recovered: "Recovered after round one",
    delta: "task instances · +8.8 percentage points",
    caveat: "<strong>Interpretation:</strong> this is a descriptive first-to-final conversion over paired task instances, not a causal estimate of TRACER's effect. The preregistered R-B − R-A comparison was 0.0 points for Flash and −2.8 points for Pro.",
    liveEyebrow: "RUN THE REAL COMPILER", liveTitle: "Want more than a recorded replay?",
    liveBody: "Clone the repository and execute the same pipeline with a supplied candidate. Lean runs locally; no model API or payment is required.",
    copy: "Copy", copied: "Copied", footer: "All 24 repair pairs and displayed metrics are traceable to public repository artifacts.",
    openEvidence: "Open evidence", failed: "REJECTED", passed: "VERIFIED", before: "Frozen fixture", after: "Public solution",
    compiled: "Lean compiled this proof successfully. The released file also passed an independent recompilation.",
    verifiedSignal: "status: kernel_pass\npolicy: complete proof, warning state recorded\nrelease check: independent recompilation passed",
    allErrors: "All errors", allTopics: "All domains"
  },
  zh: {
    eyebrow: "由编译器约束的 LEAN 修复",
    title: "浏览 24 个失败证明及其验证修复。",
    lede: "按错误类型筛选，查看编译器信号，并在冻结的错误证明与独立复编译通过的解之间切换。全部交互都在浏览器完成，无需 API key。",
    browse: "浏览 24 个修复", resultsLink: "查看公开结果",
    evidence: "证据可追溯 · 公开发布包 research-six-arm-313f437f",
    verifiedCases: "组验证修复", topics: "类证明领域", categories: "类诊断错误",
    staticNote: "交互式静态回放 · 不发起网络请求",
    caseEyebrow: "验证修复浏览器", caseTitle: "不同错误需要不同修复动作",
    caseBody: "左侧均为冻结基准中的失败证明，右侧均为公开且通过 Lean 独立复编译的成功证明。",
    filterError: "错误类别", filterTopic: "证明领域", examples: "案例",
    firstCandidate: "冻结错误证明", compileFail: "编译器拒绝",
    feedbackRepair: "验证修复", kernelPass: "独立复编译通过",
    candidate: "证明代码", compiler: "Lean 编译器", feedback: "TRACER 结构化信号",
    retrieved: "证据来源", replay: "播放修复", previous: "← 上一个", next: "下一个 →",
    pipelineEyebrow: "TRACER 改进的位置", pipelineTitle: "改进的是修复闭环，而不是另造一个 Lean 内核",
    pipelineBody: "TRACER 不绑定某个模型，而是改进生成到验收之间的工程链路：诊断可追溯，检索可随当前错误变化，任何证明都必须经过真实编译才能被接受。",
    p1Title: "安全打补丁", p1Body: "只替换隔离临时项目里的目标证明区域，保留 import 与定理头。", p1Effect: "效果：原始源码不被覆盖。",
    p2Title: "保留编译信号", p2Body: "同时保存原始诊断、规范化类别、结构化目标、警告和超时。", p2Effect: "效果：反馈压缩后仍可审计。",
    p3Title: "让检索随错误变化", p3Body: "反馈组暴露最新诊断；动态检索组根据当前错误状态重组查询。", p3Effect: "效果：R-E 改变了 90% 的合格 Flash 查询。",
    p4Title: "限制修复轮数", p4Body: "只在预先声明的轮数内重试，并记录每个候选、诊断、检索示例、延迟和用量。", p4Effect: "效果：864 个实例中有 76 个在首轮后被挽回。",
    p5Title: "验证后再发布", p5Body: "拒绝未完成证明和危险结构，保存成功文件，并独立复编译公开解。", p5Effect: "效果：发布的 811 个证明全部独立复编译。",
    pipelineBoundary: "<strong>边界：</strong>TRACER 不替代 Lean、不训练新模型，也不声称每种反馈组都更好；它把模型输出变成有界、编译验证、可检查的修复过程。",
    published: "已发布六臂实验", resultsTitle: "有界修复循环挽回了多少任务",
    resultsBody: "在全部模型、实验臂与重复任务实例上，对比第一轮候选与最多三轮后的最终结果。",
    firstRound: "第一轮候选", threeRounds: "三轮预算内", recovered: "第一轮后挽回",
    delta: "个任务实例 · 提高 8.8 个百分点",
    caveat: "<strong>解释边界：</strong>这是配对任务实例从首轮到末轮的描述性转化，不是 TRACER 因果效应估计。预注册的 R-B − R-A 对比在 Flash 上为 0.0 个百分点，在 Pro 上为 −2.8 个百分点。",
    liveEyebrow: "运行真实编译器", liveTitle: "想体验的不只是网页回放？",
    liveBody: "克隆仓库后，用给定候选运行同一条补丁和编译链。Lean 在本地真实编译，无需模型 API，也不会产生费用。",
    copy: "复制", copied: "已复制", footer: "页面中的 24 组修复与全部指标均可追溯到仓库公开证据。",
    openEvidence: "打开证据", failed: "已拒绝", passed: "已验证", before: "冻结错误夹具", after: "公开成功证明",
    compiled: "Lean 已成功编译该证明；发布文件还通过了独立复编译。",
    verifiedSignal: "status: kernel_pass\npolicy: 完整证明，警告状态已记录\nrelease check: 独立复编译通过",
    allErrors: "全部错误", allTopics: "全部领域"
  }
};

const categoryNames = {
  en: { type_mismatch: "type mismatch", unknown_identifier: "unknown identifier", unsolved_goals: "unsolved goals", compile_error: "tactic / elaboration" },
  zh: { type_mismatch: "类型不匹配", unknown_identifier: "未知标识符", unsolved_goals: "未解决目标", compile_error: "策略 / elaboration" }
};
const topicNames = {
  en: { recursive_lists: "recursive lists", quantifiers: "quantifiers", functions: "functions", options: "options", recursive_nat: "recursive naturals" },
  zh: { recursive_lists: "递归列表", quantifiers: "量词逻辑", functions: "函数性质", options: "Option 结构", recursive_nat: "自然数递归" }
};

let language = "en";
let currentRound = 0;
let currentCase = 0;
let visibleCases = [...data.cases];
let replayTimer;

function displayCategory(value) { return categoryNames[language][value] || value; }
function displayTopic(value) { return topicNames[language][value] || value; }

function renderRound(index, animate = false) {
  currentRound = index;
  const item = visibleCases[currentCase] || data.cases[0];
  const passed = index === 1;
  all(".step").forEach((step) => step.classList.toggle("active", Number(step.dataset.round) === index));
  $("#candidate-code").textContent = passed ? item.repairedProof : item.initialProof;
  $("#diagnostic").textContent = passed ? translations[language].compiled : item.initialDiagnostic;
  $("#feedback").textContent = passed ? translations[language].verifiedSignal : item.structuredFeedback;
  $("#round-label").textContent = passed ? translations[language].after : translations[language].before;
  const evidence = $("#retrieval");
  evidence.textContent = passed ? item.solutionPath.split("/").slice(-5).join("/") : `benchmark.json · ${item.id}`;
  evidence.href = passed ? `${repository}/blob/main/${item.solutionPath}` : `${repository}/blob/main/published/research-six-arm-313f437f/benchmark.json`;
  const status = $("#compile-status");
  status.className = `status ${passed ? "passed" : "failed"}`;
  status.textContent = translations[language][passed ? "passed" : "failed"];
  const workspace = $(".workspace");
  workspace.classList.toggle("success", passed);
  if (animate) {
    workspace.classList.remove("flash");
    requestAnimationFrame(() => workspace.classList.add("flash"));
  }
}

function renderCase(animate = false) {
  const item = visibleCases[currentCase] || data.cases[0];
  $("#problem-name").textContent = item.theorem;
  $("#topic-name").textContent = displayTopic(item.topic);
  $("#error-name").textContent = displayCategory(item.category);
  $("#difficulty-name").textContent = item.difficulty;
  all(".case-card").forEach((card) => card.classList.toggle("active", card.dataset.id === item.id));
  renderRound(currentRound, animate);
}

function renderCaseList() {
  const category = $("#category-filter").value;
  const topic = $("#topic-filter").value;
  visibleCases = data.cases.filter((item) => (category === "all" || item.category === category) && (topic === "all" || item.topic === topic));
  currentCase = 0;
  $("#visible-count").textContent = `${visibleCases.length} / ${data.cases.length}`;
  $("#case-list").innerHTML = visibleCases.map((item) => `
    <button class="case-card" type="button" role="option" data-id="${item.id}">
      <span class="case-category ${item.category}">${displayCategory(item.category)}</span>
      <strong>${item.id}</strong>
      <small>${displayTopic(item.topic)}</small>
    </button>`).join("");
  all(".case-card").forEach((card, index) => card.addEventListener("click", () => {
    currentCase = index;
    currentRound = 0;
    renderCase(true);
    if (window.innerWidth < 760) $(".workspace").scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  renderCase();
}

function populateFilters() {
  const category = $("#category-filter");
  const topic = $("#topic-filter");
  const selectedCategory = category.value || "all";
  const selectedTopic = topic.value || "all";
  category.innerHTML = `<option value="all">${translations[language].allErrors}</option>` + [...new Set(data.cases.map((item) => item.category))].map((value) => `<option value="${value}">${displayCategory(value)}</option>`).join("");
  topic.innerHTML = `<option value="all">${translations[language].allTopics}</option>` + [...new Set(data.cases.map((item) => item.topic))].map((value) => `<option value="${value}">${displayTopic(value)}</option>`).join("");
  category.value = selectedCategory;
  topic.value = selectedTopic;
}

function applyLanguage(next) {
  language = next;
  document.documentElement.lang = next === "en" ? "en" : "zh-CN";
  all("[data-i18n]").forEach((node) => {
    const value = translations[next][node.dataset.i18n];
    if (!value) return;
    if (value.includes("<strong>")) node.innerHTML = value;
    else node.textContent = value;
  });
  $("#language").textContent = next === "en" ? "中文" : "English";
  populateFilters();
  renderCaseList();
}

function replay() {
  clearTimeout(replayTimer);
  renderRound(0, true);
  replayTimer = setTimeout(() => renderRound(1, true), 1300);
}

$("#case-count").textContent = data.evidence.caseCount;
$("#topic-count").textContent = data.evidence.topicCount;
$("#category-count").textContent = data.evidence.categoryCount;
all(".step").forEach((step) => step.addEventListener("click", () => {
  clearTimeout(replayTimer);
  renderRound(Number(step.dataset.round), true);
}));
$("#category-filter").addEventListener("change", renderCaseList);
$("#topic-filter").addEventListener("change", renderCaseList);
$("#replay").addEventListener("click", replay);
$("#previous-case").addEventListener("click", () => { currentCase = (currentCase - 1 + visibleCases.length) % visibleCases.length; currentRound = 0; renderCase(true); });
$("#next-case").addEventListener("click", () => { currentCase = (currentCase + 1) % visibleCases.length; currentRound = 0; renderCase(true); });
$("#language").addEventListener("click", () => applyLanguage(language === "en" ? "zh" : "en"));
$("#copy-command").addEventListener("click", async () => {
  const command = $("#local-command").textContent;
  try { await navigator.clipboard.writeText(command); }
  catch (_) {
    const helper = document.createElement("textarea");
    helper.value = command; helper.style.position = "fixed"; helper.style.opacity = "0";
    document.body.appendChild(helper); helper.select(); document.execCommand("copy"); helper.remove();
  }
  $("#copy-command").textContent = translations[language].copied;
  setTimeout(() => { $("#copy-command").textContent = translations[language].copy; }, 1300);
});

applyLanguage("en");
if (new URLSearchParams(window.location.search).get("preview") === "examples") {
  document.body.classList.add("preview-examples");
  renderRound(1);
}
