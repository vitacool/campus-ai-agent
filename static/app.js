const form = document.querySelector("#chat-form");
const input = document.querySelector("#question");
const messages = document.querySelector("#messages");
const knowledge = document.querySelector("#knowledge");
const statusBadge = document.querySelector("#status");
const statsBadge = document.querySelector("#stats");
const knowledgeCount = document.querySelector("#knowledge-count");
const avgLatency = document.querySelector("#avg-latency");

function appendMessage(role, text, meta = "", sources = [], chatId = null) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const body = document.createElement("p");
  body.textContent = text;
  article.appendChild(body);

  if (sources.length) {
    const sourceList = document.createElement("div");
    sourceList.className = "source-list";
    sources.forEach((source) => {
      const item = document.createElement("span");
      const terms = source.matched_terms?.slice(0, 3).join(" / ") || "无";
      item.textContent = `${source.title} · ${source.score} · ${terms}`;
      sourceList.appendChild(item);
    });
    article.appendChild(sourceList);
  }

  if (meta) {
    const metaNode = document.createElement("div");
    metaNode.className = "meta";
    metaNode.textContent = meta;
    article.appendChild(metaNode);
  }

  if (role === "assistant" && chatId) {
    const feedback = document.createElement("div");
    feedback.className = "feedback";
    feedback.innerHTML = `
      <button type="button" data-rating="up">有帮助</button>
      <button type="button" data-rating="down">需改进</button>
    `;
    feedback.addEventListener("click", async (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      await sendFeedback(chatId, button.dataset.rating);
      feedback.textContent = "已记录反馈";
    });
    article.appendChild(feedback);
  }

  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
}

async function loadKnowledge() {
  const response = await fetch("/api/knowledge");
  const items = await response.json();
  knowledge.innerHTML = "";

  items.forEach((item) => {
    const node = document.createElement("section");
    node.className = "knowledge-item";
    node.innerHTML = `<strong>${item.title}</strong><span>${item.category}</span>`;
    knowledge.appendChild(node);
  });
}

async function loadStats() {
  const response = await fetch("/api/stats");
  const stats = await response.json();
  statsBadge.textContent = `${stats.chat_count} 次问答`;
  knowledgeCount.textContent = stats.knowledge_count;
  avgLatency.textContent = `${stats.average_latency_ms}ms`;
}

async function sendFeedback(chatId, rating) {
  await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, rating }),
  });
  await loadStats();
}

async function ask(question) {
  appendMessage("user", question);
  input.value = "";

  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const data = await response.json();

  if (data.error) {
    appendMessage("assistant", data.error);
    return;
  }

  statusBadge.textContent = data.used_model ? "大模型增强模式" : "本地检索模式";
  const sourceNames = data.sources.map((source) => source.title).join("、") || "无匹配来源";
  appendMessage(
    "assistant",
    data.answer,
    `工具：${data.tool} | 来源：${sourceNames} | 耗时：${data.latency_ms}ms`,
    data.sources,
    data.id,
  );
  await loadStats();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  await ask(question);
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => ask(button.dataset.question));
});

loadKnowledge();
loadStats();
