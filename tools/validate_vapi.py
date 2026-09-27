"""Check the Vapi assistant config we send against Vapi's official OpenAPI spec.

Vapi rejects unknown or renamed fields, and it has renamed fields before (silenceTimeoutSeconds and
messagePlan moved into hooks). Run this after changing backend/vapi_config.py or when Vapi ships changes:

  python -m tools.validate_vapi                   # downloads the spec from Vapi's public docs repo
  python -m tools.validate_vapi --spec spec.json  # use a local copy
"""
import argparse
import json
import os
import sys
import urllib.request

SPEC_URL = "https://raw.githubusercontent.com/VapiAI/docs/main/fern/apis/api/openapi.json"


class Checker:
    def __init__(self, spec: dict):
        self.S = spec["components"]["schemas"]
        self.errors: list[str] = []

    def resolve(self, sch: dict) -> dict:
        while "$ref" in sch:
            sch = self.S[sch["$ref"].split("/")[-1]]
        if "allOf" in sch and len(sch["allOf"]) == 1:
            return self.resolve(sch["allOf"][0])
        return sch

    def options(self, sch: dict) -> list[dict]:
        sch = self.resolve(sch)
        for k in ("oneOf", "anyOf"):
            if k in sch:
                out = []
                for o in sch[k]:
                    out += self.options(o)
                return out
        return [sch]

    def matches(self, value, sch: dict) -> list[str]:
        """Return the errors for value against one concrete schema."""
        errs: list[str] = []
        self._check(value, sch, "$", errs)
        return errs

    def check(self, value, sch: dict, path: str):
        self._check(value, sch, path, self.errors)

    def _check(self, value, sch: dict, path: str, errs: list[str]):
        opts = self.options(sch)
        if len(opts) > 1:
            results = [self.matches(value, o) for o in opts]
            if not any(len(r) == 0 for r in results):
                best = min(results, key=len)
                errs.append(f"{path}: matches none of {len(opts)} variants; closest: {best[:3]}")
            return
        sch = opts[0]
        t = sch.get("type")
        if t == "array" and "enum" in sch and isinstance(value, list):  # enum on the array = allowed items
            bad = [v for v in value if v not in sch["enum"]]
            if bad:
                errs.append(f"{path}: {bad} not allowed")
            return
        if "enum" in sch and value not in sch["enum"]:
            errs.append(f"{path}: {value!r} not in {sch['enum'][:12]}")
            return
        if t == "object" or "properties" in sch:
            if not isinstance(value, dict):
                errs.append(f"{path}: expected object, got {type(value).__name__}")
                return
            props = sch.get("properties") or {}
            for req in sch.get("required") or []:
                if req not in value:
                    errs.append(f"{path}: missing required field '{req}'")
            if props:
                for k, v in value.items():
                    if k not in props:
                        errs.append(f"{path}.{k}: unknown field (Vapi would reject it)")
                    else:
                        self._check(v, props[k], f"{path}.{k}", errs)
        elif t == "array":
            if not isinstance(value, list):
                errs.append(f"{path}: expected array")
                return
            for i, v in enumerate(value):
                self._check(v, sch.get("items") or {}, f"{path}[{i}]", errs)
        elif t == "string":
            if not isinstance(value, str):
                errs.append(f"{path}: expected string, got {type(value).__name__} {value!r}")
        elif t in ("number", "integer"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errs.append(f"{path}: expected number, got {value!r}")
                return
            if "minimum" in sch and value < sch["minimum"]:
                errs.append(f"{path}: {value} below minimum {sch['minimum']}")
            if "maximum" in sch and value > sch["maximum"]:
                errs.append(f"{path}: {value} above maximum {sch['maximum']}")
        elif t == "boolean" and not isinstance(value, bool):
            errs.append(f"{path}: expected boolean")


def validate(assistant: dict, spec: dict) -> list[str]:
    c = Checker(spec)
    c.check(assistant, {"$ref": "#/components/schemas/CreateAssistantDTO"}, "assistant")
    return c.errors


def sample_assistant() -> dict:
    os.environ.setdefault("PUBLIC_URL", "https://example.onrender.com")
    from backend import brain
    from backend.vapi_config import build_assistant
    plan = brain.normalize_plan(brain._mock_plan({"questions": ["Why?"], "duration_min": 15}))
    plan["keyterms"] = ["Spring Boot", "Kafka"]
    return build_assistant("abc123", plan, brain.opening_message(plan), "tok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec")
    a = ap.parse_args()
    if a.spec:
        spec = json.load(open(a.spec))
    else:
        with urllib.request.urlopen(SPEC_URL, timeout=60) as r:
            spec = json.load(r)
    failed = False
    for mode in ("smart", "patient"):
        os.environ["ENDPOINTING_MODE"] = mode
        errs = validate(sample_assistant(), spec)
        print(f"[{mode}] {'OK' if not errs else 'ERRORS'}")
        for e in errs:
            print("  -", e)
        failed |= bool(errs)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
