#!/usr/bin/env python3
"""Build the rule library branches of this repo from elastic/integrations.

One branch per stack, one commit per package release (security_detection_engine),
rules under rules/ laid out like elastic/detection-rules.

Without --apply it only prints the plan and writes nothing. See README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

PACKAGE_PATH = "packages/security_detection_engine"
RULES_PATH = f"{PACKAGE_PATH}/kibana/security_rule"
MANIFEST_PATH = f"{PACKAGE_PATH}/manifest.yml"
LIBRARY_DIR = "rules"
PACKAGE_FILES = {
    "manifest.yml": "manifest.yml",
    "changelog.yml": "changelog.yml",
    "docs/README.md": f"{LIBRARY_DIR}/README.md",
    "img/security-logo-color-64px.svg": "security-logo-color-64px.svg",
}
ROOT_PACKAGE_PATHS = tuple(target for target in PACKAGE_FILES.values() if "/" not in target)
STATIC_PATHS = ("README.md", ".gitignore", "LICENSE.txt", "scripts")
RULE_ID_PATTERN = r'^rule_id[[:space:]]*=[[:space:]]*"[^"]+"'
DEFAULT_STACKS = ",".join(
    [
        "main=origin/main",
        "backport-9.5=origin/backport-security_detection_engine-9.5",
        "backport-9.4=origin/backport-security_detection_engine-9.4",
        "backport-8.19=origin/backport-security_detection_engine-8.19",
    ]
)


class Release(NamedTuple):
    sha: str
    date: str
    author_name: str
    author_email: str
    subject: str
    version: str
    package_blobs: Dict[str, str]


class Top(NamedTuple):
    version: int
    blob: str


class Entry(NamedTuple):
    blob: str
    kind: str
    rule_id: Optional[str] = None
    version: Optional[int] = None
    behind: bool = False


Op = Dict[str, object]


def git(cwd: Path, *args: str, env: Optional[Dict[str, str]] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args],
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        encoding="utf-8",
    )


def git_out(cwd: Path, *args: str) -> str:
    return git(cwd, *args).stdout


class BlobReader:
    """Reads objects from one repo through a single `git cat-file --batch` process."""

    def __init__(self, cwd: Path) -> None:
        self.process = subprocess.Popen(
            ["git", "cat-file", "--batch"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )

    def read(self, sha: str) -> bytes:
        self.process.stdin.write(f"{sha}\n".encode())
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode().strip()
        if header.endswith(" missing"):
            raise RuntimeError(f"Object not found: {header}")
        size = int(header.split()[2])
        data = self.process.stdout.read(size)
        self.process.stdout.read(1)
        return data

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait()


def parse_args() -> argparse.Namespace:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="create the branches, commits and tags")
    parser.add_argument("--integrations", type=Path, default=home / "Code/elastic/integrations")
    parser.add_argument("--detection-rules", type=Path, default=home / "Code/elastic/detection-rules")
    parser.add_argument("--detection-rules-ref", default="origin/main")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--stacks", default=DEFAULT_STACKS, help="comma separated <branch>=<integrations ref>")
    parser.add_argument("--keep-latest", type=int, default=None, help="keep only the earliest version plus this many latest ones per rule (default: keep all)")
    parser.add_argument("--only", help="build only this branch")
    parser.add_argument("--max-releases", type=int)
    parser.add_argument("--plan-out", type=Path)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Integrations history
# ---------------------------------------------------------------------------


# Content that differs from the source file, by the git blob id it will have in this repo.
REWRITTEN: Dict[str, bytes] = {}
_flat_manifest_cache: Dict[str, str] = {}


def flatten_icon_path(integrations: Path, blob: str) -> str:
    """Blob id of the manifest with icons.src pointing at the icon next to it instead of in img/."""
    if blob in _flat_manifest_cache:
        return _flat_manifest_cache[blob]
    source = subprocess.run(["git", "cat-file", "blob", blob], cwd=integrations, capture_output=True, check=True).stdout
    data = re.sub(rb"^(\s*src:\s*)/img/", rb"\1/", source, flags=re.MULTILINE)
    result = blob
    if data != source:
        result = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        REWRITTEN[result] = data
    _flat_manifest_cache[blob] = result
    return result


def read_package_blobs(integrations: Path, sha: str) -> Dict[str, str]:
    """Blob ids of the package files at a commit, keyed by their path in this repo."""
    blobs: Dict[str, str] = {}
    for source, target in PACKAGE_FILES.items():
        found = git(integrations, "rev-parse", f"{sha}:{PACKAGE_PATH}/{source}", check=False)
        if found.returncode == 0:
            blobs[target] = found.stdout.strip()
            if target == "manifest.yml":
                blobs[target] = flatten_icon_path(integrations, blobs[target])
    return blobs


def read_releases(integrations: Path, ref: str, max_releases: Optional[int]) -> List[Release]:
    log = git_out(
        integrations,
        "log",
        "--first-parent",
        "--reverse",
        "--format=%H%x1f%aI%x1f%an%x1f%ae%x1f%s",
        ref,
        "--",
        MANIFEST_PATH,
    )
    releases: List[Release] = []
    previous_version = None
    for row in filter(None, log.split("\n")):
        sha, date, author_name, author_email, subject = row.split("\x1f")
        shown = git(integrations, "show", f"{sha}:{MANIFEST_PATH}", check=False)
        if shown.returncode != 0:
            continue
        match = re.search(r"^version:\s*(\S+)", shown.stdout, re.MULTILINE)
        if not match or match.group(1) == previous_version:
            continue
        previous_version = match.group(1)
        package_blobs = read_package_blobs(integrations, sha)
        releases.append(Release(sha, date, author_name, author_email, subject, previous_version, package_blobs))
    return releases[:max_releases] if max_releases else releases


def read_tops(integrations: Path, sha: str) -> Dict[str, Top]:
    listing = git(integrations, "ls-tree", f"{sha}:{RULES_PATH}", check=False)
    tops: Dict[str, Top] = {}
    if listing.returncode != 0:
        return tops
    for line in listing.stdout.split("\n"):
        match = re.match(r"^\d+ blob ([0-9a-f]+)\t(.+)_(\d+)\.json$", line)
        if not match:
            continue
        blob, rule_id, version = match.group(1), match.group(2), int(match.group(3))
        existing = tops.get(rule_id)
        if existing is None or version > existing.version:
            tops[rule_id] = Top(version, blob)
    return tops


def select_versions(versions: Set[int], keep_latest: Optional[int]) -> List[int]:
    ordered = sorted(versions)
    if keep_latest is None or len(ordered) <= keep_latest + 1:
        return ordered
    return [ordered[0], *ordered[-keep_latest:]]


# ---------------------------------------------------------------------------
# Rule paths from detection-rules history
# ---------------------------------------------------------------------------


def to_library_path(source_path: str) -> str:
    prefix = "rules_building_block/"
    if source_path.startswith(prefix):
        relative = f"building_block/{source_path[len(prefix):]}"
    else:
        relative = re.sub(r"^rules/", "", source_path)
    return re.sub(r"\.toml$", ".json", relative)


class Snapshots:
    """rule_id -> path in detection-rules, at a date or at the base ref."""

    def __init__(self, detection_rules: Path, base_sha: str) -> None:
        self.detection_rules = detection_rules
        self.cache: Dict[str, Dict[str, str]] = {}
        self.final = self._load(base_sha)
        self.base_sha = base_sha

    def _load(self, sha: str) -> Dict[str, str]:
        if sha in self.cache:
            return self.cache[sha]
        result = git(
            self.detection_rules, "grep", "-n", "-I", "-E", "-e", RULE_ID_PATTERN, sha, "--", "rules", "rules_building_block",
            check=False,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        rules: Dict[str, str] = {}
        for line in result.stdout.split("\n"):
            match = re.match(r'^[0-9a-f]{40}:(.+?):\d+:rule_id\s*=\s*"([^"]+)"', line)
            if match and match.group(2) not in rules:
                rules[match.group(2)] = match.group(1)
        self.cache[sha] = rules
        return rules

    def at_date(self, date: str) -> Dict[str, str]:
        sha = git_out(
            self.detection_rules, "rev-list", "-1", "--first-parent", f"--before={date}", self.base_sha
        ).strip()
        return self._load(sha) if sha else {}


# ---------------------------------------------------------------------------
# Plan: one entry per release
# ---------------------------------------------------------------------------


class StackPlan(NamedTuple):
    branch: str
    ref: str
    plan: List[Tuple[Release, List[Op]]]
    final_state: Dict[str, Entry]
    moves: int
    warnings: List[str]
    ever_top_count: int
    kept_count: int
    tip_tree_matches: bool
    tip_identical: int


def plan_stack(args: argparse.Namespace, branch: str, ref: str, snapshots: Snapshots) -> StackPlan:
    integrations: Path = args.integrations
    releases = read_releases(integrations, ref, args.max_releases)
    tops_by_release = [read_tops(integrations, release.sha) for release in releases]

    ever_top: Dict[str, Set[int]] = {}
    for tops in tops_by_release:
        for rule_id, top in tops.items():
            ever_top.setdefault(rule_id, set()).add(top.version)
    kept = {rule_id: select_versions(versions, args.keep_latest) for rule_id, versions in ever_top.items()}

    top_blob: Dict[str, str] = {}
    last_known: Dict[str, str] = {}
    location_of: Dict[str, str] = {}
    plan: List[Tuple[Release, List[Op]]] = []
    warnings: List[str] = []
    written: Dict[str, Entry] = {}
    moves = 0

    for release, tops in zip(releases, tops_by_release):
        for rule_id, top in tops.items():
            top_blob[f"{rule_id}_{top.version}"] = top.blob
        if not tops:
            continue

        snapshot = snapshots.at_date(release.date)
        last_known.update(snapshot)

        following: Dict[str, Entry] = {name: Entry(blob, "package") for name, blob in release.package_blobs.items()}
        for rule_id, top in tops.items():
            chosen = max(version for version in kept[rule_id] if version <= top.version)
            blob = top_blob[f"{rule_id}_{chosen}"]

            source_path = snapshot.get(rule_id) or snapshots.final.get(rule_id)
            deleted_path = last_known.get(rule_id)
            if source_path:
                kind, relative = "matched", f"{LIBRARY_DIR}/{to_library_path(source_path)}"
            elif deleted_path:
                kind, relative = "deleted", f"{LIBRARY_DIR}/_deleted/{to_library_path(deleted_path)}"
            else:
                kind, relative = "unmatched", f"{LIBRARY_DIR}/_unmatched/{rule_id}.json"

            if relative in following:
                warnings.append(f"Path collision on {relative}, {rule_id} stored with its id appended")
                relative = re.sub(r"\.json$", f"_{rule_id}.json", relative)
            following[relative] = Entry(blob, kind, rule_id, chosen, chosen < top.version)
            if rule_id in location_of and location_of[rule_id] != relative:
                moves += 1
            location_of[rule_id] = relative

        ops: List[Op] = []
        for relative, entry in following.items():
            if relative in written and written[relative].blob == entry.blob:
                continue
            op: Op = {"op": "write", "path": relative, "blob": entry.blob}
            if entry.rule_id is not None:
                op.update({"ruleId": entry.rule_id, "version": entry.version})
            ops.append(op)
        for relative in written:
            if relative not in following:
                ops.append({"op": "delete", "path": relative})
        plan.append((release, ops))
        written = following

    tip_tree_matches = bool(releases) and (
        git_out(integrations, "rev-parse", f"{ref}:{RULES_PATH}").strip()
        == git_out(integrations, "rev-parse", f"{releases[-1].sha}:{RULES_PATH}").strip()
    )
    tip_tops = tops_by_release[-1] if tops_by_release else {}
    tip_identical = sum(
        1 for entry in written.values() if entry.rule_id and entry.blob == tip_tops.get(entry.rule_id, Top(0, "")).blob
    )
    return StackPlan(
        branch,
        ref,
        plan,
        written,
        moves,
        warnings,
        sum(len(versions) for versions in ever_top.values()),
        sum(len(versions) for versions in kept.values()),
        tip_tree_matches,
        tip_identical,
    )


def verify_blobs(integrations: Path, stack_plans: List[StackPlan]) -> Tuple[int, List[dict], int]:
    expected: Dict[str, Tuple[str, int]] = {}
    for stack_plan in stack_plans:
        for _, ops in stack_plan.plan:
            for op in ops:
                if op["op"] == "write" and op.get("ruleId"):
                    expected[str(op["blob"])] = (str(op["ruleId"]), int(op["version"]))
    reader = BlobReader(integrations)
    problems: List[dict] = []
    stubs = 0
    for blob, (rule_id, version) in expected.items():
        attributes = json.loads(reader.read(blob))["attributes"]
        if attributes.get("rule_id") != rule_id or attributes.get("version") != version:
            problems.append(
                {"blob": blob, "expected": [rule_id, version], "actual": [attributes.get("rule_id"), attributes.get("version")]}
            )
        if attributes.get("deprecated"):
            stubs += 1
    reader.close()
    return len(expected), problems, stubs


def print_stack(args: argparse.Namespace, stack_plan: StackPlan) -> None:
    branch, ref, plan = stack_plan.branch, stack_plan.ref, stack_plan.plan
    kinds: Dict[str, int] = {}
    behind = 0
    for entry in stack_plan.final_state.values():
        if entry.kind == "package":
            continue
        kinds[entry.kind] = kinds.get(entry.kind, 0) + 1
        behind += entry.behind
    rules_at_tip = sum(1 for entry in stack_plan.final_state.values() if entry.rule_id)
    rules_touched = sum(1 for _, ops in plan if any(op.get("ruleId") for op in ops))
    versions = {f"{op['ruleId']}_{op['version']}" for _, ops in plan for op in ops if op.get("ruleId")}
    tags = [f"{branch}/v{release.version}" for release, _ in plan]
    short = git_out(args.integrations, "rev-parse", "--short", ref).strip()

    print(f"\n=== {branch}  ({ref} @ {short})")
    print(f"  commits (one per package release): {len(plan)}, of which change rules: {rules_touched}, manifest only: {len(plan) - rules_touched}")
    print(f"  rules at tip: {rules_at_tip} {json.dumps(kinds)}, behind their package top version at tip: {behind}")
    print(f"  rule versions ever top of a release: {stack_plan.ever_top_count}, kept ({"all" if args.keep_latest is None else f"earliest + latest {args.keep_latest}"}): {stack_plan.kept_count}, written: {len(versions)}")
    print(f"  rule files at tip identical to the package's: {stack_plan.tip_identical} of {rules_at_tip}")
    print(f"  folder moves: {stack_plan.moves}, duplicate tags: {len(tags) - len(set(tags))}")
    if not stack_plan.tip_tree_matches:
        print("  ! the tip of the ref has rule changes that are not in a version-bump commit")
    for warning in stack_plan.warnings[:5]:
        print(f"  ! {warning}")

    def show(item: Tuple[Release, List[Op]]) -> None:
        release, ops = item
        writes = sum(1 for op in ops if op.get("ruleId"))
        print(f"    {release.date[:10]}  v{release.version:<14} +/~{writes:>4} rules  {release.sha[:10]}")

    print("  first:")
    for item in plan[:3]:
        show(item)
    print("  last:")
    for item in plan[-3:]:
        show(item)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def remove_empty_dirs(repo: Path, start: Path) -> None:
    root = repo / LIBRARY_DIR
    directory = start
    while directory != root and root in directory.parents:
        if not directory.exists() or any(directory.iterdir()):
            return
        directory.rmdir()
        directory = directory.parent


def start_branch(repo: Path, branch: str) -> None:
    exists = git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
    if exists:
        raise RuntimeError(f"Branch {branch} already exists in {repo}")
    git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    git(repo, "read-tree", "--empty")
    shutil.rmtree(repo / LIBRARY_DIR, ignore_errors=True)
    for path in ROOT_PACKAGE_PATHS:
        (repo / path).unlink(missing_ok=True)


def apply_stack(args: argparse.Namespace, repo: Path, stack_plan: StackPlan) -> None:
    branch, plan = stack_plan.branch, stack_plan.plan
    start_branch(repo, branch)
    reader = BlobReader(args.integrations)
    used_tags: Set[str] = set()

    for index, (release, ops) in enumerate(plan, start=1):
        for op in ops:
            target = repo / str(op["path"])
            if op["op"] == "write":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(REWRITTEN.get(str(op["blob"])) or reader.read(str(op["blob"])))
            else:
                target.unlink()
                remove_empty_dirs(repo, target.parent)
        static_paths = [path for path in STATIC_PATHS if (repo / path).exists()]
        root_paths = sorted({str(op["path"]) for op in ops if str(op["path"]) in ROOT_PACKAGE_PATHS})
        git(repo, "add", "-A", "--", LIBRARY_DIR, *root_paths, *static_paths)

        identity = {
            "GIT_AUTHOR_NAME": release.author_name,
            "GIT_AUTHOR_EMAIL": release.author_email,
            "GIT_AUTHOR_DATE": release.date,
            "GIT_COMMITTER_NAME": release.author_name,
            "GIT_COMMITTER_EMAIL": release.author_email,
            "GIT_COMMITTER_DATE": release.date,
        }
        message = (
            f"{release.subject}\n\nSource: elastic/integrations@{release.sha}\n"
            f"Package: security_detection_engine {release.version}"
        )
        git(repo, "-c", "commit.gpgsign=false", "commit", "--no-verify", "-q", "-m", message, env={**os.environ, **identity})

        tag = f"{branch}/v{release.version}"
        if tag in used_tags:
            print(f"  ! tag {tag} already used in this branch, not tagging {release.sha[:10]}", file=sys.stderr)
        else:
            git(repo, "tag", tag)
        used_tags.add(tag)

        if index % 50 == 0 or index == len(plan):
            print(f"  {branch}: committed {index}/{len(plan)}")
    reader.close()


def verify_applied(repo: Path, stack_plan: StackPlan) -> None:
    """Check the branch tip and its tags against the plan. Blob ids equal the integrations ones."""
    branch = stack_plan.branch
    tree = git_out(repo, "ls-tree", "-r", branch, "--", LIBRARY_DIR, *ROOT_PACKAGE_PATHS)
    actual = {}
    for line in filter(None, tree.split("\n")):
        meta, path = line.split("\t", 1)
        actual[path] = meta.split()[2]
    expected = {path: entry.blob for path, entry in stack_plan.final_state.items()}
    commits = int(git_out(repo, "rev-list", "--count", branch).strip())
    tags = len(git_out(repo, "tag", "--list", f"{branch}/v*").split())
    problems = []
    if actual != expected:
        problems.append("tip tree differs from the plan")
    if commits != len(stack_plan.plan):
        problems.append(f"{commits} commits, expected {len(stack_plan.plan)}")
    if tags != len(stack_plan.plan):
        problems.append(f"{tags} tags, expected {len(stack_plan.plan)}")
    print(f"  verified {branch}: {len(actual)} files, {commits} commits, {tags} tags" + (f"  ! {problems}" if problems else ""))
    if problems:
        raise RuntimeError(f"Verification failed for {branch}: {problems}")


def main() -> None:
    args = parse_args()
    started_at = time.monotonic()
    repo = Path(git_out(args.repo, "rev-parse", "--show-toplevel").strip())
    base_sha = git_out(args.detection_rules, "rev-parse", args.detection_rules_ref).strip()
    stacks = [
        tuple(entry.split("=", 1)) for entry in args.stacks.split(",") if not args.only or entry.split("=")[0] == args.only
    ]

    print(f"Integrations: {args.integrations}")
    print(f"Detection-rules paths from: {args.detection_rules} @ {base_sha[:12]}")
    print(f"Output repo: {repo}")

    snapshots = Snapshots(args.detection_rules, base_sha)
    stack_plans = [plan_stack(args, branch, ref, snapshots) for branch, ref in stacks]
    for stack_plan in stack_plans:
        print_stack(args, stack_plan)

    checked, problems, stubs = verify_blobs(args.integrations, stack_plans)
    print(f"\nChecked {checked} distinct rule files: {len(problems)} name/content mismatches, {stubs} deprecated stubs")
    for problem in problems[:5]:
        print(f"  {json.dumps(problem)}")

    if args.plan_out:
        serializable = [
            {
                "branch": stack_plan.branch,
                "releases": [
                    {"commit": release.sha, "date": release.date, "version": release.version, "ops": ops}
                    for release, ops in stack_plan.plan
                ],
            }
            for stack_plan in stack_plans
        ]
        args.plan_out.write_text(json.dumps(serializable, indent=2))
        print(f"Plan written to {args.plan_out}")

    seconds = time.monotonic() - started_at
    if not args.apply:
        print(f"\nDry run: nothing written ({seconds:.0f}s). Pass --apply to create the branches.")
        return
    if problems:
        raise RuntimeError("Refusing to apply with name/content mismatches")
    for stack_plan in stack_plans:
        apply_stack(args, repo, stack_plan)
    print("\nVerifying the branches against the plan...")
    for stack_plan in stack_plans:
        verify_applied(repo, stack_plan)
    git(repo, "checkout", "-q", stack_plans[0].branch)
    print(f"\nDone in {time.monotonic() - started_at:.0f}s.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        print(f"\nFailed: {detail}", file=sys.stderr)
        sys.exit(1)
