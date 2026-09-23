# Contributing

Issues and pull requests are welcome. This is a small tool with one maintainer.

## Reporting a bug

Open an issue with what you ran, what happened, and the full output of the doctor:

```bash
~/.claude/plugins/marketplaces/lesson-cut/scripts/lc doctor     # in a clone: ~/lesson-cut/scripts/lc doctor
```

The doctor prints paths under your home folder; replace your home path with `~` if you prefer.
Never paste an API key, and do not attach a take or a transcript you cannot share publicly. A
security problem goes through [SECURITY.md](SECURITY.md), not an issue.

## Changing a tool

- Read the whole file first. Most comments name the failure that put a line there, and some cite a
  rule number from the author's private ledger, which does not ship; the comment carries the reason.
- **Stricter, not quieter.** A change that makes a check stricter is safer than one that makes it
  quieter. Loosen a check only with a case that shows it was wrong, and say so in the pull request.
- After a change, rebuild a real project and compare its `edl.json` and `master.ass` with the
  previous version's before trusting it.
- Shell scripts run under macOS's bash 3.2: no associative arrays, no `mapfile`, no `${var,,}`.
  Run `bash -n` on any script you touch.
- Keep shipped text free of em and en dashes, and write invisible characters (such as the
  right-to-left embedding marks) as escapes like `"\u202b"`, never as literal characters.

## Releasing

1. Bump the version in `.claude-plugin/plugin.json` **and** `metadata.version` in
   `.claude-plugin/marketplace.json`, and the `Version X.Y.Z, YYYY-MM-DD` line at the top of
   `GUIDE.md`, which the PDF takes its version from. An installed copy only updates when the version
   changes, so a release without a bump never reaches anyone.
2. Add the release to `CHANGELOG.md`.
3. Run `claude plugin validate --strict .` from the repository root.
4. If `GUIDE.md` changed, rebuild the PDF as [docs/build/README.md](docs/build/README.md) describes.
5. In the clone you release from, set a repo-local identity before committing:
   `git config user.name "<your name>"` and
   `git config user.email "<id>+<user>@users.noreply.github.com"` (no `--global`). Every commit
   records its author's email, and so does the annotated tag in step 7.
6. Commit, then push the branch: `git push origin main`. Installs follow the default branch, not
   the tag.
7. Run `claude plugin tag --push`. It creates `lesson-cut--vX.Y.Z` and pushes that tag only.

Contributions are released under the MIT License in [LICENSE](LICENSE).
