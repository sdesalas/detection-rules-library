# detection-rules-library

Prebuilt Elastic Security detection rules as a git repository, built from the
`security_detection_engine` package in
[`elastic/integrations`](https://github.com/elastic/integrations). It is a
prototype of delivering prebuilt rules through git instead of Fleet.

Each release of the package is one commit, and each stack the package supports
is one branch. A consumer can read the rules at a commit, list what changed
between two commits, and fetch single files, without cloning the repository.

## Layout

```
manifest.yml                         package manifest at that release (version, kibana.version condition)
changelog.yml                        package changelog at that release (links each release to its integrations PR)
security-logo-color-64px.svg         the package icon (the manifest's `icons`)
LICENSE.txt                          Elastic License 2.0, the package's license (`source.license: Elastic-2.0`)
rules/
  README.md                          the package description, with links to the install and update docs
  windows/<rule file name>.json      one file per rule (`.json` or `.yml`), in the same folder as in elastic/detection-rules
  integrations/github/...
  building_block/...                 rules from rules_building_block/ in detection-rules
  _deleted/...                       rules that detection-rules no longer has
  _unmatched/<rule_id>.json          rules detection-rules never had (none expected)
scripts/
  build_library.py                   rebuilds the branches from elastic/integrations
```

`README.md`, `.gitignore`, `LICENSE.txt` and `scripts/` are part of every commit, so each
branch is self-contained. Between releases only `rules/` and the package files at the root change.
`manifest.yml`, `changelog.yml`, `rules/README.md` and the icon are copies of the package files at that
release (`README.md` and the icon come from the package's `docs/` and `img/`), so the commit shows the
same package metadata Fleet would have. The one change is the manifest's `icons.src`, which points at the
icon next to the manifest instead of in `img/`. The package's `NOTICE.txt` is not copied; `LICENSE.txt`
covers the library.

## Guidelines for maintaining this repo

How to keep this repo, and any repo built with the same structure, consistent.

**What goes where**

- Every folder under `rules/` holds detection rule files, and only those. They are the files that
  will be loaded into the appropriate Kibana detection rules library. The folder a rule is in says
  where it belongs, so nothing else goes in these folders.
- The package files are at the root: `manifest.yml`, `changelog.yml` and the icon, next to
  `LICENSE.txt`. They apply to everything in the library, including exception lists and value
  lists in their own folders. `rules/README.md` describes the rules.

**Keeping the history trustworthy**

- Rule files the build copies from the source are unchanged, so their blob ids match the source. A
  library that is maintained by hand edits the files directly, and a rebuild from the source would
  replace those edits, so maintain such a copy as its own repository.
- One file per rule. Its git history is its list of versions, so don't add a file per version.
- One commit per release of the source, one tag per commit, one branch per stack or release line.
- Every version that was current at some release stays, so each tag matches the source's release.

**Adding another delivery source**

- Give it its own repository with the same layout and the same branch, commit and tag conventions,
  so Kibana reads every source the same way: tags to find a release, a tree comparison to see what
  changed, a blob fetch to get one file.
- Only three things change from source to source: where the releases come from (version bumps of the
  package manifest in elastic/integrations here), how an item's id and version are read
  (`<rule_id>_<version>.json` here), and where each item goes in the folder (from the
  elastic/detection-rules history here). The commit, tag and check logic stays.
- `scripts/build_library.py` is not yet split into a shared part and a source-specific part: today it
  is written for this source only.

## Branches and tags

| Branch | Package line | `kibana.version` |
|---|---|---|
| `main` | latest | `^9.6.0` |
| `backport-9.5` | 9.5.x | `^9.5.0` |
| `backport-9.4` | 9.4.x | `^9.4.0` |
| `backport-8.19` | 8.19.x | `^8.19.0` |

Branch names follow the `backport-security_detection_engine-<minor>` branches in
elastic/integrations, without the package name. The branches are independent
histories: they don't share commits.

Every commit has a tag `<branch>/v<package version>`, for example
`main/v9.6.1-beta.1` or `backport-9.5/v9.5.10`. The tag marks the state of the
rules as of that package version, so a consumer can map a package version to a
commit without reading the history. Tags are per branch because the same package
version number can appear on more than one branch.

## Rule files

- Each file holds one rule as `{ id, type: "security-rule", attributes }`, in **JSON or YAML**.
  `id` is `<rule_id>_<version>`, and `attributes.rule_id` and `attributes.version` are the source of
  truth for identity and version, not the file name or extension.
- The build script writes JSON only, copied from the integrations package byte for byte. YAML files
  (`.yml` or `.yaml`) hold the same document and are also supported, for libraries that are
  maintained by hand: long fields (`note`, `query`, `setup`, `description`) read as multi-line text
  instead of one line.
- The file name is the original detection-rules file name with the extension of the format
  (`.json` or `.yml`) in place of `.toml`.
- A rule is one file, in one format. Its git history is its list of versions: releasing a new
  version rewrites the file. Converting a rule between JSON and YAML is a rename in a commit.
- 132 rules are deprecated stubs: only `deprecated`, sometimes `deprecated_reason`,
  `name`, `rule_id` and `version`. They carry no query. The deprecation date is in
  `detection_rules/etc/deprecated_rules.json` of detection-rules, not here.

**YAML files** follow these conventions, to keep the data the same whichever parser reads it:

- Same document, same keys in sorted order, no anchors, aliases, tags or merge keys, one document per file.
- Multi-line strings as literal blocks (`|`), long descriptions wrapped, and strings that a YAML 1.1
  parser could read as another type (`no`, `on`, `1.10`) quoted.
- Comments are allowed, and are not part of the rule: they are lost when the file is converted to JSON.
- Written to parse with the `yaml` package Kibana already depends on (YAML 1.2, core schema). Converting
  the 2,479 rule files at the tip of `main` to YAML and back gave identical data for every file with
  that package. Other parsers (for example Python's PyYAML, which is YAML 1.1) have not been tested.

TOML is not a storage format here. Nothing in Kibana reads this repo yet.

## Which versions are kept

Every version of a rule that was current at some release is kept. A rule's file at any commit is the version
that was current at that release, so each tag matches the package of that version exactly, and the history of
a rule's file is its list of versions. `--keep-latest N` limits this to the earliest version plus the latest `N`
per rule, at the cost of middle releases that no longer match their package. The impact of each choice is in
[scripts/README.md](scripts/README.md#choosing-which-versions-to-keep).

Rules released before the package used versioned file names
(`rule-<rule_id>.json`) are not included.

## Commits

One commit per package release, with the author and date of the integrations
commit and `Source: elastic/integrations@<sha>` in the body. A release can be a
`-beta` or a GA version, and a release that changes no rules still gets a commit
because the manifest changes.

## Building it

`scripts/build_library.py` rebuilds all branches. It needs Python 3.9 or newer
(tested on 3.12) and `git`, nothing else, plus local clones of:

- `elastic/integrations`, with full history and its remote branches
- `elastic/detection-rules`, with full history, to place each rule in its folder

```sh
# dry run: prints a plan per branch, writes nothing
python3 scripts/build_library.py

# create the branches, commits and tags (refuses if a branch already exists)
python3 scripts/build_library.py --apply
```

Run it from an empty clone of this repo. How the data is carried over, the options, the
dry run output and the checks are described in [scripts/README.md](scripts/README.md).

Rule folders come from detection-rules: for each release, the folder a rule had in
detection-rules at that date, below `rules/` here (`rules/windows/foo.toml` in
detection-rules becomes `rules/windows/foo.json`). If it moved, its file moves in the
first release after that.

## Using it from a script or Kibana

- List versions: `ls-refs` for `refs/tags/` gives package version to commit.
- What changed: compare the `rules/` trees of two commits.
- Fetch a file: request the blob by id.

## Limits

- Dates are package release dates, not rule authoring dates.
- Rule folders for past releases are inferred from detection-rules history by date.
- Only the stacks above are built. More `backport-*` branches can be added with the
  `--stacks` option.
