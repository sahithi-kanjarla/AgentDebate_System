"""Statistics, standard library only.

- Wilson 95% interval for one accuracy.
- Paired comparison of two conditions on the same questions: exact McNemar test on the
  discordant pairs, plus a seeded paired bootstrap interval for the accuracy difference.

A difference is only called a difference when BOTH the McNemar p-value is below 0.05 and the
bootstrap interval excludes zero. Anything else is "no detectable difference", whatever the
point estimates look like.
"""

import random
from dataclasses import dataclass
from math import comb, sqrt

Z95 = 1.959964
ALPHA = 0.05
BOOTSTRAP_REPS = 10_000


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. n == 0 gives the uninformative (0, 1)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(x_only: int, y_only: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts (binomial, p = 0.5).

    No discordant pairs means the two conditions agreed on every question: p = 1.
    """
    n = x_only + y_only
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(x_only, y_only) + 1))
    return min(1.0, 2 * tail / 2**n)


def paired_bootstrap(
    diffs: list[int], seed: int, reps: int = BOOTSTRAP_REPS
) -> tuple[float, float]:
    """95% percentile interval of the mean of per-question differences (each -1, 0 or 1)."""
    n = len(diffs)
    if n == 0 or not any(diffs):
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(reps))
    return (means[int(reps * ALPHA / 2)], means[int(reps * (1 - ALPHA / 2)) - 1])


@dataclass(frozen=True)
class Comparison:
    n: int
    x_only: int  # X right, Y wrong
    y_only: int  # Y right, X wrong
    both_right: int
    both_wrong: int
    diff: float  # accuracy(X) - accuracy(Y), as a fraction
    ci: tuple[float, float]
    p: float

    @property
    def discordant(self) -> int:
        return self.x_only + self.y_only

    @property
    def detectable(self) -> bool:
        return self.p < ALPHA and (self.ci[0] > 0 or self.ci[1] < 0)


def compare(x: list[bool], y: list[bool], seed: int = 0) -> Comparison:
    if len(x) != len(y):
        raise ValueError("paired comparison needs the same questions in the same order")
    pairs = list(zip(x, y, strict=True))
    x_only = sum(1 for a, b in pairs if a and not b)
    y_only = sum(1 for a, b in pairs if b and not a)
    both = sum(1 for a, b in pairs if a and b)
    n = len(pairs)
    diffs = [int(a) - int(b) for a, b in pairs]
    return Comparison(
        n=n,
        x_only=x_only,
        y_only=y_only,
        both_right=both,
        both_wrong=n - x_only - y_only - both,
        diff=(x_only - y_only) / n if n else 0.0,
        ci=paired_bootstrap(diffs, seed),
        p=mcnemar_exact(x_only, y_only),
    )


def reading(c: Comparison, x_name: str, y_name: str) -> str:
    """One plain sentence. Never ranks by point estimate unless the evidence supports it."""
    if c.n == 0:
        return "no questions"
    if c.discordant == 0:
        return "no detectable difference (identical outcome on every question)"
    if not c.detectable:
        return (
            f"no detectable difference ({x_name} only: {c.x_only}, {y_name} only: {c.y_only}; "
            f"p = {c.p:.3f})"
        )
    winner, loser = (x_name, y_name) if c.diff > 0 else (y_name, x_name)
    return f"{winner} higher than {loser} (p = {c.p:.3f}, interval excludes 0)"
