#!/usr/bin/env python3
"""Daily OpenProject snapshot — cron entry point.

Wraps ``flask openproject snapshot`` so the Belel crontab can fire a
plain ``python3 scripts/openproject_snapshot.py`` without depending on
the CLI's app-context loader. Output is logged to stdout (cron captures
it via shell redirection).

Cron wiring (per April spec, mirrored on the Drifterbot pattern):
  - Belel crontab fires at OPENPROJECT_SNAPSHOT_HOUR_UTC (default 07:00)
  - SSH into the droplet, invoke this script under the venv
  - Exit code 0 = success; non-zero = ops should check logs

This script is intentionally a thin wrapper. All the work lives in
``app.services.openproject_snapshot.run_snapshot_for_active_clients``
so it stays testable via the flask CLI.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    """Invoke the flask CLI under the venv's python."""
    repo_dir = os.environ.get(
        'PSI_FUNCTION_REPO_DIR', '/opt/consulting-site/production/current',
    )
    venv_python = os.path.join(repo_dir, '.venv', 'bin', 'python')

    for_date = os.environ.get('OPENPROJECT_SNAPSHOT_DATE')  # YYYY-MM-DD or None
    cmd = [venv_python, '-m', 'flask', 'openproject', 'snapshot']
    if for_date:
        cmd.extend(['--date', for_date])

    print(f'[snapshot] invoking: {" ".join(cmd)}', flush=True)
    result = subprocess.run(cmd, cwd=repo_dir, check=False)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
