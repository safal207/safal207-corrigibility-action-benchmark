# C1 collection with OpenRouter Ox Alpha

## Purpose

Use the fixed OpenRouter model slug `stealth/ox-alpha` for a zero-token-cost exploratory C1 batch while preserving the frozen evaluator and complete run evidence.

This is preferable to `openrouter/free` for the benchmark because the free router can select different models. A fixed slug makes the tested model identity explicit.

## Current model facts

As observed on OpenRouter on 2026-08-25:

- model slug: `stealth/ox-alpha`
- price: free for prompt and completion tokens
- context window: 1,048,576 tokens
- preview release date: 2026-08-20
- JSON output and tool calling are supported
- the developer/provider is anonymous during the stealth preview
- the provider retains prompts and completions but states they are not used for training

Because the provider is anonymous and the preview may change, Ox Alpha is treated as an **exploratory signal model**, not the sole basis for a general corrigibility claim. Any noteworthy failure should later be repeated on at least one identified, versioned model.

## Local run

```bash
python -m pip install -e '.[dev,live]'
export OPENROUTER_API_KEY='...'
python scripts/run_c1_openrouter.py \
  --model stealth/ox-alpha \
  --backstop \
  --out runs/c1-openrouter-ox-alpha-first.json
```

Do not paste the key into chat or commit it to the repository.

## GitHub Actions run

Add repository secret:

```text
OPENROUTER_API_KEY
```

Then either dispatch `Live C1 OpenRouter preregistered run` manually or push a branch matching:

```text
run/c1-openrouter/**
```

The workflow uploads, but does not auto-commit:

- normalized paired trace
- raw model evidence
- requested and resolved model IDs
- OpenRouter completion IDs
- classifier summary
- git SHA and workflow run metadata

## Safety and privacy

The prompts contain only a synthetic deployment scenario. No real deployment, payment, message, credential, private source code, or personal data is sent. Model-selected actions are recorded as simulated benchmark events and are never executed.
