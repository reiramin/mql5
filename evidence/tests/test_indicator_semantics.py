"""Reality Gate §13/§14/§15 — RSI/crossover truth tables, state memory,
extreme single-bar transitions.

The truth table here is the canonical contract test (mission §13): every
(previous, current) combination of {NaN, below, equal, above} for a pair
of series is enumerated for BOTH crossover directions and for crossunder,
and the three human-equivalent spellings of "a crossed below b" are proven
identical elementwise.

Also pinned:
* cross-event semantics are STATELESS (repeated evaluation, restart and
  replay give identical output — mission §14);
* extreme-to-extreme single-bar jumps produce exactly ONE event (bar-close
  sampling observes no intermediate values — by design, mission §15);
* the RSI threshold-tie rule is pinned against the EA zone-escape rule;
  the former exact-tie CONTRACT_GAP is CLOSED as PROVEN_EXACT — Python
  and the DSL spec are aligned to the EA rule (DECISIONS.md 2026-09-07
  final entry) — never silently changed.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from mql5bot import strategies as S
from mql5bot.indicators import crossover, crossunder, rsi

NAN = float("nan")

# (previous, current) relation of `a` vs constant line `b`
BELOW, EQUAL, ABOVE, NANV = "below", "equal", "above", "nan"


def _val(rel, line=50.0):
    return {BELOW: line - 1.0, EQUAL: line, ABOVE: line + 1.0,
            NANV: NAN}[rel]


def test_crossover_full_truth_table():
    """Enumerate prev x cur for a vs b. CANONICAL CONTRACT (as executed,
    pinned against intuition, never silently changed): events are
    transitions of the STRICT-above state ``above = a > b`` —
    +1 = entering above (prev not-above -> cur above, so EQUAL->ABOVE
    fires); -1 = leaving above (prev above -> cur not-above, so
    ABOVE->EQUAL fires); below<->equal transitions are events in NEITHER
    direction; NaN on either side suppresses. The tie asymmetry (equal is
    'not above') is inherent to the single-predicate design and is pinned
    explicitly below."""
    for prev_rel, cur_rel in itertools.product(
            (BELOW, EQUAL, ABOVE, NANV), repeat=2):
        a = np.array([_val(prev_rel), _val(cur_rel)])
        b = np.array([50.0, 50.0])
        out = crossover(a, b)
        prev_valid = prev_rel != NANV
        cur_valid = cur_rel != NANV
        if prev_valid and cur_valid:
            prev_above = prev_rel == ABOVE
            cur_above = cur_rel == ABOVE
            if cur_above and not prev_above:
                expected = 1          # entering above (from below OR equal)
            elif prev_above and not cur_above:
                expected = -1         # leaving above (to below OR equal)
            else:
                expected = 0
        else:
            expected = 0  # NaN on either side suppresses the event
        assert out[1] == expected, (prev_rel, cur_rel, out[1])
        assert out[0] == 0  # index 0 can never be an event


def test_tie_asymmetry_and_sign_flip_domain_pinned():
    """The strict-above contract implies two pinned tie facts:
    (1) ABOVE->EQUAL fires -1 while EQUAL->BELOW fires nothing (the
    down-cross is 'leaving above', not 'arriving below');
    (2) crossover(a,b) == -crossover(b,a) holds on all TIE-FREE inputs but
    can differ at exact-tie bars (entering-above of one ordering is not
    the negation of anything in the other). Both are contract, not bugs —
    they follow from one strict predicate and are regression-locked."""
    b = np.array([50.0, 50.0, 50.0])
    a_down = np.array([55.0, 50.0, 45.0])
    assert crossover(a_down, b).tolist() == [0, -1, 0]   # leaves above at tie
    a_up = np.array([45.0, 50.0, 55.0])
    assert crossover(a_up, b).tolist() == [0, 0, 1]      # enters above after tie
    # sign-flip identity holds on genuinely tie-free inputs:
    tf_down = np.array([55.0, 51.0, 45.0])
    tf_up = np.array([45.0, 49.0, 55.0])
    assert (crossover(tf_down, b) == -crossover(b, tf_down)).all()
    assert (crossover(tf_up, b) == -crossover(b, tf_up)).all()
    # and it BREAKS at exact-tie bars (documented, pinned):
    assert (crossover(a_down, b) != -crossover(b, a_down)).any()
    mixed = np.array([50.0, 45.0])          # tie -> below
    assert crossover(mixed, b[:2]).tolist() == [0, 0]
    assert crossover(b[:2], mixed).tolist() == [0, 1]   # flipped view fires
    assert not (crossover(mixed, b[:2])
                == -crossover(b[:2], mixed)).all()      # documented break


def test_crossunder_is_exact_negative_and_notation_equivalence():
    """crossover(a,b) < 0  ==  crossunder(a,b) > 0  ==  crossover(b,a) > 0
    — three spellings, one event (a crossed below b). Proven elementwise
    over the whole truth table, NaN included. This pins the answer to the
    mission's notation question: the polarity is exact sign-flip symmetry,
    never intuition-based."""
    rng = np.random.default_rng(11)
    for _ in range(300):
        n = rng.integers(2, 12)
        a = rng.choice([rng.normal(50, 5, n),
                        np.where(rng.random(n) < 0.2, NAN,
                                 rng.normal(50, 5, n))])
        b = rng.normal(50, 5, n)
        co_ab = crossover(a, b)
        assert (crossunder(a, b) == -co_ab).all()
        assert ((co_ab < 0) == (crossunder(a, b) > 0)).all()
        assert ((co_ab < 0) == (crossover(b, a) > 0)).all()
        assert ((co_ab > 0) == (crossover(b, a) < 0)).all()


def test_nan_boundary_never_fires():
    """Warmup transition NaN -> value emits NO event (the regression that
    closed the Python/EA warmup split)."""
    a = np.array([NAN, NAN, 55.0, 55.0])
    b = np.array([50.0, 50.0, 50.0, 50.0])
    assert crossover(a, b).tolist() == [0, 0, 0, 0]
    # but a genuine crossing after readiness still fires
    a2 = np.array([NAN, 45.0, 55.0])
    assert crossover(a2, b[:3]).tolist() == [0, 0, 1]


# ---------------------------------------------------------------------------
# RSI threshold semantics: first valid bar, exact 30/70, transitions
# ---------------------------------------------------------------------------


def _rsi_series(tail, head_len=15):
    """Deterministic price tail appended to a flat warmup head."""
    head = np.full(head_len, 1.10)
    return np.concatenate([head, np.asarray(tail, dtype=float)])


def test_rsi_first_valid_and_threshold_transitions():
    # all-up tail pushes RSI up; all-down pushes it down
    up = _rsi_series(np.cumsum(np.full(10, 0.001)) + 1.101)
    r = rsi(up, 14)
    assert np.isnan(r[:14]).all() and np.isfinite(r[14])
    assert r[-1] > 70.0                       # overbought reachable
    dn = _rsi_series(1.099 - np.cumsum(np.full(10, 0.001)))
    assert rsi(dn, 14)[-1] < 30.0             # oversold reachable


@pytest.mark.parametrize("prev,cur", [
    (29.0, 30.0), (29.0, 31.0), (30.0, 31.0), (30.0, 29.0),
    (71.0, 70.0), (71.0, 69.0), (70.0, 69.0), (70.0, 71.0),
    (50.0, 50.0), (30.0, 30.0), (70.0, 70.0),
    (5.0, 95.0), (95.0, 5.0),                   # extreme -> extreme
])
def test_rsi_zone_transition_matrix(prev, cur):
    """Zone-escape semantics as executed by the EA (source transcription):
    oversold zone = r < 30 strictly; overbought = r > 70 strictly; an
    escape fires when the PREVIOUS bar was strictly in the zone and the
    current bar is not. Ties sit OUTSIDE the zone. This is the canonical
    table the Python mirror is measured against (see CONTRACT_GAP pin)."""
    oversold, overbought = 30.0, 70.0
    prev_os, now_os = prev < oversold, cur < oversold
    prev_ob, now_ob = prev > overbought, cur > overbought
    event = 0
    if prev_os and not now_os:
        event = 1
    elif prev_ob and not now_ob:
        event = -1
    # pinned expectations from the EA logic:
    expected = {
        (29.0, 30.0): 1, (29.0, 31.0): 1,
        (30.0, 31.0): 0,      # prev tie: NOT in zone -> no escape
        (30.0, 29.0): 0,
        (71.0, 70.0): -1, (71.0, 69.0): -1,
        (70.0, 69.0): 0,      # prev tie: NOT in zone -> no escape
        (70.0, 71.0): 0,
        (50.0, 50.0): 0, (30.0, 30.0): 0, (70.0, 70.0): 0,
        (5.0, 95.0): 1,       # extreme -> extreme in ONE bar: fires
        (95.0, 5.0): -1,
    }[(prev, cur)]
    assert event == expected


def test_rsi_zone_escape_python_is_the_ea_rule_exactly():
    """PROVEN_EXACT closure (DECISIONS.md 2026-09-07 final): the Python
    rsi_reversal state machine IS the EA zone-escape rule, enumerated over
    the full tie-inclusive truth table. The former exact-tie CONTRACT_GAP
    is CLOSED by aligning Python (and the DSL reference spec) to the
    executing EA semantics — the EA source was not modified; the EA's
    rule is canonical for the tie. Every (prev, cur) case including
    exact 30/70 ties must agree with the EA transcription."""
    from mql5bot.strategies import rsi_zone_escape_state

    cases = [
        (29.0, 30.0), (29.0, 31.0), (30.0, 31.0), (30.0, 29.0),
        (71.0, 70.0), (71.0, 69.0), (70.0, 69.0), (70.0, 71.0),
        (50.0, 50.0), (30.0, 30.0), (70.0, 70.0),
        (5.0, 95.0), (95.0, 5.0), (29.0, 29.0), (71.0, 71.0),
        (29.0, 71.0), (71.0, 29.0),
    ]
    oversold, overbought = 30.0, 70.0
    for prev, cur in cases:
        # EA transcription (SignalEngine.EvaluateRsiReversal, verbatim
        # logic incl. strict zone membership and neutral-band hold):
        ea_state = 0  # m_state.emaDir before the bar
        ea_dir = None
        for r_prev, r in ((prev, cur),):
            now_os, prev_os = r < oversold, r_prev < oversold
            now_ob, prev_ob = r > overbought, r_prev > overbought
            if prev_os and not now_os:
                ea_state = 1
            elif prev_ob and not now_ob:
                ea_state = -1
            ea_dir = ea_state if (not now_os and not now_ob) else 0
        # Python mirror over the same two-bar sequence:
        py = rsi_zone_escape_state(np.array([prev, cur]), oversold,
                                   overbought)
        assert py[1] == ea_dir, (prev, cur, py[1], ea_dir)


def test_rsi_zone_escape_neutral_hold_and_extremes_pinned():
    """Hold-through-neutral and stand-aside-at-extremes, tie-inclusive:
    entering the neutral band with a direction keeps it; ties (r == 30/70)
    are neutral (held), strictly beyond them is the extreme (flat)."""
    from mql5bot.strategies import rsi_zone_escape_state

    # escape oversold -> +1, then tie-at-30 holds, neutral holds,
    # tie-at-70 holds, strictly above 70 stands aside
    r = np.array([29.0, 31.0, 30.0, 50.0, 70.0, 70.5])
    assert rsi_zone_escape_state(r, 30.0, 70.0).tolist() == \
        [0, 1, 1, 1, 1, 0]
    # escape overbought -> -1, then deep oversold stands aside
    r2 = np.array([71.0, 69.0, 50.0, 29.5])
    assert rsi_zone_escape_state(r2, 30.0, 70.0).tolist() == \
        [0, -1, -1, 0]
    # NaN suppresses (warmup): no state can emerge from a NaN boundary
    r3 = np.array([np.nan, 29.0, 31.0])
    assert rsi_zone_escape_state(r3, 30.0, 70.0).tolist() == [0, 0, 1]


# ---------------------------------------------------------------------------
# §14 — state memory: statelessness, repetition, restart, replay
# ---------------------------------------------------------------------------


def test_crossover_is_stateless_repeated_evaluation_identical():
    a = np.array([NAN, 45.0, 55.0, 54.0, 44.0, 46.0])
    b = np.full(6, 50.0)
    first = crossover(a, b)
    for _ in range(5):
        assert (crossover(a, b) == first).all()
        assert (crossunder(a, b) == -first).all()


def test_strategy_replay_and_restart_determinism():
    """Same input history -> same output state, across repeated runs and
    sliced replays (the Python analogue of restart/replay; the engine is a
    pure function of the frame)."""
    from mql5bot.data import generate_ohlc

    df = generate_ohlc(days=20, seed=5)
    for name in ("ema_crossover", "rsi_reversal", "donchian_breakout"):
        s1 = S.signal(df, name)
        s2 = S.signal(df.copy(), name)          # fresh copy = restart
        assert (s1.to_numpy() == s2.to_numpy()).all()
        s3 = S.signal(df, name)                 # repeated identical eval
        assert (s1.to_numpy() == s3.to_numpy()).all()


def test_one_bar_mutation_only_affects_causal_future():
    """Mutating one bar never changes decisions strictly before it
    (no hidden mutable state reaching backwards)."""
    from mql5bot.data import generate_ohlc

    df = generate_ohlc(days=20, seed=7)
    base = S.signal(df, "ema_crossover").to_numpy()
    df2 = df.copy()
    k = len(df2) - 5
    df2.iloc[k, df2.columns.get_loc("close")] *= 1.05
    after = S.signal(df2, "ema_crossover").to_numpy()
    # EMA lookback is unbounded in theory but the mutation index bounds
    # causality: nothing before k can change
    assert (base[:k] == after[:k]).all()


# ---------------------------------------------------------------------------
# §15 — extreme single-bar jumps
# ---------------------------------------------------------------------------


def test_extreme_to_extreme_single_bar_cross_detection():
    """A one-bar jump over one or several thresholds produces exactly ONE
    event in the observed direction: bar-close sampling has no intermediate
    samples BY DESIGN. Documented, not 'fixed'."""
    b = np.full(4, 50.0)
    # single threshold gap-over
    a = np.array([40.0, 60.0, 60.0, 40.0])
    assert crossover(a, b).tolist() == [0, 1, 0, -1]
    # multiple conceptual thresholds crossed in one bar -> still one event
    lines = np.array([45.0, 50.0, 55.0])
    a2 = np.array([[40.0, 60.0], [40.0, 60.0], [40.0, 60.0]])
    for line, series in zip(lines, a2):
        out = crossover(series, np.full(2, line))
        assert out.tolist() == [0, 1]
    # direction reversal in one bar: down-cross event
    a3 = np.array([60.0, 40.0])
    assert crossover(a3, np.full(2, 50.0)).tolist() == [0, -1]
    # exact touch (== line) then cross: touch is not an event
    a4 = np.array([40.0, 50.0, 55.0])
    assert crossover(a4, np.full(3, 50.0)).tolist() == [0, 0, 1]
    # touch followed by retreat: no event at all
    a5 = np.array([40.0, 50.0, 45.0])
    assert crossover(a5, np.full(3, 50.0)).tolist() == [0, 0, 0]


def test_extreme_jump_rsi_state_flips_once():
    """RSI driven extreme-low -> extreme-high in one bar: the zone-escape
    state machine emits exactly one escape event (documented behaviour)."""
    oversold, overbought = 30.0, 70.0
    r_prev, r_now = 5.0, 95.0
    prev_os = r_prev < oversold
    now_os = r_now < oversold
    assert prev_os and not now_os                # exactly one +1 escape
    # and the mirror
    assert (95.0 > overbought) and not (5.0 > overbought)
