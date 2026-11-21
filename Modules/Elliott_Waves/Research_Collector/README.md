# Elliott Wave Research Collector (Local)

Run manually from the project root once per day:

    py -3 scripts\\run_elliott_research_collector.py

The collector runs only when started by the user. It does not install a scheduled task, run a background service, expose a web server, or upload project data.

Outputs:
- Modules/Elliott_Waves/Dataset/external_references/collected_analyses.jsonl
- Modules/Elliott_Waves/Dataset/external_references/latest_report.md

Initial public listing pages: Elliott Wave Insight Forex, EW Strategy Free Charts, and FXStreet EURUSD analysis. Edit sources.json to enable or disable sources. Sites can change their pages or access rules; errors are reported and are not bypassed.

The collector stores source metadata and short meta-description excerpts, not complete articles or chart images. It does not log in, bypass paywalls, CAPTCHAs, rate limits or other access controls. Respect source terms, robots rules and applicable rights. Private/local use does not automatically create a copyright or scraping exception.

Every item starts as unreviewed and training_eligible=false. The collector does not create ground-truth labels. Human review and rights checks are required before any training use.

## Chart image OCR

The collector checks article Open Graph/Twitter image metadata and same-page image tags. It downloads at most two candidate images per article only from configured allowed image domains, with an 8 MB size cap, and saves them under `Dataset/external_references/chart_images/`. Pillow and RapidOCR detect text and likely Elliott labels / EURUSD price strings.

OCR output is appended to `Dataset/external_references/chart_image_extractions.jsonl`. Each detected text item stores confidence, pixel bounding box, and normalized image position. OCR coordinates alone are not calibrated chart data; OCR confusion remains possible.

## Chart-to-Wave Mapper

The daily command runs the mapper after image extraction and local chart review. It can also be run separately:

    py -3 scripts\\run_chart_to_wave_mapper.py

It reads the latest OCR record per image, article publication metadata, and the shared EURUSD BID OHLC datasets. It supports chart timeframes M5, M15, H1 and H4. For each detected wave label it attempts to estimate price from the right-axis OCR fit, estimate time from readable date-axis ticks, locate the nearest candle, and select the closest OHLC field. Consecutive points are proposed as wave segments only when the chart price is within 25 pips of the matched candle's OHLC range.

Outputs:
- `Dataset/external_references/chart_wave_mappings.jsonl` — structured point and segment records;
- `Dataset/external_references/chart_wave_mapping_report.md` — per-image status, warnings and counts.

Calibration remains approximate. Chart layouts, cropped labels, nonlinear/log axes, irregular date spacing and OCR errors can make a mapping wrong. If date ticks or a valid price-axis fit are missing, coordinates stay unresolved. If estimated chart price differs from the nearest candle OHLC by more than 25 pips, that point is marked `price_mismatch` and excluded from segment construction. A nearest candle match is not proof that the expert pivot occurred at that exact candle.

Every record remains `needs_visual_review` and `training_eligible=false`. Only a later human-confirmation workflow may promote reviewed labels for training.

## Local review

A static local review page is generated at `Dataset/external_references/chart_review.html`. Open it in a browser to inspect saved chart images and OCR suggestions; it does not upload or serve images.

The collector does not bypass access controls or download from unconfigured third-party image hosts. Local/private processing does not automatically override copyright or site terms.
