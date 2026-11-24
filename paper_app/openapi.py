"""Public HTTP operations for workstation-based research clients."""

from . import agent_goals
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
                          ("404", "Resource unavailable"), ("409", "Conflict"), ("415", "Unsupported media type"),
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
AI_ROLE = enum("local", "cloud")
AI_NONCE = schema("string", pattern="^[A-Za-z0-9_-]{43}$")
AI_SIGNATURE = schema("string", pattern="^[A-Za-z0-9_-]{86}$",
                      description="64-byte Ed25519 signature in unpadded base64url.")
SIGNED_CHALLENGE = {"challenge": AI_NONCE, "signature": AI_SIGNATURE}
PUBLIC_KEY = {**AI_NONCE, "description": "32-byte Ed25519 public key in unpadded base64url."}
BINARY = schema("string", format="binary")
AUDIENCE = enum(*AUDIENCES)
RECIPIENTS = array(STRING)
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
}
RUN_FIELDS = {
    "id": ID, "revision": ID, "experiment_id": ID, "title": STRING, "description": STRING,
    "methods": STRING, "settings": STRING, "status": enum("planned", "running", "complete", "failed"),
    "audience": AUDIENCE,
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
SCHEMAS = {
    "Error": obj({"error": STRING}, ("error",)),
    "AgentGoal": obj({"id": ID, "agent": STRING, "agent_role": AI_ROLE, "requester": STRING,
                      "objective": STRING, "acceptance_criteria": STRING, "sources": AGENT_GOAL_REFERENCES,
                      "status": AGENT_GOAL_STATUS, "revision": ID, "created": COUNT, "updated": COUNT,
                      "source_unavailable": BOOLEAN, "actions": array(AGENT_GOAL_ACTION)},
                     ("id", "status", "revision", "agent", "requester", "source_unavailable", "actions")),
    "AgentGoalEvent": obj({"revision": ID, "action": enum("create", *AGENT_GOAL_ACTION["enum"]),
                           "actor": STRING, "status": AGENT_GOAL_STATUS, "note": STRING, "evidence": AGENT_GOAL_REFERENCES,
                           "created": COUNT, "redacted": BOOLEAN}, ("revision", "action", "actor", "status", "note", "evidence")),
    "Account": obj({"id": ID, "role": enum("user", "member", "local", "cloud"), "username": STRING,
                    "display_name": STRING, "has_private_key": BOOLEAN, "key_only": BOOLEAN}, ("id", "role", "username")),
    "Paper": obj({"id": ID, "path": STRING, **METADATA, "owner_id": nullable(ID),
                  "audience": nullable(AUDIENCE), "has_pdf": schema("integer", enum=[0, 1]),
                  "recipients": RECIPIENTS}, ("id", "path", "title")),
    "Document": obj({"id": ID, "owner_id": ID, "title": STRING, "markdown": STRING, "audience": AUDIENCE,
                     "revision": ID, "recipients": RECIPIENTS}, ("id", "title", "revision")),
    "Comment": obj({
        "id": ID, "paper_id": nullable(ID), "document_id": nullable(ID), "parent_id": nullable(ID),
        "body": STRING, "audience": nullable(AUDIENCE), "author_id": nullable(ID), "author_name": nullable(STRING),
        "author_kind": nullable(enum("user", "ai")), "deleted": COUNT, "finding_id": nullable(ID),
        "goal_id": nullable(ID), "doi_refs": array(STRING),
    }, ("id", "body")),
    "Evidence": {"oneOf": [
        obj({"kind": enum("pdf"), "id": ID, "page": ID}, ("kind", "id", "page")),
        obj({"kind": enum("document"), "id": ID, "start": ID, "end": ID, "revision": ID},
            ("kind", "id", "start", "end", "revision")),
        obj({"kind": enum("run_artifact"), "id": ID}, ("kind", "id")),
    ]},
    "Finding": obj(FINDING_FIELDS, ("id", "document_id", "statement", "kind", "evidence")),
    "Goal": obj({
        "id": ID, "document_id": ID, "question": STRING, "rationale": STRING, "uncertainty": STRING,
        "evidence_ids": ID_LIST, "revision": ID, "briefs": array(obj({"id": ID, "markdown": STRING})),
    }, ("id", "document_id", "question", "evidence_ids", "briefs")),
    "Experiment": obj(EXPERIMENT_FIELDS, ("id", "title", "revision")),
    "Run": obj(RUN_FIELDS, ("id", "title", "revision")),
    "ArtifactInput": obj(ITEM_FIELDS, ("experiment_id", "title", "kind")),
    "Artifact": obj({
        **ITEM_FIELDS, "versions": array(obj({"id": ID, "number": ID, "filename": STRING,
                                             "sha256": nullable(STRING), "size": nullable(COUNT)})),
    }, ("id", "title", "kind", "versions")),
    "SkillSummary": obj(SKILL_SUMMARY, SKILL_SUMMARY),
    "Skill": obj({**SKILL_SUMMARY, "markdown": SKILL_MARKDOWN, "recipients": RECIPIENTS}, (*SKILL_SUMMARY, "markdown")),
}

COMMENTS_PAGE = obj({"comments": array(ref("Comment")), "next_before": nullable(ID)}, ("comments", "next_before"))
SKILL_DETAIL = obj({"skill": ref("Skill")}, ("skill",))
REVIEW_KIND = enum("paper", "document", "thread")
AI_ROLE = enum("local", "cloud")
REVIEW = obj({
    "id": ID, "kind": REVIEW_KIND, "target_id": ID, "position": nullable(ID), "post": BOOLEAN,
    "status": enum("pending", "complete", "failed"), "response": STRING, "comment_id": nullable(ID),
    "agent": STRING, "agent_role": AI_ROLE,
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
            obj({"goals": array(ref("AgentGoal")), "next_before": nullable(ID)}, ("goals", "next_before")),
            obj({"goal": ref("AgentGoal"), "events": array(ref("AgentGoalEvent")), "next_before": nullable(ID)},
                ("goal", "events", "next_before")),
        ]}, params=(param("id", ID, description="Goal ID for a detail view."), BEFORE),
            description="Only the assigning human and assigned AI account can read the goal. "
                        "With id, before pages through older events by revision. Otherwise it pages through goals by ID.",
            security=[{"ApplicationKey": []}, {"BrowserSession": []}]),
        "post": operation("Assign an agent goal or update its progress",
            acknowledgement("goal", "events", "next_before", goal=ref("AgentGoal"), events=array(ref("AgentGoalEvent")),
                            next_before=nullable(ID)),
            body={"oneOf": [
                obj({"action": enum("create"), "request_id": AGENT_GOAL_REQUEST_ID, "agent": STRING,
                     "objective": STRING, "acceptance_criteria": STRING, "sources": AGENT_GOAL_REFERENCES},
                    ("action", "request_id", "agent", "objective", "acceptance_criteria")),
                obj({"action": AGENT_GOAL_ACTION, "request_id": AGENT_GOAL_REQUEST_ID, "id": ID, "revision": ID,
                     "note": STRING, "evidence": AGENT_GOAL_REFERENCES}, ("action", "request_id", "id", "revision")),
            ]},
            description="Use an action from the goal's actions list. Retry an identical update with the same request_id. "
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
                "agents": array(obj({"id": ID, "username": STRING, "role": AI_ROLE, "last_authenticated": nullable(COUNT)})),
                "next_before": nullable(STRING)}, ("invitations", "agents", "next_before")),
            params=(param("before", STRING, description="The previous page's next_before invitation cursor."),),
            security=[{"ApplicationKey": []}, {"BrowserSession": []}]),
        "post": operation("Create, rotate, replace, or cancel an AI invitation",
            acknowledgement("invite_id", invite_id=STRING, registration_path=STRING,
                            registration_url=schema("string", format="uri"), username=STRING, role=AI_ROLE,
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
        obj({"account": nullable(ref("Account")), "google_available": BOOLEAN,
             "sign_in_keys": array(obj({"key_id": STRING, "label": STRING, "created": nullable(COUNT)}))}, ("account",)),
        security=[{}, {"ApplicationKey": []}, {"BrowserSession": []}])},
    "/api/paper-catalog": {"get": operation("Search the library's visible papers",
        obj({"papers": array(ref("Paper")), "count": COUNT, "total": COUNT, "page": ID,
             "groups": array(obj({"id": ID, "name": STRING})), "publishers": array(STRING), "account": nullable(ref("Account"))},
            ("papers", "count", "total", "page")),
        params=(param("q", STRING), param("group", ID), param("publisher", STRING), param("from_year", ID),
                param("through_year", ID), param("page", ID), param("facets", enum("1"))))},
    "/api/paper-detail": {"get": operation("Read a visible paper's metadata",
        obj({"paper": ref("Paper"), "group_ids": ID_LIST}, ("paper", "group_ids")), params=(PAPER_ID,))},
    "/api/paper-page": {"get": operation("Read a page of visible papers",
        obj({"papers": array(ref("Paper")), "next_after": nullable(ID)}, ("papers", "next_after")), params=(AFTER,))},
    "/api/paper-access": {"post": operation("Change sharing for a paper you own", acknowledgement(),
        body=obj({"paper_id": ID, "audience": AUDIENCE, "recipients": RECIPIENTS, "allow_title": BOOLEAN},
                 ("paper_id", "audience")))},
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
    "/api/papers": {"post": operation("Import a PDF",
        obj({"paper_id": ID, "metrics": COUNT, "has_text": BOOLEAN}, ("paper_id", "metrics", "has_text")),
        body=BINARY, request_type="application/pdf",
        params=(param("X-Paper-Filename", STRING, location="header", required=True, description="Percent-encoded PDF filename."),
                param("X-Paper-Audience", AUDIENCE, location="header"),
                param("X-Paper-Recipients", STRING, location="header", description="Percent-encoded JSON array of usernames."),
                param("X-Paper-Metric-Keywords", STRING, location="header", description="Percent-encoded JSON array of up to 20 literal keyword phrases.")))},
    "/papers/{paper_id}/source.pdf": {"get": operation("Download a visible PDF", BINARY,
        params=(param("paper_id", ID, location="path", required=True), param("download", enum("1"))),
        response_type="application/pdf")},
    "/api/documents": {
        "get": operation("List visible documents",
            obj({"documents": array(ref("Document")), "comments": array(ref("Comment")),
                 "papers": array(ref("Paper")), "account": nullable(ref("Account"))}, ("documents",)),
            params=(param("content", enum("summary")), param("comments", enum("none")))),
        "post": operation("Create or update a document", acknowledgement("document_id", "revision", document_id=ID, revision=ID),
            body=obj({"document_id": ID, "revision": ID, "title": STRING, "markdown": STRING,
                      "audience": AUDIENCE, "recipients": RECIPIENTS}, ("title", "markdown"))),
    },
    "/api/document": {"get": operation("Read a visible document", obj({"document": ref("Document")}, ("document",)),
        params=(param("id", ID, required=True),))},
    "/api/document-comments": {"get": operation("Read visible document discussion", COMMENTS_PAGE, params=(DOCUMENT_ID, BEFORE))},
    "/api/paper-comments": {"get": operation("Read visible paper discussion", COMMENTS_PAGE, params=(PAPER_ID, BEFORE))},
    "/api/comments": {"post": operation("Post, reply to, or edit a comment", acknowledgement("comment_id", comment_id=ID),
        body=obj({"paper_id": ID, "document_id": ID, "comment_id": ID, "parent_id": ID, "finding_id": ID, "goal_id": ID,
                  "body": STRING, "audience": AUDIENCE, "recipients": RECIPIENTS, "doi_refs": array(STRING),
                  "location": obj({"kind": enum("pdf", "document"), "id": ID, "position": ID}, ("kind", "id", "position"))},
                 ("body",)), description="Choose exactly one of paper_id and document_id.")},
    "/api/delete-comment": {"post": operation("Delete a comment you authored", acknowledgement(),
        body=obj({"paper_id": ID, "document_id": ID, "comment_id": ID}, ("comment_id",)),
        description="Choose exactly one of paper_id and document_id.")},
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
        "post": operation("Propose a goal or advance its workflow", acknowledgement("id", id=ID, revision=ID,
                                                                                   brief_id=ID, experiment_id=ID, decision_id=ID),
            description="Rank, confirm, decide, and revise_design require the human workspace owner.",
            body={"oneOf": [
                obj({"action": enum(action), "document_id": ID, **fields},
                    ("action", "document_id", *fields))
                for action, fields in (
                    ("propose", {"question": STRING, "rationale": STRING, "uncertainty": STRING, "evidence_ids": ID_LIST}),
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
             "can_edit": BOOLEAN, "brief": nullable(obj())}, ("experiment", "runs", "items", "can_edit", "brief")),
        params=(param("id", ID, required=True),))},
    "/api/experiment-runs": {"post": operation("Create or update a run", acknowledgement("id", id=ID),
        body=obj(RUN_FIELDS, ("experiment_id", "title")), description="Updates require id and revision.")},
    "/api/research-grants": {"post": operation("Set named readers and editors for a research item you own",
        acknowledgement(), body=obj({"id": ID, "kind": enum("experiment", "run", "item", "tool"),
                                     "readers": RECIPIENTS, "editors": RECIPIENTS}, ("id", "kind")))},
    "/api/research-items": {"post": operation("Record an artifact or another version without uploading bytes",
        acknowledgement("id", id=ID), body=ref("ArtifactInput"), description="New versions require id and revision.")},
    "/api/research-upload": {"post": operation("Upload an artifact or another version", acknowledgement("id", id=ID),
        params=(param("X-Research-Metadata", STRING, location="header", required=True,
                      description="Percent-encoded JSON matching ArtifactInput, with filename. New versions require id and revision."),),
        body=BINARY, request_type="application/octet-stream")},
    "/research-versions/{version_id}/file": {"get": operation("Download a visible uploaded artifact version", BINARY,
        params=(param("version_id", ID, location="path", required=True),), response_type="application/octet-stream")},
    "/api/review-agents": {"get": operation("List AI accounts eligible to access the review target",
        obj({"agents": array(obj({"username": STRING, "display_name": STRING, "role": AI_ROLE},
                                 ("username", "display_name", "role")))}, ("agents",)),
        params=(param("kind", REVIEW_KIND, required=True), param("target_id", ID, required=True)),
        description="Requires a human account with access to the target. Eligibility follows source sharing.")},
    "/api/reviews": {
        "get": operation("Read your review requests or pending AI assignments",
            {"oneOf": [REVIEW_DETAIL, REVIEW_LIST]},
            params=(param("id", ID, description="Return one request, including thread context for the assigned AI."),
                    param("kind", REVIEW_KIND), param("target_id", ID)),
            description="AI accounts receive up to 30 pending assignments in creation order. Human accounts receive up to 30 of their own requests, newest first. Supply kind and target_id together to filter by source."),
        "post": operation("Request a review or return an assigned review result",
            acknowledgement("review", review=REVIEW), body={"oneOf": [
                obj({"action": enum("create"), "kind": REVIEW_KIND, "target_id": ID, "position": nullable(ID),
                     "agent": STRING, "agent_role": AI_ROLE, "post": BOOLEAN},
                    ("action", "kind", "target_id", "agent", "agent_role")),
                obj({"action": enum("complete"), "id": ID, "status": enum("complete", "failed"), "response": STRING},
                    ("action", "id", "status", "response")),
            ]}),
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
