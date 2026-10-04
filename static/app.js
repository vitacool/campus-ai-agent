const form = document.querySelector("#chat-form");
const input = document.querySelector("#question");
const messages = document.querySelector("#messages");
const knowledge = document.querySelector("#knowledge");
const statusBadge = document.querySelector("#status");

function appendMessage(role, text, meta = "") {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const body = document.createElement("p");
  body.textContent = text;
  article.appendChild(body);

  if (meta) {
    const metaNode = document.createElement("div");
    metaNode.className = "meta";
    metaNode.textContent = meta;
    article.appendChild(metaNode);
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) return;

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
  const sources = data.sources.map((source) => source.title).join("、") || "无匹配来源";
  appendMessage("assistant", data.answer, `工具：${data.tool} | 来源：${sources}`);
});

loadKnowledge();
