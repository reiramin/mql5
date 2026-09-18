# Certification — ema_crossover on EURUSD H1

- EA: `Experts\Mql5Bot\Mql5Bot.ex5`
- manifest binding: `S5-CERT-20260918`
- spread floor: 0.0 pips | trade minimum: 100 | slippage tiers: [0.5, 1.0, 2.0, 3.0] pips
- runner note: headless MT5 tester via mt5tester.run_backtest

## VERDICT: NOT VERIFIED

- status model: EMPIRICAL_VALIDATION_PENDING | MT5: NOT VERIFIED
- status reason: required MT5 legs did not run (terminal host required)

Reasons:
- bear_2022:1 minute OHLC did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- bear_2022:Every tick did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- bear_2022:Every tick based on real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- bear_2022:Real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- crash_2020:1 minute OHLC did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- crash_2020:Every tick did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- crash_2020:Every tick based on real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- crash_2020:Real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- trend_2021:1 minute OHLC did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- trend_2021:Every tick did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- trend_2021:Every tick based on real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- trend_2021:Real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- range_2023:1 minute OHLC did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- range_2023:Every tick did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- range_2023:Every tick based on real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')
- range_2023:Real ticks did not run (TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType')

## Legs
| regime | grade | ran | ok | trades | net profit | max dd % |
| --- | --- | --- | --- | ---: | ---: | ---: |
| bear_2022 | mt5-1 minute OHLC | False | False | 0 | - | - |
| bear_2022 | mt5-Every tick | False | False | 0 | - | - |
| bear_2022 | mt5-Every tick based on real ticks | False | False | 0 | - | - |
| bear_2022 | mt5-Real ticks | False | False | 0 | - | - |
| crash_2020 | mt5-1 minute OHLC | False | False | 0 | - | - |
| crash_2020 | mt5-Every tick | False | False | 0 | - | - |
| crash_2020 | mt5-Every tick based on real ticks | False | False | 0 | - | - |
| crash_2020 | mt5-Real ticks | False | False | 0 | - | - |
| trend_2021 | mt5-1 minute OHLC | False | False | 0 | - | - |
| trend_2021 | mt5-Every tick | False | False | 0 | - | - |
| trend_2021 | mt5-Every tick based on real ticks | False | False | 0 | - | - |
| trend_2021 | mt5-Real ticks | False | False | 0 | - | - |
| range_2023 | mt5-1 minute OHLC | False | False | 0 | - | - |
| range_2023 | mt5-Every tick | False | False | 0 | - | - |
| range_2023 | mt5-Every tick based on real ticks | False | False | 0 | - | - |
| range_2023 | mt5-Real ticks | False | False | 0 | - | - |

Backtests are research evidence, not a promise of live profit.