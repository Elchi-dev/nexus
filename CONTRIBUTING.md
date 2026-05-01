# contributing to nexus

first off: thank you. genuinely.

---

## philosophy

nexus believes that every function deserves:

- at least one `TypeAlias` or `Protocol`
- a docstring that explains not just *what* but *why* and *at what cost*
- a reason to exist that you could explain to a junior dev at 11pm, slightly tired

we do not believe in simplicity for its own sake.
we do believe in **clarity**, even when the implementation is complex.

these are not contradictions. they are the tension that makes good software.

---

## how to contribute

1. fork the repo
2. create a branch: `git checkout -b feat/your-feature-name`
3. make your changes
4. run `make test` and `make lint` — both must be green
5. push and open a PR against `main`

---

## code style

**Python**: ruff + mypy strict. type everything. if it doesn't have a type hint, does it even exist?

**Rust**: `cargo clippy -- -D warnings` must pass. `cargo fmt` must be clean.

**commits**: conventional commits, please.

| prefix | use for |
|---|---|
| `feat:` | new feature |
| `fix:` | bug fix |
| `refactor:` | code change with no feature/fix |
| `docs:` | documentation only |
| `chore:` | maintenance, deps, config |
| `test:` | adding or fixing tests |

---

## what makes a good PR?

- it does **one thing** clearly
- tests exist for the new behaviour
- the CI is green
- the description explains *why*, not just *what*
- you haven't touched `line_break()` without a very compelling reason

---

## what we won't merge

- anything that removes a design pattern without replacing it with a better one
- `print("\n")` as a replacement for `line_break()` (we will find you)
- PRs that silently make the codebase *less* interesting
- code without type hints (non-negotiable)

---

## first time contributing?

look for issues tagged [`good first issue`](https://github.com/Elchi-Dev/nexus/issues?q=label%3A%22good+first+issue%22).
they're real issues, not busywork.

questions? open a [Discussion](https://github.com/Elchi-Dev/nexus/discussions) — not an Issue.

> [!NOTE]
> we're only slightly joking about the complexity thing.
> good code is clear code. sometimes clear code is also 300 lines. we've made peace with this.
