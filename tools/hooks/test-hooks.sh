#!/bin/sh
# Self-test for the git hooks in .githooks/, run in a throwaway repository.
# Usage: sh tools/hooks/test-hooks.sh
set -u

root=$(cd "$(dirname "$0")/../.." && pwd)
hooks="$root/.githooks"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0

expect() {
  want=$1
  desc=$2
  shift 2
  "$@" >/dev/null 2>&1
  got=$?
  if [ "$got" -eq "$want" ]; then
    echo "ok   - $desc"
  else
    echo "FAIL - $desc (exit $got, expected $want)"
    failures=$((failures + 1))
  fi
}

repeat() { printf "%${2}s" "" | tr ' ' "$1"; }

export GIT_AUTHOR_NAME="Devaraj-05" GIT_AUTHOR_EMAIL="padma.devaraj1800@gmail.com"
export GIT_COMMITTER_NAME="Devaraj-05" GIT_COMMITTER_EMAIL="padma.devaraj1800@gmail.com"

git init -q "$work/repo"
cd "$work/repo" || exit 1
git config core.hooksPath /dev/null
git config core.autocrlf false
git commit -q --allow-empty -m "init"

# commit-msg
printf 'docs: add plan\n' > "$work/clean.txt"
printf 'docs: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n' > "$work/coauthor.txt"
printf 'feat: x\n\nGenerated with [Claude Code](https://claude.com/claude-code)\n' > "$work/generated.txt"
printf 'docs: explain how Claude Code is used here\n' > "$work/mention.txt"
expect 0 "commit-msg accepts a clean message" sh "$hooks/commit-msg" "$work/clean.txt"
expect 1 "commit-msg rejects a Claude co-author trailer" sh "$hooks/commit-msg" "$work/coauthor.txt"
expect 1 "commit-msg rejects a 'Generated with Claude Code' line" sh "$hooks/commit-msg" "$work/generated.txt"
expect 0 "commit-msg allows a plain mention of Claude" sh "$hooks/commit-msg" "$work/mention.txt"

# pre-commit: identity
expect 0 "pre-commit accepts the project identity" sh "$hooks/pre-commit"
expect 1 "pre-commit rejects another author email" env GIT_AUTHOR_EMAIL=someone@example.com sh "$hooks/pre-commit"
expect 1 "pre-commit rejects another committer name" env GIT_COMMITTER_NAME=Claude sh "$hooks/pre-commit"

# pre-commit: secrets (key-shaped strings are built at runtime so this file stays clean)
printf 'OPENAI_API_KEY=\n' > .env.example
git add .env.example
expect 0 "pre-commit allows .env.example" sh "$hooks/pre-commit"
git reset -q

printf 'PLACEHOLDER=1\n' > .env
git add -f .env
expect 1 "pre-commit blocks a staged .env file" sh "$hooks/pre-commit"
git reset -q
rm -f .env

printf 'client = make("%s")\n' "sk-proj-$(repeat A 48)" > leak.py
git add leak.py
expect 1 "pre-commit blocks an OpenAI-style key" sh "$hooks/pre-commit"
git reset -q
rm -f leak.py

printf '%s_API_KEY=%s\n' "DEEPGRAM" "$(repeat 7 40)" > settings.txt
git add settings.txt
expect 1 "pre-commit blocks a Deepgram key assignment" sh "$hooks/pre-commit"
git reset -q
rm -f settings.txt

# pre-push
zero=0000000000000000000000000000000000000000
foreign=$(GIT_AUTHOR_NAME=Other GIT_AUTHOR_EMAIL=other@example.com \
  GIT_COMMITTER_NAME=Other GIT_COMMITTER_EMAIL=other@example.com \
  git commit-tree "HEAD^{tree}" -p HEAD -m "test: foreign identity")
attributed=$(git commit-tree "HEAD^{tree}" -p HEAD -m "test: attribution" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>")
clean=$(git commit-tree "HEAD^{tree}" -p HEAD -m "test: clean")
prepush() { printf 'refs/heads/topic %s refs/heads/topic %s\n' "$1" "$2" | sh "$hooks/pre-push"; }
expect 1 "pre-push rejects a foreign-identity commit" prepush "$foreign" "$zero"
expect 1 "pre-push rejects an attributed commit" prepush "$attributed" "$zero"
expect 0 "pre-push accepts a clean commit" prepush "$clean" "$zero"
expect 0 "pre-push ignores branch deletion" prepush "$zero" "$clean"

if [ "$failures" -ne 0 ]; then
  echo "$failures hook test(s) failed"
  exit 1
fi
echo "all hook tests passed"
