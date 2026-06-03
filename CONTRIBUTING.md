# Contributing to SchemaScribe

Thanks for your interest — contributions of all sizes are welcome! 🎉

## Ways to help

- 🐛 **Report bugs** — open an issue with steps to reproduce.
- 💡 **Suggest features** — partition patterns, new output formats, other databases.
- 📝 **Improve docs** — typos and clarifications count!
- 🔧 **Send a PR** — see below.

## Development setup

```bash
git clone <your-fork-url>
cd database-re-engineering
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running the tests

The unit tests need **no database** — they exercise the pattern, relationship,
and inference logic on in-memory fixtures.

```bash
pytest -q
```

## Project layout

```
schemascribe/
├── cli.py            # argument parsing + logging
├── pipeline.py       # the end-to-end orchestrator
├── config.py         # defaults + YAML loading
├── db.py             # read-only connection management
├── extractor.py      # SQL metadata extraction (PostgreSQL)
├── models.py         # plain dataclasses
├── patterns.py       # table categorisation + partition grouping
├── relationships.py  # foreign-key + naming-based join inference
├── inference.py      # plain-English column/table descriptions
├── generator.py      # Jinja2 rendering to Markdown + JSON
└── templates/        # the Markdown templates
```

## Guidelines

- Keep functions small and well-named; match the existing docstring style.
- Anything database-specific belongs in `extractor.py` so other engines can be
  added cleanly later.
- Add or update a test when you change behaviour.
- No hard-coded, environment-specific values — make it configurable instead.

## Code of conduct

Be kind and constructive. We're all here to make a useful tool.

## Maintainer

SchemaScribe is created and maintained by **Vinod Bokare**.
