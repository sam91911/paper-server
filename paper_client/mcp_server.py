"""Expose a small set of Paper Library operations over local MCP stdio."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

from .agent import AgentClient
from .review import LibraryError


VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
ID = {"type": "integer", "minimum": 1, "maximum": 2**63 - 1}
TOOLS = {
    "search_papers": ("Search papers visible to the enrolled account.", {
        "query": {"type": "string", "maxLength": 500}, "page": ID,
    }, ()),
    "read_paper": ("Read publication metadata and PDF availability for a visible paper.", {
        "paper_id": ID,
    }, ("paper_id",)),
    "read_comments": ("Read a page of comments visible to the enrolled account.", {
        "paper_id": ID, "before": ID,
    }, ("paper_id",)),
    "post_comment": ("Post a comment as the enrolled account. The default audience is owner only.", {
        "paper_id": ID, "parent_id": ID, "body": {"type": "string", "maxLength": 20000},
        "audience": {"type": "string", "enum": ["owner", "users", "local", "all"]},
    }, ("paper_id", "body")),
}


def tool_specs(allow_comments):
    return [
        {
            "name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": list(required), "additionalProperties": False},
            "annotations": {"readOnlyHint": name != "post_comment", "openWorldHint": False},
        }
        for name, (description, properties, required) in TOOLS.items()
        if allow_comments or name != "post_comment"
    ]


def call_tool(client, name, args, allow_comments):
    if not isinstance(name, str) or name not in TOOLS or (name == "post_comment" and not allow_comments):
        raise ValueError("Unknown tool.")
    _, properties, required = TOOLS[name]
    if not isinstance(args, dict) or args.keys() - properties.keys() or set(required) - args.keys():
        raise ValueError("Provide the arguments listed in the tool schema.")
    for key, value in args.items():
        schema = properties[key]
        if schema["type"] == "integer":
            valid = type(value) is int and 1 <= value <= ID["maximum"]
        else:
            valid = isinstance(value, str) and len(value) <= schema.get("maxLength", 20000)
        if not valid or ("enum" in schema and value not in schema["enum"]):
            raise ValueError(f"Invalid argument {key}.")
    if name == "search_papers":
        query = urlencode({"q": args.get("query", ""), "page": args.get("page", 1)})
        return client.get_json(f"/api/paper-catalog?{query}")
    if name == "read_paper":
        return client.get_json(f"/api/paper-detail?{urlencode(args)}")
    if name == "read_comments":
        return client.get_json(f"/api/paper-comments?{urlencode(args)}")
    return json.loads(client.request("/api/comments", {"audience": "owner", **args}))


def reply(client, request, allow_comments=False):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    if "id" not in request:
        return None
    envelope = {"jsonrpc": "2.0", "id": request["id"]}
    method = request["method"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        return {**envelope, "error": {"code": -32602, "message": "Invalid params"}}
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {"protocolVersion": version if version in VERSIONS else VERSIONS[0],
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "paper-library", "version": "0.1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_specs(allow_comments)}
    elif method == "tools/call":
        try:
            data = call_tool(client, params.get("name"), params.get("arguments", {}), allow_comments)
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
        except (LibraryError, OSError, ValueError, KeyError) as error:
            result = {"isError": True, "content": [{"type": "text", "text": str(error)}]}
    else:
        return {**envelope, "error": {"code": -32601, "message": "Method not found"}}
    return {**envelope, "result": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--allow-comments", action="store_true")
    args = parser.parse_args()
    try:
        client = AgentClient.from_identity(args.identity.expanduser())
    except (OSError, ValueError, KeyError, TypeError):
        parser.error("Could not load the enrolled Paper Library identity. Check the path and file permissions.")
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            response = reply(client, request, args.allow_comments)
        if response is not None:
            print(json.dumps(response, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
