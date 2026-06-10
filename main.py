import logging
import sys
from pathlib import Path

from agent.orchestrator import AgentOrchestrator
from config import DEFAULT_SEARCH_CONFIG, load_settings
from output.writer import print_summary, write_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> int:
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    config = DEFAULT_SEARCH_CONFIG
    orchestrator = AgentOrchestrator(settings)

    print("Starting JobFindr search...")
    print(f"  Worker:   {settings.worker_url}")
    if not config.direct_targets:
        print("  Note: stealth worker must be running (cd worker && npm start)")
    print(f"  Role:        {config.role}")
    print(f"  Location:    {config.location}")
    print(f"  Experience:  {config.experience or 'any'}")
    post_window = (
        f"last {config.posted_within_days} days"
        if config.posted_within_days is not None
        else "any time"
    )
    print(f"  Posted:      {post_window}")
    print(f"  Profile:     {config.company_profile}")

    if config.resume_enabled:
        resume_path = Path(config.resume_path)
        if resume_path.exists() and resume_path.read_text(encoding="utf-8").strip():
            print(
                f"  Resume:      {config.resume_path} "
                f"(scoring enabled, deep threshold >{config.resume_deep_threshold})"
            )
        else:
            print(f"  Resume:      not found at {config.resume_path} (scoring disabled)")
    else:
        print("  Resume:      scoring disabled in config")

    result = orchestrator.run(config)
    output_path = write_results(result)
    print_summary(result, output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
