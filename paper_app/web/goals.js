"use strict";

const goalPanel = element("research-goals");
const goalProposal = element("goal-proposal-form");
const goalStatus = element("goal-status");
const goalList = element("goal-list");
let goalDocumentId = null;
let goalLoadSequence = 0;
let goalLoading = false;

function selectGoalDocument(item) {
  goalDocumentId = item?.id ?? null;
  goalLoadSequence++;
  goalLoading = false;
  goalPanel.open = false;
  goalPanel.hidden = !item;
  goalList.replaceChildren();
  element("goal-evidence-options").replaceChildren();
  goalProposal.reset();
  goalStatus.textContent = "";
}

function goalButton(parent, label, handler) {
  const button = add(parent, "button", label, "secondary");
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

function goalField(form, name, label, tag = "textarea", value = "") {
  const node = add(add(form, "label", label), tag);
  node.name = name;
  node.required = true;
  node.value = value;
  if (tag === "textarea") {
    node.maxLength = 4000;
    node.rows = 2;
  }
  return node;
}

function goalForm(parent, label, handler) {
  const panel = add(parent, "details");
  add(panel, "summary", label);
  const form = add(panel, "form");
  submit(form, async () => {
    const id = goalDocumentId;
    const data = handler(form.elements);
    const response = await api("research-goals", {document_id: id, ...data});
    if (id === goalDocumentId) await loadGoalPanel(String(response.id));
  }, goalStatus);
  return form;
}

function findingOption(row) {
  return [row.id, `#${row.id} · ${row.statement.slice(0, 100)}`];
}

function goalFindingLink(parent, documentId, id, label = `Finding #${id}`) {
  add(parent, "a", label).href = `/documents?document=${documentId}&finding=${id}`;
}

function renderBriefForm(parent, goal, available, previous = null) {
  const design = previous?.stage === "design";
  const label = design ? "Revise design brief" : previous ? "Revise feasibility brief" : "Draft feasibility brief";
  const form = goalForm(parent, label, fields => ({
    action: design ? "revise_design" : "draft", goal_id: goal.id,
    brief_id: design ? previous.id : undefined, revision: goal.revision,
    baseline_id: Number(fields.baseline_id.value),
    approach: fields.approach.value, criterion: fields.criterion.value,
    conditions: fields.conditions.value, budget: fields.budget.value,
  }));
  goalField(form, "approach", "Approach", "textarea", previous?.approach);
  const baseline = goalField(form, "baseline_id", "Baseline finding", "select");
  setOptions(baseline, available.map(findingOption), "Choose a baseline");
  if (previous) baseline.value = String(previous.baseline_id);
  goalField(form, "criterion", "Success criterion", "textarea", previous?.criterion);
  const conditions = goalField(form, "conditions", "Measurement conditions", "textarea", previous?.conditions);
  baseline.addEventListener("change", () => {
    if (!conditions.value) conditions.value = available.find(row => row.id === Number(baseline.value))?.conditions ?? "";
  });
  goalField(form, "budget", "Time or resource budget", "textarea", design?.budget);
  add(form, "button", "Save draft");
}

function renderDecisionForm(parent, goal, brief, available) {
  const judged = new Set(brief.decisions.map(item => item.run_id));
  const runs = brief.runs.filter(run => ["complete", "failed"].includes(run.status) && !judged.has(run.id));
  const eligible = available.filter(row => row.kind === "run_result");
  if (!runs.length || !eligible.some(row => runs.some(run => row.run_ids.includes(run.id)))) {
    add(parent, "p", "Record a completed or failed run and cite its uploaded output in a run finding to review the result.");
    return;
  }
  const form = goalForm(parent, "Record a decision", fields => ({
    action: "decide", goal_id: goal.id, brief_id: brief.id, revision: goal.revision,
    run_id: Number(fields.run_id.value), result_id: Number(fields.result_id.value),
    outcome: fields.outcome.value, next_step: fields.next_step.value, rationale: fields.rationale.value,
  }));
  const run = goalField(form, "run_id", "Run", "select");
  setOptions(run, runs.map(row => [row.id, row.title]), "Choose a run");
  const result = goalField(form, "result_id", "Run result finding", "select");
  setOptions(result, [], "Choose a run first");
  run.addEventListener("change", () => {
    setOptions(result, eligible.filter(row => row.run_ids.includes(Number(run.value))).map(findingOption), "Choose a result");
  });
  const outcome = goalField(form, "outcome", "Outcome", "select");
  setOptions(outcome, [["met", "Met the criterion"], ["missed", "Missed under the tested conditions"],
    ["inconclusive", "Inconclusive"]], "Choose an outcome");
  const next = goalField(form, "next_step", "Next step", "select");
  const choices = [["iterate", "Revise and test again"], ["set_aside", "Set aside"]];
  if (brief.stage === "feasibility") choices.splice(1, 0, ["design", "Move to full design"]);
  setOptions(next, choices, "Choose a next step");
  goalField(form, "rationale", "Reason for the decision");
  add(form, "button", "Save decision");
}

const outcomeLabels = {met: "Met the criterion", missed: "Missed under the tested conditions", inconclusive: "Inconclusive"};
const nextLabels = {iterate: "Revise and test again", design: "Move to full design", set_aside: "Set aside"};

function renderGoalDecision(parent, goal, decision) {
  const record = add(parent, "article", undefined, "paper-comment");
  record.id = `goal-decision-${decision.id}`;
  add(record, "strong", `Run #${decision.run_id} · ${outcomeLabels[decision.outcome]} · ${nextLabels[decision.next_step]}`);
  add(record, "p", `${decision.author_name} · ${decision.created} UTC`, "comment-time");
  add(record, "p", decision.rationale, "comment-body");
  const evidence = decision.evidence;
  const measurements = [evidence.baseline, evidence.result].filter(row => row.value)
    .map(row => `${row.metric} ${row.value} ${row.unit} (${row.conditions})`);
  if (measurements.length) add(record, "p", measurements.join(" · "));
  if (evidence.comparison.difference !== null) {
    const unit = evidence.result.unit === "%" ? "percentage points" : evidence.result.unit;
    add(record, "p", `Absolute difference: ${evidence.comparison.difference} ${unit}`);
  }
  if (evidence.comparison.reasons.length) add(record, "p", evidence.comparison.reasons.join(" "));
  const run = add(record, "details");
  add(run, "summary", `Run record at revision ${evidence.run.revision}`);
  if (evidence.run.methods) add(run, "p", `Methods — ${evidence.run.methods}`, "comment-body");
  if (evidence.run.settings) add(run, "p", `Settings — ${evidence.run.settings}`, "comment-body");
  goalFindingLink(add(record, "p"), goal.document_id, decision.result_id, "Result finding");
  for (const ref of evidence.artifacts) {
    add(add(record, "p"), "a", `Download artifact version #${ref.id}`).href = `/research-versions/${ref.id}/file`;
  }
}

function renderGoalBrief(parent, goal, brief, available, manager) {
  const panel = add(parent, "details");
  const name = brief.stage === "design" ? "Full design brief" : "Feasibility brief";
  add(panel, "summary", `${name} #${brief.id} · ${brief.confirmed ? "Confirmed" : "Draft"}`);
  panel.open = true;
  add(panel, "p", `Draft by ${brief.author_name} · ${roleLabels[brief.author_role]} · ${brief.created} UTC`);
  if (brief.confirmed) add(panel, "p", `Confirmed ${brief.confirmed} UTC`);
  const markdown = add(panel, "pre", brief.markdown);
  markdown.className = "goal-brief-text";
  goalFindingLink(panel, goal.document_id, brief.baseline_id, "Open baseline finding");
  if (brief.origin_decision_id) {
    add(add(panel, "p"), "a", "Review the supporting feasibility decision").href =
      `#goal-decision-${brief.origin_decision_id}`;
  }
  goalButton(panel, "Copy brief", async () => {
    const doc = goalDocumentId;
    try {
      const fresh = await api(`research-goals?document_id=${doc}`);
      if (doc !== goalDocumentId) return;
      const source = fresh.goals.find(row => row.id === goal.id)?.briefs.find(row => row.id === brief.id);
      if (!source) {
        await loadGoalPanel();
        throw new Error("This brief is unavailable.");
      }
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(source.markdown);
          goalStatus.textContent = "Brief copied.";
          return;
        } catch {
          // The selected text below supports browsers without clipboard access.
        }
      }
      const manual = add(panel, "textarea");
      manual.setAttribute("aria-label", "Markdown brief");
      manual.readOnly = true;
      manual.value = source.markdown;
      manual.select();
      goalStatus.textContent = "Copy the selected Markdown.";
    } catch (error) {
      goalStatus.textContent = error.message;
    }
  });
  if (brief.experiment_id) {
    add(add(panel, "p"), "a", "Open linked experiment").href = `/experiments?id=${brief.experiment_id}`;
    for (const decision of brief.decisions) renderGoalDecision(panel, goal, decision);
    if (manager) renderDecisionForm(panel, goal, brief, available);
  } else if (manager && goal.selected) {
    const form = goalForm(panel, "Confirm brief", () => ({
      action: "confirm", goal_id: goal.id, brief_id: brief.id, revision: goal.revision,
    }));
    add(form, "button", "Confirm and create experiment");
  }
  if (goal.selected && (brief.stage === "feasibility" || manager)) {
    renderBriefForm(panel, goal, available, brief);
  }
}

