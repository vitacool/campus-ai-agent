const list = document.querySelector("#admin-list");
const form = document.querySelector("#knowledge-form");
const message = document.querySelector("#admin-message");
const idInput = document.querySelector("#item-id");
const titleInput = document.querySelector("#item-title");
const categoryInput = document.querySelector("#item-category");
const contentInput = document.querySelector("#item-content");
const keywordsInput = document.querySelector("#item-keywords");
const resetButton = document.querySelector("#reset-form");

let items = [];
let editingId = null;

function getPayload() {
  return {
    id: idInput.value.trim(),
    title: titleInput.value.trim(),
    category: categoryInput.value.trim(),
    content: contentInput.value.trim(),
    keywords: keywordsInput.value
      .split(",")
      .map((keyword) => keyword.trim())
      .filter(Boolean),
  };
}

function setForm(item = null) {
  editingId = item?.id || null;
  idInput.value = item?.id || "";
  idInput.disabled = Boolean(item);
  titleInput.value = item?.title || "";
  categoryInput.value = item?.category || "";
  contentInput.value = item?.content || "";
  keywordsInput.value = item?.keywords?.join(", ") || "";
  message.textContent = item ? `正在编辑：${item.title}` : "";
}

async function loadItems() {
  const response = await fetch("/api/knowledge");
  items = await response.json();
  renderList();
}

function renderList() {
  list.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement("article");
    node.className = "admin-item";
    node.innerHTML = `
      <div>
        <strong>${item.title}</strong>
        <span>${item.category} · ${item.id}</span>
      </div>
      <p>${item.content}</p>
      <div class="admin-actions">
        <button type="button" data-action="edit" data-id="${item.id}">编辑</button>
        <button type="button" data-action="delete" data-id="${item.id}">删除</button>
      </div>
    `;
    list.appendChild(node);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = getPayload();
  const response = await fetch(editingId ? `/api/knowledge/${editingId}` : "/api/knowledge", {
    method: editingId ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(editingId ? { ...payload, id: undefined } : payload),
  });

  if (!response.ok) {
    const error = await response.json();
    message.textContent = error.detail || "保存失败";
    return;
  }

  setForm();
  message.textContent = "保存成功，向量索引已重建";
  await loadItems();
});

list.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  const item = items.find((row) => row.id === button.dataset.id);
  if (button.dataset.action === "edit" && item) {
    setForm(item);
  }

  if (button.dataset.action === "delete" && item) {
    await fetch(`/api/knowledge/${item.id}`, { method: "DELETE" });
    if (editingId === item.id) setForm();
    message.textContent = "已删除，向量索引已重建";
    await loadItems();
  }
});

resetButton.addEventListener("click", () => setForm());
loadItems();
