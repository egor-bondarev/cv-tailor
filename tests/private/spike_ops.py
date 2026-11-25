"""Turn spike meta.json (prefix-addressed ops) into Op objects for a parsed resume."""

from cvtailor.models import Op, ParsedResume


def spike_ops(resume: ParsedResume, meta: dict) -> list[Op]:
    ops = []
    for spec in meta["ops"]:
        [block] = [b for b in resume.blocks if b.text.startswith(spec["prefix"])]
        fields = {k: v for k, v in spec.items() if k not in ("prefix",)}
        key = "after" if spec["op"] == "insert_after" else "block"
        ops.append(Op(**fields, **{key: block.id}))
    return ops
