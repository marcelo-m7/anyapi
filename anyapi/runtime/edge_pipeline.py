"""Central Supabase Edge Function pipeline; no user code or arbitrary destination URLs."""
from __future__ import annotations
import re
import os
import time
import requests
from .paths import render_template
from .schema import validate
from .code_runner import RunnerError

SLUG=re.compile(r"^[a-z][a-z0-9-]{1,62}$")
MAX_STEPS=8
STEP_REF=re.compile(r"\{\{\s*steps\.([a-z][a-z0-9_]*)\.")

def _step_refs(value):
    if isinstance(value,str): return set(STEP_REF.findall(value))
    if isinstance(value,list): return set().union(*(_step_refs(v) for v in value)) if value else set()
    if isinstance(value,dict): return set().union(*(_step_refs(v) for v in value.values())) if value else set()
    return set()


def validate_pipeline(processor, catalog):
    errors=[]
    if not isinstance(processor,dict) or processor.get("type")!="edge_pipeline":
        return [{"path":"processor.type","message":"Expected edge_pipeline"}]
    steps=processor.get("steps")
    if not isinstance(steps,list) or not 1<=len(steps)<=MAX_STEPS:
        return [{"path":"processor.steps","message":"Pipeline requires 1 to 8 steps"}]
    identifiers=set()
    for i,step in enumerate(steps):
        previous_ids=set(identifiers)
        if not isinstance(step,dict):
            errors.append({"path":f"processor.steps[{i}]","message":"Expected object"});continue
        identifier=step.get("id")
        slug=step.get("function")
        if not isinstance(identifier,str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,30}",identifier) or identifier in identifiers:
            errors.append({"path":f"processor.steps[{i}].id","message":"Unique lowercase identifier required"})
        else: identifiers.add(identifier)
        if not isinstance(slug,str) or slug not in catalog:
            errors.append({"path":f"processor.steps[{i}].function","message":"Function is not registered or enabled"})
        arguments=step.get("arguments")
        future=_step_refs(arguments)-previous_ids
        if future: errors.append({"path":f"processor.steps[{i}].arguments","message":"Arguments reference a current, future or unknown step: "+",".join(sorted(future))})
        if not isinstance(arguments,dict):
            errors.append({"path":f"processor.steps[{i}].arguments","message":"Expected mapping object"})
        if step.get("on_error","stop") not in ("stop","continue"):
            errors.append({"path":f"processor.steps[{i}].on_error","message":"Invalid failure policy"})
    unknown_output=_step_refs(processor.get("output"))-identifiers
    if unknown_output: errors.append({"path":"processor.output","message":"Output references unknown step: "+",".join(sorted(unknown_output))})
    return errors

def run_pipeline(processor,input_data,context,catalog,settings,deadline,log):
    problems=validate_pipeline(processor,catalog)
    if problems: raise RunnerError("Invalid pipeline configuration","invalid_processor")
    state={"input":input_data,"steps":{},"context":context}
    for position,step in enumerate(processor["steps"]):
        if time.monotonic()>=deadline: raise RunnerError("Pipeline time limit exceeded","timeout")
        slug=step["function"]
        record=catalog[slug]
        args=render_template(step["arguments"],state)
        invalid=validate(args,record["input_schema"])
        if invalid: raise RunnerError(f"Arguments for step {position+1} violate schema","input_validation")
        remaining=deadline-time.monotonic()
        if remaining <= 0:
            raise RunnerError("Pipeline execution timed out","timeout")
        remaining=min(remaining,8.0)
        if not settings.supabase_url.startswith("https://"):
            raise RunnerError("Supabase HTTPS URL is required","runtime_unavailable")
        endpoint=f"{settings.supabase_url}/functions/v1/{slug}"
        api_key=settings.supabase_service_key
        key=os.getenv("ANYAPI_EDGE_FUNCTION_JWT") or api_key
        if not api_key or not key or key.count(".")!=2:
            raise RunnerError("A valid server-side JWT is required for Edge Function invocation","runtime_unavailable")
        # All destinations come from the server-owned registry; never from users.
        try:
            response=requests.post(endpoint,json=args,headers={"apikey":api_key,"Authorization":"Bearer "+key},timeout=remaining,allow_redirects=False)
            if response.is_redirect: raise RunnerError("Function redirects are prohibited","upstream_error")
            if len(response.content)>1_000_000: raise RunnerError("Function response too large","upstream_error")
            envelope=response.json()
        except (requests.RequestException,ValueError) as exc:
            raise RunnerError("Edge Function request failed","upstream_error") from exc
        if not isinstance(envelope,dict) or type(envelope.get("success")) is not bool or not isinstance(envelope.get("meta"),dict) or "data" not in envelope or "error" not in envelope:
            raise RunnerError("Edge Function returned an invalid envelope","upstream_error")
        if response.status_code>=400 or not envelope["success"]:
            log("warn",f"Step {step['id']} failed")
            if step.get("on_error","stop")=="continue":
                state["steps"][step["id"]]=envelope
                continue
            raise RunnerError("Edge Function failed at step "+step["id"],"upstream_error")
        if validate(envelope["data"],record["output_schema"]):
            raise RunnerError("Edge Function output schema mismatch","output_validation")
        state["steps"][step["id"]]=envelope
        log("info",f"Completed {step['id']} ({slug})")
    output=render_template(processor.get("output", "{{steps."+processor["steps"][-1]["id"]+".data}}"),state)
    return output