function renderGoal(goal, available, manager) {
  const card = add(goalList, "article", undefined, "paper-comment");
  card.id = `goal-${goal.id}`;
  const heading = add(card, "h3", goal.question);
  heading.tabIndex = -1;
  add(card, "p", `${goal.author_name} · ${roleLabels[goal.author_role]} · ${goal.created} UTC`, "comment-time");
  add(card, "p", goal.selected ? "Selected" : goal.deferred ? "Set aside" : "Candidate");
  add(card, "h4", "Why it matters now");
  add(card, "p", goal.rationale, "comment-body");
  add(card, "h4", "Uncertainty to resolve");
  add(card, "p", goal.uncertainty, "comment-body");
  const evidence = add(card, "ul");
  for (const id of goal.evidence_ids) {
    const label = available.find(row => row.id === id)?.statement.slice(0, 100);
    goalFindingLink(add(evidence, "li"), goal.document_id, id, label);
  }
  goalButton(card, "Discuss goal", () => {
    element("document-discussion").open = true;
    setDocumentReply(null, null, goal.id);
    documentCommentForm.elements.body.focus();
  });
  if (manager) {
    const form = goalForm(card, "Set priority", fields => ({
      action: "rank", goal_id: goal.id, revision: goal.revision,
      priority: Number(fields.priority.value), selected: fields.selected.checked,
    }));
    const priority = goalField(form, "priority", "Priority (1 is highest)", "input");
    priority.type = "number";
    priority.min = "1";
    priority.max = "1000000";
    priority.value = goal.priority ?? "";
    const selected = goalField(form, "selected", "Selected for testing", "input");
    selected.type = "checkbox";
    selected.required = false;
    selected.checked = Boolean(goal.selected);
    add(form, "button", "Save priority");
    if (goal.priority_history.length) {
      const history = add(card, "details");
      add(history, "summary", "Priority history");
      const rows = add(history, "ul");
      for (const change of goal.priority_history) {
        add(rows, "li", `Priority ${change.priority} · ${change.selected ? "Selected" : "Candidate"} · ${change.created} UTC`);
      }
    }
  }
  if (goal.selected) renderBriefForm(card, goal, available);
  for (const brief of goal.briefs) renderGoalBrief(card, goal, brief, available, manager);
  return heading;
}

