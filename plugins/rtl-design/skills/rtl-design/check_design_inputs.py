#!/usr/bin/env python3
"""
check_design_inputs.py — check the input set of an RTL tool run before linting it.

A lint or elaboration tool reports on the files it was given. When the filelist or
an include path resolves to the wrong tree, the tool's messages look like RTL bugs
(duplicate declaration, undeclared identifier) although the RTL is correct. This
script resolves a `.f` filelist the way a tool does and reports what is wrong with
the input set itself. It reads; it never writes or edits a design file.

Usage:
    python3 check_design_inputs.py <filelist.f> [--root DIR] [--cwd DIR]
        [--env NAME=VALUE ...] [--generated OUT_DIR=SOURCE ...]

    --root       design root; include dirs and sources outside it are reported, and the
                 search for sibling trees on disk stops there
    --cwd        directory the tool runs from (default: current directory)
    --env        value for $NAME / ${NAME} / $(NAME) in the filelist, over the environment
    --generated  a generated output dir on the include path and the generator source
                 (file or dir) it is built from; reported if the output is older

Filelist syntax understood: `-f` (paths relative to --cwd), `-F` (paths relative to
the filelist that names them), `+incdir+a+b`, `-I dir`, `-Idir`, `-incdir dir`,
`-y dir`, `//` and `#` comments. Other options are ignored. A vendor project file is
not a `.f` filelist: apply the `design_input_check` rules in SKILL.md by hand.

Output: one JSON object on stdout. Exit code 1 if status is FAIL, 2 on a usage error,
0 otherwise.
"""

import argparse
import json
import os
import re
import sys

HDL_EXTS = {".v", ".vh", ".sv", ".svh", ".svi", ".vp", ".svp", ".h", ".inc"}
SOURCE_EXTS = HDL_EXTS | {".vhd", ".vhdl"}
VAR_RE = re.compile(r"\$\{(\w+)\}|\$\((\w+)\)|\$(\w+)")
# regmap_gen / regmap_gen_v2 / regmap_gen_old / regmap_gen.bak / regmap_gen-2 / v1 / v2.
# A bare digit needs a separator: uart0 and uart1 are two instances, not two versions.
_VERSION_WORD = r"(?:v?\d+(?:[._]\d+)*|old|new|bak|backup|orig|prev|copy|tmp|legacy|deprecated)"
VERSION_SUFFIX_RE = re.compile(rf"(?:[._-]{_VERSION_WORD}|v\d+)+$", re.I)
VERSION_ONLY_RE = re.compile(rf"^{_VERSION_WORD}$", re.I)
MAX_ANCESTORS = 4


class Inputs:
    def __init__(self, cwd, env):
        self.cwd = cwd
        self.env = env
        self.filelists = []
        self.include_dirs = []
        self.library_dirs = []
        self.sources = []
        self.issues = []

    def issue(self, severity, kind, message, paths=(), **extra):
        entry = {"severity": severity, "kind": kind, "message": message, "paths": list(paths)}
        entry.update(extra)
        self.issues.append(entry)


def _expand(token, inputs, origin):
    """Expand $VAR forms; return None (and report) if a variable has no value."""
    missing = []

    def repl(match):
        name = match.group(1) or match.group(2) or match.group(3)
        if name in inputs.env:
            return inputs.env[name]
        missing.append(name)
        return match.group(0)

    expanded = VAR_RE.sub(repl, token)
    if missing:
        inputs.issue(
            "WARN", "unresolved_variable",
            f"{', '.join(sorted(set(missing)))} has no value, so '{token}' was not checked "
            "- pass --env NAME=VALUE",
            [origin],
        )
        return None
    return expanded


def _resolve(path, base):
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))


def _strip_comment(line):
    line = line.split("//", 1)[0]
    if line.lstrip().startswith("#"):
        return ""
    return line


def _add_dir(dirs, path):
    if path not in dirs:
        dirs.append(path)


