#!/bin/bash
set -e

REPO_DIR="/root/padel-tracking"
cd "$REPO_DIR"

VENUE=${1:-halstenbek}

python3 padel_tracker.py --venue "$VENUE"

git add "$VENUE/snapshots/"
if git diff --cached --quiet; then
  echo "Keine neuen Snapshots fuer $VENUE."
  exit 0
fi

TIMESTAMP=$(TZ="Europe/Berlin" date "+%Y-%m-%d %H:%M")
git commit -m "snapshot [$VENUE]: $TIMESTAMP"
git pull --rebase
git push
echo "Gepusht [$VENUE]: $TIMESTAMP"
