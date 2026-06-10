import json
from datetime import datetime, timezone
from pathlib import Path

from agent.usage_tracker import format_bytes
from models.job import SearchResult

RESULTS_DIR = Path("results")


def write_results(result: SearchResult) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = RESULTS_DIR / f"{timestamp}.json"

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2)

    return output_path


def print_summary(result: SearchResult, output_path: Path, top_n: int = 10) -> None:
    print("\n=== JobFindr Search Results ===")
    print(f"Role:        {result.config_role}")
    print(f"Location:    {result.config_location}")
    print(f"Experience:  {result.config_experience or 'any'}")
    post_window = (
        f"last {result.config_posted_within_days} days"
        if result.config_posted_within_days is not None
        else "any time"
    )
    print(f"Posted:      {post_window}")
    print(f"Profile:     {result.config_company_profile}")
    if result.vc_firms_used:
        vc_preview = ", ".join(result.vc_firms_used[:3])
        if len(result.vc_firms_used) > 3:
            vc_preview += "..."
        print(f"VC firms:        {len(result.vc_firms_used)} ({vc_preview})")
        print(f"Target companies: {result.target_companies_count} (see data/target_companies.json)")
    print(f"Companies discovered: {result.companies_discovered}")
    print(f"Companies with ATS:   {result.companies_with_ats}")
    print(f"Total jobs found:     {len(result.jobs)}")

    if result.resume_scoring_enabled:
        cache_note = "cached" if result.resume_cache_used else "inline"
        print(
            f"Resume scoring:       {result.jobs_title_scored} title-scored, "
            f"{result.jobs_full_scored} full-description scored ({cache_note} resume)"
        )

    if result.ats_breakdown:
        breakdown = ", ".join(f"{k}: {v}" for k, v in result.ats_breakdown.items())
        print(f"ATS breakdown:        {breakdown}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for err in result.errors:
            print(f"  - {err.company}: {err.error}")

    if result.jobs:
        print(f"\nTop {min(top_n, len(result.jobs))} listings:")
        for i, job in enumerate(result.jobs[:top_n], start=1):
            if job.qualify_score is not None:
                score_label = f"{job.qualify_score}/100"
                if job.match_score is not None:
                    score_label += f" (match {job.match_score:.2f})"
            elif job.match_score is not None:
                score_label = f"{job.match_score:.2f}"
            else:
                score_label = "n/a"
            location = job.location or "Unknown"
            posted = job.posted_at.strftime("%Y-%m-%d") if job.posted_at else "unknown"
            print(f"  {i}. [{score_label}] {job.title} @ {job.company} ({location}, posted {posted})")
            if job.qualify_rationale:
                print(f"     {job.qualify_rationale}")
            print(f"     {job.apply_url}")

    print("\n--- Usage ---")
    tokens = result.usage.tokens
    proxy = result.usage.proxy
    print(
        f"AI tokens:  {tokens.total_tokens:,} total "
        f"({tokens.prompt_tokens:,} prompt + {tokens.completion_tokens:,} completion) "
        f"across {tokens.api_calls} calls"
    )
    print(
        f"Proxy traffic: {proxy.requests} requests, "
        f"{format_bytes(proxy.bytes_downloaded)} down / {format_bytes(proxy.bytes_uploaded)} up "
        f"({proxy.search_calls} searches, {proxy.scrape_calls} scrapes)"
    )

    print(f"\nFull results saved to: {output_path}")
