"use strict";

const element = id => document.getElementById(id);
const status = element("agent-goal-status");
const createForm = element("set-agent-goal");
const actionForm = element("agent-goal-action");
const list = element("agent-goal-list");
const historyList = element("agent-goal-history");
const moreGoals = element("more-agent-goals");
const moreEvents = element("more-agent-goal-events");
const agentSearch = element("find-goal-agent");
const agentMatches = element("goal-agent-matches");
const setGoalPanel = element("set-goal-panel");
const attentionOnly = element("goal-attention-only");
const scheduleForm = element("agent-schedules");
const researchFields = element("agent-research-fields");
let schedules = [];
const labels = {
  assigned: "Assigned", in_progress: "In progress", blocked: "Blocked", paused: "Paused",
  submitted: "Submitted", completed: "Completed", canceled: "Canceled",
  create: "Created goal", start: "Start or resume work", progress: "Record progress", block: "Report blocker",
  submit: "Submit result", pause: "Pause", resume: "Resume", request_changes: "Request changes",
  accept: "Accept result", release: "Release claim", cancel: "Cancel goal",
  approve: "Approve next round", finish: "Finish goal", retry: "Retry stalled research",
};

let activeGoal, goalCursor, eventCursor, pending, busy;

function agentNames(value) {
  return value.split(/[\n,]+/).map(name => name.trim()).filter(Boolean);
}

function addSearchedAgent() {
  const value = agentSearch.value.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{1,31}$/.test(value)) return;
  const allowlist = createForm.elements.agents;
  const names = agentNames(allowlist.value);
  if (!names.some(name => name.toLowerCase() === value.toLowerCase())) allowlist.value = [...names, value].join("\n");
  agentSearch.value = "";
}

element("add-goal-agent").addEventListener("click", addSearchedAgent);
agentSearch.addEventListener("keydown", event => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  addSearchedAgent();
});

function add(parent, tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  parent.append(node);
  return node;
}

function goalStatus(goal) {
  let state = goal.status === "assigned" ? "Ready" : labels[goal.status];
  if (goal.attention === "stalled") state = "Needs research direction";
  else if (goal.attention === "approval" || (goal.require_approval && goal.status === "submitted")) state = "Awaiting approval";
  else if (goal.status === "submitted") state = "Awaiting review";
  return `${state} · ${goal.agent ? `Claimed by ${goal.agent} (${goal.agent_role})` : "Unclaimed"}`;
}

function markSelectedGoal() {
  for (const link of list.querySelectorAll("[data-goal-id]")) {
    if (link.dataset.goalId === String(activeGoal?.id)) link.setAttribute("aria-current", "true");
    else link.removeAttribute("aria-current");
  }
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
  const params = new URLSearchParams();
  if (before) params.set("before", before);
  if (attentionOnly.checked) params.set("work", "attention");
  const {goals, next_before, assignable_agents} = await api(`agent-goals?${params}`);
  if (!before) {
    list.replaceChildren();
    agentMatches.replaceChildren();
    for (const username of assignable_agents) add(agentMatches, "option").value = username;
    setGoalPanel.hidden = assignable_agents.length === 0;
  }
  if (!goals.length && !before) add(list, "li", attentionOnly.checked ? "No goals need review." : "No goals yet.");
  for (const goal of goals) {
    const row = add(list, "li");
    const label = goal.source_unavailable ? `Goal #${goal.id} · Source unavailable` : goal.objective.slice(0, 160);
    const link = add(row, "a", label);
    link.href = `/agent-goals?id=${goal.id}`;
    link.dataset.goalId = String(goal.id);
    link.addEventListener("click", event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      run(() => openGoal(goal.id, true));
    });
    const state = add(row, "p", goalStatus(goal), "goal-list-status");
    state.dataset.status = goal.status;
  }
  markSelectedGoal();
  goalCursor = next_before;
  moreGoals.hidden = goalCursor === null;
}

