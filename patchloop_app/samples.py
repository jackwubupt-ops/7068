"""Run the sample requests in samples/ headlessly and save their traces.

    python -m patchloop_app.samples --backend deepseek --out results/samples
    python -m patchloop_app.samples --backend qwen --out results/samples-qwen 01_ordinary

Each sample goes through the SAME SessionManager as the web app (clarification
rule, agent run, stop states). For every sample this writes:
  <out>/<name>.json  the full session views (request, every event, result, patch)
  <out>/<name>.md    a readable trace for the report / submission
Samples never auto-accept a patch: the human-confirmation step is left pending.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from patchloop_app.session import Request, SessionManager

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


def load_samples(names: list[str] | None = None) -> list[dict]:
    samples = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SAMPLES_DIR.glob("*.json"))]
    if names:
        samples = [s for s in samples if s["name"] in names]
    return samples


def build_request(spec: dict, backend: str, task_lookup) -> Request:
    fields = dict(spec)
    if fields.get("issue") == "@task":
        fields["issue"] = task_lookup(fields["instance_id"]).problem_statement
    return Request(backend=backend, **fields)


def to_markdown(sample: dict, views: list[dict]) -> str:
    out = [f"# Sample {sample['name']}: {sample['kind']}", "", sample["description"], "",
           f"**Expected:** {sample['expect']}", ""]
    for view in views:
        req, res = view["request"], view["result"]
        out += [f"## Session {view['id']} (round {view['round']}) -> `{view['status']}`", "",
                f"- model backend: `{req['backend']}`, agent: `{req['agent']}`, retrieval_k: {req['retrieval_k']}",
                f"- tokens: {res.get('prompt_tokens')} prompt / {res.get('completion_tokens')} completion; "
                f"duration: {res.get('duration_seconds')} s; run status: `{res.get('status')}`", ""]
        if view["questions"]:
            out += ["Questions asked:", ""] + [f"- {q}" for q in view["questions"]] + [""]
        out += ["| t (s) | kind | step |", "|---|---|---|"]
        for e in view["events"]:
            if e["kind"] == "thinking":
                continue
            title = e["title"].replace("|", "\\|")
            out.append(f"| {e['t']} | {e['kind']} | {title} |")
        out.append("")
        if view["patch"]:
            out += ["Patch awaiting the user's confirmation:", "", "```diff", view["patch"].rstrip(), "```", ""]
    return "\n".join(out) + "\n"


def run_sample(manager: SessionManager, sample: dict, backend: str, task_lookup) -> list[dict]:
    session = manager.start(build_request(sample["request"], backend, task_lookup), run_async=False)
    views = [session.view()]
    follow = sample.get("follow_up")
    if follow and session.status not in ("failed", "cancelled"):
        changes = {k: v for k, v in follow.items() if k != "guidance"}
        if session.status == "awaiting_confirmation":
            manager.reject(session.id)  # the maintainer asks for a different fix instead
            views[0] = session.view()
        second = manager.follow_up(session.id, follow.get("guidance", ""), run_async=False, **changes)
        views.append(second.view())
    return views


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("names", nargs="*", help="sample names (default: all)")
    parser.add_argument("--backend", choices=("qwen", "deepseek"), default="deepseek")
    parser.add_argument("--out", type=Path, default=Path("results/samples"))
    parser.add_argument("--runs-dir", type=Path, default=Path("/data/app-runs/samples"))
    args = parser.parse_args(argv)

    from patchloop_task2.backends import load_settings, make_backend
    from swebench_dev import load_dev_tasks

    settings = load_settings(args.backend)
    by_id = {t.instance_id: t for t in load_dev_tasks("princeton-nlp/SWE-bench_Lite")}

    def lookup(iid):
        if iid not in by_id:
            raise ValueError(f"Unknown example task {iid}")
        return by_id[iid]

    manager = SessionManager(args.runs_dir, {args.backend: lambda: make_backend(args.backend, settings)},
                             task_lookup=lookup)
    args.out.mkdir(parents=True, exist_ok=True)
    for sample in load_samples(args.names):
        t0 = time.monotonic()
        views = run_sample(manager, sample, args.backend, lookup)
        (args.out / f"{sample['name']}.json").write_text(
            json.dumps({"sample": sample, "backend": args.backend, "model": settings.model,
                        "sessions": views}, indent=2, ensure_ascii=False), encoding="utf-8")
        (args.out / f"{sample['name']}.md").write_text(to_markdown(sample, views), encoding="utf-8")
        print(f"{sample['name']:22s} -> {' / '.join(v['status'] for v in views)}  "
              f"({time.monotonic() - t0:.0f}s)")
    print(f"traces written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
