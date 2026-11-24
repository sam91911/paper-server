"use strict";

const element = id => document.getElementById(id);
const status = element("agent-goal-status");
const createForm = element("set-agent-goal");
const actionForm = element("agent-goal-action");
const list = element("agent-goal-list");
const historyList = element("agent-goal-history");
const moreGoals = element("more-agent-goals");
const moreEvents = element("more-agent-goal-events");
const labels = {
  assigned: "Assigned", in_progress: "In progress", blocked: "Blocked", paused: "Paused",
  submitted: "Submitted", completed: "Completed", canceled: "Canceled",
  create: "Assigned goal", start: "Start or resume work", progress: "Record progress", block: "Report blocker",
  submit: "Submit result", pause: "Pause", resume: "Resume", request_changes: "Request changes",
  accept: "Accept result", cancel: "Cancel goal",
};

let activeGoal, goalCursor, eventCursor, pending, busy;

function add(parent, tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  parent.append(node);
  return node;
}

function references(value) {
  return value.split("\n").map(line => line.trim()).filter(Boolean).map(line => {
    const match = /^([a-z_]+):([1-9][0-9]*)$/.exec(line);
    if (!match || !Number.isSafeInteger(Number(match[2]))) throw new Error("Enter workspace references as type:ID.");
    return {kind: match[1], id: Number(match[2])};
  });
}

function addReferences(parent, references) {
  if (!references.length) return;
  const items = add(parent, "ul");
  for (const {kind, id, document_id, paper_id} of references) {
    const row = add(items, "li");
    const label = `${kind.replaceAll("_", " ")} #${id}`;
    const links = {
      document: `/documents?document=${id}`,
      paper: `/papers?paper=${id}`,
      experiment: `/experiments?id=${id}`,
      finding: `/documents?document=${document_id}&finding=${id}`,
      research_goal: `/documents?document=${document_id}&goal=${id}`,
      thread: document_id ? `/documents?document=${document_id}` : `/papers?paper=${paper_id}`,
    };
    add(row, "a", label).href = links[kind];
  }
}

async function run(operation) {
  if (busy) return;
  busy = true;
  status.textContent = "";
  try {
    await operation();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    busy = false;
  }
}

async function post(payload) {
  const serialized = JSON.stringify(payload);
  if (pending?.serialized !== serialized) pending = {serialized, id: crypto.randomUUID()};
  const result = await api("agent-goals", {...payload, request_id: pending.id});
  pending = undefined;
  return result;
}

async function loadList(before) {
  const {goals, next_before} = await api(before ? `agent-goals?before=${before}` : "agent-goals");
  if (!before) list.replaceChildren();
  if (!goals.length && !before) add(list, "li", "No goals yet.");
  for (const goal of goals) {
    const row = add(list, "li");
    const label = goal.source_unavailable ? `Goal #${goal.id} · Source unavailable` : goal.objective.slice(0, 160);
    const link = add(row, "a", label);
    link.href = `/agent-goals?id=${goal.id}`;
    link.addEventListener("click", event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      run(() => openGoal(goal.id, true));
    });
    add(row, "p", `${labels[goal.status]} · ${goal.agent} (${goal.agent_role})`);
  }
  goalCursor = next_before;
  moreGoals.hidden = goalCursor === null;
}

function showEvents(events, nextBefore, append = false) {
  if (!append) historyList.replaceChildren();
  for (const event of events) {
    const row = add(historyList, "li");
    add(row, "strong", labels[event.action]);
    add(row, "p", `${event.actor} · ${new Date(event.created * 1000).toLocaleString()}`);
    if (event.redacted) add(row, "p", "Evidence access was withdrawn.");
    if (event.note) add(row, "p", event.note, "goal-brief-text");
    addReferences(row, event.evidence);
  }
  eventCursor = nextBefore;
  moreEvents.hidden = eventCursor === null;
}

function showGoal({goal, events, next_before}) {
  activeGoal = goal;
  element("agent-goal-detail").hidden = false;
  const title = element("agent-goal-title");
  title.textContent = `Goal #${goal.id}`;
  element("agent-goal-summary").textContent = `${labels[goal.status]} · Assigned to ${goal.agent} (${goal.agent_role}) by ${goal.requester}`;
  const content = element("agent-goal-content");
  content.replaceChildren();
  if (goal.source_unavailable) {
    add(content, "p", "The assignment’s sources or agent are unavailable.");
  } else {
    add(content, "h3", "Objective");
    add(content, "p", goal.objective, "goal-brief-text");
    add(content, "h3", "Acceptance criteria");
    add(content, "p", goal.acceptance_criteria, "goal-brief-text");
    if (goal.sources.length) add(content, "h3", "Shared sources");
    addReferences(content, goal.sources);
  }
  actionForm.hidden = goal.actions.length === 0;
  const action = actionForm.elements.action;
  action.replaceChildren();
  for (const value of goal.actions) add(action, "option", labels[value]).value = value;
  showEvents(events, next_before);
}

async function openGoal(id, focus = false) {
  showGoal(await api(`agent-goals?id=${id}`));
  history.replaceState(null, "", `/agent-goals?id=${id}`);
  if (focus) element("agent-goal-title").focus();
}

createForm.addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const {agent, objective, acceptance_criteria, sources} = createForm.elements;
    const result = await post({action: "create", agent: agent.value, objective: objective.value,
      acceptance_criteria: acceptance_criteria.value, sources: references(sources.value)});
    createForm.reset();
    showGoal(result);
    history.replaceState(null, "", `/agent-goals?id=${result.goal.id}`);
    await loadList();
    status.textContent = "Goal assigned.";
  });
});

actionForm.addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const {action, note, evidence} = actionForm.elements;
    const result = await post({id: activeGoal.id, revision: activeGoal.revision, action: action.value,
      note: note.value, evidence: references(evidence.value)});
    note.value = "";
    evidence.value = "";
    showGoal(result);
    await loadList();
    status.textContent = "Goal updated.";
  });
});

element("refresh-agent-goals").addEventListener("click", () => run(async () => {
  await loadList();
  if (activeGoal) await openGoal(activeGoal.id);
}));
moreGoals.addEventListener("click", () => run(() => loadList(goalCursor)));
moreEvents.addEventListener("click", () => run(async () => {
  const result = await api(`agent-goals?id=${activeGoal.id}&before=${eventCursor}`);
  showEvents(result.events, result.next_before, true);
}));

run(async () => {
  const {account} = await api("account");
  if (!account) {
    element("agent-goal-sign-in").hidden = false;
    return;
  }
  const params = new URLSearchParams(location.search);
  const panel = element("set-goal-panel");
  panel.hidden = !["user", "member"].includes(account.role);
  element("agent-goal-workspace").hidden = false;
  const researchGoal = Number(params.get("research_goal"));
  if (!panel.hidden && Number.isSafeInteger(researchGoal) && researchGoal > 0) {
    panel.open = true;
    createForm.elements.sources.value = `research_goal:${researchGoal}`;
  }
  await loadList();
  const id = Number(params.get("id"));
  if (Number.isSafeInteger(id) && id > 0) await openGoal(id);
});
