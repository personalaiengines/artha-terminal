// Portfolio risk mathematics.
//
// Pure functions over price/value series — no React, no fetching — so the
// statistics can be tested in isolation (web/lib/risk.test.ts) instead of being
// buried in JSX on a page about real money. That page has a history of shipping
// hardcoded risk numbers (beta was once the literal constant 1.06); everything
// here is computed from a real series or returns null.
//
// Convention: every series is OLDEST-FIRST, which is how /api/portfolio/curve
// and /api/history both return them. Order matters for drawdown and for the
// pairing in covariance; it does not for volatility or percentiles.
//
// Missing data is null, never 0. A zero correlation and an unknown correlation
// mean opposite things to someone sizing a position.

export type Point = { t: string; v: number };

/** NSE trading days in a year — the annualisation factor for daily statistics. */
export const TRADING_DAYS = 252;

/** Simple period-over-period returns. n prices produce n-1 returns. */
export function returns(values: number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < values.length; i++) {
    const prev = values[i - 1];
    const cur = values[i];
    // A zero or non-finite prior price has no defined return. Skipping keeps
    // one bad tick from poisoning every statistic downstream with Infinity.
    if (!Number.isFinite(prev) || prev === 0 || !Number.isFinite(cur)) continue;
    out.push(cur / prev - 1);
  }
  return out;
}

export function mean(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}

/** Sample standard deviation (n−1). 0 for fewer than two observations. */
export function stdev(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1));
}

/** A daily standard deviation as an annualised percentage. */
export function annualisedPct(dailyStdev: number): number {
  return dailyStdev * Math.sqrt(TRADING_DAYS) * 100;
}

/** Sample covariance. The two series are aligned on their most recent
 *  overlapping observations, so a symbol with a shorter history shortens the
 *  comparison rather than silently pairing mismatched dates. */
export function covariance(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  if (n < 2) return 0;
  const x = a.slice(a.length - n);
  const y = b.slice(b.length - n);
  const mx = mean(x);
  const my = mean(y);
  let s = 0;
  for (let i = 0; i < n; i++) s += (x[i] - mx) * (y[i] - my);
  return s / (n - 1);
}

/** Pearson correlation, clamped to [−1, 1]. null when either series is flat —
 *  a constant series has no variance, so correlation is undefined, not zero. */
export function correlation(a: number[], b: number[]): number | null {
  const n = Math.min(a.length, b.length);
  if (n < 2) return null;
  const x = a.slice(a.length - n);
  const y = b.slice(b.length - n);
  const sx = stdev(x);
  const sy = stdev(y);
  if (!sx || !sy) return null;
  return Math.max(-1, Math.min(1, covariance(x, y) / (sx * sy)));
}

/** Pairwise correlation of every symbol's returns against every other.
 *  `matrix[i][j]` corresponds to `symbols[i]` vs `symbols[j]`. */
export function correlationMatrix(
  series: Record<string, number[]>
): { symbols: string[]; matrix: (number | null)[][] } {
  const symbols = Object.keys(series).filter((s) => (series[s]?.length ?? 0) > 2);
  const rets = symbols.map((s) => returns(series[s]));
  const matrix = rets.map((a, i) =>
    rets.map((b, j) => (i === j ? 1 : correlation(a, b)))
  );
  return { symbols, matrix };
}

/** Sensitivity to a benchmark: cov(portfolio, benchmark) / var(benchmark).
 *  null when the benchmark never moved. */
export function beta(portfolio: number[], benchmark: number[]): number | null {
  const n = Math.min(portfolio.length, benchmark.length);
  if (n < 2) return null;
  const b = benchmark.slice(benchmark.length - n);
  const varB = stdev(b) ** 2;
  if (!varB) return null;
  return covariance(portfolio.slice(portfolio.length - n), b) / varB;
}

export type Underwater = { t: string; v: number; peak: number; ddPct: number };