function showResearch(parent, event) {
  if (event.redacted) add(parent, "p", "Evidence is unavailable to this account.");
  if (event.research) {
    for (const [key, label] of [["findings", "Findings"], ["uncertainty", "Uncertainty"], ["next_step", "Next step"]]) {
      if (event.research[key]) {
        add(parent, "strong", label);
        add(parent, "p", event.research[key], "goal-brief-text");
      }
    }
  }
  if (event.note && event.note !== event.research?.findings) add(parent, "p", event.note, "goal-brief-text");
  addReferences(parent, event.evidence);
}

function updateResearchFields() {
  const enabled = actionForm.elements.action.value === "submit" && activeGoal?.continuous;
  researchFields.hidden = !enabled;
  researchFields.disabled = !enabled;
}

function showEvents(events, nextBefore, append = false) {
  if (!append) historyList.replaceChildren();
  for (const event of events) {
    const row = add(historyList, "li");
    add(row, "strong", labels[event.action]);
    add(row, "p", `${event.actor} · ${new Date(event.created * 1000).toLocaleString()}`);
    showResearch(row, event);
  }
  eventCursor = nextBefore;
  moreEvents.hidden = eventCursor === null;
}

function showGoal({goal, events, next_before, last_submission}) {
  activeGoal = goal;
  element("agent-goal-empty").hidden = true;
  element("agent-goal-detail").hidden = false;
  element("goal-browse-controls").open = false;
  markSelectedGoal();
  const title = element("agent-goal-title");
  title.textContent = `Goal #${goal.id}`;
  element("agent-goal-summary").textContent = `${goalStatus(goal)} · Set by ${goal.requester}`;
  const content = element("agent-goal-content");
  content.replaceChildren();
  add(content, "h3", "AI allowlist");
  add(content, "p", goal.agents.join(", "));
  if (goal.continuous) add(content, "p", "Continuous goal");
  if (goal.require_approval) add(content, "p", "Approval required before each round");
  if (goal.source_unavailable) {
    add(content, "p", "The goal’s sources or allowlisted accounts are unavailable.");
  } else {
    add(content, "h3", "Objective");
    add(content, "p", goal.objective, "goal-brief-text");
    if (goal.acceptance_criteria) {
      add(content, "h3", "Acceptance criteria");
      add(content, "p", goal.acceptance_criteria, "goal-brief-text");
    }
    if (goal.required_skills.length) {
      add(content, "h3", "Required skills");
      const skills = add(content, "ul");
      for (const skill of goal.required_skills) {
        add(add(skills, "li"), "a", skill.title).href = `/skills?skill=${skill.id}`;
      }
    }
    if (goal.sources.length) add(content, "h3", "Shared sources");
    addReferences(content, goal.sources);
  }
  const latestRound = element("agent-latest-round");
  const submission = last_submission || events.find(event => event.action === "submit");
  latestRound.replaceChildren();
  latestRound.hidden = !submission;
  if (submission) {
    add(latestRound, "h3", "Latest research submission");
    showResearch(latestRound, submission);
  }
  if (goal.attention === "stalled") {
    add(content, "p", "The agent reported the same blocker repeatedly or submitted rounds without new evidence. Add research direction before retrying.");
  }
  actionForm.hidden = goal.actions.length === 0;
  const action = actionForm.elements.action;
  action.replaceChildren();
  for (const value of goal.actions) add(action, "option", labels[value]).value = value;
  updateResearchFields();
  showEvents(events, next_before);
}

async function openGoal(id, focus = false) {
  showGoal(await api(`agent-goals?id=${id}`));
  history.replaceState(null, "", `/agent-goals?id=${id}`);
  if (focus) element("agent-goal-title").focus();
}

createForm.elements.continuous.addEventListener("change", () => {
  createForm.elements.acceptance_criteria.required = !createForm.elements.continuous.checked;
});

