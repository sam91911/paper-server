"""Public HTTP operations for workstation-based research clients."""

from . import agent_goals, client_distribution, experiments
from .sharing import AUDIENCES


def schema(type_, **keywords):
    return {"type": type_, **keywords}


def obj(properties=None, required=()):
    result = schema("object")
    if properties:
        result["properties"] = properties
    if required:
        result["required"] = list(required)
    return result


def array(items):
    return schema("array", items=items)


def nullable(value):
    return {"anyOf": [value, schema("null")]}


def enum(*values):
    return schema("string", enum=list(values))


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def param(name, value, *, location="query", required=False, description=None):
    result = {"name": name, "in": location, "required": required, "schema": value}
    if description:
        result["description"] = description
    return result


def media(value, content_type="application/json"):
    return {"content": {content_type: {"schema": value}}}


def operation(summary, response, *, params=(), body=None, request_type="application/json",
              response_type="application/json", description=None, security=None):
    result = {
        "summary": summary,
        "responses": {"200": {"description": "Success", **media(response, response_type)}},
    }
    for code, message in (("400", "Invalid input"), ("401", "Sign in required"), ("403", "Access denied"),
                          ("404", "Resource unavailable"), ("409", "Conflict"), ("413", "Upload size or quota exceeded"),
                          ("415", "Unsupported media type"),
                          ("422", "PDF text extraction failed"), ("500", "Server error"), ("502", "Upstream service error")):
        result["responses"][code] = {"description": message, **media(ref("Error"))}
    if params:
        result["parameters"] = list(params)
    if body:
        result["requestBody"] = {"required": True, **media(body, request_type)}
    if description:
        result["description"] = description
    if security is not None:
        result["security"] = security
    return result


def acknowledgement(*required, **fields):
    return obj({"ok": schema("boolean", const=True), **fields}, ("ok", *required))


STRING = schema("string")
BOOLEAN = schema("boolean")
COUNT = schema("integer", minimum=0)
ID = schema("integer", format="int64", minimum=1)
SCHEDULE_TIME = nullable(schema("integer", minimum=0, maximum=253402300799,
                                description="Scheduled time in UTC seconds since the Unix epoch."))
VOTE = schema("integer", enum=[-1, 0, 1])
VOTE_FIELDS = {"vote_score": schema("integer"), "my_vote": VOTE}
AI_ROLE = enum("local", "cloud")
AI_NONCE = schema("string", pattern="^[A-Za-z0-9_-]{43}$")
AI_SIGNATURE = schema("string", pattern="^[A-Za-z0-9_-]{86}$",
                      description="64-byte Ed25519 signature in unpadded base64url.")
SIGNED_CHALLENGE = {"challenge": AI_NONCE, "signature": AI_SIGNATURE}
PUBLIC_KEY = {**AI_NONCE, "description": "32-byte Ed25519 public key in unpadded base64url."}
BINARY = schema("string", format="binary")
AUDIENCE = enum(*AUDIENCES)
RECIPIENTS = array(STRING)
GOAL_ACCESS_FIELDS = {"audience": enum("inherit", *AUDIENCES), "recipients": RECIPIENTS}
ID_LIST = array(ID)
AGENT_GOAL_REQUEST_ID = schema("string", pattern="^[A-Za-z0-9_-]{16,64}$")
AGENT_GOAL_STATUS = enum(*agent_goals.STATES)
AGENT_GOAL_ACTION = enum(*agent_goals.OWNER_ACTIONS, *agent_goals.AGENT_ACTIONS)
AGENT_GOAL_REFERENCES = schema("array", maxItems=20, items=obj(
    {"kind": enum(*agent_goals.SOURCE_KINDS), "id": ID,
     "document_id": {**ID, "readOnly": True}, "paper_id": {**ID, "readOnly": True}}, ("kind", "id")))
PAPER_ID = param("paper_id", ID, required=True)
DOCUMENT_ID = param("document_id", ID, required=True)
AFTER = param("after", COUNT, description="The previous response's next_after cursor.")
BEFORE = param("before", ID, description="The previous response's next_before cursor.")
METADATA = {field: STRING for field in ("doi", "title", "authors", "year", "venue", "publisher", "source")}
EXPERIMENT_FIELDS = {
    "id": ID, "revision": ID, "title": STRING, "description": STRING, "audience": AUDIENCE,
    "paper_id": nullable(ID), "research_document_id": nullable(ID),
    "source_commit": {**nullable(STRING), "readOnly": True},
}
REPRODUCTION_OUTCOME = enum(*experiments.REPRODUCTION_OUTCOMES)
REPRODUCTION_CHECK = {"run_revision": ID, "outcome": REPRODUCTION_OUTCOME,
                      "observed": schema("string", minLength=1, maxLength=10000)}
REPRODUCTION_RECORD = obj({
    "dependencies": schema("array", maxItems=100, items=schema("string", maxLength=512)),
    "inputs": schema("array", maxItems=100, items=obj({
        "name": schema("string", maxLength=512), "sha256": schema("string", pattern="^[A-Fa-f0-9]{64}$"),
    }, ("name", "sha256"))),
    "seed": schema("string", maxLength=200), "expected_output": schema("string", maxLength=10000),
})
RUN_FIELDS = {
    "id": ID, "revision": ID, "experiment_id": ID, "title": STRING, "description": STRING,
    "methods": STRING, "settings": STRING, "status": enum("planned", "running", "complete", "failed"),
    "audience": AUDIENCE, "reproduction": REPRODUCTION_RECORD,
}
ITEM_FIELDS = {
    "id": ID, "revision": ID, "experiment_id": ID, "run_id": nullable(ID), "title": STRING,
    "description": STRING, "kind": enum("code", "environment", "equipment", "tool_record", "data"),
    "filename": STRING, "external_ref": STRING, "audience": AUDIENCE,
}
FINDING_FIELDS = {
    "id": ID, "revision": ID, "document_id": ID, "statement": STRING,
    "kind": enum("observation", "baseline", "run_result"), "verified_baseline": BOOLEAN,
    "evidence": array(ref("Evidence")), "metric": STRING, "value": STRING, "unit": STRING, "conditions": STRING,
}
BRIEF_FIELDS = {"approach": STRING, "baseline_id": ID, "criterion": STRING, "conditions": STRING, "budget": STRING}
SKILL_SUMMARY = {
    "id": ID, "owner_id": ID, "audience": AUDIENCE, "title": schema("string", maxLength=160),
    "description": schema("string", maxLength=1000), "tags": schema("array", maxItems=20, items=schema("string", maxLength=40)),
    "archived": BOOLEAN, "revision": ID, "created": STRING, "updated": STRING,
}
SKILL_MARKDOWN = schema("string", maxLength=10_000)
SKILL_FIELDS = {name: SKILL_SUMMARY[name] for name in ("audience", "title", "description", "tags")}
SKILL_FIELDS.update(markdown=SKILL_MARKDOWN, recipients=RECIPIENTS)
GOAL_LINK = obj({"id": ID, "kind": enum("research_goal", "agent_goal"), "label": STRING, "url": STRING},
                ("id", "kind", "label", "url"))
