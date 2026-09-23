const data = window.TRACER_DEMO;
const $ = (selector) => document.querySelector(selector);
const all = (selector) => [...document.querySelectorAll(selector)];

const translations = {
  en: {
    eyebrow: "COMPILER-GROUNDED PROOF REPAIR",
    title: "Watch one failed Lean proof become a verified repair.",
    lede: "No API key. No simulated success. Replay one sanitized trajectory from the audited 864-task release.",
    replay: "Replay the repair", resultsLink: "See published results",
    evidence: "Evidence: public release research-six-arm-313f437f",
    firstCandidate: "First candidate", compileFail: "Compile fails",
    feedbackRepair: "Feedback repair", kernelPass: "Kernel pass",
    candidate: "Candidate proof", compiler: "Lean compiler", feedback: "TRACER feedback",
    retrieved: "Top retrieved example", published: "PUBLISHED SIX-ARM RELEASE",
    resultsTitle: "What the bounded repair loop recovered",
    resultsBody: "Across every model/arm/repeat task instance, compare the first candidate with the final outcome after at most three rounds.",
    firstRound: "First candidate", threeRounds: "Within three rounds", recovered: "Recovered after round one",
    delta: "task instances · +8.8 percentage points",
    caveat: "<strong>Interpretation:</strong> this is a descriptive first-to-final conversion over paired task instances, not a causal estimate of TRACER's effect. The preregistered R-B − R-A comparison was 0.0 points for Flash and −2.8 points for Pro.",
    liveEyebrow: "RUN THE REAL COMPILER", liveTitle: "Want more than a recorded replay?",
    liveBody: "Clone the repository and execute the same pipeline with a supplied candidate. Lean runs locally; no model API or payment is required.",
    copy: "Copy", copied: "Copied", footer: "Every displayed candidate and metric is traceable to the repository's public artifacts.",
    openEvidence: "Open evidence", failed: "FAILED", passed: "VERIFIED"
  },
  zh: {
    eyebrow: "由编译器约束的证明修复",
    title: "看一个失败的 Lean 证明如何变成可验证修复。",
    lede: "无需 API key，也不模拟成功。这里回放的是 864 任务审计发布包中的一条真实脱敏轨迹。",
    replay: "播放修复过程", resultsLink: "查看公开结果",
    evidence: "证据：公开发布包 research-six-arm-313f437f",
    firstCandidate: "第一轮候选", compileFail: "编译失败",
    feedbackRepair: "根据反馈修复", kernelPass: "内核通过",
    candidate: "候选证明", compiler: "Lean 编译器", feedback: "TRACER 反馈",
    retrieved: "Top-1 检索示例", published: "已发布六臂实验",
    resultsTitle: "有界修复循环挽回了多少任务",
    resultsBody: "在全部模型、实验臂与重复任务实例上，对比第一轮候选与最多三轮后的最终结果。",
    firstRound: "第一轮候选", threeRounds: "三轮预算内", recovered: "第一轮后挽回",
    delta: "个任务实例 · 提高 8.8 个百分点",
    caveat: "<strong>解释边界：</strong>这是配对任务实例从首轮到末轮的描述性转化，不是 TRACER 因果效应估计。预注册的 R-B − R-A 对比在 Flash 上为 0.0 个百分点，在 Pro 上为 −2.8 个百分点。",
    liveEyebrow: "运行真实编译器", liveTitle: "想体验的不只是录制回放？",
    liveBody: "克隆仓库后，用给定候选运行同一条流水线。Lean 在本地真实编译，无需模型 API，也不会产生费用。",
    copy: "复制", copied: "已复制", footer: "页面中的每个候选与指标都能追溯到仓库公开证据。",
    openEvidence: "打开证据", failed: "失败", passed: "已验证"
  }
};

let language = "en";
let currentRound = 0;
let replayTimer;

function renderRound(index, animate = false) {
  currentRound = index;
  const round = data.caseStudy.rounds[index];
  all(".step").forEach((step) => step.classList.toggle("active", Number(step.dataset.round) === index));
  $("#candidate-code").textContent = round.candidate;
  $("#diagnostic").textContent = round.diagnostic;
  $("#feedback").textContent = round.feedback;
  $("#retrieval").textContent = round.retrieval;
  $("#round-label").textContent = round.label;
  const status = $("#compile-status");
  status.className = `status ${round.status}`;
  status.textContent = translations[language][round.status];
  const workspace = $(".workspace");
  workspace.classList.toggle("success", round.status === "passed");
  if (animate) {
    workspace.classList.remove("flash");
    requestAnimationFrame(() => workspace.classList.add("flash"));
  }
}

function applyLanguage(next) {
  language = next;
  document.documentElement.lang = next === "en" ? "en" : "zh-CN";
  all("[data-i18n]").forEach((node) => {
    const value = translations[next][node.dataset.i18n];
    if (value.includes("<strong>")) node.innerHTML = value;
    else node.textContent = value;
  });
  $("#language").textContent = next === "en" ? "中文" : "English";
  renderRound(currentRound);
}

function replay() {
  clearTimeout(replayTimer);
  renderRound(0, true);
  $(".workspace").scrollIntoView({ behavior: "smooth", block: "center" });
  replayTimer = setTimeout(() => renderRound(1, true), 1500);
}

$("#problem-name").textContent = data.caseStudy.problem;
$("#model-name").textContent = data.caseStudy.model;
$("#arm-name").textContent = data.caseStudy.arm;
all(".step").forEach((step) => step.addEventListener("click", () => {
  clearTimeout(replayTimer);
  renderRound(Number(step.dataset.round), true);
}));
$("#replay").addEventListener("click", replay);
$("#language").addEventListener("click", () => applyLanguage(language === "en" ? "zh" : "en"));
$("#copy-command").addEventListener("click", async () => {
  const command = $("#local-command").textContent;
  try {
    await navigator.clipboard.writeText(command);
  } catch (_) {
    const helper = document.createElement("textarea");
    helper.value = command;
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    helper.remove();
  }
  $("#copy-command").textContent = translations[language].copied;
  setTimeout(() => { $("#copy-command").textContent = translations[language].copy; }, 1300);
});

applyLanguage("en");
