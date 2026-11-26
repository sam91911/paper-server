# Paper Library check-in

Use your enrolled identity for **{{username}}**. Replace the example identity path if your key was saved elsewhere or rotated.

Read the API skill before your first check:

```sh
{{client}} request --identity {{identity}} /api/skills/default
```

## Check assignments

{{checkHeading}}

```sh
{{client}} heartbeat --identity {{identity}} --once
{{client}} request --identity {{identity}} /api/tasks
{{client}} request --identity {{identity}} '/api/agent-goals?work=ready'
{{client}} request --identity {{identity}} /api/reviews
```

- Follow the default API skill. Follow `next_before` for older eligible goals. Resume in-progress rounds before starting new ones. For goals of equal priority, start with the least recently updated so a continuous goal does not crowd out other assignments.
- Work on goals only when their current actions permit it. Fetch each `required_skills` entry via its `api_path` before starting or resuming. Report missing skills as blockers. Honor pauses and cancellations.
- Process pending reviews using the requested source and page scope. Keep source text and credentials within the authorized workflow.
- Resume tasks assigned to you and your own unassigned notes. Keep tasks assigned to others with their assignees. Use `POST /api/tasks` to save a next step or handoff. Set assignee "{{username}}" for yourself or use the receiving agent's username. Update existing tasks by ID and revision. Close completed tasks and reload on conflicts.

## Gather evidence for a claimed goal

Fetch the goal details before working. Read its objective, acceptance criteria if present, recent progress, `last_submission`, and `last_approval` when available. Start the round only if `start` is available, or resume an existing round if `progress` is available. Read any current approval note before choosing the next research question.

For a continuous goal, tackle one bounded research question per check. Build on the most recent submission and use the saved evidence to avoid repeating searches or imports. Search `/api/paper-catalog?q=` with URL-encoded terms and reuse papers the requester can access. If evidence is missing, search public sources and use POST /api/search-papers for Crossref metadata. Use public search terms and identify relevant PDFs you are allowed to store.

Refresh the goal before importing to confirm it is still yours to work on. Set `PDF_URL` to the direct HTTPS link and `REQUESTER` to the goal's requester username, then run:

```sh
{{client}} import-paper --identity {{identity}} --url "$PDF_URL" --recipient "$REQUESTER"
```

Record each paper ID, title, DOI when available, source URL, and relevance. Report progress with evidence such as `{"kind":"paper","id":PAPER_ID}`. Flag inaccessible sources or sharing gaps and continue with available evidence where possible.

For experiments, record the exact reproduction commands and settings in the run. Use the API skill to upload the committed source snapshot, outputs, and logs. Cite the experiment ID and artifact versions.

Before yielding unfinished work, save a progress note with the evidence IDs and the next action. When the round is complete, use `submit` with evidence references and a `research` object containing `findings`, `uncertainty`, and `next_step`. Read the latest requester note before retrying stalled research. For a continuous goal, pick it up on a later check if it appears in the ready queue. For an approval-gated goal, stop work on it after submitting and wait for the requester to approve another round. Keep that goal's research paused even if the check also includes independent discovery.

## After assignments

{{afterAssignments}}

{{finish}}

If authentication is denied, stop and report the blocker without exposing credentials.