def parse_filelist(path, base, inputs, stack=()):
    """Read one filelist. `base` is the directory its relative paths resolve against."""
    path = os.path.normpath(path)
    if path in stack:
        inputs.issue("ERROR", "filelist_cycle", f"filelist includes itself: {path}", [path])
        return
    if not os.path.isfile(path):
        inputs.issue("ERROR", "missing_filelist", f"filelist not found: {path}", [path])
        return
    inputs.filelists.append(path)

    tokens = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            tokens.extend(_strip_comment(line).split())

    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1

        def value():
            """The option's argument, expanded; None if absent or unresolvable."""
            nonlocal i
            if i >= len(tokens):
                return None
            raw = tokens[i]
            i += 1
            return _expand(raw, inputs, path)

        if token in ("-f", "-F"):
            nested = value()
            if nested is None:
                continue
            if token == "-f":
                nested_path = _resolve(nested, base)
                parse_filelist(nested_path, base, inputs, stack + (path,))
            else:
                nested_path = _resolve(nested, os.path.dirname(path))
                parse_filelist(nested_path, os.path.dirname(nested_path), inputs, stack + (path,))
        elif token.startswith("+incdir+"):
            for part in token[len("+incdir+"):].split("+"):
                part = _expand(part, inputs, path) if part else None
                if part:
                    _add_dir(inputs.include_dirs, _resolve(part, base))
        elif token in ("-I", "-incdir"):
            part = value()
            if part:
                _add_dir(inputs.include_dirs, _resolve(part, base))
        elif token.startswith("-I") and len(token) > 2:
            part = _expand(token[2:], inputs, path)
            if part:
                _add_dir(inputs.include_dirs, _resolve(part, base))
        elif token == "-y":
            part = value()
            if part:
                _add_dir(inputs.library_dirs, _resolve(part, base))
        elif token.startswith(("-", "+")):
            continue
        else:
            expanded = _expand(token, inputs, path)
            if expanded is None:
                continue
            resolved = _resolve(expanded, base)
            # A bare word after an option this script does not know is that option's
            # value, not a source: only treat it as one if it looks like a design file.
            if os.path.isfile(resolved) or os.path.splitext(resolved)[1].lower() in SOURCE_EXTS:
                inputs.sources.append(resolved)


def _same_content(paths):
    first = None
    for path in paths:
        with open(path, "rb") as handle:
            data = handle.read()
        if first is None:
            first = data
        elif data != first:
            return False
    return True


def _hdl_names(directory):
    if not os.path.isdir(directory):
        return set()
    return {
        name for name in os.listdir(directory)
        if os.path.splitext(name)[1].lower() in HDL_EXTS
        and os.path.isfile(os.path.join(directory, name))
    }


def check_search_dirs(dirs, label, inputs):
    """A tool searches these directories in order and takes the first match."""
    seen = {}
    for directory in dirs:
        if not os.path.isdir(directory):
            inputs.issue("ERROR", f"missing_{label}_dir",
                         f"{label} directory does not exist: {directory}", [directory])
            continue
        for name in sorted(_hdl_names(directory)):
            seen.setdefault(name, []).append(os.path.join(directory, name))

    for name, paths in sorted(seen.items()):
        if len(paths) < 2:
            continue
        if _same_content(paths):
            inputs.issue(
                "WARN", f"duplicate_{label}_identical",
                f"'{name}' is in {len(paths)} {label} directories with identical content; "
                f"{paths[0]} is the one used. Harmless until one copy changes",
                paths, basename=name, wins=paths[0],
            )
        else:
            inputs.issue(
                "ERROR", f"duplicate_{label}",
                f"'{name}' is in {len(paths)} {label} directories with different content. "
                f"Search is first-match-wins, so {paths[0]} is used and the other "
                f"{'copy is' if len(paths) == 2 else 'copies are'} ignored",
                paths, basename=name, wins=paths[0],
            )


def _version_base(name):
    return "" if VERSION_ONLY_RE.match(name) else VERSION_SUFFIX_RE.sub("", name)


def _are_siblings(a, b):
    """True if two directory names are versions of one name: X and X_v2, v1 and v2."""
    return a != b and _version_base(a).lower() == _version_base(b).lower()