async function loadGoalPanel(requested = null) {
  const id = goalDocumentId;
  if (id === null) return;
  const sequence = ++goalLoadSequence;
  const current = () => goalLoadSequence === sequence && goalDocumentId === id;
  goalLoading = true;
  goalStatus.textContent = "Loading research goals…";
  try {
    const response = await api(`research-goals?document_id=${id}`);
    if (!current()) return;
    const evidence = element("goal-evidence-options");
    const chosen = new Set([...goalProposal.querySelectorAll("input[name=evidence]:checked")].map(input => input.value));
    evidence.replaceChildren();
    for (const row of response.findings) {
      const label = add(evidence, "label");
      const input = add(label, "input");
      input.type = "checkbox";
      input.name = "evidence";
      input.value = row.id;
      input.checked = chosen.has(input.value);
      label.append(` ${findingOption(row)[1]}`);
    }
    if (!response.findings.length) {
      goalButton(evidence, "Add a supporting finding", () => globalThis.showRequestedResearch?.());
    }
    goalList.replaceChildren();
    let target;
    for (const goal of response.goals) {
      const heading = renderGoal(goal, response.findings, response.can_manage);
      if (String(goal.id) === requested) target = heading;
    }
    goalStatus.textContent = requested && !target ? "This goal is unavailable."
      : response.goals.length ? "" : "No goals proposed yet.";
    target?.focus();
  } catch (error) {
    if (!current()) return;
    goalList.replaceChildren();
    element("goal-evidence-options").replaceChildren();
    goalStatus.textContent = error.message;
  } finally {
    if (current()) goalLoading = false;
  }
}

async function showRequestedGoal(goalId) {
  goalPanel.open = true;
  await loadGoalPanel(goalId);
}

goalPanel.addEventListener("toggle", () => {
  if (goalPanel.open && !goalLoading) loadGoalPanel();
});
submit(goalProposal, async () => {
  const id = goalDocumentId;
  const fields = goalProposal.elements;
  const evidence = [...goalProposal.querySelectorAll("input[name=evidence]:checked")].map(input => Number(input.value));
  const response = await api("research-goals", {action: "propose", document_id: id,
    question: fields.question.value, rationale: fields.rationale.value, uncertainty: fields.uncertainty.value,
    evidence_ids: evidence,
  });
  if (id !== goalDocumentId) return;
  goalProposal.reset();
  element("goal-proposal").open = false;
  await loadGoalPanel(String(response.id));
}, goalStatus);