DOCUMENT_CONTEXT = {"topic": schema("string", maxLength=120),
                    "research_goal_id": nullable(ID), "agent_goal_id": nullable(ID)}
TASK_FIELDS = {"title": schema("string", maxLength=160), "description": schema("string", maxLength=10000),
               "status": enum("open", "in_progress", "closed"),
               "due_on": nullable(schema("string", format="date")),
               "issue_url": nullable(schema("string", format="uri")), "assignee": nullable(STRING)}

SCHEMAS = {
    "Error": obj({"error": STRING}, ("error",)),
    "AgentGoal": obj({"id": ID, "agent": nullable(STRING), "agent_role": nullable(AI_ROLE),
                      "agents": array(STRING), "requester": STRING,
                      "continuous": BOOLEAN, "require_approval": BOOLEAN,
                      "objective": STRING, "acceptance_criteria": STRING, "sources": AGENT_GOAL_REFERENCES,
                      "required_skills": array(obj({"id": ID, "title": STRING, "revision": ID, "api_path": STRING},
                                                   ("id", "title", "revision", "api_path"))),
                      "status": AGENT_GOAL_STATUS, "revision": ID, "created": COUNT, "updated": COUNT,
                      "source_unavailable": BOOLEAN, "actions": array(AGENT_GOAL_ACTION)},
                     ("id", "status", "revision", "agent", "agent_role", "agents", "requester",
                      "continuous", "require_approval", "source_unavailable", "actions")),
    "AgentGoalEvent": obj({"revision": ID, "action": enum("create", *AGENT_GOAL_ACTION["enum"]),
                           "actor": STRING, "status": AGENT_GOAL_STATUS, "note": STRING, "evidence": AGENT_GOAL_REFERENCES,
                           "created": COUNT, "redacted": BOOLEAN}, ("revision", "action", "actor", "status", "note", "evidence")),
    "Account": obj({"id": ID, "role": enum("user", "member", "local", "cloud"), "username": STRING,
                    "display_name": STRING, "email": nullable(STRING), "has_avatar": BOOLEAN,
                    "has_private_key": BOOLEAN, "key_only": BOOLEAN}, ("id", "role", "username")),
    "Paper": obj({"id": ID, "path": STRING, **METADATA, "source_url": STRING, "owner_id": nullable(ID),
                  "audience": nullable(AUDIENCE), "has_pdf": schema("integer", enum=[0, 1]),
                  "metadata_audience": nullable(AUDIENCE), "pdf_restricted": schema("integer", enum=[0, 1]),
                  "can_read_file": schema("integer", enum=[0, 1]),
                  "recipients": RECIPIENTS, "can_manage": BOOLEAN}, ("id", "path", "title")),
    "Document": obj({"id": ID, "owner_id": ID, "title": STRING, "markdown": STRING, "audience": AUDIENCE,
                     "source_url": STRING, "kind": enum("document", "discussion"), "scheduled_at": SCHEDULE_TIME,
                     **DOCUMENT_CONTEXT, "goal_link": GOAL_LINK, **VOTE_FIELDS,
                     "revision": ID, "recipients": RECIPIENTS, "can_manage": BOOLEAN}, ("id", "title", "revision")),
    "Comment": obj({
        "id": ID, "paper_id": nullable(ID), "document_id": nullable(ID), "parent_id": nullable(ID),
        "body": STRING, "audience": nullable(AUDIENCE), "author_id": nullable(ID), "author_name": nullable(STRING),
        "author_kind": nullable(enum("user", "ai")), "deleted": COUNT, "finding_id": nullable(ID),
        "goal_id": nullable(ID), "doi_refs": array(STRING), "can_manage": BOOLEAN,
        "scheduled_at": SCHEDULE_TIME, **VOTE_FIELDS,
    }, ("id", "body")),
    "Evidence": {"oneOf": [
        obj({"kind": enum("pdf"), "id": ID, "page": ID}, ("kind", "id", "page")),
        obj({"kind": enum("document"), "id": ID, "start": ID, "end": ID, "revision": ID},
            ("kind", "id", "start", "end", "revision")),
        obj({"kind": enum("run_artifact"), "id": ID}, ("kind", "id")),
    ]},
    "Finding": obj({**FINDING_FIELDS, "can_edit": BOOLEAN}, ("id", "document_id", "statement", "kind", "evidence")),
    "Goal": obj({
        "id": ID, "document_id": ID, "question": STRING, "rationale": STRING, "uncertainty": STRING,
        "evidence_ids": ID_LIST, "revision": ID, "briefs": array(obj({"id": ID, "markdown": STRING})),
        **GOAL_ACCESS_FIELDS, "can_manage": BOOLEAN,
    }, ("id", "document_id", "question", "evidence_ids", "briefs")),
    "Experiment": obj(EXPERIMENT_FIELDS, ("id", "title", "revision")),
    "Run": obj({
        **RUN_FIELDS, "can_verify": BOOLEAN,
        "reproduction_checks": array(obj({
            **REPRODUCTION_CHECK, "reviewer": STRING, "updated": STRING, "mine": BOOLEAN,
        }, (*REPRODUCTION_CHECK, "reviewer", "updated", "mine"))),
    }, ("id", "title", "revision", "reproduction", "can_verify", "reproduction_checks")),
    "ArtifactInput": obj(ITEM_FIELDS, ("experiment_id", "title", "kind")),
    "Artifact": obj({
        **ITEM_FIELDS, "versions": array(obj({"id": ID, "number": ID, "filename": STRING,
                                             "sha256": nullable(STRING), "size": nullable(COUNT)})),
    }, ("id", "title", "kind", "versions")),
    "SkillSummary": obj(SKILL_SUMMARY, SKILL_SUMMARY),
    "Skill": obj({**SKILL_SUMMARY, "markdown": SKILL_MARKDOWN, "recipients": RECIPIENTS, "can_manage": BOOLEAN},
                 (*SKILL_SUMMARY, "markdown")),
}

