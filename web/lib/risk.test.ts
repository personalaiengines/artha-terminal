import { describe, expect, it } from "vitest";
import {
  annualisedPct, beta, correlation, correlationMatrix, covariance, drawdownStats,
  hhi, histogram, mean, percentile, returns, riskContribution, stdev,
  stressScenarios, underwater,
} from "./risk";

// Known-answer tests where possible. Statistics that only agree with themselves
// are how a plausible-but-wrong risk number ships.

describe("returns", () => {
  it("computes period-over-period returns", () => {
    // Compared with toBeCloseTo, not toEqual: 99/110-1 is -0.09999999999999998
    // in binary floating point, and an exact-equality assertion on derived
    // floats fails for reasons that have nothing to do with the maths.
    const r = returns([100, 110, 99]);
    expect(r).toHaveLength(2);
    expect(r[0]).toBeCloseTo(0.1, 12);
    expect(r[1]).toBeCloseTo(-0.1, 12);
  });

  it("produces n-1 returns", () => {
    expect(returns([1, 2, 3, 4]).length).toBe(3);
  });

  it("skips a zero or non-finite prior price instead of emitting Infinity", () => {
    // 0 -> 50 is an undefined return, not an infinite one. One bad tick must not
    // poison every downstream statistic.
    const r = returns([100, 0, 50, 55]);
    expect(r.every(Number.isFinite)).toBe(true);
    expect(r).toContainEqual(-1); // 100 -> 0 is a real -100%
    expect(r.some((x) => x === Infinity)).toBe(false);
  });

  it("returns nothing for a series too short to have a return", () => {
    expect(returns([])).toEqual([]);
    expect(returns([100])).toEqual([]);
  });
});

describe("stdev / mean", () => {
  it("uses the sample (n-1) denominator", () => {
    // [2,4,4,4,5,5,7,9]: population sd 2, sample sd = sqrt(32/7)
    expect(stdev([2, 4, 4, 4, 5, 5, 7, 9])).toBeCloseTo(Math.sqrt(32 / 7), 12);
  });
  it("is zero when there is nothing to vary", () => {
    expect(stdev([])).toBe(0);
    expect(stdev([5])).toBe(0);
    expect(stdev([5, 5, 5])).toBe(0);
  });
  it("means an empty series to 0 rather than NaN", () => {
    expect(mean([])).toBe(0);
  });
});

describe("annualisedPct", () => {
  it("scales a daily sd by sqrt(252) into percent", () => {
    expect(annualisedPct(0.01)).toBeCloseTo(1 * Math.sqrt(252), 10);
  });
});

describe("covariance / correlation", () => {
  it("correlates a series with itself at exactly 1", () => {
    const a = [0.01, -0.02, 0.03, 0.005, -0.01];
    expect(correlation(a, a)).toBeCloseTo(1, 12);
  });

  it("correlates a series with its negation at exactly -1", () => {
    const a = [0.01, -0.02, 0.03, 0.005, -0.01];
    expect(correlation(a, a.map((x) => -x))).toBeCloseTo(-1, 12);
  });

  it("matches a hand-computed correlation", () => {
    // x=[1,2,3,4,5], y=[2,4,5,4,5] -> r = 0.8挼 ... computed: 0.7745966692
    const r = correlation([1, 2, 3, 4, 5], [2, 4, 5, 4, 5]);
    expect(r).toBeCloseTo(0.7745966692414834, 10);
  });

  it("is scale-invariant", () => {
    const a = [1, 2, 3, 4, 5];
    const b = [2, 4, 5, 4, 5];
    expect(correlation(a, b)).toBeCloseTo(correlation(a.map((x) => x * 100), b)!, 12);
  });

  it("returns null for a flat series rather than 0", () => {
    // Undefined and "uncorrelated" are opposite messages to someone sizing up.
    expect(correlation([1, 1, 1, 1], [1, 2, 3, 4])).toBeNull();
  });

  it("returns null when there is nothing to pair", () => {
    expect(correlation([], [])).toBeNull();
    expect(correlation([1], [1])).toBeNull();
  });

  it("aligns unequal series on their most recent overlap", () => {
    const long = [9, 9, 1, 2, 3, 4, 5];
    const short = [1, 2, 3, 4, 5];
    expect(correlation(long, short)).toBeCloseTo(1, 12);
  });

  it("covaries a constant series to zero", () => {
    expect(covariance([1, 1, 1], [1, 2, 3])).toBe(0);
  });
});