/** Percent below the running peak, at every point.
 *
 *  A max-drawdown figure says how deep the hole was. This says how deep AND how
 *  long — which is the part that actually decides whether a drawdown was
 *  survivable.
 */
export function underwater(points: Point[]): Underwater[] {
  let peak = -Infinity;
  return points.map((p) => {
    peak = Math.max(peak, p.v);
    return { t: p.t, v: p.v, peak, ddPct: peak > 0 ? (p.v / peak - 1) * 100 : 0 };
  });
}

export type DrawdownStats = {
  worstPct: number; worstAt: string | null;
  longestDays: number; currentPct: number; recovered: boolean;
  series: Underwater[];
};

export function drawdownStats(points: Point[]): DrawdownStats {
  const series = underwater(points);
  let worstPct = 0;
  let worstAt: string | null = null;
  let longestDays = 0;
  let run = 0;
  for (const d of series) {
    if (d.ddPct < worstPct) {
      worstPct = d.ddPct;
      worstAt = d.t;
    }
    // "Underwater" is strictly below the prior peak; a new high ends the run.
    if (d.ddPct < 0) {
      run += 1;
      if (run > longestDays) longestDays = run;
    } else {
      run = 0;
    }
  }
  const currentPct = series.length ? series[series.length - 1].ddPct : 0;
  return { worstPct, worstAt, longestDays, currentPct, recovered: currentPct >= 0, series };
}

/** Linear-interpolated percentile. `p` in [0, 1]. null on an empty series. */
export function percentile(xs: number[], p: number): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const i = (s.length - 1) * Math.max(0, Math.min(1, p));
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (i - lo);
}

export type Bin = { lo: number; hi: number; mid: number; count: number };

/** Equal-width histogram. Empty when there is nothing to bin or the series is
 *  constant (one bin of everything says nothing worth drawing). */
export function histogram(xs: number[], bins = 21): Bin[] {
  if (xs.length < 2 || bins < 1) return [];
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  if (!(hi > lo)) return [];
  const w = (hi - lo) / bins;
  const out: Bin[] = Array.from({ length: bins }, (_, i) => ({
    lo: lo + i * w, hi: lo + (i + 1) * w, mid: lo + (i + 0.5) * w, count: 0,
  }));
  for (const x of xs) {
    // The maximum sits exactly on the top edge; clamp it into the last bin
    // rather than letting it index a bins+1'th that does not exist.
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((x - lo) / w)));
    out[idx].count += 1;
  }
  return out;
}

export type Contribution = {
  symbol: string;
  weightPct: number;
  riskPct: number | null;
  volPct: number | null;
};

/** Each position's share of PORTFOLIO volatility, rather than of value.
 *
 *  σp² = wᵀΣw. Position i's component contribution to risk is wᵢ·(Σw)ᵢ / σp, and
 *  those components sum exactly to σp. This function returns each as a *share*,
 *  i.e. wᵢ(Σw)ᵢ / σp² — dividing by the variance, not the standard deviation,
 *  is what makes the column sum to 100 rather than to σp.
 *
 *  This is precisely what a value-weighted concentration bar hides. A small
 *  holding in a volatile name that moves with everything else you own can carry
 *  far more risk than its weight suggests, and nothing on a weight chart says so.
 *
 *  Returns `riskPct: null` for every row when there is not enough overlapping
 *  history to form a covariance matrix — an unknown contribution must not be
 *  drawn as a zero one.
 */
