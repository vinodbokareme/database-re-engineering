<div align="center">

# 📜 SchemaScribe

### Point it at a PostgreSQL database. Get beautiful documentation back.

SchemaScribe reads your database (read-only, always) and writes clean Markdown +
JSON docs that explain **what every table is, what every column means, and how
everything joins together** — perfect for onboarding, data catalogs, and feeding
to AI assistants.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

---

> ### 🧠🗄️ More than docs — it's the **synergy layer between AI agents and your database.**
>
> An LLM agent speaks language. Your database speaks structure. Neither understands
> the other. SchemaScribe is the translator in the middle — the grounded, versioned
> **semantic layer** that lets agents and databases work in synergy, so you can build
> reliable data products on top.
>
> **Read the full architectural story → [ARCHITECTURE.md](ARCHITECTURE.md)**

---

## ✨ Why SchemaScribe?

You inherited a database with 400 tables and zero documentation. Sound familiar?

SchemaScribe turns this 👇

```
orders, order_items, customers_2021, customers_2022, customers_2023,
flyway_schema_history, qrtz_triggers, product_audit, ...
```

…into a tidy folder of readable docs 👇

```
docs/
├── summary/
│   ├── database_overview.md     ← start here
│   └── schema_index.json        ← machine-readable index
└── schemas/
    └── public/
        ├── schema_overview.md
        └── tables/
            ├── orders.md
            ├── customers.md      ← 2021/22/23 collapsed into one
            └── ...
```

— complete with plain-English summaries, column meanings, inferred join paths,
sample SQL, and "watch out for this" notes.

---

## 🚀 Quickstart (30 seconds)

```bash
# 1. Install
pip install -r requirements.txt

# 2. Tell it how to connect (read-only credentials recommended)
export PGHOST=localhost PGPORT=5432 PGDATABASE=mydb PGUSER=readonly PGPASSWORD=secret

# 3. Generate the docs
python -m schemascribe --output docs
```

That's it. Open `docs/summary/database_overview.md` and start reading.

> 💡 Prefer a `.env` file? Copy `.env.example` to `.env`, fill it in, and
> SchemaScribe loads it automatically.

---

## 📸 What the output looks like

Every table gets its own page:

```markdown
# public.orders

## 📋 What is this table? (Plain English)
> Core business table in the `public` schema.
Stores business transactions data used in day-to-day operations.

## Columns
| # | Column       | Type          | Required? | Likely meaning                    |
|---|--------------|---------------|-----------|-----------------------------------|
| 1 | id           | bigint        | ✓         | Unique identifier for this record |
| 2 | customer_id  | bigint        | ✓         | Reference to the Customer record  |
| 3 | total_amount | numeric(12,2) | ✓         | Total monetary amount             |
| 4 | created_at   | timestamptz   | ✓         | Timestamp when this record …      |

## Likely relationships (inferred)
- `customer_id` → **public.customers** (id) — confidence: **high**

## Sample queries
SELECT id, customer_id, total_amount FROM public.orders LIMIT 100;
```

---

## 🧠 What makes it smart

| Feature | What it does |
|---------|--------------|
| 🧩 **Plain-English summaries** | Guesses what each table and column is *for* from naming conventions and a built-in glossary. |
| 🔗 **Relationship inference** | Uses real foreign keys **and** naming patterns (`customer_id` → `customers`) to suggest join paths. |
| 🗂️ **Partition collapsing** | `events_2021…events_2025` become a single, clean entry instead of five near-identical pages. |
| 🏷️ **Smart categorisation** | Separates real business tables from migration trackers, schedulers, and audit noise. |
| 🤖 **AI-ready** | Each table includes a dense one-line summary written for LLMs, plus JSON for tooling. |
| 🛟 **Resilient** | Per-schema error isolation, automatic retries, and `--resume` to pick up after a failure. |
| 🔒 **Read-only & safe** | Opens the connection read-only with a statement timeout. It never writes to your DB. |
| ⚙️ **Zero-config or fully tunable** | Works out of the box; override any rule with a tiny YAML file. |

---

## ⚙️ Configuration (optional)

SchemaScribe works with no config at all. To teach it your own conventions —
custom partition naming, reference tables for join inference, domain-specific
column meanings — pass a YAML file:

```bash
python -m schemascribe --config config.yaml --output docs
```

See [`examples/config.example.yaml`](examples/config.example.yaml) for every
available option, all documented inline.

---

## 🛠️ CLI reference

```text
schemascribe [options]

  -o, --output DIR       Where to write docs (default: docs)
  -c, --config FILE      Path to a config.yaml (optional)
      --schema NAME      Only document a single schema (great for a quick test)
      --resume           Skip schemas already completed in a previous run
      --test-connection  Check credentials and exit
  -v, --verbose          Verbose console logging
      --version          Show version
```

---

## 🐍 Use it from Python

```python
from schemascribe import Config, run

config = Config.default()              # reads PG* env vars
run(config, output_dir="docs")
```

---

## 🤔 FAQ

**Does it modify my database?**
No. The connection is opened read-only with a query timeout. It only runs
`SELECT`s against the system catalogs.

**Which databases are supported?**
PostgreSQL today. The extraction layer is isolated, so other engines are a
natural next step — [contributions welcome](CONTRIBUTING.md)!

**My tables don't follow these naming conventions.**
That's exactly what the config file is for. Define your own partition patterns,
reference tables, and glossary terms.

**The inferred meanings aren't perfect.**
They're heuristics and are clearly labelled as such. Any real `COMMENT ON TABLE`
in your database always takes precedence over a guess.

---

## 🤝 Contributing

Issues and PRs are very welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
If SchemaScribe saved you time, please ⭐ the repo so others can find it!

## 📄 License

[MIT](LICENSE) — free for personal and commercial use.
