---
name: code-optimizer
description: Refactor and clean code without changing its behavior - remove dead code, merge duplicated logic, and simplify over-engineered solutions. Use this skill whenever the user asks to optimize, clean up, refactor, simplify, streamline, polish, or tidy code, or mentions dead code, unused lines, duplicate blocks, redundancy, boilerplate, over-complicated logic, or reducing complexity, even if they never say "optimize". Also use it when the user uploads or pastes code with a vague request like "make this better" or "review this for quality". Do NOT use for pure code explanations, algorithm selection, security audits, or performance profiling.
---

# Code Optimizer

Produce a cleaner, simpler version of the user's code that behaves **identically** to the original, and explain exactly what changed and why.

**Core rule:** correctness and readability come before cleverness. If a change might alter behavior and can't be verified from the code alone, do not apply it silently. Flag it as a suggestion.

---

## Scope

**In scope**
- Dead code warning, deduplication (DRY), logic simplification, structural cleanup, safe pattern improvements

**Out of scope** (mention it and stop, or suggest the right approach)
- Replacing an algorithm with a different one (simplifying the existing logic is fine)
- Security auditing or vulnerability fixes
- Architectural redesigns spanning modules
- Breaking API changes (public signatures, exported names, return shapes)
- Blind performance tuning without measurements

---

## Inputs

1. **Code**: a pasted snippet, an uploaded file, or a file path / directory. If a file is mentioned but not present, check the uploads directory before asking.
2. **Optional priority**: readability (default), performance, maintainability, minimal changes, or aggressive refactoring.
3. **Optional constraints**: keep API compatibility, preserve specific names, stay under N lines, keep the same framework or libraries.

If the user gives no priority or constraints, the defaults below can be used.

### Defaults
- **Style:** conservative. Safe, minimal, clearly justified changes.
- **Focus:** clarity over brevity. Don't golf code into unreadable one-liners.
- **Comments:** keep useful ones (why, not what), remove noise and commented-out code.
- **Naming:** prefer clear names over cryptic abbreviations, but don't rename public identifiers.
- **Aggressiveness:** the user can dial it from conservative to aggressive. Follow their setting.

---

## Workflow

### 1. Analyze
Read the whole input before changing anything. Identify intent, then find dead code, duplication, complexity hotspots, and language-specific anti-patterns. Note anything that looks generated (see Edge Cases).

### 2. Plan
Categorize each finding, rank by impact and risk (safest first), and note trade-offs. Decide which changes are safe to apply and which should only be suggested.

### 3. Refactor
Apply changes methodically, preserving behavior, error handling, and public interfaces. Keep the language's idioms and the project's existing conventions.

### 4. Verify
Before responding, check:
- Control flow and error paths are equivalent to the original
- Imports and dependencies still resolve, and nothing still used was removed
- Public signatures and return shapes are unchanged
- The output is syntactically valid for the language
- If you can run the code or its tests (a code execution tool is available), do so on both versions and confirm identical results

### 5. Report
Deliver the optimized code and the change report (format below).

---

## Optimization Categories

### 1. Dead code removal
- Unused imports/requires, variables, parameters, and private functions
- Unreachable blocks (after `return`/`raise`, impossible conditions)
- Commented-out code
- Stubs and helpers that are never called

Before removing something, confirm it isn't used via reflection, dynamic import, decorators, exports, serialization, or a framework convention. When unsure, flag instead of deleting.

### 2. Duplicate logic consolidation
- Repeated if/else blocks → extract a helper
- Near-identical functions → one parameterized function
- Similar loops → one loop or a comprehension/map
- Copy-pasted blocks → shared utility
- Repeated calculations → compute once and reuse
- Parallel conditionals → a single condition or lookup table

Only merge blocks that share the same **purpose**, not just similar-looking syntax. Two blocks that happen to look alike but change for different reasons should stay separate.

### 3. Complexity simplification
- Nested ternaries → if/else or guard clauses (early returns)
- Deep nesting → flatten with early exits
- Callback pyramids → async/await or promise chains
- Long boolean expressions → named intermediate variables
- Over-parameterized functions → sensible defaults
- Needless abstraction layers, wrappers, and single-use indirection → direct implementation
- Redundant steps (convert then convert back, copy then discard, build a list only to iterate it once)

### 4. Style and formatting
- Inconsistent naming → the file's dominant convention
- Excess blank lines and clutter
- Unnecessary parentheses, brackets, or `else` after `return`
- Missing or noisy comments and docstrings

### 5. Pattern improvements
- Magic numbers/strings → named constants
- Repetitive error handling → centralized
- Wrong or wasteful data structure → the appropriate one (e.g., list membership checks → set)
- Verbose or redundant type annotations → concise equivalents
- Redundant conditions → simplified logic

---

## Output Format

Use this structure. Omit any category with no changes. Keep prose tight.

````
# Code Optimization Report

## Summary
[1-2 sentences on what was improved]

## Metrics
- Lines: X → Y (−Z%)
- Complexity: [brief before/after, e.g. max nesting 4 → 2, duplicated blocks 3 → 0]
- Issues fixed: N

## Changes Made
### Dead Code Removed
- [what, where, why it was safe]
### Duplicates Merged
- [what was consolidated into what]
### Complexity Simplified
- [what was simplified and how]
### Style / Pattern Improvements
- [items]

## Optimized Code
[full refactored code in a fenced block with the correct language tag]

## Before / After Highlights
[2-4 short snippets showing the most meaningful changes]

## Notes & Warnings
- [assumptions made]
- [suggestions NOT applied because they carry risk]
- [testing recommendations]
````

**Delivery:**
- Short snippet (under ~40 lines): put everything inline in the reply.
- Uploaded or long file: write the optimized code to a file (same name and extension as the original unless told otherwise), present it, and keep the report in the reply.
- Never overwrite the user's original file.

Report metrics honestly. Don't estimate numbers you can't back up; count lines or say "approx.".

---

## Edge Cases

- **Already clean code:** say so plainly. Apply only genuine minor improvements. Do not invent changes to look useful.
- **Generated code** (protobuf output, ORM migrations, minified bundles, files with "auto-generated / do not edit" headers): don't optimize it. Tell the user and suggest changing the generator or source instead.
- **Untested or dynamic code:** if a change could break behavior that can't be verified statically, mark it `⚠ WARNING` in Notes and leave it unapplied, or apply it only if the user chose aggressive mode.
- **Performance vs. readability conflict:** default to readability, state the trade-off, and let the user choose.
- **Multiple valid approaches:** pick the more idiomatic one and mention the alternative in one line.
- **Conflicting constraints** (e.g., "keep under 20 lines" and "preserve all names"): flag the conflict and ask which wins.
- **Project style guides:** if the user references one or the surrounding code clearly follows one, match it over general preferences.
- **Missing context:** if the snippet references unseen code, assume unseen callers exist. Don't remove or change anything that could be an external interface.

---

## Guardrails

- Do not change behavior, introduce bugs, or break APIs.
- Do not remove error handling, logging, or validation just because it looks verbose. Only remove it if provably redundant.
- Do not add new dependencies.
- Do not rewrite everything for the sake of it. Every change must have a stated reason.
- When in doubt, suggest rather than apply, and when the ambiguity is significant, ask one focused question.