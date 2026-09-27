#!/usr/bin/env python3
"""Sync shared sections into the orchestrator agent files and IDE headers.

The orchestrators under ``plugins/*/agents/`` are self-contained prompts, so a
rule that applies to all of them has to be present in each file. This script
keeps those copies identical: the text lives once in
``tools/agent_shared_sections.md`` and is written into every target between
marker comments.

Usage:
    python3 tools/sync_agent_sections.py            # write
    python3 tools/sync_agent_sections.py --check    # CI: exit 1 on drift
    python3 tools/sync_agent_sections.py --list     # block x target matrix

Exit codes: 0 in sync / written, 1 drift (--check), 2 configuration error.

Canonical file format — free text, then any number of blocks:

    <!-- BLOCK <id>
    targets: agents | files
    only: <agent>, <agent>        (optional, agents only)
    except: <agent>, <agent>      (optional, agents only)
    files: <path>, <path>         (required when targets is files)
    after: <regex matching a heading line>
    -->
    ...markdown body...
    <!-- END BLOCK <id> -->

An agent is named by its directory under ``plugins/``. A block is inserted
immediately before the next ``## `` heading that follows the ``after`` heading,
or at end of file when none follows. Blocks sharing an insertion point keep
their order in the canonical file.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

CANONICAL = "tools/agent_shared_sections.md"
SCRIPT = "tools/sync_agent_sections.py"

BLOCK_OPEN = re.compile(r"^<!-- BLOCK ([a-z0-9-]+)\s*$")
BLOCK_CLOSE = re.compile(r"^<!-- END BLOCK ([a-z0-9-]+) -->\s*$")
MARK_BEGIN = re.compile(r"^<!-- BEGIN SHARED:([a-z0-9-]+) .*-->\s*$")
MARK_END = re.compile(r"^<!-- END SHARED:([a-z0-9-]+) -->\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
SECTION = re.compile(r"^## ")
HEADING = re.compile(r"^#{1,6} ")

HEADER_KEYS = {"targets", "only", "except", "files", "after"}


class ConfigError(Exception):
    """The canonical file or a target cannot be processed as written."""


class Block:
    """One shared section and where it goes."""

    def __init__(
        self,
        id: str,
        targets: str,
        after: re.Pattern,
        body: str,
        only: list[str],
        exclude: list[str],
        files: list[str],
    ) -> None:
        self.id = id
        self.targets = targets
        self.after = after
        self.body = body
        self.only = only
        self.exclude = exclude
        self.files = files

    @property
    def heading(self) -> str | None:
        first = self.body.split("\n", 1)[0]
        return first if HEADING.match(first) else None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _decode(data: bytes) -> tuple[str, str]:
    """Return (text with LF newlines, the newline style the file used)."""
    text = data.decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), eol


def _encode(text: str, eol: str) -> bytes:
    return text.replace("\n", eol).encode("utf-8")


def _split(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n" if lines else ""


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _outside_fences(lines: list[str]):
    """Yield (index, line) for lines that are not inside a fenced code block."""
    fenced = False
    for i, line in enumerate(lines):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield i, line


# ---------------------------------------------------------------------------
# Canonical file
# ---------------------------------------------------------------------------

def parse_canonical(text: str) -> list[Block]:
    lines = _split(text.replace("\r\n", "\n"))
    blocks: list[Block] = []
    seen: set[str] = set()
    i = 0
    while i < len(lines):
        opened = BLOCK_OPEN.match(lines[i])
        if not opened:
            if BLOCK_CLOSE.match(lines[i]):
                raise ConfigError(f"{CANONICAL}:{i + 1}: END BLOCK without a BLOCK")
            i += 1
            continue
        block_id, start = opened.group(1), i + 1
        if block_id in seen:
            raise ConfigError(f"{CANONICAL}:{start}: duplicate block id '{block_id}'")
        seen.add(block_id)

        header: dict[str, str] = {}
        i += 1
        while i < len(lines) and lines[i].strip() != "-->":
            key, sep, value = lines[i].partition(":")
            key = key.strip()
            if not sep or key not in HEADER_KEYS:
                raise ConfigError(
                    f"{CANONICAL}:{i + 1}: block '{block_id}': unrecognised header line"
                )
            header[key] = value.strip()
            i += 1
        if i == len(lines):
            raise ConfigError(f"{CANONICAL}:{start}: block '{block_id}': header not closed")
        i += 1

        body: list[str] = []
        while i < len(lines) and not BLOCK_CLOSE.match(lines[i]):
            if BLOCK_OPEN.match(lines[i]):
                raise ConfigError(
                    f"{CANONICAL}:{i + 1}: block '{block_id}' not closed before next block"
                )
            body.append(lines[i])
            i += 1
        if i == len(lines):
            raise ConfigError(f"{CANONICAL}:{start}: block '{block_id}' is not closed")
        if BLOCK_CLOSE.match(lines[i]).group(1) != block_id:
            raise ConfigError(f"{CANONICAL}:{i + 1}: END BLOCK does not match '{block_id}'")
        i += 1

        blocks.append(_build_block(block_id, header, body, start))
    return blocks


def _build_block(block_id: str, header: dict[str, str], body: list[str], line: int) -> Block:
    where = f"{CANONICAL}:{line}: block '{block_id}'"
    targets = header.get("targets")
    if targets not in ("agents", "files"):
        raise ConfigError(f"{where}: targets must be 'agents' or 'files'")
    if "after" not in header:
        raise ConfigError(f"{where}: missing 'after'")
    try:
        after = re.compile(header["after"])
    except re.error as exc:
        raise ConfigError(f"{where}: bad 'after' regex: {exc}") from exc
    only, exclude, files = (_csv(header.get(k, "")) for k in ("only", "except", "files"))
    if targets == "files" and not files:
        raise ConfigError(f"{where}: targets is 'files' but no 'files' given")
    if targets == "files" and (only or exclude):
        raise ConfigError(f"{where}: 'only'/'except' apply to agents, not files")
    if targets == "agents" and files:
        raise ConfigError(f"{where}: 'files' given but targets is 'agents'")
    if only and exclude:
        raise ConfigError(f"{where}: use 'only' or 'except', not both")
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        raise ConfigError(f"{where}: empty body")
    for text in body:
        if MARK_BEGIN.match(text) or MARK_END.match(text):
            raise ConfigError(f"{where}: body contains a SHARED marker line")
    return Block(block_id, targets, after, "\n".join(body), only, exclude, files)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

def discover_agents(root: Path) -> dict[str, Path]:
    agents: dict[str, Path] = {}
    for path in sorted(root.glob("plugins/*/agents/*.md")):
        key = path.parent.parent.name
        if key in agents:
            raise ConfigError(f"plugins/{key}/agents/: more than one agent file")
        agents[key] = path
    return agents


def plan(root: Path, blocks: list[Block]) -> dict[Path, list[Block]]:
    """Map every target file to the blocks it should carry, in canonical order.

    Every agent is a target even when no block applies to it, so that a block
    left behind in an agent that has since been excluded is still removed.
    """
    agents = discover_agents(root)
    targets: dict[Path, list[Block]] = {path: [] for path in agents.values()}
    for block in blocks:
        if block.targets == "files":
            for rel in block.files:
                path = root / rel
                if not path.is_file():
                    raise ConfigError(f"block '{block.id}': target file not found: {rel}")
                targets.setdefault(path, []).append(block)
            continue
        for key in block.only + block.exclude:
            if key not in agents:
                raise ConfigError(f"block '{block.id}': unknown agent '{key}'")
        for key, path in agents.items():
            if block.only and key not in block.only:
                continue
            if key in block.exclude:
                continue
            targets[path].append(block)
    return targets


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _strip(lines: list[str], name: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        begin = MARK_BEGIN.match(lines[i])
        if not begin:
            if MARK_END.match(lines[i]):
                raise ConfigError(f"{name}:{i + 1}: END SHARED marker without a BEGIN")
            out.append(lines[i])
            i += 1
            continue
        block_id, start = begin.group(1), i + 1
        i += 1
        while i < len(lines) and not MARK_END.match(lines[i]):
            if MARK_BEGIN.match(lines[i]):
                raise ConfigError(f"{name}:{start}: block '{block_id}' has no END marker")
            i += 1
        if i == len(lines):
            raise ConfigError(f"{name}:{start}: block '{block_id}' has no END marker")
        if MARK_END.match(lines[i]).group(1) != block_id:
            raise ConfigError(f"{name}:{i + 1}: END marker does not match '{block_id}'")
        i += 1
        # Collapse the blank lines that surrounded the block to a single one.
        while out and not out[-1].strip():
            out.pop()
        while i < len(lines) and not lines[i].strip():
            i += 1
        if out and i < len(lines):
            out.append("")
    return out


def strip_blocks(text: str, name: str = "<text>") -> str:
    """Return ``text`` with every synced block removed."""
    normalised, eol = _decode(text.encode("utf-8"))
    return _join(_strip(_split(normalised), name)).replace("\n", eol)


def _insertion_index(lines: list[str], block: Block, name: str) -> int:
    anchor = None
    for i, line in _outside_fences(lines):
        if anchor is None:
            if HEADING.match(line) and block.after.search(line):
                anchor = i
        elif SECTION.match(line):
            return i
    if anchor is None:
        raise ConfigError(
            f"{name}: no heading matches {block.after.pattern!r} (block '{block.id}')"
        )
    return len(lines)


def _marker_begin(block: Block) -> str:
    return (
        f"<!-- BEGIN SHARED:{block.id} (synced from {CANONICAL} - edit there, "
        f"then run {SCRIPT}) -->"
    )


def render(text: str, blocks: list[Block], name: str) -> str:
    """Return ``text`` (LF newlines) carrying exactly ``blocks``."""
    lines = _strip(_split(text), name)

    for block in blocks:
        heading = block.heading
        if heading is None:
            continue
        for i, line in _outside_fences(lines):
            if line.rstrip() == heading:
                raise ConfigError(
                    f"{name}:{i + 1}: shared heading '{heading}' appears outside the "
                    f"synced block; remove the hand-written copy"
                )

    by_index: dict[int, list[Block]] = {}
    for block in blocks:
        by_index.setdefault(_insertion_index(lines, block, name), []).append(block)

    for index in sorted(by_index, reverse=True):
        before, after = lines[:index], lines[index:]
        while before and not before[-1].strip():
            before.pop()
        chunk: list[str] = []
        for block in by_index[index]:
            if chunk:
                chunk.append("")
            chunk.append(_marker_begin(block))
            chunk.extend(block.body.split("\n"))
            chunk.append(f"<!-- END SHARED:{block.id} -->")
        lines = before + ([""] if before else []) + chunk + ([""] + after if after else [])
    return _join(lines)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _load(root: Path) -> dict[Path, list[Block]]:
    canonical = root / CANONICAL
    if not canonical.is_file():
        raise ConfigError(f"{CANONICAL}: not found under {root}")
    return plan(root, parse_canonical(canonical.read_bytes().decode("utf-8")))


def run(root: Path, check: bool) -> tuple[int, list[str]]:
    """Sync or check every target under ``root``. Returns (exit code, messages)."""
    root = Path(root).resolve()
    messages: list[str] = []
    try:
        targets = _load(root)
        pending: list[tuple[Path, str, str, str]] = []
        for path, blocks in targets.items():
            name = _rel(root, path)
            current, eol = _decode(path.read_bytes())
            expected = render(current, blocks, name)
            if expected != current:
                pending.append((path, current, expected, eol))
    except (ConfigError, UnicodeDecodeError) as exc:
        return 2, [f"error: {exc}"]

    for path, current, expected, eol in pending:
        name = _rel(root, path)
        if check:
            messages.append(f"drift: {name}")
            messages.extend(
                line.rstrip("\n")
                for line in difflib.unified_diff(
                    current.splitlines(keepends=True),
                    expected.splitlines(keepends=True),
                    fromfile=f"{name} (current)",
                    tofile=f"{name} (expected)",
                )
            )
        else:
            path.write_bytes(_encode(expected, eol))
            messages.append(f"updated {name}")

    if check and pending:
        messages.append(
            f"{len(pending)} file(s) out of sync with {CANONICAL}; run: python3 {SCRIPT}"
        )
        return 1, messages
    messages.append(f"{len(targets)} target(s) in sync with {CANONICAL}")
    return 0, messages


def list_matrix(root: Path) -> tuple[int, list[str]]:
    root = Path(root).resolve()
    try:
        targets = _load(root)
    except (ConfigError, UnicodeDecodeError) as exc:
        return 2, [f"error: {exc}"]
    return 0, [
        f"{_rel(root, path)}: {', '.join(b.id for b in blocks) or '-'}"
        for path, blocks in targets.items()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync shared sections into orchestrator agent files and IDE headers."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the repo containing this script)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report drift; write nothing")
    mode.add_argument("--list", action="store_true", help="print which blocks go where")
    args = parser.parse_args(argv)

    code, messages = list_matrix(args.root) if args.list else run(args.root, args.check)
    stream = sys.stdout if code == 0 else sys.stderr
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