COMMENTS_PAGE = obj({"comments": array(ref("Comment")), "next_before": nullable(ID)}, ("comments", "next_before"))
SKILL_DETAIL = obj({"skill": ref("Skill")}, ("skill",))
REVIEW_KIND = enum("paper", "document", "thread")
AI_ROLE = enum("local", "cloud")
PDF_REVIEW_OPTIONS = {"end_page": nullable(ID), "whole_pdf": BOOLEAN, "source_format": enum("pdf", "text")}
REVIEW = obj({
    "id": ID, "kind": REVIEW_KIND, "target_id": ID, "position": nullable(ID), "post": BOOLEAN,
    "status": enum("pending", "complete", "failed", "withdrawn"), "response": STRING, "comment_id": nullable(ID),
    "agent": STRING, "agent_role": AI_ROLE, **PDF_REVIEW_OPTIONS,
    "thread": array(obj({"id": ID, "body": STRING}, ("id", "body"))),
}, ("id", "kind", "target_id", "position", "post", "status", "response", "comment_id", "agent", "agent_role"))
REVIEW_DETAIL = obj({"review": REVIEW}, ("review",))
REVIEW_LIST = obj({"reviews": array(REVIEW)}, ("reviews",))
METRIC_FIELDS = {"page": ID, "metric": STRING, "value": STRING, "unit": STRING,
                 "conditions": STRING, "evidence": STRING}
PAPER_METRIC = obj({"id": ID, "paper_id": ID, "revision": ID, "can_edit": BOOLEAN, "removed": BOOLEAN, **METRIC_FIELDS},
                   ("id", "paper_id", "revision", "can_edit", "removed", *METRIC_FIELDS))
