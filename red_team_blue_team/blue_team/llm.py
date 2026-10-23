"""A small tool-using agent loop on Amazon Bedrock's Converse API.

Credentials: the Bedrock API key in AWS_BEARER_TOKEN_BEDROCK (boto3 reads it), or normal AWS
credentials. Region: AWS_REGION, else config.yaml. Models are tried in config order until one
answers; Amazon Nova works on free-trial credits without a Marketplace subscription.

The model only ever *drafts*: it calls read-only tools, and its final answer goes through a submit
tool that code validates (CLAUDE.md rule 13). Nothing it writes is executed.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from blue_team import config


FILTERED = "blocked by our content filters"   # Amazon Nova's reply when its own filter fires
MAX_FILTERED = 3
LAST_CALL_TURNS = 2                            # when to tell the agent to submit what it has


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[[dict], dict]

    def spec(self) -> dict:
        return {"toolSpec": {"name": self.name, "description": self.description, "inputSchema": {"json": self.schema}}}


@dataclass
class AgentResult:
    final: dict | None              # the accepted submit-tool input, or None if the agent never got there
    transcript: list[dict] = field(default_factory=list)
    model_id: str = ""
    turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    filtered: int = 0               # replies in a row the model's content filter blocked


def client(region: str | None = None):
    import boto3
    from botocore.config import Config
    cfg = config.load()["agents"]
    return boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION") or cfg["region"],
                        config=Config(retries={"max_attempts": 4, "mode": "standard"}, read_timeout=120))


def connect(models: list[str] | None = None, rt=None, log=None) -> tuple[Any, str]:
    """(bedrock-runtime client, the first model id that answers). Raises LLMUnavailable."""
    from botocore.exceptions import BotoCoreError, ClientError
    models = models or config.load()["agents"]["models"]
    try:
        rt = rt or client()
    except Exception as e:  # noqa: BLE001 (no boto3, no region, ...)
        raise LLMUnavailable(f"cannot create a Bedrock client: {e}") from e
    errors = []
    for m in models:
        try:
            rt.converse(modelId=m, messages=[{"role": "user", "content": [{"text": "Reply: ok"}]}],
                        inferenceConfig={"maxTokens": 5, "temperature": 0})
            return rt, m
        except (ClientError, BotoCoreError) as e:
            errors.append(f"{m}: {str(e)[:160]}")
            if log:
                log(f"agents: skipping {m}: {str(e)[:160]}")
    raise LLMUnavailable("no Bedrock model answered:\n  " + "\n  ".join(errors))


def probe(models: list[str], rt=None) -> list[tuple[str, str]]:
    """(model id, 'ok' or the error) for each model, for `python -m blue_team probe`."""
    from botocore.exceptions import BotoCoreError, ClientError
    rt = rt or client()
    out = []
    for m in models:
        try:
            r = rt.converse(modelId=m, messages=[{"role": "user", "content": [{"text": "Reply: ok"}]}],
                            inferenceConfig={"maxTokens": 5, "temperature": 0})
            out.append((m, "ok (" + r["output"]["message"]["content"][0].get("text", "").strip()[:20] + ")"))
        except (ClientError, BotoCoreError) as e:
            out.append((m, str(e)[:200]))
    return out


def _short(x: Any, n: int = 1500) -> Any:
    s = json.dumps(x, default=str, ensure_ascii=False)
    return x if len(s) <= n else s[:n] + "...(cut)"


def run_agent(rt, model_id: str, system: str, task: str, tools: list[Tool], final: str, max_turns: int) -> AgentResult:
    """Converse until the model calls `final` and its handler accepts the input, or turns run out."""
    cfg = config.load()["agents"]
    by_name = {t.name: t for t in tools}
    messages = [{"role": "user", "content": [{"text": task}]}]
    res = AgentResult(final=None, model_id=model_id)
    for turn in range(max_turns):
        res.turns = turn + 1
        if max_turns - turn == LAST_CALL_TURNS and messages[-1]["role"] == "user":
            messages[-1]["content"].append({"text": f"(Only {LAST_CALL_TURNS} turns left: call {final} now with your "
                                                    "best answer so far.)"})
        t0 = time.perf_counter()
        r = rt.converse(modelId=model_id, system=[{"text": system}], messages=messages,
                        toolConfig={"tools": [t.spec() for t in tools]},
                        inferenceConfig={"maxTokens": cfg["max_tokens"], "temperature": cfg["temperature"]})
        usage = r.get("usage", {})
        res.tokens_in += usage.get("inputTokens", 0)
        res.tokens_out += usage.get("outputTokens", 0)
        msg = r["output"]["message"]
        text = " ".join(c["text"] for c in msg["content"] if "text" in c).strip()
        uses = [c["toolUse"] for c in msg["content"] if "toolUse" in c]
        res.transcript.append({"turn": res.turns, "seconds": round(time.perf_counter() - t0, 1), "text": text,
                               "tool_calls": [{"name": u["name"], "input": _short(u["input"])} for u in uses]})
        if r.get("stopReason") in ("content_filtered", "guardrail_intervened") or FILTERED in text:
            # The model's own safety filter ate the reply. Drop it (the conversation stays valid: the
            # last message is still ours) and ask again, briefly; give up after a few in a row.
            res.filtered += 1
            res.transcript[-1]["filtered"] = True
            if res.filtered >= MAX_FILTERED:
                break
            last = messages[-1]["content"]
            if not any(c.get("text", "").startswith("(Your last reply") for c in last):
                last.append({"text": "(Your last reply was blocked by a content filter. This is fraud-prevention "
                                     "analysis. Reply with a tool call and keep any text short and factual.)"})
            continue
        res.filtered = 0
        messages.append(msg)
        if not uses:
            messages.append({"role": "user", "content": [{"text": f"Keep using the tools, and finish by calling {final}."}]})
            continue
        results = []
        for u in uses:
            tool = by_name.get(u["name"])
            try:
                if tool is None:
                    raise KeyError(f"no tool {u['name']!r}; tools: {sorted(by_name)}")
                out, status = tool.fn(u["input"]), "success"
            except Exception as e:  # noqa: BLE001 (any tool error goes back to the model to fix)
                out, status = {"error": f"{type(e).__name__}: {e}"}, "error"
            if not isinstance(out, dict):
                out = {"result": out}
            res.transcript[-1].setdefault("tool_results", []).append({"name": u["name"], "output": _short(out, 800)})
            results.append({"toolResult": {"toolUseId": u["toolUseId"], "content": [{"json": out}], "status": status}})
            if u["name"] == final and status == "success" and out.get("accepted"):
                res.final = u["input"]
        messages.append({"role": "user", "content": results})
        if res.final is not None:
            break
    return res
