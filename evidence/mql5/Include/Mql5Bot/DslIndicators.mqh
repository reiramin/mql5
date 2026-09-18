//+------------------------------------------------------------------+
//|  DslIndicators.mqh — canonical Aegis indicator ports              |
//|                                                                  |
//|  STATUS: compile-observed on Windows; MQL5<->Python PARITY is     |
//|  OWNER-PENDING until tools/run_dsl_parity.ps1 reports 14/14 EXACT.|
//|                                                                  |
//|  Operation-for-operation mirrors of python/mql5bot/indicators.py. |
//|  Scope is deliberately MINIMAL (mission fail-closed rule): only   |
//|  the kinds the committed parity fixtures exercise (EMA/RSI/ATR)   |
//|  plus the canonical channel kinds (DONCHIAN/HIGHEST/LOWEST) are   |
//|  ported. SMA/BBANDS/MACD and every other kind are NOT here — the  |
//|  loader refuses them; nothing is approximated.                    |
//|                                                                  |
//|  The parity contract compares positions EXACTLY, so these         |
//|  deliberately do NOT use the MT5 built-ins (iMA's EMA seeds from  |
//|  the first close; the canonical EMA seeds with SMA(period) and is |
//|  NaN before it — a built-in would approximate, which is           |
//|  forbidden). All arrays are CHRONOLOGICAL ([0] = oldest closed    |
//|  bar) and NaN during warmup, exactly like the Python reference.   |
//|                                                                  |
//|  Floating-point fidelity: seeds/means mirror numpy's pairwise     |
//|  8-accumulator reduction (DslNumpySum) and the recursive loops    |
//|  mirror the Python order exactly, so results are bit-reproducible |
//|  on IEEE-754 doubles. Any residual platform deviation surfaces in |
//|  the owner parity run as a position mismatch and is a FINDING,    |
//|  never silently absorbed.                                         |
//+------------------------------------------------------------------+
#ifndef DSL_INDICATORS_MQH
#define DSL_INDICATORS_MQH

double DslIndNaN() { double z = 0.0; return z / z; }
bool   DslIndIsNaN(const double v) { return v != v; }

void DslFillNaN(double &out[], const int n)
  {
   ArrayResize(out, n);
   double nan = DslIndNaN();
   for(int i = 0; i < n; i++) out[i] = nan;
  }

//+------------------------------------------------------------------+
//| numpy add.reduce over a[offset..offset+n) — EXACT mirror of       |
//| numpy's pairwise_sum (block size 128, 8-way unrolled partials):   |
//| n < 8 sequential; n <= 128 eight accumulators over 8-blocks then   |
//| ((r0+r1)+(r2+r3))+((r4+r5)+(r6+r7)) plus a sequential remainder;  |
//| larger n split recursively at n/2 rounded down to a multiple of 8.|
//+------------------------------------------------------------------+
double DslNumpySum(const double &a[], const int offset, const int n)
  {
   if(n < 8)
     {
      double res = 0.0;
      for(int i = 0; i < n; i++) res += a[offset + i];
      return res;
     }
   if(n <= 128)
     {
      double r0 = a[offset],     r1 = a[offset + 1];
      double r2 = a[offset + 2], r3 = a[offset + 3];
      double r4 = a[offset + 4], r5 = a[offset + 5];
      double r6 = a[offset + 6], r7 = a[offset + 7];
      int i;
      for(i = 8; i < n - (n % 8); i += 8)
        {
         r0 += a[offset + i];     r1 += a[offset + i + 1];
         r2 += a[offset + i + 2]; r3 += a[offset + i + 3];
         r4 += a[offset + i + 4]; r5 += a[offset + i + 5];
         r6 += a[offset + i + 6]; r7 += a[offset + i + 7];
        }
      double res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7));
      for(; i < n; i++) res += a[offset + i];
      return res;
     }
   int n2 = n / 2;
   n2 -= n2 % 8;
   return DslNumpySum(a, offset, n2) + DslNumpySum(a, offset + n2, n - n2);
  }

//+------------------------------------------------------------------+
//| EMA — mirrors indicators.ema: alpha = 2/(period+1); seeded with   |
//| the numpy mean of the first `period` values; NaN before that;    |
//| ALL-NaN when fewer than `period` samples exist.                   |
//+------------------------------------------------------------------+
void DslEma(const double &v[], const int period, double &out[])
  {
   int n = ArraySize(v);
   DslFillNaN(out, n);
   int p = MathMax(period, 1);
   if(n < p) return;
   double alpha = 2.0 / (p + 1.0);
   out[p - 1] = DslNumpySum(v, 0, p) / p;
   for(int i = p; i < n; i++)
      out[i] = out[i - 1] + alpha * (v[i] - out[i - 1]);
  }

