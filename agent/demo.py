"""
Demo entrypoint — runs all 3 sessions sequentially with pauses.
Usage: source .venv/bin/activate && GEMINI_API_KEY=... python -m agent.demo
"""
import argparse
from agent.runner import run_session
from agent.scenarios import SCENARIOS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-stream", action="store_true")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  RevMem Demo — Contract Reconciliation")
    print("  3 sessions showing continual learning + expanding autonomy")
    print("=" * 60)

    results = []
    env_id = None
    prev_interaction = None
    prev_deal = None

    for session_num in [1, 2, 3]:
        if session_num > 1:
            print(f"\n{'─'*60}")
            input(f"Press Enter to start Session {session_num}...")

        current_deal = SCENARIOS[session_num]["deal"]
        if current_deal != prev_deal:
            env_id = None
            prev_interaction = None

        result = run_session(
            session_num, env_id, prev_interaction,
            stream=not args.no_stream,
        )
        results.append(result)

        prev_deal = current_deal
        env_id = result.get("environment_id")
        prev_interaction = result.get("interaction_id")

    print("\n" + "=" * 60)
    print("  DEMO SUMMARY")
    print("=" * 60)
    for r in results:
        print(
            f"  S{r['session_number']}: "
            f"tier={r['tier']:12s} "
            f"rep={r['reputation']:.2f} "
            f"memories_used={r['memories_used']} "
            f"deal={r['deal']}"
        )
    print("=" * 60)


if __name__ == "__main__":
    main()
