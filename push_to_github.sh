#!/bin/bash
# Run this once from Terminal to push the price tracker to GitHub.
# It will prompt for your GitHub username + Personal Access Token (or use SSH).
#
# Usage: bash push_to_github.sh

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=== Price Tracker → GitHub Push ==="
echo "Repo: https://github.com/LifeWithPies/price_tracker_dashboard"
echo ""

# Remove stale lock file if present
rm -f .git/index.lock 2>/dev/null || true

# Configure git identity if not set
git config user.name  "LifeWithPies" 2>/dev/null || true
git config user.email "krovvidiprashant@gmail.com" 2>/dev/null || true

# Stage all tracked files (respects .gitignore)
git add \
  .github/workflows/price_check.yml \
  .gitignore \
  PROJECT_INSTRUCTIONS.md \
  TECHNICAL_SPEC.md \
  dashboard.html index.html \
  db.py gen_dashboard3.py gen_dashboard4.py \
  notifier.py price_check.py price_check_gh.py \
  requirements.txt scraper.py \
  tracker_state.json unfollow_product.py

# Show what's staged
echo "Staged files:"
git status --short
echo ""

# Commit (skip if nothing new)
if git diff --cached --quiet; then
  echo "Nothing to commit — already up to date."
else
  git commit -m "feat: initial commit — price tracker with GitHub Actions + dashboard"
  echo "Committed."
fi

# Push
echo ""
echo "Pushing to origin/main..."
echo "(You'll be prompted for GitHub credentials — use your PAT as the password)"
echo ""
git push -u origin main

echo ""
echo "✓ Done! Your repo is live at:"
echo "  https://github.com/LifeWithPies/price_tracker_dashboard"
echo ""
echo "Next steps:"
echo "  1. Add GitHub Secrets (Settings → Secrets → Actions):"
echo "     ANTHROPIC_API_KEY, SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL, RAINFOREST_API_KEY"
echo "  2. Enable GitHub Pages (Settings → Pages → Branch: main, Folder: / (root))"
echo "     Dashboard will be at: https://LifeWithPies.github.io/price_tracker_dashboard/"