describe("correlationMatrix", () => {
  const A = [100, 101, 102, 103, 104];

  // Correlation is over RETURNS, not prices, and the difference bites here.
  // A linearly falling price series is NOT return-anticorrelated with a linearly
  // rising one — [10, 9.9, 9.8, 9.7] has returns that grow more negative while
  // A's grow less positive, so the two correlate at +0.9998. To actually invert
  // A, compound the negation of its returns.
  const invert = (base: number, prices: number[]) => {
    const out = [base];
    returns(prices).forEach((r) => out.push(out[out.length - 1] * (1 - r)));
    return out;
  };
  const scale = (k: number, prices: number[]) => prices.map((p) => p * k);

  const series = {
    A,
    B: scale(0.5, A),        // identical returns -> correlation +1
    C: invert(10, A),        // exactly negated returns -> correlation -1
  };

  it("has a unit diagonal and is symmetric", () => {
    const { symbols, matrix } = correlationMatrix(series);
    expect(symbols).toEqual(["A", "B", "C"]);
    symbols.forEach((_, i) => expect(matrix[i][i]).toBe(1));
    for (let i = 0; i < symbols.length; i++)
      for (let j = 0; j < symbols.length; j++)
        expect(matrix[i][j]).toBeCloseTo(matrix[j][i]!, 12);
  });

  it("finds the co-movers and the opposite", () => {
    const { matrix } = correlationMatrix(series);
    expect(matrix[0][1]).toBeCloseTo(1, 6);
    expect(matrix[0][2]).toBeCloseTo(-1, 6);
  });

  it("drops symbols with no usable history", () => {
    const { symbols } = correlationMatrix({ ...series, D: [1], E: [] });
    expect(symbols).toEqual(["A", "B", "C"]);
  });
});

describe("beta", () => {
  it("is 1 against itself and 2 for a doubly-sensitive series", () => {
    const bench = [0.01, -0.02, 0.015, -0.005, 0.02];
    expect(beta(bench, bench)).toBeCloseTo(1, 12);
    expect(beta(bench.map((x) => x * 2), bench)).toBeCloseTo(2, 12);
  });
  it("is null when the benchmark never moved", () => {
    expect(beta([0.01, 0.02], [0, 0])).toBeNull();
  });
});

describe("underwater / drawdownStats", () => {
  const points = [
    { t: "d1", v: 100 }, { t: "d2", v: 120 }, { t: "d3", v: 90 },
    { t: "d4", v: 100 }, { t: "d5", v: 130 }, { t: "d6", v: 120 },
  ];

  it("measures against the running peak, never a later one", () => {
    const uw = underwater(points);
    expect(uw[0].ddPct).toBe(0);              // first point is its own peak
    expect(uw[1].ddPct).toBe(0);              // new high
    expect(uw[2].ddPct).toBeCloseTo(-25, 10); // 90 vs peak 120
    expect(uw[4].ddPct).toBe(0);              // recovered to a new high
  });

  it("reports the worst trough and where it happened", () => {
    const s = drawdownStats(points);
    expect(s.worstPct).toBeCloseTo(-25, 10);
    expect(s.worstAt).toBe("d3");
  });

  it("counts the longest underwater run, not the total days below water", () => {
    // d3,d4 are one run of 2; d6 is a separate run of 1.
    expect(drawdownStats(points).longestDays).toBe(2);
  });

  it("reports the current drawdown and whether it has recovered", () => {
    const s = drawdownStats(points);
    expect(s.currentPct).toBeCloseTo((120 / 130 - 1) * 100, 10);
    expect(s.recovered).toBe(false);
    expect(drawdownStats([{ t: "a", v: 1 }, { t: "b", v: 2 }]).recovered).toBe(true);
  });

  it("handles an empty series without throwing", () => {
    const s = drawdownStats([]);
    expect(s.worstPct).toBe(0);
    expect(s.worstAt).toBeNull();
    expect(s.series).toEqual([]);
  });
});

