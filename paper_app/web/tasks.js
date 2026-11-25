"use strict";

const taskElement = id => document.getElementById(id);
const taskStatus = taskElement("task-status");
const taskForm = taskElement("task-editor");
const taskFilter = taskElement("task-filter");
const taskStatusLabels = {open: "Open", in_progress: "In progress", closed: "Closed"};
let taskItems = [];
let editingTask;

function taskPart(parent, tag, content) {
  const item = document.createElement(tag);
  item.textContent = content;
  parent.append(item);
  return item;
}

function openTaskEditor(task) {
  editingTask = task;
  taskForm.reset();
  taskElement("task-details").disabled = Boolean(task && !task.can_manage);
  taskElement("task-editor-title").textContent = task ? `Edit task #${task.id}` : "New task";
  for (const name of ["title", "description", "assignee", "due_on", "issue_url", "status"]) {
    if (task) taskForm.elements[name].value = task[name] ?? "";
  }
  taskForm.hidden = false;
  (taskElement("task-details").disabled ? taskForm.elements.status : taskForm.elements.title).focus();
}

function renderTasks() {
  const list = taskElement("task-list");
  list.replaceChildren();
  const filter = taskFilter.value;
  const today = new Date();
  const localDate = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0")].join("-");
  for (const task of taskItems) {
    if (filter !== "all" && (task.status === "closed") !== (filter === "closed")) continue;
    const row = taskPart(list, "li", "");
    row.className = "task-card";
    const header = taskPart(row, "div", "");
    header.className = "task-toolbar";
    taskPart(header, "h2", `#${task.id} ${task.title}`);
    const edit = taskPart(header, "button", "Edit");
    edit.className = "secondary";
    edit.setAttribute("aria-label", `Edit task #${task.id}`);
    edit.addEventListener("click", () => {
      if (!taskForm.querySelector("button").disabled) openTaskEditor(task);
    });
    taskPart(row, "p", `${taskStatusLabels[task.status]} · Created by ${task.creator} · ${task.assignee || "Unassigned"}`);
    if (task.due_on) {
      const overdue = task.status !== "closed" && task.due_on < localDate;
      const deadline = taskPart(row, "p", overdue ? "Overdue · " : "Due ");
      deadline.classList.toggle("task-overdue", overdue);
      taskPart(deadline, "time", task.due_on).dateTime = task.due_on;
    }
    if (task.description) taskPart(row, "p", task.description).className = "task-description";
    if (task.issue_url) taskPart(row, "a", "View GitHub issue").href = task.issue_url;
  }
  if (!list.children.length) taskPart(list, "li", "No tasks match this view.");
}

async function loadTasks() {
  ({tasks: taskItems} = await api("tasks"));
  renderTasks();
}

taskFilter.addEventListener("change", renderTasks);
taskElement("new-task").addEventListener("click", () => openTaskEditor());
taskElement("cancel-task").addEventListener("click", () => { taskForm.hidden = true; });
taskForm.addEventListener("submit", async event => {
  event.preventDefault();
  const fields = taskForm.elements;
  const data = {id: editingTask?.id, revision: editingTask?.revision, status: fields.status.value};
  if (!taskElement("task-details").disabled) {
    Object.assign(data, {title: fields.title.value, description: fields.description.value,
      assignee: fields.assignee.value.trim() || null, due_on: fields.due_on.value || null,
      issue_url: fields.issue_url.value.trim() || null});
  }
  const submit = taskForm.querySelector("button");
  taskElement("new-task").disabled = true;
  submit.disabled = true;
  try {
    await api("tasks", data);
    taskForm.hidden = true;
    if (taskFilter.value !== "all") taskFilter.value = data.status === "closed" ? "closed" : "";
    await loadTasks();
    taskStatus.textContent = "Task saved.";
  } catch (error) {
    taskStatus.textContent = error.message;
    if (error.status === 409) await loadTasks().catch(() => {});
  } finally {
    submit.disabled = false;
    taskElement("new-task").disabled = false;
  }
});

async function setupTasks() {
  const {account} = await api("account");
  taskElement("task-sign-in").hidden = Boolean(account);
  if (!account) return;
  await loadTasks();
  taskElement("task-workspace").hidden = false;
}

setupTasks().catch(error => { taskStatus.textContent = error.message; });