createForm.addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const {agents, objective, acceptance_criteria, sources, required_skills, continuous, require_approval} = createForm.elements;
    const usernames = agentNames(agents.value);
    const skillIds = agentNames(required_skills.value).map(value => {
      const id = Number(value);
      if (!/^[1-9][0-9]*$/.test(value) || !Number.isSafeInteger(id)) throw new Error("Enter positive skill IDs.");
      return id;
    });
    const result = await post({action: "create", agents: usernames, objective: objective.value,
      continuous: continuous.checked, require_approval: require_approval.checked,
      acceptance_criteria: acceptance_criteria.value, sources: references(sources.value), required_skill_ids: skillIds});
    createForm.reset();
    acceptance_criteria.required = true;
    showGoal(result);
    history.replaceState(null, "", `/agent-goals?id=${result.goal.id}`);
    await loadList();
    status.textContent = "Goal saved.";
  });
});

actionForm.addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const {action, note, evidence} = actionForm.elements;
    const payload = {id: activeGoal.id, revision: activeGoal.revision, action: action.value,
      note: note.value, evidence: references(evidence.value)};
    if (!researchFields.disabled) {
      const research = Object.fromEntries(["findings", "uncertainty", "next_step"].map(key => [key, actionForm.elements[key].value.trim()]));
      if (Object.values(research).some(Boolean)) {
        payload.research = research;
        if (!payload.note.trim()) delete payload.note;
      }
    }
    const result = await post(payload);
    actionForm.reset();
    showGoal(result);
    await loadList();
    status.textContent = "Goal updated.";
  });
});

actionForm.elements.action.addEventListener("change", updateResearchFields);
attentionOnly.addEventListener("change", () => run(() => loadList()));

function showSchedule() {
  const schedule = schedules.find(item => item.agent === scheduleForm.elements.agent.value);
  if (!schedule) return;
  scheduleForm.elements.interval.value = schedule.interval_seconds;
  const format = stamp => new Date(stamp * 1000).toLocaleString();
  element("agent-schedule-summary").textContent = `Next due ${schedule.next_run ? format(schedule.next_run) : "—"} · Consecutive failures ${schedule.failures}`;
  const history = element("agent-schedule-runs");
  history.replaceChildren();
  for (const execution of schedule.runs) {
    const state = execution.finished === null
      ? (execution.deadline * 1000 <= Date.now() ? "Completion overdue" : "Running")
      : (execution.success ? "Succeeded" : "Failed");
    const row = add(history, "li", `${state} · ${format(execution.started)}`);
    if (execution.detail) add(row, "p", execution.detail);
  }
  if (!schedule.runs.length) add(history, "li", "No executions yet.");
}

function setSchedules(result) {
  schedules = result.schedules;
  const picker = scheduleForm.elements.agent;
  const selected = picker.value;
  picker.replaceChildren();
  for (const schedule of schedules) add(picker, "option", schedule.agent).value = schedule.agent;
  if (schedules.some(item => item.agent === selected)) picker.value = selected;
  element("agent-schedules-panel").hidden = schedules.length === 0;
  showSchedule();
}

scheduleForm.elements.agent.addEventListener("change", showSchedule);
scheduleForm.addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const action = event.submitter?.value || "configure";
    setSchedules(await api("agent-schedules", {action, agent: scheduleForm.elements.agent.value,
      interval_seconds: Number(scheduleForm.elements.interval.value)}));
    status.textContent = action === "run_now" ? "Run queued for the agent." : "Schedule saved.";
  });
});
element("refresh-agent-schedules").addEventListener("click", () => run(async () => {
  setSchedules(await api("agent-schedules"));
}));

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
  element("agent-goal-workspace").hidden = false;
  element("goal-attention-filter").hidden = !["user", "member"].includes(account.role);
  await loadList();
  if (account.role === "user") setSchedules(await api("agent-schedules"));
  const researchGoal = Number(params.get("research_goal"));
  if (!setGoalPanel.hidden && Number.isSafeInteger(researchGoal) && researchGoal > 0) {
    setGoalPanel.open = true;
    createForm.elements.sources.value = `research_goal:${researchGoal}`;
  }
  const id = Number(params.get("id"));
  if (Number.isSafeInteger(id) && id > 0) await openGoal(id);
});