describe("percentile", () => {
  it("hits the exact endpoints", () => {
    expect(percentile([1, 2, 3, 4, 5], 0)).toBe(1);
    expect(percentile([1, 2, 3, 4, 5], 1)).toBe(5);
  });
  it("interpolates between observations", () => {
    expect(percentile([1, 2, 3, 4], 0.5)).toBeCloseTo(2.5, 12);
  });
  it("does not depend on input order", () => {
    expect(percentile([5, 1, 4, 2, 3], 0.25)).toBe(percentile([1, 2, 3, 4, 5], 0.25));
  });
  it("is null on an empty series", () => {
    expect(percentile([], 0.5)).toBeNull();
  });
});

describe("histogram", () => {
  it("bins every observation exactly once", () => {
    const xs = [1, 2, 2, 3, 3, 3, 4, 5];
    const bins = histogram(xs, 4);
    expect(bins.reduce((a, b) => a + b.count, 0)).toBe(xs.length);
  });
  it("puts the maximum in the last bin rather than off the end", () => {
    const bins = histogram([0, 1, 2, 3, 10], 5);
    expect(bins[bins.length - 1].count).toBeGreaterThanOrEqual(1);
    expect(bins.reduce((a, b) => a + b.count, 0)).toBe(5);
  });
  it("returns nothing to draw for a constant or tiny series", () => {
    expect(histogram([5, 5, 5])).toEqual([]);
    expect(histogram([1])).toEqual([]);
  });
});

describe("riskContribution", () => {
  // Two uncorrelated-ish names, one clearly more volatile.
  const calm = [100, 100.5, 100, 100.4, 100.1, 100.6, 100.2, 100.7];
  const wild = [100, 108, 94, 110, 92, 112, 90, 115];

  it("reports a lone position's weight but not a fabricated 100% risk share", () => {
    const { rows, portfolioVolPct } = riskContribution({ A: 1 }, { A: wild });
    // One symbol cannot form a covariance matrix with a peer, so the split is
    // unknown. Asserting the null is the point — without it this test passes
    // just as happily if the code invents riskPct: 100.
    expect(rows).toHaveLength(1);
    expect(rows[0].weightPct).toBeCloseTo(100, 10);
    expect(rows[0].riskPct).toBeNull();
    expect(portfolioVolPct).toBeNull();
  });

  it("sums risk contributions to 100%", () => {
    const { rows } = riskContribution({ A: 50, B: 50 }, { A: calm, B: wild });
    const total = rows.reduce((a, r) => a + (r.riskPct ?? 0), 0);
    expect(total).toBeCloseTo(100, 8);
  });

  it("gives the volatile name more risk than its weight", () => {
    // The whole point of the component: equal money, unequal risk.
    const { rows } = riskContribution({ A: 50, B: 50 }, { A: calm, B: wild });
    const wildRow = rows.find((r) => r.symbol === "B")!;
    expect(wildRow.weightPct).toBeCloseTo(50, 8);
    expect(wildRow.riskPct!).toBeGreaterThan(wildRow.weightPct);
  });

  it("reports a portfolio volatility between the two holdings' own", () => {
    const { rows, portfolioVolPct } = riskContribution({ A: 50, B: 50 }, { A: calm, B: wild });
    const vols = rows.map((r) => r.volPct!);
    expect(portfolioVolPct!).toBeGreaterThan(0);
    expect(portfolioVolPct!).toBeLessThan(Math.max(...vols));
  });

  it("reports weights but a null risk split when history is missing", () => {
    const { rows, portfolioVolPct } = riskContribution({ A: 50, B: 50 }, { A: calm, B: [] });
    expect(portfolioVolPct).toBeNull();
    expect(rows.every((r) => r.riskPct === null)).toBe(true);
    // Weights are still known and still reported.
    expect(rows.map((r) => Math.round(r.weightPct))).toEqual([50, 50]);
  });

  it("returns nothing for an unweighted book", () => {
    expect(riskContribution({}, {}).rows).toEqual([]);
    expect(riskContribution({ A: 0 }, { A: calm }).rows).toEqual([]);
  });

  it("normalises weights that do not already sum to 100", () => {
    const { rows } = riskContribution({ A: 1, B: 3 }, { A: calm, B: wild });
    expect(rows.find((r) => r.symbol === "A")!.weightPct).toBeCloseTo(25, 8);
    expect(rows.find((r) => r.symbol === "B")!.weightPct).toBeCloseTo(75, 8);
  });
});

