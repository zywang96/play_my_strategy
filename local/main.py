from __future__ import annotations

import argparse

import core
from gui import launch_ui


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb-path", required=True, help="Full path to adb executable")
    parser.add_argument("--api-url", required=True, help="Backend API base URL")
    args = parser.parse_args()

    core.configure_runtime(args.adb_path, args.api_url)

    launch_ui()
    