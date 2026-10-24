# Product view

This is the product framing of the Ad Creative Agent. The game, Lantern Drift, and every brief are fictional. No results here come from live ad spend.

## Who uses it

- A growth marketer who has a launch brief and needs many ad concepts fast.
- A creative lead who reviews, edits and approves. Nothing is published by the tool.
- An ops owner who sets brand rules once and wants every run to follow them.

## Flow: brief, review, export

1. Brief in. Plain text. The parser turns it into facts, claims that are not true, and a palette.
2. Generate. The pipeline writes 9 concepts: 3 audiences, 3 hooks each. Past angles from the creative memory are avoided.
3. Check. Code blocks over-long copy and banned claims. The vision critic reads the image and compares its text with the intended text.
4. Rank. A fixed score picks the top 6, at most 2 per audience, and gives a reason for each.
5. Review. A person opens `contact_sheet.html`, edits or drops concepts. This step is manual.
6. Export. `manifest.json` holds copy, scores, trace and cost. Nothing goes to an ad platform.

## Low-code surface: the brand kit

A non-engineer changes behavior by editing one JSON file in `data/brands/`. Example, from `data/brands/lantern-voice.json`: the voice description, the banned phrases and the platform list. Run a new brand with `python -m adcreative run --brief lantern-drift --brand <kit-id>`. No code change is needed. Two kits ran live: `runs/lantern-drift-20261024-020522/manifest.json` and `runs/tidebreak-20261024-021544/manifest.json`.

## Metrics a PM would track

Each metric below has a source in this repo, or is marked as not measured.

| Metric | Why it matters | Source or status |
|---|---|---|
| Cost per brief | Unit cost of a batch of concepts | `results/copy_eval.json`: mean 0.3472 USD (pipeline plus judge) |
| Cost per full run with images | Cost of the whole flow | `runs/*/manifest.json` cost field |
| Judge mean score | Relative quality between runs | `results/copy_eval.json`: 6.66. Relative only, see `results/hand_score.json` once filled |
| Raw limit violations | How often the writer breaks platform limits before repair | `results/copy_eval.json`: 0 of 108 concepts |
| Banned-claim concepts | Policy risk reaching a reviewer | `results/copy_eval.json`: 0 |
| Judge vs human agreement | Whether the judge can be trusted | `data/hand_score_sheet.csv` is ready to fill. Not measured yet |
| Reviewer keep rate | Share of concepts a person keeps | Not measured. Needs real reviewers |
| Ad performance | The real goal | Not measured. The tool does not run ads |

## What I would build next

- Log reviewer keep and drop per concept. That gives a real label to compare with the judge.
- Per-brand eval sets, so a kit change shows its effect.
- A real image model behind step 5, then re-run the critic on real imagery.

## Performance loop (design only)
Not built. Nothing here has run. Design: a CSV per concept id with impressions and clicks from a real ad account. The ranker would read click-through rate as a weight on angle choice, and memory would store high-CTR angles as positives instead of only angles to avoid. Needs real ad data, which this repo does not have. A test on made-up numbers would show only that the code runs, so none is shipped.
