"""Public HTTP operations for workstation-based research clients."""

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
              response_type="application/json", description=None):
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
    return result


def acknowledgement(*required, **fields):
    return obj({"ok": schema("boolean", const=True), **fields}, ("ok", *required))


STRING = schema("string")
BOOLEAN = schema("boolean")
COUNT = schema("integer", minimum=0)
ID = schema("integer", format="int64", minimum=1)
BINARY = schema("string", format="binary")
AUDIENCE = enum(*AUDIENCES)
RECIPIENTS = array(STRING)
ID_LIST = array(ID)
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
    "Account": obj({"id": ID, "role": enum("user", "member", "local", "cloud"), "username": STRING,
                    "display_name": STRING}, ("id", "role", "username")),
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
    "/api/account": {"get": operation("Check the current account",
        obj({"account": nullable(ref("Account")), "google_available": BOOLEAN}, ("account",)))},
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


def document(port):
    return {
        "openapi": "3.1.0",
        "info": {"title": "Paper Library API", "version": "1.0.0",
                 "description": "Shared HTTP interface for Local AI and Cloud AI workstation clients."},
        "servers": [{"url": f"http://127.0.0.1:{port}"}],
        "security": [{"ApplicationKey": []}],
        "paths": PATHS,
        "components": {"schemas": SCHEMAS, "securitySchemes": {
            "ApplicationKey": {"type": "http", "scheme": "bearer", "description": "Application key issued by the library."},
        }},
    }
