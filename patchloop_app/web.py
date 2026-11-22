"""PatchLoop web app: the interactive entry point of the agent system.

    python -m patchloop_app.web --port 7860 --runs-dir /data/app-runs

Open http://127.0.0.1:7860 (through an SSH tunnel, or see --host/--token).
Needs at least one backend: DEEPSEEK_API_KEY in .env (no GPU) and/or the local
vLLM server (scripts/start_qwen_small.sh). Settings come from .env exactly as for
the batch experiments.
"""
from __future__ import annotations

import argparse
import hmac
import os
import shutil
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, render_template, request

from patchloop_app.session import Request, SessionManager

TOKEN_COOKIE = "patchloop_token"


def create_app(manager: SessionManager, *, health=None, tasks=None, token: str | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).with_name("templates")))
    tasks = tasks or []
    by_id = {t.instance_id: t for t in tasks}

    def default_backend() -> str:
        # A request without "backend" uses qwen if configured, else the only one there is
        # (e.g. a DeepSeek-only deployment without a GPU).
        factories = manager.backend_factory
        if isinstance(factories, dict) and factories and "qwen" not in factories:
            return next(iter(factories))
        return "qwen"

    @app.before_request
    def check_token():
        if not token:
            return None
        given = request.args.get("token") or request.cookies.get(TOKEN_COOKIE) or ""
        if not hmac.compare_digest(given, token):
            return Response("Access token required: open /?token=...", status=401)
        return None

    @app.after_request
    def remember_token(resp):
        if token and request.args.get("token"):
            resp.set_cookie(TOKEN_COOKIE, token, httponly=True, samesite="Strict")
        return resp

    def fail(message, status=400):
        return jsonify({"error": message}), status

    @app.get("/")
    def index():
        return render_template("patchloop.html")

    @app.get("/api/health")
    def api_health():
        try:
            return jsonify(health() if health else {"status": "unknown"})
        except Exception as exc:
            return jsonify({"status": "down", "error": f"{type(exc).__name__}: {exc}"[:300]}), 503

    @app.get("/api/tasks")
    def api_tasks():
        return jsonify([{"instance_id": t.instance_id, "repo": t.repo,
                         "title": t.problem_statement.strip().splitlines()[0][:120]} for t in tasks])

    @app.get("/api/tasks/<iid>")
    def api_task(iid):
        if iid not in by_id:
            return fail("unknown task", 404)
        t = by_id[iid]
        return jsonify({"instance_id": t.instance_id, "repo": t.repo, "base_commit": t.base_commit,
                        "issue": t.problem_statement})

    @app.post("/api/sessions")
    def api_start():
        body = request.get_json(force=True, silent=True) or {}
        try:
            req = Request(
                issue=str(body.get("issue", "")), source=str(body.get("source", "swebench")),
                instance_id=body.get("instance_id"), repo_path=body.get("repo_path"),
                commit=str(body.get("commit") or "HEAD"), agent=str(body.get("agent", "pcr")),
                edit_format=str(body.get("edit_format", "search_replace")),
                retrieval_k=int(body.get("retrieval_k", 10)),
                skip_clarification=bool(body.get("skip_clarification", False)),
                exec_feedback=bool(body.get("exec_feedback", False)),
                reasoning_effort=str(body.get("reasoning_effort") or "none"),
                snippet_name=(str(body["snippet_name"]).strip() if body.get("snippet_name") else None),
                snippet_code=(str(body["snippet_code"]) if body.get("snippet_code") else None),
                backend=str(body.get("backend") or default_backend()),
            )
            session = manager.start(req)
        except (ValueError, TypeError) as exc:
            return fail(str(exc))
        return jsonify(session.view())

    @app.get("/api/sessions")
    def api_list():
        rows = sorted(manager.sessions.values(), key=lambda s: s.created, reverse=True)
        return jsonify([{"id": s.id, "status": s.status, "round": s.round, "parent": s.parent,
                         "agent": s.request.agent, "source": s.request.source,
                         "title": (s.request.issue.strip().splitlines() or [""])[0][:90],
                         "target": s.request.instance_id or s.request.repo_path
                         or (f"pasted {s.request.snippet_name}" if s.request.snippet_name else "")}
                        for s in rows[:30]])

    @app.get("/api/sessions/<sid>")
    def api_get(sid):
        try:
            return jsonify(manager.get(sid).view(int(request.args.get("since", 0))))
        except KeyError:
            return fail("unknown session", 404)

    def decision(sid, action):
        try:
            return jsonify(getattr(manager, action)(sid))
        except KeyError:
            return fail("unknown session", 404)
        except ValueError as exc:
            return fail(str(exc))

    @app.post("/api/sessions/<sid>/accept")
    def api_accept(sid):
        return decision(sid, "accept")

    @app.post("/api/sessions/<sid>/reject")
    def api_reject(sid):
        return decision(sid, "reject")

    @app.post("/api/sessions/<sid>/cancel")
    def api_cancel(sid):
        return decision(sid, "cancel")

    @app.post("/api/sessions/<sid>/followup")
    def api_followup(sid):
        body = request.get_json(force=True, silent=True) or {}
        try:
            changes = {k: body.get(k) for k in ("agent", "edit_format", "backend", "exec_feedback",
                                                "reasoning_effort")}
            if body.get("retrieval_k") is not None:
                changes["retrieval_k"] = int(body["retrieval_k"])
            session = manager.follow_up(sid, str(body.get("guidance", "")), **changes)
        except KeyError:
            return fail("unknown session", 404)
        except (ValueError, TypeError) as exc:
            return fail(str(exc))
        return jsonify(session.view())

    @app.get("/api/sessions/<sid>/patch")
    def api_patch(sid):
        try:
            session = manager.get(sid)
        except KeyError:
            return fail("unknown session", 404)
        if not session.patch:
            return fail("no patch", 404)
        resp = make_response(session.patch)
        resp.headers["Content-Type"] = "text/x-diff; charset=utf-8"
        resp.headers["Content-Disposition"] = f"attachment; filename=patchloop-{sid}.patch"
        return resp

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PatchLoop interactive repair agent (web UI)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 (default; use an SSH tunnel). 0.0.0.0 REQUIRES --token")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--runs-dir", default=os.environ.get("PATCHLOOP_APP_RUNS", "/data/app-runs"))
    parser.add_argument("--token", default=os.environ.get("PATCHLOOP_APP_TOKEN"),
                        help="access token (also PATCHLOOP_APP_TOKEN); required when not on 127.0.0.1")
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite",
                        help="dev split offered as ready-made example tasks")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost") and not args.token:
        parser.error("Refusing to listen on a public interface without --token")

    from patchloop_task2.backends import BACKENDS, load_settings, make_backend
    from swebench_dev import load_dev_tasks

    configured, problems = {}, {}
    for name in BACKENDS:
        try:
            settings = load_settings(name)
            make_backend(name, settings).verify()
            configured[name] = settings
        except Exception as exc:  # report and continue with the other backend
            problems[name] = f"{type(exc).__name__}: {exc}"[:200]
            print(f"backend {name} unavailable: {problems[name]}")
    if not configured:
        parser.error("No model backend is available (start vLLM and/or set DEEPSEEK_API_KEY)")
    try:
        tasks = load_dev_tasks(args.dataset)
    except Exception as exc:  # the app still works on local repositories
        print(f"Example tasks unavailable ({type(exc).__name__}); local repositories still work")
        tasks = []
    by_id = {t.instance_id: t for t in tasks}

    def lookup(iid):
        if iid not in by_id:
            raise ValueError(f"Unknown example task {iid}")
        return by_id[iid]

    def factory_for(name, settings):
        def factory(reasoning_effort=None):
            # A request may switch DeepSeek thinking on (RQ1); budgets follow backends.REASONING_DEFAULTS.
            if reasoning_effort in (None, "none"):
                return make_backend(name, settings)
            return make_backend(name, load_settings(name, reasoning_effort=reasoning_effort))
        return factory

    factories = {name: factory_for(name, st) for name, st in configured.items()}
    manager = SessionManager(args.runs_dir, factories, task_lookup=lookup)

    def health():
        return {"status": "ok", "backends": {
            name: {"model": st.model, "context_chars": st.context_chars, "max_calls": st.max_calls,
                   "data_leaves_server": name == "deepseek"} for name, st in configured.items()},
            "unavailable": problems,
            "tests": {"docker": bool(shutil.which("docker")),
                      "local_image": os.environ.get("PATCHLOOP_TEST_IMAGE") or None}}

    app = create_app(manager, health=health, tasks=tasks, token=args.token)
    print(f"PatchLoop web app on http://{args.host}:{args.port}  (runs in {args.runs_dir})")
    app.run(host=args.host, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
