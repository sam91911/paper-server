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
{{client}} request --identity {{identity}} /api/agent-goals
{{client}} request --identity {{identity}} /api/reviews
```

- Follow the default API skill. Resume active assignments before claiming new ones. Follow `next_before` for older unfinished goals.
- Work on goals only when their current actions permit it. Fetch each `required_skills` entry via its `api_path` before starting or resuming. Report missing skills as blockers. Honor pauses and cancellations. Record progress and cite evidence IDs before submitting.
- Process pending reviews using the requested source and page scope. Keep source text and credentials within the authorized workflow.
- Resume tasks assigned to you and your own unassigned notes. Keep tasks assigned to others with their assignees. Use `POST /api/tasks` to save a next step or handoff. Set assignee "{{username}}" for yourself or use the receiving agent's username. Update existing tasks by ID and revision. Close completed tasks and reload on conflicts.

## Gather evidence for a claimed goal

Start with its objective, acceptance criteria, and latest progress. Search `/api/paper-catalog?q=` with URL-encoded terms and reuse papers the requester can access. If evidence is missing, search public sources and use POST /api/search-papers for Crossref metadata. Use public search terms and identify relevant PDFs you are allowed to store.

Refresh the goal before importing to confirm it is still yours to work on. Set `PDF_URL` to the direct HTTPS link and `REQUESTER` to the goal's requester username, then run:

```sh
{{client}} import-paper --identity {{identity}} --url "$PDF_URL" --recipient "$REQUESTER"
```

Record each paper ID, title, DOI when available, source URL, and relevance. Report progress with evidence such as `{"kind":"paper","id":PAPER_ID}`. Flag inaccessible sources or sharing gaps and continue with available evidence where possible.

For experiments, record the exact reproduction commands and settings in the run. Use the API skill to upload the committed source snapshot, outputs, and logs. Cite the experiment ID and artifact versions.

## After assignments

{{afterAssignments}}

{{finish}}

If authentication is denied, stop and report the blocker without exposing credentials.
