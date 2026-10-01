# Contributing to digital-chip-design-agents

## Skill File Standards

Every `SKILL.md` must have these sections in order:

```markdown
---                          ← YAML frontmatter (required)
name: domain-name
description: >
  One-sentence description for Claude Code's skill discovery.
version: x.y.z
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Domain Name

## Purpose
One paragraph — what this skill enables Claude to do.

## Stage: stage_name          ← Repeat per stage

### Domain Rules
Numbered rules. Be specific — vague rules are not useful.

### QoR Metrics to Evaluate
Measurable pass/fail criteria with units (ns, %, count).

### Common Issues & Fixes
Table: Issue | Fix

### Output Required
Bullet list of files/artifacts the stage must produce.
```

## Adding a New Skill

1. Create `plugins/<new-domain>/skills/<new-domain>/SKILL.md` following the standard above.

2. Add an entry to `.claude-plugin/marketplace.json`:
```json
{
  "name": "chip-design-<new-domain>",
  "source": { "source": "github", "repo": "chuanseng-ng/digital-chip-design-agents" },
  "description": "One-line description",
  "category": "engineering",
  "keywords": ["keyword1", "keyword2"]
}
```

3. Create `plugins/<new-domain>/agents/<new-domain>-orchestrator.md` with this minimum structure:
```markdown
---
name: <new-domain>-orchestrator
description: >
  When to invoke this orchestrator.
model: sonnet
effort: high
maxTurns: 50
skills:
  - digital-chip-design-agents:<new-domain>
---

## Stage Sequence
stage_1 → stage_2 → stage_3

## Loop-Back Rules
- stage_2 FAIL (condition)  → stage_1  (max N×)

## Sign-off Criteria
- metric_name: value

## Behaviour Rules
1. ...
```

4. Add the shared sections. Every orchestrator carries a set of guards word for word — run
   `--list` below to see which block goes where. They are not written by hand:
```bash
python3 tools/sync_agent_sections.py          # writes the shared blocks into each agent
python3 tools/sync_agent_sections.py --list   # shows which block goes where
```
   The text lives once in `tools/agent_shared_sections.md` and is inserted after
   `## Behaviour Rules`, between `BEGIN SHARED` / `END SHARED` marker comments. To change a
   shared rule, edit that file and re-run the script — never edit between the markers. To
   exclude a new agent from a block, add it to the block's `except:` list.

5. Run validation locally:
```bash
python3 -c "
import glob
for p in sorted(glob.glob('plugins/*/skills/*/SKILL.md')):
    c = open(p, encoding='utf-8').read()
    assert c.startswith('---'), f'{p}: missing frontmatter'
    for s in ['## Purpose','## Domain Rules','## QoR Metrics','## Output Required']:
        assert s in c, f'{p}: missing {s}'
    print(f'OK: {p}')
"
python3 tools/sync_agent_sections.py --check
python3 -m pytest tests/ -q
```

6. Open a Pull Request — the CI `validate.yml` must pass before merge.

## Improving Existing Skills

- **Domain Rules**: Be more specific, add new tool-specific commands, update metrics
- **QoR Metrics**: Add units; tighten targets based on real project experience
- **Loop-back rules in orchestrators**: Add new transitions or tighten max iterations

## Pull Request Checklist

- [ ] SKILL.md has YAML frontmatter with `name`, `description`, `version`
- [ ] SKILL.md has all four required sections
- [ ] marketplace.json updated if new domain added
- [ ] Orchestrator .md has frontmatter with `model`, `effort`, `maxTurns`, `skills`
- [ ] Orchestrator .md has `## Stage Sequence`, `## Loop-Back Rules`, `## Sign-off Criteria`, `## Behaviour Rules`
- [ ] Shared sections are in sync: `python3 tools/sync_agent_sections.py --check`
- [ ] Local validation passes (see above)
- [ ] Count remains consistent: agents = marketplace entries, and skills ≥ agents (a plugin may register more than one skill)

## Versioning

- `PATCH` (x.x.1) — fixes or clarifications within existing skills
- `MINOR` (x.1.0) — new skill or orchestrator domain added
- `MAJOR` (2.0.0) — breaking change to frontmatter schema or stage interface

## Shared metadata in plugin.json

Each `plugins/<domain>/.claude-plugin/plugin.json` repeats the same `author`,
`homepage`, `repository`, and `license` fields. These are intentional — the
plugin installer reads each manifest in isolation and requires these fields to
be present. The canonical values are:

```json
"author":     { "name": "chuanseng-ng", "url": "https://github.com/chuanseng-ng" },
"homepage":   "https://github.com/chuanseng-ng/digital-chip-design-agents",
"repository": "https://github.com/chuanseng-ng/digital-chip-design-agents",
"license":    "MIT"
```

When updating these fields, change all 16 `plugin.json` files and
`.claude-plugin/marketplace.json` together.