describe("stressScenarios", () => {
  const rets = [0.02, -0.03, 0.01, -0.08, 0.005, -0.01];

  it("marks lived-through shocks as observed and round ones as not", () => {
    const s = stressScenarios(100000, rets);
    expect(s.filter((x) => x.observed).length).toBe(2);
    expect(s.filter((x) => !x.observed).map((x) => x.pct)).toEqual([-5, -10]);
  });

  it("uses the real worst day", () => {
    const worst = stressScenarios(100000, rets)[0];
    expect(worst.pct).toBeCloseTo(-8, 10);
    expect(worst.value).toBeCloseTo(-8000, 6);
  });

  it("still offers the hypotheticals with no history at all", () => {
    const s = stressScenarios(100000, []);
    expect(s.map((x) => x.pct)).toEqual([-5, -10]);
    expect(s.every((x) => !x.observed)).toBe(true);
  });
});

describe("hhi", () => {
  it("scores a single position at the 10000 maximum", () => {
    expect(hhi([100])).toBeCloseTo(10000, 8);
  });
  it("scores n equal positions at 10000/n", () => {
    expect(hhi([25, 25, 25, 25])).toBeCloseTo(2500, 8);
    expect(hhi([20, 20, 20, 20, 20])).toBeCloseTo(2000, 8);
  });
  it("normalises weights that do not sum to 100", () => {
    expect(hhi([1, 1, 1, 1])).toBeCloseTo(2500, 8);
  });
  it("is null for an empty book", () => {
    expect(hhi([])).toBeNull();
    expect(hhi([0, 0])).toBeNull();
  });
});

describe("gaps the first review found", () => {
  it("clamps correlation into [-1, 1] even under floating-point drift", () => {
    const a = [0.001, 0.002, 0.003, 0.004, 0.005];
    const r = correlation(a, a)!;
    expect(r).toBeLessThanOrEqual(1);
    expect(r).toBeGreaterThanOrEqual(-1);
    expect(correlation(a, a.map((x) => -x))!).toBeGreaterThanOrEqual(-1);
  });

  it("emits null, not 0, for a pair with no usable overlap", () => {
    // 0 says 'measured, and they are unrelated'. null says 'not measured'.
    // Sizing a position off the wrong one of those is the whole hazard.
    const { symbols, matrix } = correlationMatrix({
      A: [100, 101, 102, 103],
      B: [50, 50, 50, 50],   // flat: variance 0, correlation undefined
    });
    expect(symbols).toEqual(["A", "B"]);
    expect(matrix[0][1]).toBeNull();
    expect(matrix[1][0]).toBeNull();
    expect(matrix[0][1]).not.toBe(0);
  });

  it("keeps a legitimate zero VaR distinct from an unknown one", () => {
    // A book that never moved has a real 0% 5th-percentile day.
    expect(percentile([0, 0, 0, 0], 0.05)).toBe(0);
    expect(percentile([], 0.05)).toBeNull();
  });
});