//+------------------------------------------------------------------+
//| RSI — mirrors indicators.rsi: Wilder smoothing, seeds at index    |
//| `period` from the numpy means of the first `period` gains/losses |
//| (zero entries included), rs clamps avg_loss at 1e-12; ALL-NaN    |
//| when n <= period.                                                 |
//+------------------------------------------------------------------+
void DslRsi(const double &v[], const int period, double &out[])
  {
   int n = ArraySize(v);
   DslFillNaN(out, n);
   int p = MathMax(period, 1);
   if(n <= p) return;
   double gain[], loss[];
   ArrayResize(gain, p);
   ArrayResize(loss, p);
   for(int j = 0; j < p; j++)
     {
      double d = v[j + 1] - v[j];
      gain[j] = (d > 0.0) ? d : 0.0;
      loss[j] = (d < 0.0) ? -d : 0.0;
     }
   double avgG = DslNumpySum(gain, 0, p) / p;
   double avgL = DslNumpySum(loss, 0, p) / p;
   double rs = avgG / MathMax(avgL, 1e-12);
   out[p] = 100.0 - 100.0 / (1.0 + rs);
   for(int i = p + 1; i < n; i++)
     {
      double d = v[i] - v[i - 1];
      double g = (d > 0.0) ? d : 0.0;
      double l = (d < 0.0) ? -d : 0.0;
      avgG = (avgG * (p - 1) + g) / p;
      avgL = (avgL * (p - 1) + l) / p;
      rs = avgG / MathMax(avgL, 1e-12);
      out[i] = 100.0 - 100.0 / (1.0 + rs);
     }
  }

//+------------------------------------------------------------------+
//| ATR — mirrors indicators.atr: Wilder smoothing on true range,     |
//| prev_close[0] = close[0], seed at index `period` = numpy mean of |
//| tr[1..p]; ALL-NaN when n <= period.                               |
//+------------------------------------------------------------------+
void DslAtr(const double &high[], const double &low[],
            const double &close[], const int period, double &out[])
  {
   int n = ArraySize(high);
   DslFillNaN(out, n);
   int p = MathMax(period, 1);
   if(n <= p) return;
   double tr[];
   ArrayResize(tr, p);
   for(int i = 1; i <= p; i++)
     {
      double pc = close[i - 1];
      tr[i - 1] = MathMax(high[i] - low[i],
                          MathMax(MathAbs(high[i] - pc),
                                  MathAbs(low[i] - pc)));
     }
   out[p] = DslNumpySum(tr, 0, p) / p;
   for(int i = p + 1; i < n; i++)
     {
      double pc = close[i - 1];
      double t = MathMax(high[i] - low[i],
                         MathMax(MathAbs(high[i] - pc),
                                 MathAbs(low[i] - pc)));
      out[i] = (out[i - 1] * (p - 1) + t) / p;
     }
  }

//+------------------------------------------------------------------+
//| DONCHIAN — mirrors indicators.donchian: channel of the PREVIOUS   |
//| `period` bars (excludes the current bar). upper[i] = max(high[    |
//| i-p .. i-1]) for i >= p; NaN before; ALL-NaN unless n > period.   |
//| A NaN inside the window propagates (numpy max semantics).         |
//+------------------------------------------------------------------+
void DslDonchian(const double &high[], const double &low[],
                 const int period, double &upper[], double &lower[])
  {
   int n = ArraySize(high);
   DslFillNaN(upper, n);
   DslFillNaN(lower, n);
   int p = MathMax(period, 1);
   if(n <= p) return;
   for(int i = p; i < n; i++)
     {
      double hi = high[i - p], lo = low[i - p];
      bool nan = DslIndIsNaN(hi) || DslIndIsNaN(lo);
      for(int k = i - p + 1; k <= i - 1 && !nan; k++)
        {
         if(DslIndIsNaN(high[k]) || DslIndIsNaN(low[k])) { nan = true; break; }
         if(high[k] > hi) hi = high[k];
         if(low[k] < lo) lo = low[k];
        }
      if(!nan) { upper[i] = hi; lower[i] = lo; }
     }
  }

//+------------------------------------------------------------------+
//| HIGHEST — mirrors indicators.highest: rolling max INCLUDING the   |
//| current bar, NaN-padded before index period-1; a NaN inside the   |
//| window propagates (numpy max semantics).                          |
//+------------------------------------------------------------------+
void DslHighest(const double &v[], const int period, double &out[])
  {
   int n = ArraySize(v);
   DslFillNaN(out, n);
   int p = MathMax(period, 1);
   if(n < p) return;
   for(int i = p - 1; i < n; i++)
     {
      double hi = v[i - p + 1];
      bool nan = DslIndIsNaN(hi);
      for(int k = i - p + 2; k <= i && !nan; k++)
        {
         if(DslIndIsNaN(v[k])) { nan = true; break; }
         if(v[k] > hi) hi = v[k];
        }
      if(!nan) out[i] = hi;
     }
  }

//+------------------------------------------------------------------+
//| LOWEST — mirrors indicators.lowest: rolling min INCLUDING the     |
//| current bar, NaN-padded; NaN inside the window propagates.        |
//+------------------------------------------------------------------+
void DslLowest(const double &v[], const int period, double &out[])
  {
   int n = ArraySize(v);
   DslFillNaN(out, n);
   int p = MathMax(period, 1);
   if(n < p) return;
   for(int i = p - 1; i < n; i++)
     {
      double lo = v[i - p + 1];
      bool nan = DslIndIsNaN(lo);
      for(int k = i - p + 2; k <= i && !nan; k++)
        {
         if(DslIndIsNaN(v[k])) { nan = true; break; }
         if(v[k] < lo) lo = v[k];
        }
      if(!nan) out[i] = lo;
     }
  }

#endif // DSL_INDICATORS_MQH