METRIC_HISTORY = obj({
    "original": obj(METRIC_FIELDS, METRIC_FIELDS),
    "corrections": array(obj({"revision": ID, "editor": STRING, "reason": STRING, "created": STRING, "removed": BOOLEAN, **METRIC_FIELDS},
                             ("revision", "editor", "reason", "created", "removed", *METRIC_FIELDS))),
    "next_before": nullable(ID), "editors": array(STRING),
}, ("original", "corrections", "next_before"))
CROSSREF = array(obj({**METADATA, "short_venue": STRING, "venue_group": STRING}))
PATHS = {
    client_distribution.DOWNLOAD_ROUTE: {"get": operation("Download the installable Python agent client",
        BINARY, response_type="application/zip", security=[],
        description="Save the response as paper-client.zip and install it with Python pip.")},
    "/api/health": {"get": {
        "summary": "Check whether the server can read its database",
        "security": [],
        "responses": {
            "200": {"description": "Database readable", **media(obj({"status": enum("ok")}, ("status",)))},
            "503": {"description": "Database unavailable", **media(obj({"status": enum("unavailable")}, ("status",)))},
        },
    }},
    "/api/agent-goals": {
        "get": operation("Read your agent goals or a goal's progress history", {"oneOf": [
            obj({"goals": array(ref("AgentGoal")), "next_before": nullable(ID), "assignable_agents": array(STRING)},
                ("goals", "next_before", "assignable_agents")),
            obj({"goal": ref("AgentGoal"), "events": array(ref("AgentGoalEvent")), "next_before": nullable(ID),
                 "last_submission": nullable(ref("AgentGoalEvent")), "last_approval": nullable(ref("AgentGoalEvent"))},
                ("goal", "events", "next_before")),
        ]}, params=(param("id", ID, description="Goal ID for a detail view."), BEFORE,
                    param("work", enum("ready"), description="AI accounts can list claimable and in-progress work.")),
            description="The requester and allowlisted AI accounts with access to the sources can read a goal. "
                        "The agent and agent_role fields identify the claimant and are null before a claim. "
                        "With id, before pages through older events by revision. Otherwise it pages through goals by ID. "
                        "Continuous or approval-gated goal details include the latest applicable checkpoint regardless of history pagination.",
            security=[{"ApplicationKey": []}, {"BrowserSession": []}]),
        "post": operation("Create an agent goal or update its progress",
            acknowledgement("goal", "events", "next_before", goal=ref("AgentGoal"), events=array(ref("AgentGoalEvent")),
                            next_before=nullable(ID), last_submission=nullable(ref("AgentGoalEvent")),
                            last_approval=nullable(ref("AgentGoalEvent"))),
            body={"oneOf": [
                {**obj({"action": enum("create"), "request_id": AGENT_GOAL_REQUEST_ID, "agent": STRING,
                     "agents": schema("array", items=STRING, minItems=1, maxItems=50),
                     "continuous": BOOLEAN, "require_approval": BOOLEAN,
                     "objective": STRING, "acceptance_criteria": STRING, "sources": AGENT_GOAL_REFERENCES,
                     "required_skill_ids": schema("array", items=ID, maxItems=agent_goals.MAX_REQUIRED_SKILLS)},
                    ("action", "request_id", "objective")),
                 "oneOf": [{"required": ["agents"]}, {"required": ["agent"]}]},
                obj({"action": AGENT_GOAL_ACTION, "request_id": AGENT_GOAL_REQUEST_ID, "id": ID, "revision": ID,
                     "note": STRING, "evidence": AGENT_GOAL_REFERENCES}, ("action", "request_id", "id", "revision")),
            ]},
            description="The requester must own or have goal posting access for every selected AI account. "
                        "Use agents to create an unclaimed goal for an allowlist. The legacy agent field assigns it immediately. "
                        "The first allowlisted agent to start claims the goal. Use an action from the goal's actions list. "
                        "Acceptance criteria are required unless continuous is true. "
                        "Continuous goals stay open until the requester finishes or cancels them. "
                        "When require_approval is true, the requester must approve the first and each subsequent round. "
                        "Retry an identical update with the same request_id. "
                        "A stale revision returns 409. Progress, block, submit, and request_changes require a note.",
            security=[{"ApplicationKey": []}, {"BrowserSession": []}]),
    },
    "/api/human-key/challenge": {"post": operation("Request a one-time human sign-in or enrollment challenge",
        obj({"challenge": AI_NONCE, "message": STRING, "expires_in": COUNT}, ("challenge", "message", "expires_in")),
        body=obj({"action": enum("register", "login", "attach"), "username": STRING}, ("action",)),
        description="Sign the exact returned message as UTF-8. Supply username for register or login. "
                    "Attaching a key requires a browser session. Challenges expire after two minutes.",
        security=[{}, {"BrowserSession": []}])},
    "/api/human-key/register": {"post": operation("Create a human account with a signed challenge",
        obj({"account": ref("Account")}, ("account",)),
        body=obj({**SIGNED_CHALLENGE, "public_key": PUBLIC_KEY, "email": STRING, "display_name": STRING, "invite": STRING},
                 ("challenge", "signature", "public_key", "email", "display_name")),
        description="Use a register challenge. A successful request begins a browser session.", security=[])},
    "/api/human-key/login": {"post": operation("Start a human browser session with a signed challenge",
        obj({"account": ref("Account")}, ("account",)),
        body=obj(SIGNED_CHALLENGE, ("challenge", "signature")), security=[])},
    "/api/human-key/attach": {"post": operation("Add a public key to the signed-in human account",
        obj({"account": ref("Account")}, ("account",)),
        body=obj({**SIGNED_CHALLENGE, "public_key": PUBLIC_KEY, "label": STRING}, ("challenge", "signature", "public_key")),
        description="Use an attach challenge from the same account.", security=[{"BrowserSession": []}])},
    "/api/human-key/revoke": {"post": operation("Revoke one of your human sign-in keys",
        obj({"account": schema("null")}, ("account",)),
        body=obj({"key_id": STRING}, ("key_id",)),
        description="Signs out existing sessions. Key-only users must retain at least one key.",
        security=[{"BrowserSession": []}])},
    "/api/ai/invitations": {
        "get": operation("List your AI invitations and managed agents",
            obj({"invitations": array(obj({"invite_id": STRING, "username": STRING, "role": AI_ROLE,
                "mode": enum("enroll", "rotate"), "created": COUNT, "expires": COUNT,
                "status": enum("pending", "used", "canceled", "expired")})),
                "agents": array(obj({"id": ID, "username": STRING, "role": AI_ROLE, "last_authenticated": nullable(COUNT),
                                     "last_heartbeat": nullable(COUNT), "online": BOOLEAN, "disabled_at": nullable(COUNT),
                                     "goal_delegates": array(STRING)})),
                "next_before": nullable(STRING)}, ("invitations", "agents", "next_before")),
            params=(param("before", STRING, description="The previous page's next_before invitation cursor."),),
            security=[{"ApplicationKey": []}, {"BrowserSession": []}]),
        "post": operation("Create, rotate, replace, or cancel an AI invitation",
            acknowledgement("invite_id", invite_id=STRING, registration_path=STRING,
                            registration_url=schema("string", format="uri"), client_download_url=schema("string", format="uri"),
                            username=STRING, role=AI_ROLE,
                            expires_in=COUNT, mode=enum("enroll", "rotate"), status=enum("canceled")),
            body={"oneOf": [
                obj({"action": enum("create"), "username": STRING, "role": AI_ROLE}, ("username", "role")),
                obj({"action": enum("rotate"), "username": STRING}, ("action", "username")),
                obj({"action": enum("cancel", "replace"), "invite_id": STRING}, ("action", "invite_id")),
            ]},
            description="Requires a trusted human. Rotation additionally requires management access to the agent. "
                        "Registration URLs expire in 15 minutes.",
            security=[{"ApplicationKey": []}, {"BrowserSession": []}]),
    },
    "/api/ai/register/{token}": {"post": operation("Enroll an AI account with its public key",
        acknowledgement("account", account=ref("Account")),
        params=(param("token", AI_NONCE, location="path", required=True),),
        body=obj({"public_key": PUBLIC_KEY,
                  "signature": AI_SIGNATURE}, ("public_key", "signature")), security=[],
        description="Sign the ASCII string paper-library:register:<invited username>:/api/ai/register/<token>."
                    " A successful request consumes the invitation. A rotation preserves the account and invalidates its previous credentials.")},
    "/api/ai/challenge": {"post": operation("Request a one-time AI sign-in challenge",
        acknowledgement("challenge", "username", "expires_in", challenge=AI_NONCE, username=STRING, expires_in=COUNT),
        body=obj({"username": STRING}, ("username",)), security=[],
        description="Use the returned username in the signature. The challenge expires in two minutes.")},
    "/api/ai/login": {"post": operation("Exchange a signed AI challenge for an access token",
        acknowledgement("access_token", "token_type", "expires_in",
                        access_token=STRING, token_type=enum("Bearer"), expires_in=COUNT),
        body=obj({"username": STRING, "challenge": AI_NONCE, "signature": AI_SIGNATURE},
                 ("username", "challenge", "signature")), security=[],
        description="Sign the ASCII string paper-library:login:<username>:<challenge>."
                    " The access token expires in 15 minutes.")},
    "/api/ai/heartbeat": {"post": operation("Report presence for the authenticated AI account",
        acknowledgement("last_heartbeat", "interval_seconds", last_heartbeat=COUNT, interval_seconds=ID),
        body=obj(), description="Send an empty JSON object. The heartbeat timestamp is in Unix seconds.",
        security=[{"ApplicationKey": []}, {"BrowserSession": []}])},
    "/api/ai/goal-delegates": {"post": operation("Grant or revoke goal posting access for a managed agent",
        acknowledgement(),
        body=obj({"action": enum("grant", "revoke"), "agent": STRING, "username": STRING},
                 ("action", "agent", "username")),
        description="Requires the agent's owner. Access lets the selected human create goals for that agent.",
        security=[{"ApplicationKey": []}, {"BrowserSession": []}])},
    "/api/ai/deactivate": {"post": operation("Deactivate a managed AI account and keep its data",
        acknowledgement("username", "disabled_at", username=STRING, disabled_at=COUNT),
        body=obj({"username": STRING}, ("username",)),
        description="Requires the agent's trusted human operator. Revokes credentials and cancels pending key rotations.",
        security=[{"ApplicationKey": []}, {"BrowserSession": []}])},
    "/api/human-invitations": {
        "get": operation("List human signup invitations you issued that are still pending",
            obj({"invitations": array(obj({"invite_id": STRING, "email": schema("string", format="email"), "expires": COUNT,
                                         "role": enum("member", "user")}, ("invite_id", "email", "expires", "role")))}, ("invitations",)),
            description="Requires a trusted human browser session. Expiry is a Unix timestamp.",
            security=[{"BrowserSession": []}]),
        "post": operation("Create or revoke a one-time human signup link",
            acknowledgement(invitation_url=schema("string", format="uri"), invite_id=STRING, expires_in=COUNT,
                            role=enum("member", "user")),
            body={"oneOf": [
                obj({"action": enum("create"), "email": schema("string", format="email"),
                     "role": {**enum("member", "user"), "default": "member"}}, ("email",)),
                obj({"action": enum("revoke"), "invite_id": STRING}, ("action", "invite_id")),
            ]},
            description="Requires a trusted human browser session. Creation returns the link, its ID, and its lifetime in seconds. "
                        "The email-bound link grants the chosen role on signup and expires after 24 hours. "
                        "You can replace or revoke your own pending link.",
            security=[{"BrowserSession": []}]),
    },
    "/api/account": {"get": operation("Check the current account",
        obj({"account": nullable(ref("Account")), "google_available": BOOLEAN, "invitation_required": BOOLEAN,
             "sign_in_keys": array(obj({"key_id": STRING, "label": STRING, "created": nullable(COUNT)})),
             "passkeys": array(obj({"id": STRING, "label": STRING, "created": COUNT}))}, ("account",)),
        security=[{}, {"ApplicationKey": []}, {"BrowserSession": []}])},
    "/api/account/profile": {"post": operation("Update your profile",
        acknowledgement(), body=obj({"display_name": schema("string", maxLength=120), "email": nullable(STRING),
                                      "avatar": nullable(STRING)}),
        description="An empty nickname uses the username. A blank email removes the profile email. "
                    "Upload a base64-encoded PNG up to 256 × 256 pixels and 350 KB, or pass null to remove the avatar.",
        security=[{"BrowserSession": []}])},
    "/api/account/avatar": {"get": operation("Read your profile avatar",
        schema("string", format="binary"), response_type="image/png", security=[{"BrowserSession": []}])},
    "/api/paper-catalog": {"get": operation("Search the library's visible papers",
        obj({"papers": array(ref("Paper")), "count": COUNT, "total": COUNT, "page": ID,
             "groups": array(obj({"id": ID, "name": STRING})), "publishers": array(STRING), "account": nullable(ref("Account"))},
            ("papers", "count", "total", "page")),
        params=(param("q", STRING), param("group", ID), param("publisher", STRING), param("from_year", ID),
                param("through_year", ID), param("page", ID), param("facets", enum("1"))))},
    "/api/public-papers": {"get": operation("Read explicitly published paper snapshots",
        obj({"papers": array(obj({"id": ID, "title": STRING, "doi": STRING, "source_url": STRING, "summary": STRING})),
             "next_after": nullable(ID)}, ("papers", "next_after")),
        params=(PAPER_ID, AFTER), security=[{}])},
    "/api/paper-publication": {"post": operation("Publish or unpublish a paper you manage", acknowledgement(),
        body=obj({"paper_id": ID, "action": enum("publish", "unpublish"), "summary": STRING}, ("paper_id", "action")),
        security=[{"BrowserSession": []}])},
    "/api/paper-detail": {"get": operation("Read a visible paper's metadata",
        obj({"paper": ref("Paper"), "group_ids": ID_LIST}, ("paper", "group_ids")), params=(PAPER_ID,))},
    "/api/paper-page": {"get": operation("Read a page of visible papers",
        obj({"papers": array(ref("Paper")), "next_after": nullable(ID)}, ("papers", "next_after")), params=(AFTER,))},
    "/api/paper-access": {"post": operation("Change sharing for a paper you own", acknowledgement(),
        body=obj({"paper_id": ID, "audience": AUDIENCE, "recipients": RECIPIENTS, "allow_title": BOOLEAN,
                  "metadata_audience": nullable(AUDIENCE)}, ("paper_id", "audience")),
        description="The audience and recipients fields control PDF access. Set metadata_audience to share "
                    "metadata more broadly, or null to follow PDF access. Omitting it preserves the current setting.")},
    "/api/paper-reference": {"post": operation("Create a paper reference without a PDF",
        acknowledgement("paper_id", paper_id=ID),
        body=obj({**METADATA, "source_url": STRING, "metadata_audience": nullable(AUDIENCE)}),
        description="Supply a DOI, title, or publication link. Metadata defaults to all signed-in accounts. "
                    "Comments use the same endpoints as PDF-backed papers.")},
    "/api/paper-reference-preview": {"post": operation("Look up reference metadata and visible DOI matches",
        obj({"metadata": CROSSREF, "existing": array(obj({"id": ID, "title": STRING, "doi": STRING},
                                                        ("id", "title", "doi")))}, ("metadata", "existing")),
        body=obj({"doi": STRING}, ("doi",)))},
    "/api/zotero-import": {"post": operation("Import selected Zotero CSL JSON references",
        acknowledgement("items", items=array(obj({"paper_id": ID, "existing": BOOLEAN}, ("paper_id", "existing")))),
        body=obj({"items": array(schema("object")), "metadata_audience": AUDIENCE}, ("items",)),
        description="Accepts 1 to 200 CSL JSON items and reuses visible records with matching DOIs. "
                    "Imported metadata defaults to owner only. Attach PDFs separately with X-Paper-ID.")},
    "/api/metric-page": {"get": operation("Read a page of visible metrics",
        obj({"metrics": array(obj({"paper_id": ID, "page": ID, "paper": STRING, "metric": STRING, "value": STRING,
                                   "unit": STRING, "conditions": STRING, "evidence": STRING})), "next_after": nullable(ID)},
            ("metrics", "next_after")), params=(AFTER,))},
    "/api/paper-metrics": {
        "get": operation("List a paper's metrics with current revisions and edit permissions",
            obj({"metrics": array(PAPER_METRIC), "next_after": nullable(ID),
                 "can_manage_editors": BOOLEAN, "can_claim_paper": BOOLEAN},
                ("metrics", "next_after", "can_manage_editors", "can_claim_paper")),
            params=(PAPER_ID, AFTER, param("removed", enum("0", "1"), description="Use 1 to list removed metrics."))),
        "post": operation("Correct, remove, or restore a metric you have permission to edit",
            acknowledgement("metric_id", "revision", "removed", metric_id=ID, revision=ID, removed=BOOLEAN),
            body=obj({"metric_id": ID, "revision": ID, "reason": STRING, "action": enum("correct", "remove", "restore"), **METRIC_FIELDS},
                     ("metric_id", "revision", "reason")),
            description="Requires paper access and ownership or an explicit grant. Trusted humans can edit legacy unowned metrics. The default action is correct and requires a changed field. Remove and restore require only the ID, revision, action, and reason. A stale revision returns 409."),
    },
    "/api/metric-history": {"get": operation("Read the extracted values and correction history",
        METRIC_HISTORY, params=(param("metric_id", ID, required=True), BEFORE),
        description="Only the paper owner receives the list of named editors.")},
    "/api/metric-editors": {"post": operation("Grant or revoke edit access to one metric as its paper owner",
        acknowledgement(), body=obj({"metric_id": ID, "username": STRING, "action": enum("grant", "revoke")},
                                    ("metric_id", "username", "action")),
        description="An editor still needs permission to view the paper.")},
    "/api/claim-paper": {"post": operation("Take ownership of a legacy unowned paper as a trusted human",
        acknowledgement(), body=obj({"paper_id": ID}, ("paper_id",)),
        description="The library preserves the paper's trusted-human read access.")},
    "/api/detect-paper-metrics": {"post": operation("Detect metrics from the verified PDF of a paper you manage",
        obj({"metrics": COUNT, "has_text": BOOLEAN}, ("metrics", "has_text")),
        body=obj({"paper_id": ID, "keywords": array(STRING)}, ("paper_id",)),
        description="Keywords are literal nearby phrases. Leave them empty to use the default detector. Existing revisions and removals are preserved.")},
    "/api/search-papers": {"post": operation("Search Crossref", CROSSREF,
        body=obj({"topic": STRING, "keywords": array(STRING), "publisher": STRING, "year_from": nullable(ID),
                  "year_to": nullable(ID)}, ("topic",)))},
    "/api/papers": {"post": operation("Import or attach a PDF",
        obj({"paper_id": ID, "metrics": COUNT, "has_text": BOOLEAN}, ("paper_id", "metrics", "has_text")),
        body=BINARY, request_type="application/pdf",
        params=(param("X-Paper-Filename", STRING, location="header", required=True, description="Percent-encoded PDF filename."),
                param("X-Paper-ID", ID, location="header", description="Attach to an existing reference you manage."),
                param("X-Paper-Audience", AUDIENCE, location="header"),
                param("X-Paper-Recipients", STRING, location="header", description="Percent-encoded JSON array of usernames."),
                param("X-Paper-Metric-Keywords", STRING, location="header", description="Percent-encoded JSON array of up to 20 literal keyword phrases.")))},
    "/papers/{paper_id}/source.pdf": {"get": operation("Download a visible PDF", BINARY,
        params=(param("paper_id", ID, location="path", required=True), param("download", enum("1"))),
        response_type="application/pdf")},
    "/api/document-goals": {"get": operation("List goals available to link to a document",
        obj({"goals": array(GOAL_LINK)}, ("goals",)))},
    "/api/tasks": {
        "get": operation("List tasks owned by or assigned to the current account, including its agents’ owned tasks",
            obj({"tasks": array(obj({**TASK_FIELDS, "id": ID, "revision": ID, "owner_id": ID,
                                     "assignee_id": nullable(ID), "creator": STRING, "can_manage": BOOLEAN},
                                    ("id", "revision", "title", "status")))}, ("tasks",))),
        "post": operation("Create or update a task", acknowledgement("id", id=ID),
            body=obj({**TASK_FIELDS, "id": ID, "revision": ID}),
            description="Creation requires title. Updates require id and revision. Assignees can update status. "
                        "Use an HTTPS github.com issue URL for issue_url."),
    },
    "/api/documents": {
        "get": operation("List visible documents",
            obj({"documents": array(ref("Document")), "comments": array(ref("Comment")),
                 "papers": array(ref("Paper")), "account": nullable(ref("Account"))}, ("documents",)),
            params=(param("content", enum("summary")), param("comments", enum("none")))),
        "post": operation("Create or update a document or news entry", acknowledgement("document_id", "revision", document_id=ID, revision=ID),
            body=obj({"document_id": ID, "revision": ID, "title": STRING, "markdown": STRING,
                      "audience": AUDIENCE, "recipients": RECIPIENTS, "source_url": schema("string", format="uri", maxLength=2048),
                      **DOCUMENT_CONTEXT},
                     ("title", "markdown")), description="Supply an HTTPS source_url to list the document in News."),
    },
    "/api/news": {"get": operation("List visible news entries",
        obj({"documents": array(ref("Document")), "papers": array(ref("Paper")), "account": nullable(ref("Account"))},
            ("documents",)), description="Use /api/document to read the notes and /api/document-comments for the discussion.")},
    "/api/discussions": {
        "get": operation("List standalone discussion threads", obj({"documents": array(ref("Document"))}, ("documents",))),
        "post": operation("Create or update a standalone discussion thread",
            acknowledgement("document_id", "revision", document_id=ID, revision=ID),
            body=obj({"document_id": ID, "revision": ID, "title": STRING, "markdown": STRING,
                      "audience": AUDIENCE, "recipients": RECIPIENTS, "scheduled_at": SCHEDULE_TIME, **DOCUMENT_CONTEXT},
                      ("title", "markdown"))),
    },
    "/api/document": {"get": operation("Read a visible document", obj({"document": ref("Document")}, ("document",)),
        params=(param("id", ID, required=True),))},
    "/api/document-comments": {"get": operation("Read visible document discussion", COMMENTS_PAGE, params=(DOCUMENT_ID, BEFORE))},
    "/api/paper-comments": {"get": operation("Read visible paper discussion", COMMENTS_PAGE, params=(PAPER_ID, BEFORE))},
    "/api/comments": {"post": operation("Post, reply to, or edit a comment", acknowledgement("comment_id", comment_id=ID),
        body=obj({"paper_id": ID, "document_id": ID, "comment_id": ID, "parent_id": ID, "finding_id": ID, "goal_id": ID,
                  "body": STRING, "audience": AUDIENCE, "recipients": RECIPIENTS, "doi_refs": array(STRING),
                  "scheduled_at": SCHEDULE_TIME,
                  "location": obj({"kind": enum("pdf", "document"), "id": ID, "position": ID}, ("kind", "id", "position"))},
                 ("body",)), description="Choose exactly one of paper_id and document_id.")},
    "/api/delete-comment": {"post": operation("Delete a comment you authored", acknowledgement(),
        body=obj({"paper_id": ID, "document_id": ID, "comment_id": ID}, ("comment_id",)),
        description="Choose exactly one of paper_id and document_id.")},
    "/api/thread-votes": {"post": operation("Set or clear a vote on a visible discussion or comment",
        acknowledgement(*VOTE_FIELDS, **VOTE_FIELDS),
        body=obj({"paper_id": ID, "document_id": ID, "comment_id": ID, "vote": VOTE}, ("vote",)),
        description="Choose a paper or document. Include comment_id to vote on a comment. A vote of zero clears your vote.")},
    "/api/research-findings": {
        "get": operation("List or compare visible findings",
            {"oneOf": [obj({"findings": array(ref("Finding")), "experiments": array(obj({"id": ID, "title": STRING}))},
                           ("findings", "experiments")),
                       obj({"comparison": obj({"difference": nullable(STRING), "reasons": array(STRING),
                                               "findings": array(obj({"id": ID, "value": STRING, "unit": STRING}))})},
                           ("comparison",))]}, params=(DOCUMENT_ID, param("left", ID), param("right", ID)),
            description="Supply both left and right finding IDs to compare numerical values."),
        "post": operation("Record or update an evidence-backed finding", acknowledgement("id", "revision", id=ID, revision=ID),
            body=obj(FINDING_FIELDS, ("document_id", "statement", "evidence"))),
    },
    "/api/research-goals": {
        "get": operation("Read visible goals and briefs",
            obj({"goals": array(ref("Goal")), "can_manage": BOOLEAN, "findings": array(obj({"id": ID, "statement": STRING}))},
                ("goals", "can_manage", "findings")), params=(DOCUMENT_ID,)),
        "post": operation("Propose a goal, change its access, or advance its workflow", acknowledgement("id", id=ID, revision=ID,
                                                                                   brief_id=ID, experiment_id=ID, decision_id=ID),
            description="Rank, confirm, decide, and revise_design require the human workspace owner. "
                        "The goal author or their operator can use set_access. Readers also need the document and evidence.",
            body={"oneOf": [
                obj({"action": enum(action), "document_id": ID, **fields,
                     **(GOAL_ACCESS_FIELDS if action in ("propose", "set_access") else {})},
                    ("action", "document_id", *fields))
                for action, fields in (
                    ("propose", {"question": STRING, "rationale": STRING, "uncertainty": STRING, "evidence_ids": ID_LIST}),
                    ("set_access", {"goal_id": ID, "revision": ID}),
                    ("draft", {"goal_id": ID, **BRIEF_FIELDS}),
                    ("rank", {"goal_id": ID, "revision": ID, "selected": BOOLEAN, "priority": ID}),
                    ("confirm", {"goal_id": ID, "revision": ID, "brief_id": ID}),
                    ("decide", {"goal_id": ID, "revision": ID, "brief_id": ID, "run_id": ID, "result_id": ID,
                                "outcome": enum("met", "missed", "inconclusive"),
                                "next_step": enum("iterate", "design", "set_aside"), "rationale": STRING}),
                    ("revise_design", {"goal_id": ID, "revision": ID, "brief_id": ID, **BRIEF_FIELDS}),
                )
            ]}),
    },
    "/api/experiments": {
        "get": operation("List visible experiments", obj({"experiments": array(ref("Experiment"))}, ("experiments",))),
        "post": operation("Create or update an experiment", acknowledgement("id", id=ID), body=obj(EXPERIMENT_FIELDS),
            description="New experiments require a title. Updates require id and revision."),
    },
    "/api/experiment-detail": {"get": operation("Read an experiment, its runs, and artifact versions",
        obj({"experiment": ref("Experiment"), "runs": array(ref("Run")), "items": array(ref("Artifact")),
             "can_edit": BOOLEAN, "brief": nullable(obj()), "compute_tasks": array(obj())},
            ("experiment", "runs", "items", "can_edit", "brief")),
        params=(param("id", ID, required=True),))},
    "/api/experiment-compute": {
        "get": operation("Read compute tasks for an accessible experiment",
            obj({"tasks": array(obj())}, ("tasks",)), params=(param("experiment_id", ID, required=True),)),
        "post": operation("Post, claim, release, complete, or cancel a compute task",
            acknowledgement("id", "revision", id=ID, revision=ID),
            body=obj({"action": enum("create", "claim", "release", "complete", "cancel"), "experiment_id": ID,
                      "id": ID, "revision": ID, "title": STRING, "instructions": STRING, "result": STRING,
                      "resources": obj({
                          "cpu_cores": ID, "ram_gib": ID, "disk_gib": ID, "wall_minutes": ID,
                          "gpu_count": COUNT, "vram_gib_per_gpu": COUNT,
                      }, ("cpu_cores", "ram_gib", "disk_gib", "wall_minutes", "gpu_count", "vram_gib_per_gpu"))},
                     ("action", "experiment_id")),
            description="Editors create tasks with a title, run instructions, and resource estimates. "
                        "Experiment readers can claim an open task. Actions on existing tasks require id and revision. "
                        "The claimant completes the task with a result summary after running it externally."),
    },
    "/api/experiment-runs": {"post": operation("Create or update a run", acknowledgement("id", id=ID),
        body=obj(RUN_FIELDS, ("experiment_id", "title")),
        description="Updates require id and revision. Omit reproduction to retain its value or send an empty object to clear it.")},
    "/api/run-reproductions": {"post": operation("Record an independent rerun", acknowledgement(),
        body=obj({"run_id": ID, **REPRODUCTION_CHECK}, ("run_id", *REPRODUCTION_CHECK)),
        description="A human reader can save one check per completed run revision. Saving again replaces their check.")},
    "/api/research-grants": {"post": operation("Set named readers and editors for a research item you own",
        acknowledgement(), body=obj({"id": ID, "kind": enum("experiment", "run", "item", "tool"),
                                     "readers": RECIPIENTS, "editors": RECIPIENTS}, ("id", "kind")))},
    "/api/research-items": {"post": operation("Record an artifact or another version without uploading bytes",
        acknowledgement("id", id=ID), body=ref("ArtifactInput"), description="New versions require id and revision.")},
    "/api/research-upload": {"post": operation("Upload an artifact or another version",
        acknowledgement("id", "version_id", id=ID, version_id=ID),
        params=(param("X-Research-Metadata", STRING, location="header", required=True,
                      description="Percent-encoded JSON matching ArtifactInput, with filename. New versions require id and revision."),),
        body=BINARY, request_type="application/octet-stream")},
    "/research-versions/{version_id}/file": {"get": operation("Download a visible uploaded artifact version", BINARY,
        params=(param("version_id", ID, location="path", required=True),), response_type="application/octet-stream")},
    "/research-versions/{version_id}/entries": {"get": operation("List the files in an uploaded ZIP version",
        obj({"commit": nullable(STRING), "files": array(obj({"path": STRING, "size": COUNT}, ("path", "size")))},
            ("commit", "files")),
        params=(param("version_id", ID, location="path", required=True),))},
    "/research-versions/{version_id}/entry": {"get": operation("Download a file from an uploaded ZIP version", BINARY,
        params=(param("version_id", ID, location="path", required=True), param("path", STRING, required=True)),
        response_type="application/octet-stream")},
    "/api/review-agents": {"get": operation("List AI accounts eligible to access the review target",
        obj({"agents": array(obj({"username": STRING, "display_name": STRING, "role": AI_ROLE},
                                 ("username", "display_name", "role")))}, ("agents",)),
        params=(param("kind", REVIEW_KIND, required=True), param("target_id", ID, required=True)),
        description="Requires a human account with access to the target. Eligibility follows source sharing.")},
    "/api/reviews": {
        "get": operation("Read your review requests or pending AI assignments",
            {"oneOf": [REVIEW_DETAIL, REVIEW_LIST, obj({"text": STRING}, ("text",))]},
            params=(param("id", ID, description="Return one request, including thread context for the assigned AI."),
                    param("kind", REVIEW_KIND), param("target_id", ID),
                    param("context", enum("text"), description="Fetch page-labelled text for an assigned pending paper review.")),
            description="AI accounts receive up to 30 pending assignments in creation order. Human accounts receive up to 30 of their own requests, newest first. Supply kind and target_id together to filter by source."),
        "post": operation("Request or withdraw a review or return an assigned result",
            acknowledgement("review", review=REVIEW), body={"oneOf": [
                obj({"action": enum("create"), "kind": REVIEW_KIND, "target_id": ID, "position": nullable(ID),
                     "agent": STRING, "agent_role": AI_ROLE, "post": BOOLEAN, **PDF_REVIEW_OPTIONS},
                    ("action", "kind", "target_id", "agent", "agent_role")),
                obj({"action": enum("complete"), "id": ID, "status": enum("complete", "failed"), "response": STRING},
                    ("action", "id", "status", "response")),
                obj({"action": enum("withdraw"), "id": ID}, ("action", "id")),
            ]}, description="The requester can withdraw a pending review. A withdrawn review is removed from the agent queue and cannot accept a result. "
                            "Paper reviews accept an inclusive position–end_page range or whole_pdf with no positions. "
                            "Set source_format to text to let the assigned agent fetch extracted text."),
    },
    "/api/skills/default": {"get": operation("Fetch the built-in guide to using the library API",
        obj({"skill": obj({"id": enum("default"), "title": STRING, "description": STRING, "markdown": STRING,
                           "tags": array(STRING)}, ("id", "title", "description", "markdown", "tags"))}, ("skill",)))},
    "/api/skills": {
        "get": operation("Find visible skills", obj({"skills": array(ref("SkillSummary")), "next_after": nullable(ID)},
                                                   ("skills", "next_after")),
            params=(param("q", STRING, description="Title, description, or tag substring."),
                    param("tag", STRING, description="Exact tag, ignoring case."),
                    param("archived", enum("0", "1"), description="Use 1 to list your archived skills."), AFTER)),
        "post": operation("Create or manage a skill you own", acknowledgement("skill", skill=ref("Skill")),
            body={"oneOf": [
                obj({"action": enum("create"), **SKILL_FIELDS}, ("title", "markdown")),
                obj({"action": enum("update"), "id": ID, "revision": ID, **SKILL_FIELDS},
                    ("action", "id", "revision", "title", "markdown")),
                obj({"action": enum("archive", "restore"), "id": ID, "revision": ID}, ("action", "id", "revision")),
            ]}),
    },
    "/api/skills/{skill_id}": {"get": operation("Fetch a visible skill's Markdown", SKILL_DETAIL,
        params=(param("skill_id", ID, location="path", required=True),))},
}


def document(port, public_url=None):
    return {
        "openapi": "3.1.0",
        "info": {"title": "Paper Library API", "version": "1.0.0",
                 "description": "Shared HTTP interface for Local AI and Cloud AI workstation clients."},
        "servers": [{"url": public_url or f"http://127.0.0.1:{port}"}],
        "security": [{"ApplicationKey": []}],
        "paths": PATHS,
        "components": {"schemas": SCHEMAS, "securitySchemes": {
            "ApplicationKey": {"type": "http", "scheme": "bearer",
                               "description": "Library application key or short-lived AI access token."},
            "BrowserSession": {"type": "apiKey", "in": "cookie", "name": "paper_session"},
        }},
    }