def _within(path, root):
    path, root = os.path.normcase(path), os.path.normcase(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def check_sibling_trees(dirs, label, root, inputs):
    """Report parallel version trees that hold a same-named file: two on the search
    path, or one on disk beside a directory that is on it."""
    reported = set()

    # Two directories on the path that differ in one component, by a version suffix.
    for i, first in enumerate(dirs):
        for second in dirs[i + 1:]:
            a, b = first.split(os.sep), second.split(os.sep)
            if len(a) != len(b):
                continue
            diff = [k for k in range(len(a)) if a[k] != b[k]]
            if (len(diff) == 1 and _are_siblings(a[diff[0]], b[diff[0]])
                    and _hdl_names(first) & _hdl_names(second)):
                reported.update((first, second))
                inputs.issue(
                    "WARN", "sibling_tree",
                    f"two versions of one tree are both on the {label} path "
                    f"('{a[diff[0]]}' and '{b[diff[0]]}'); the first listed wins: {first}",
                    [first, second],
                )

    # A version sibling of an ancestor that holds the same sub-path but is not on the path.
    for directory in dirs:
        if directory in reported:
            continue
        names = _hdl_names(directory)
        current, tail = directory, []
        for _ in range(MAX_ANCESTORS):
            parent, name = os.path.split(current)
            if not name or not os.path.isdir(parent):
                break
            if root is not None and not _within(parent, root):
                break
            for other in sorted(os.listdir(parent)):
                if not _are_siblings(name, other):
                    continue
                candidate = os.path.join(parent, other, *reversed(tail))
                if candidate not in dirs and names & _hdl_names(candidate):
                    inputs.issue(
                        "WARN", "sibling_tree_on_disk",
                        f"'{other}' beside '{name}' holds the same file names but is not on the "
                        f"{label} path - confirm {directory} is the current tree",
                        [directory, candidate],
                    )
            tail.append(name)
            current = parent


def check_outside_root(root, inputs):
    if root is None:
        return
    for kind, paths in (("include directory", inputs.include_dirs),
                        ("library directory", inputs.library_dirs),
                        ("source", inputs.sources)):
        for path in paths:
            if not _within(path, root):
                inputs.issue("WARN", "outside_root",
                             f"{kind} resolves outside the design root {root}: {path}", [path])


def check_sources(inputs):
    by_name = {}
    for path in inputs.sources:
        if not os.path.isfile(path):
            inputs.issue("ERROR", "missing_source", f"source file does not exist: {path}", [path])
        by_name.setdefault(os.path.basename(path), [])
        if path not in by_name[os.path.basename(path)]:
            by_name[os.path.basename(path)].append(path)
    for name, paths in sorted(by_name.items()):
        if len(paths) > 1:
            inputs.issue("WARN", "duplicate_source",
                         f"'{name}' is listed from {len(paths)} different directories", paths,
                         basename=name)


def _newest_mtime(path):
    if os.path.isfile(path):
        return os.path.getmtime(path)
    newest = None
    for folder, _, names in os.walk(path):
        for name in names:
            mtime = os.path.getmtime(os.path.join(folder, name))
            newest = mtime if newest is None else max(newest, mtime)
    return newest


def check_generated(pairs, cwd, inputs):
    for pair in pairs:
        out_dir, sep, source = pair.partition("=")
        if not sep or not out_dir or not source:
            inputs.issue("ERROR", "bad_generated_argument",
                         f"--generated expects OUT_DIR=SOURCE, got '{pair}'", [])
            continue
        out_dir, source = _resolve(out_dir, cwd), _resolve(source, cwd)
        out_time = _newest_mtime(out_dir) if os.path.exists(out_dir) else None
        src_time = _newest_mtime(source) if os.path.exists(source) else None
        if out_time is None or src_time is None:
            inputs.issue("ERROR", "missing_generated",
                         f"generated output or its source is missing or empty: {out_dir} <- {source}",
                         [out_dir, source])
        elif out_time < src_time:
            inputs.issue("WARN", "stale_generated",
                         f"generated output {out_dir} is older than its source {source} - regenerate",
                         [out_dir, source])
        if out_dir not in inputs.include_dirs:
            inputs.issue("WARN", "generated_not_on_path",
                         f"generated output {out_dir} is not one of the include directories",
                         [out_dir])


def run(filelist, root=None, cwd=None, env=None, generated=()):
    cwd = os.path.abspath(cwd or os.getcwd())
    merged_env = dict(os.environ)
    merged_env.update(env or {})
    inputs = Inputs(cwd, merged_env)
    root = _resolve(root, cwd) if root else None

    top = _resolve(filelist, cwd)
    parse_filelist(top, cwd, inputs)
    check_search_dirs(inputs.include_dirs, "include", inputs)
    check_search_dirs(inputs.library_dirs, "library", inputs)
    check_sibling_trees(inputs.include_dirs, "include", root, inputs)
    check_sibling_trees(inputs.library_dirs, "library", root, inputs)
    check_outside_root(root, inputs)
    check_sources(inputs)
    check_generated(generated, cwd, inputs)

    errors = [i for i in inputs.issues if i["severity"] == "ERROR"]
    warnings = [i for i in inputs.issues if i["severity"] == "WARN"]
    # An empty input set is not a clean one: nothing was checked.
    evidence = bool(inputs.sources or inputs.include_dirs or inputs.library_dirs)
    if errors:
        status = "FAIL"
    elif not evidence:
        status = "WARN"
        inputs.issue("WARN", "empty_input_set",
                     "no sources or include directories found in the filelist - not verified", [top])
        warnings = [i for i in inputs.issues if i["severity"] == "WARN"]
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"

    kinds = {}
    for entry in inputs.issues:
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1

    return {
        "tool": "design-input-check",
        "status": status,
        "verified": status == "FAIL" or evidence,
        "filelist": top,
        "filelists": inputs.filelists,
        "cwd": cwd,
        "root": root,
        "include_dirs": inputs.include_dirs,
        "library_dirs": inputs.library_dirs,
        "source_count": len(inputs.sources),
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "duplicate_include_basenames": kinds.get("duplicate_include", 0),
            "by_kind": kinds,
        },
        "issues": inputs.issues,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the input set (filelist, include paths) of an RTL tool run"
    )
    parser.add_argument("filelist")
    parser.add_argument("--root")
    parser.add_argument("--cwd")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--generated", action="append", default=[], metavar="OUT_DIR=SOURCE")
    args = parser.parse_args(argv)

    env = {}
    for item in args.env:
        name, sep, value = item.partition("=")
        if not sep or not name:
            parser.error(f"--env expects NAME=VALUE, got '{item}'")
        env[name] = value

    result = run(args.filelist, root=args.root, cwd=args.cwd, env=env, generated=args.generated)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
