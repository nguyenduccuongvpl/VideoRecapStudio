#!/usr/bin/env python3
"""Spike script to programmatically run and print Capability Doctor checks."""

import sys
from pathlib import Path

# Add src folder to sys.path to enable importing video_recap
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from video_recap.application.doctor import run_doctor_checks  # noqa: E402


def main() -> None:
    print("Executing Capability Doctor programmatic check...")
    report = run_doctor_checks()

    print("\n--- Raw Capability Items ---")
    for item in report.items:
        print(f"Name: {item.name}")
        print(f"  Required: {item.required}")
        print(f"  Status:   {item.status}")
        print(f"  Details:  {item.details}")
        print("-" * 30)

    print(f"\nFinal Validity Check: {report.is_valid}")
    if report.is_valid:
        print("RESULT: System is healthy and meets all core dependencies.")
        sys.exit(0)
    else:
        print("RESULT: System is missing required dependencies!")
        sys.exit(1)


if __name__ == "__main__":
    main()