export function riskContribution(
  weights: Record<string, number>,
  series: Record<string, number[]>
): { rows: Contribution[]; portfolioVolPct: number | null } {
  const symbols = Object.keys(weights);
  const totalWeight = symbols.reduce((a, s) => a + Math.max(0, weights[s] || 0), 0);
  if (!symbols.length || totalWeight <= 0) return { rows: [], portfolioVolPct: null };

  const weightPct = (s: string) => (Math.max(0, weights[s] || 0) / totalWeight) * 100;

  const usable = symbols.filter((s) => (series[s]?.length ?? 0) > 2);
  const rets = usable.map((s) => returns(series[s]));
  const n = rets.length ? Math.min(...rets.map((r) => r.length)) : 0;

  // Not enough overlapping history for a covariance matrix: report the weights,
  // and say the risk split is unknown rather than inventing one.
  if (usable.length !== symbols.length || usable.length < 2 || n < 2) {
    return {
      rows: symbols.map((s) => ({
        symbol: s, weightPct: weightPct(s), riskPct: null,
        volPct: (series[s]?.length ?? 0) > 2 ? annualisedPct(stdev(returns(series[s]))) : null,
      })),
      portfolioVolPct: null,
    };
  }

  const R = rets.map((r) => r.slice(r.length - n));
  const w = usable.map((s) => Math.max(0, weights[s] || 0) / totalWeight);

  // Covariance matrix once, then reuse — it is symmetric, so only half is computed.
  const cov: number[][] = usable.map(() => new Array(usable.length).fill(0));
  for (let i = 0; i < usable.length; i++) {
    for (let j = i; j < usable.length; j++) {
      const c = covariance(R[i], R[j]);
      cov[i][j] = c;
      cov[j][i] = c;
    }
  }

  const sigmaW = w.map((_, i) => w.reduce((a, wj, j) => a + cov[i][j] * wj, 0));
  const varP = w.reduce((a, wi, i) => a + wi * sigmaW[i], 0);
  const sd = Math.sqrt(Math.max(0, varP));

  if (!sd) {
    return {
      rows: usable.map((s) => ({ symbol: s, weightPct: weightPct(s), riskPct: null, volPct: null })),
      portfolioVolPct: null,
    };
  }

  return {
    rows: usable.map((s, i) => ({
      symbol: s,
      weightPct: weightPct(s),
      // wᵢ(Σw)ᵢ / σp², i.e. the component contribution as a share of σp.
      riskPct: ((w[i] * sigmaW[i]) / varP) * 100,
      volPct: annualisedPct(stdev(R[i])),
    })),
    portfolioVolPct: annualisedPct(sd),
  };
}

export type Scenario = {
  label: string; note: string; pct: number; value: number; observed: boolean;
};

/** What the book loses under a set of one-day shocks.
 *
 *  Two kinds, kept visibly distinct via `observed`: shocks this portfolio has
 *  actually lived through (its own worst day, its 5th-percentile day), and
 *  round hypotheticals. Presenting a hypothetical as if it were history is the
 *  sort of thing this page has been burned by before.
 */
export function stressScenarios(current: number, dailyReturns: number[]): Scenario[] {
  const out: Scenario[] = [];
  const worst = dailyReturns.length ? Math.min(...dailyReturns) : null;
  const p5 = percentile(dailyReturns, 0.05);

  if (worst != null) {
    out.push({
      label: "Worst day repeats", note: `deepest single-day fall in ${dailyReturns.length} sessions`,
      pct: worst * 100, value: current * worst, observed: true,
    });
  }
  if (p5 != null) {
    out.push({
      label: "A bad day (5th pct)", note: "worse than 95% of observed sessions",
      pct: p5 * 100, value: current * p5, observed: true,
    });
  }
  for (const shock of [-0.05, -0.1]) {
    out.push({
      label: `Market ${(shock * 100).toFixed(0)}%`,
      note: "hypothetical uniform shock, not an observed move",
      pct: shock * 100, value: current * shock, observed: false,
    });
  }
  return out;
}

/** Herfindahl-Hirschman index over portfolio weights, 0–10000.
 *  A single position scores 10000; n equal positions score 10000/n. */
export function hhi(weightsPct: number[]): number | null {
  const total = weightsPct.reduce((a, b) => a + b, 0);
  if (total <= 0) return null;
  return weightsPct.reduce((a, w) => a + ((w / total) * 100) ** 2, 0);
}
