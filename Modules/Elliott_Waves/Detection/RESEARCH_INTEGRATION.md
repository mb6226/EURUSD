# Elliott Engine Research Integration Audit

Scope: EURUSD only. The project market-data pipeline remains the source of OHLCV data;
all external analyzers are treated as research references, not ground truth.

## Audit findings

| Project | Finding | Decision |
|---|---|---|
| drstevendev/ElliottWaveAnalyzer | Useful monowave / skipped-pivot search ideas and impulse/ABC rule structure. The public repository has no declared license. | Do not copy or vendor its source. Its ideas informed a clean-room research design only. |
| Wkemery/ElliotWaveAnalysis | GPL-3.0, last source push in 2018, hard-coded local paths, legacy Plotly imports, and a separate ATR swing generator plus configurable Fibonacci checks. | Do not embed its source in this repository: this repository has no project-wide open-source license, and a tightly integrated GPL derivative would create licensing obligations. Implement independent ATR pivots and transparent raw-ratio diagnostics instead. |
| nkieu-config/elliott-wave-engine | Its LICENSE explicitly says all rights reserved and prohibits copying, modifying, merging, and derivative works without permission. | Excluded from code integration. Do not copy its implementation. |
| WaveCharts | Free charting/annotation product, but it does not automatically analyze a market; its published asset coverage does not establish EURUSD forex support. | Optional manual annotation reference only; not an engine dependency. |

## Implemented in this branch

research_engines.py adds two independent research components:

1. Wilder ATR calculation and an ATR-reversal swing detector. Every confirmed pivot records both the extreme candle and the later confirmation candle, so downstream evaluation can enforce causal availability.
2. Raw impulse / ABC measurements: leg lengths, observed retracement and extension ratios, durations, and transparent hard-rule checks. It deliberately does not force fixed Fibonacci levels or assign calibrated probabilities.

These are complementary to the existing directional-change detector and candidate engine; they do not replace them.

## EURUSD data policy

- Consume only the project's canonical EURUSD OHLCV candles.
- Do not silently mix non-EURUSD examples or other instruments.
- Preserve UTC timestamps and tick-volume provenance.
- Keep confirmed and provisional pivots separate.
- Do not promote heuristic counts, OCR detections, or third-party chart interpretations to expert labels automatically.
- Store source references, publication timestamps, and revisions for any externally sourced analysis.
- Check each source's terms and permissions before bulk collection or model-training use.

## Validation still required

- Run the full test suite on the Windows workstation.
- Compare ATR pivots with the existing directional-change pivots over the full EURUSD history and several timeframes.
- Audit causal availability and sensitivity to ATR period / multiplier using chronological walk-forward folds.
- Keep the new engine out of the champion forecaster until independent expert labels demonstrate value over the existing baseline.
