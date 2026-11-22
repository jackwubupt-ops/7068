"""Planner handoff used by the repair pipelines: issue -> localized repair plan."""


def run_localization(issue, repo_root, base_commit, **kwargs):
    """Run the Planner (prompt_agent.plan_repair) with bounded read-only tools."""
    from prompt_agent import plan_repair
    return plan_repair(issue, repo_root, base_commit, **kwargs)
