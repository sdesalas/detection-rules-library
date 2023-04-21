# scripts/build_library.py

Builds the branches of this repo from the `security_detection_engine` package history in
[`elastic/integrations`](https://github.com/elastic/integrations). This page describes how the
data is carried over, what the script checks, and what a dry run reports, so the result can be
reviewed without reading the code.

Python 3.9 or newer (tested on 3.12), standard library and `git` only.

## What it does

For each stack (branch) it reads the first-parent history of the integrations ref and:

1. **Finds the releases.** A release is a commit that changes the `version:` in
   `packages/security_detection_engine/manifest.yml`. Beta and GA versions are both releases.
2. **Reads the rules of each release** from the tree of that commit
   (`packages/security_detection_engine/kibana/security_rule/<rule_id>_<version>.json`). For each
   rule, the highest version in the tree is the rule's *current* version at that release.
   Older files named `rule-<rule_id>.json` (no version in the name) are ignored.
3. **Writes each rule at its current version.** At every release, the library holds each rule at the
   version that was current then, so every tag matches the package of that release. Every version
   that was current at some release is kept. `--keep-latest N` limits this to the earliest version
   plus the latest `N` per rule; see [Choosing which versions to keep](#choosing-which-versions-to-keep).
4. **Places each rule in a folder** using the detection-rules history (see below).
5. **Creates one commit per release**, with the release's author and date, and a tag.

The file content is the integrations JSON, unchanged. The package files are copied too: `manifest.yml`,
`changelog.yml` and the icon (`img/…svg`) to the root, and `docs/README.md` to `rules/README.md`. The package's
`NOTICE.txt` is not copied. The only edit is the manifest's `icons.src`, rewritten from `/img/<icon>` to `/<icon>`
so it still resolves. File names are the original detection-rules
file name with `.json` in place of `.toml`. Because the content is unchanged, git blob ids in this repo
equal the blob ids in integrations.

### Folders

For each release, the script takes the last commit of detection-rules (first parent of
`--detection-rules-ref`) before the release date, finds each rule by `rule_id` in the `.toml` files
under `rules/` and `rules_building_block/`, and uses that file's folder:

| detection-rules path | library path |
|---|---|
| `rules/windows/foo.toml` | `rules/windows/foo.json` |
| `rules/integrations/github/foo.toml` | `rules/integrations/github/foo.json` |
| `rules_building_block/foo.toml` | `rules/building_block/foo.json` |

If a rule is not in that snapshot, in order: its path at `--detection-rules-ref`; then
`rules/_deleted/<last known path>` if it was seen at an earlier release; then
`rules/_unmatched/<rule_id>.json`. If a rule moved in detection-rules, its file moves in the first release
after the move.

### Commits and tags

| | |
|---|---|
| Subject | the integrations commit subject |
| Body | `Source: elastic/integrations@<sha>` and `Package: security_detection_engine <version>` |
| Author, dates | the integrations commit's |
| Content | `rules/` changes, including `rules/README.md`, and the package files at the root: `manifest.yml`, `changelog.yml` and `security-logo-color-64px.svg` (copies of the package files at that release; the README and icon come from the package's `docs/` and `img/`), plus `README.md`, `.gitignore`, `LICENSE.txt` and `scripts/` unchanged in every commit |
| Tag | `<branch>/v<package version>`, for example `main/v9.6.1-beta.1` |

Branches are independent histories (they do not share commits).

## Usage

```sh
python3 scripts/build_library.py            # dry run: prints the plan, writes nothing
python3 scripts/build_library.py --apply    # creates branches, commits and tags
```

`--apply` stops before writing anything if a file name does not match its JSON content, and refuses
to run if a branch already exists. After writing it checks each branch against the plan (below).

| Option | Default | Meaning |
|---|---|---|
| `--apply` | off | Create the branches. Without it nothing is written. |
| `--integrations <path>` | `~/Code/elastic/integrations` | Clone of elastic/integrations with full history and remote branches. |
| `--detection-rules <path>` | `~/Code/elastic/detection-rules` | Clone of elastic/detection-rules with full history. |
| `--detection-rules-ref <ref>` | `origin/main` | Ref used for the final rule paths and as the history to search. |
| `--repo <path>` | this repo | Where the branches are created. |
| `--stacks <list>` | the four below | Comma separated `<branch>=<integrations ref>`. |
| `--only <branch>` | all | Build one branch only. |
| `--keep-latest <n>` | keep all | Keep only the earliest version plus the latest `n` per rule. |
| `--max-releases <n>` | all | Only the first `n` releases (for trying things out). |
| `--plan-out <file>` | none | Write the plan (commits and file operations) as JSON. |

Default stacks: `main=origin/main` and `backport-<minor>=origin/backport-security_detection_engine-<minor>`
for 9.5, 9.4 and 8.19.

## Dry run output

Run on 2026-11-16 with integrations at `origin/main` `b9eb76df0f` and detection-rules at `9398c9d4f51b`.
A GA release usually follows its beta and changes no rules.

```
Integrations: ~/Code/elastic/integrations
Detection-rules paths from: ~/Code/elastic/detection-rules @ 9398c9d4f51b
Output repo: ~/Code/sdesalas/detection-rules-library

=== main  (origin/main @ b9eb76df0f)
  commits (one per package release): 214, of which change rules: 112, manifest only: 102
  rules at tip: 2479 {"matched": 2479}, behind their package top version at tip: 0
  rule versions ever top of a release: 21791, kept (all): 21791, written: 21791
  rule files at tip identical to the package's: 2479 of 2479
  folder moves: 363, duplicate tags: 0
  first:
    2023-04-21  v8.7.3-beta.0   +/~ 768 rules  58853dbf2f
    2023-04-26  v8.7.3-beta.1   +/~  72 rules  d10b876af3
    2023-04-26  v8.7.3          +/~   0 rules  0b24ea5848
  last:
    2026-10-23  v9.5.9          +/~   0 rules  33bcf06eb1
    2026-11-11  v9.6.1-beta.1   +/~ 692 rules  d2479eab97
    2026-11-11  v9.6.1          +/~   0 rules  60f06cc354

=== backport-9.5  (origin/backport-security_detection_engine-9.5 @ 843dca5ded)
  commits (one per package release): 214, of which change rules: 112, manifest only: 102
  rules at tip: 2429 {"matched": 2429}, behind their package top version at tip: 0
  rule versions ever top of a release: 21515, kept (all): 21515, written: 21515
  rule files at tip identical to the package's: 2429 of 2429
  folder moves: 363, duplicate tags: 0
  first:
    2023-04-21  v8.7.3-beta.0   +/~ 768 rules  58853dbf2f
    2023-04-26  v8.7.3-beta.1   +/~  72 rules  d10b876af3
    2023-04-26  v8.7.3          +/~   0 rules  0b24ea5848
  last:
    2026-10-23  v9.5.9          +/~   0 rules  33bcf06eb1
    2026-11-11  v9.5.10-beta.1  +/~ 328 rules  9a659b8258
    2026-11-11  v9.5.10         +/~   0 rules  843dca5ded

=== backport-9.4  (origin/backport-security_detection_engine-9.4 @ 3bbaf7d8ae)
  commits (one per package release): 214, of which change rules: 112, manifest only: 102
  rules at tip: 2414 {"matched": 2414}, behind their package top version at tip: 0
  rule versions ever top of a release: 20213, kept (all): 20213, written: 20213
  rule files at tip identical to the package's: 2414 of 2414
  folder moves: 363, duplicate tags: 0
  first:
    2023-04-21  v8.7.3-beta.0   +/~ 768 rules  58853dbf2f
    2023-04-26  v8.7.3-beta.1   +/~  72 rules  d10b876af3
    2023-04-26  v8.7.3          +/~   0 rules  0b24ea5848
  last:
    2026-10-23  v9.4.16         +/~   0 rules  3412664a23
    2026-11-11  v9.4.17-beta.1  +/~ 327 rules  5bd57eba89
    2026-11-11  v9.4.17         +/~   0 rules  3bbaf7d8ae

=== backport-8.19  (origin/backport-security_detection_engine-8.19 @ 731a128a87)
  commits (one per package release): 212, of which change rules: 110, manifest only: 102
  rules at tip: 2157 {"matched": 2157}, behind their package top version at tip: 0
  rule versions ever top of a release: 18054, kept (all): 18054, written: 18054
  rule files at tip identical to the package's: 2157 of 2157
  folder moves: 292, duplicate tags: 0
  first:
    2023-04-21  v8.7.3-beta.0   +/~ 768 rules  58853dbf2f
    2023-04-26  v8.7.3-beta.1   +/~  72 rules  d10b876af3
    2023-04-26  v8.7.3          +/~   0 rules  0b24ea5848
  last:
    2026-10-23  v8.19.36        +/~   0 rules  39ce1f354c
    2026-11-11  v8.19.37-beta.1 +/~ 216 rules  c9569a635a
    2026-11-11  v8.19.37        +/~   0 rules  731a128a87

Checked 38658 distinct rule files: 0 name/content mismatches, 132 deprecated stubs

Dry run: nothing written (134s). Pass --apply to create the branches.
```

## Summary

| | `main` | `backport-9.5` | `backport-9.4` | `backport-8.19` |
|---|---|---|---|---|
| Integrations ref | `origin/main` | `origin/backport-security_detection_engine-9.5` | `origin/backport-security_detection_engine-9.4` | `origin/backport-security_detection_engine-8.19` |
| Package version at tip | 9.6.1 | 9.5.10 | 9.4.17 | 8.19.37 |
| Commits (one per package release) | 214 | 214 | 214 | 212 |
| of which change rules | 112 | 112 | 112 | 110 |
| of which manifest only | 102 | 102 | 102 | 102 |
| Rule versions that were current at some release | 21,791 | 21,515 | 20,213 | 18,054 |
| Rule versions written | 21,791 | 21,515 | 20,213 | 18,054 |
| Rules at tip | 2,479 | 2,429 | 2,414 | 2,157 |
| Rule files at tip identical to the package's | 2,479 of 2,479 | 2,429 of 2,429 | 2,414 of 2,414 | 2,157 of 2,157 |
| Rules behind the package at tip | 0 | 0 | 0 | 0 |
| Rules in `_deleted/` or `_unmatched/` at tip | 0 | 0 | 0 | 0 |
| Folder moves over the history | 363 | 363 | 363 | 292 |
| Duplicate tags | 0 | 0 | 0 | 0 |

History starts at the 2023-04-21 release (v8.7.3-beta.0, 768 rules), the first package release with
versioned rule file names.

## Choosing which versions to keep

The package has shipped many versions of most rules (a median of 9, a maximum of 31 current at some
release). The default keeps all of them. `--keep-latest N` keeps only the earliest version plus the
latest `N` per rule. Both were built and compared on 2026-11-16, same inputs as above:

| | Earliest + latest 5 | Every version (default) | Change |
|---|---|---|---|
| Commits per branch (`main` / 9.5 / 9.4 / 8.19) | 214 / 214 / 214 / 212 | 214 / 214 / 214 / 212 | none |
| of which change rules, `main` | 110 | 112 | +2 |
| Rule files at the tip of `main` | 2,479 | 2,479 | none |
| Rule versions written, `main` | 11,858 | 21,791 | +84% |
| Rule versions written, all four branches | 45,676 | 81,573 | +79% |
| Rule-file writes across all commits, `main` (includes folder moves) | 14,734 | 27,901 | +89% |
| Rule files changed per commit, `main`: median / max (commits that change rules) | 24 / 2,112 | 83.5 / 2,112 | median up, max same |
| Packed repo size, all four branches (after `git repack -a -d -f`) | 13.6 MiB (33,477 objects) | 15.6 MiB (42,161 objects) | +14% |
| `main/v8.17.6`: rules identical to the real package | 172 of 1,315 | 1,315 of 1,315 | exact |
| `main/v9.5.9` and `backport-9.5/v9.5.9`: rules identical | not measured | 2,394 of 2,394 on both | exact |

- The number of commits and the number of files at each tip do not depend on the choice. Only the history
  inside each rule file grows. Versions of one rule are near duplicates, so git stores them as small
  deltas: versions written grow 84% on `main` while the packed size grows 14%.
- With `--keep-latest`, the kept versions are the earliest and the latest `N`. For a middle release, a rule's
  current version is usually not one of them, so the file shows the highest kept version at or below it,
  typically the earliest. Only branch tips are exact. That is what the 172 of 1,315 above shows.
- Sizes are after a full repack. A plain `git gc` packed the same data to 27 to 35 MiB depending on the run, so it
  is not comparable between builds.
- Not measured: how a consumer behaves on the larger history.

## Checks

**In the dry run** (the script stops `--apply` if a check on file content fails):

| Check | Result |
|---|---|
| Every written rule file's name (`<rule_id>_<version>.json`) matches `attributes.rule_id` and `attributes.version` inside the JSON | 38,658 distinct files checked, 0 mismatches |
| Deprecated stubs (`attributes.deprecated`: no query, only name and ids) among them | 132 |
| The rule folder of the last release equals the rule folder at the tip of the integrations ref (no rule changes outside a version bump) | no warning on any branch |
| Rule files at the tip of each branch are byte-identical (same blob id) to the package's current version at the integrations tip | all, see the summary |
| No two rules map to the same path | no warning on any branch |
| No duplicate tag names within a branch | 0 |

**After `--apply`**, for each branch: the files under `rules/` and the package files at the root at the branch tip (paths and blob ids) equal the plan's final
state, the number of commits equals the number of releases, and the number of `<branch>/v*` tags equals the number of releases.

## Limits

- Dates are package release dates, not rule authoring dates.
- Rule folders for past releases are inferred from detection-rules history by date, so a rule can appear
  under a folder it had slightly before or after the release it belongs to.
- With `--keep-latest`, only branch tips are exact; by default every release is exact.
- Releases before versioned rule file names (before 2023-04-21) are not included.
- Only the stacks listed above are built; `--stacks` adds more.
- Rule ids in detection-rules are found with a line pattern, not a TOML parser.
