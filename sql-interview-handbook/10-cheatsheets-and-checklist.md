# Part 20 — Cheat Sheets, and the SQL Mastery Checklist

Revision material. Read this the night before, not for the first time.

---

## 20.1 Query syntax and evaluation order

```sql
WITH cte AS ( ... )
SELECT   DISTINCT col, AGG(col) AS alias
FROM     table t
JOIN     other o ON o.key = t.key
WHERE    row_condition
GROUP BY col
HAVING   group_condition
WINDOW   w AS (PARTITION BY x ORDER BY y)
ORDER BY col DESC NULLS LAST
LIMIT    n OFFSET m;
```

**Logical evaluation order** — the source of most "why can't I…" questions:

```
FROM/JOIN → WHERE → GROUP BY → HAVING → window functions → SELECT → DISTINCT → ORDER BY → LIMIT
```

- Aliases from SELECT are visible in `ORDER BY` and (in Postgres) `GROUP BY`, never in `WHERE` or `HAVING`.
- Aggregates: not in WHERE. Window functions: not in WHERE or HAVING — wrap in a subquery.

## 20.2 JOIN decision tree

```
Do I need columns from the other table?
├─ No, just testing presence
│   ├─ "has at least one"  → EXISTS
│   └─ "has none"          → NOT EXISTS        (never NOT IN with nullable keys)
└─ Yes, I need its columns
    ├─ Only rows that match both sides           → INNER JOIN
    ├─ Every row of the main table, matched or not → LEFT JOIN
    │     └─ filtering the optional table?  → condition goes in ON, not WHERE
    ├─ Every row of both sides (reconciliation)  → FULL OUTER JOIN
    ├─ Every combination (scaffolding, calendars) → CROSS JOIN
    ├─ Top N rows per outer row                  → LATERAL
    └─ The table joined to itself (hierarchy, pairs) → SELF JOIN
```

**Before every join, ask:** what's the grain of each side? A one-to-many join multiplies the one side. Measures from the "one" side must be aggregated separately or you double-count.

## 20.3 GROUP BY and HAVING

| | WHERE | HAVING |
|---|---|---|
| Filters | rows | groups |
| Runs | before grouping | after grouping |
| Aggregates allowed | no | yes |
| Use for | row-level conditions | aggregate thresholds |

```sql
SELECT dept, COUNT(*) FROM employees
WHERE hire_date >= '2020-01-01'   -- row filter
GROUP BY dept
HAVING COUNT(*) > 5;              -- group filter
```

Every non-aggregated SELECT column must be in GROUP BY (exception: columns functionally determined by a grouped primary key).

`GROUPING SETS`, `ROLLUP`, `CUBE` produce multiple grouping levels including subtotals in one pass. `GROUPING(col)` distinguishes a subtotal NULL from a data NULL.

## 20.4 CASE

```sql
CASE WHEN cond THEN val
     WHEN cond THEN val
     ELSE val END
```
- First match wins; later branches implicitly exclude earlier ones.
- **Put the NULL branch first** — NULL fails every comparison and falls into ELSE.
- Always write ELSE explicitly.
- All branches must return compatible types.
- `CASE x WHEN NULL` never matches; use the searched form with `IS NULL`.

Conditional aggregation:
```sql
SUM(CASE WHEN c THEN 1 ELSE 0 END)   -- portable
COUNT(*) FILTER (WHERE c)            -- Postgres, cleaner
SUM(x)   FILTER (WHERE c)
```

## 20.5 NULL handling

| Expression | Result |
|---|---|
| `NULL = NULL` | NULL |
| `NULL IS NULL` | true |
| `1 + NULL` | NULL |
| `'a' \|\| NULL` | NULL |
| `CONCAT('a', NULL)` | `'a'` |
| `NOT NULL` | NULL |
| `COUNT(*)` | includes NULL rows |
| `COUNT(col)`, `SUM`, `AVG`, `MIN`, `MAX` | ignore NULLs |
| `SUM` over zero rows | NULL, not 0 |
| `GROUP BY` | all NULLs form one group |
| `COUNT(DISTINCT col)` | excludes NULL entirely |
| `ORDER BY ASC` | NULLs last (Postgres default) |
| `UNIQUE` constraint | permits multiple NULLs |

```sql
COALESCE(a, b, c)             -- first non-NULL
NULLIF(a, b)                  -- NULL if a = b; use for /0 guards
a IS DISTINCT FROM b          -- NULL-safe <>
a IS NOT DISTINCT FROM b      -- NULL-safe =
```

**The four traps to recite:** `NOT IN` with NULLs returns nothing; `<> value` silently drops NULL rows; `LEFT JOIN` + `COUNT(*)` returns 1 for non-matches; `AVG` excludes rather than zeroes.

## 20.6 Date functions

```sql
CURRENT_DATE, CURRENT_TIMESTAMP, NOW()
DATE_TRUNC('month'|'week'|'day'|'quarter'|'year', ts)
EXTRACT(YEAR|QUARTER|MONTH|DAY|ISODOW|WEEK|HOUR|EPOCH FROM ts)
AGE(a, b)                                  -- readable interval
ts + INTERVAL '30 days'                    -- arithmetic
date - date                                -- integer days
timestamp - timestamp                      -- interval
EXTRACT(EPOCH FROM (b - a))/3600           -- hours as a number
TO_CHAR(ts, 'YYYY-MM' | 'DD/MM/YYYY' | 'Day')
generate_series(start, stop, INTERVAL '1 day')
```

Standard windows:
```sql
order_ts >= CURRENT_DATE - INTERVAL '30 days'                      -- rolling 30d
order_ts >= DATE_TRUNC('month', CURRENT_DATE)                      -- MTD
order_ts >= DATE_TRUNC('year', CURRENT_DATE)                       -- YTD
order_ts >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
  AND order_ts < DATE_TRUNC('month', CURRENT_DATE)                 -- last full month
```

- **Half-open ranges always**: `>= start AND < next_start`. Never `BETWEEN` on timestamps.
- Postgres weeks start Monday (ISO). Many US tools start Sunday.
- UK financial year: `DATE_TRUNC('year', ts - INTERVAL '3 months') + INTERVAL '3 months'`.
- `EXTRACT(MONTH)` merges years; `DATE_TRUNC('month')` doesn't.

## 20.7 String functions

```sql
a || b            CONCAT(a,b)         CONCAT_WS(sep, a, b, c)
LOWER  UPPER  INITCAP
TRIM  LTRIM  RTRIM  BTRIM(x, chars)
LENGTH  LPAD(x,n,c)  RPAD
LEFT(x,n)  RIGHT(x,n)  SUBSTRING(x FROM n FOR len)  SUBSTRING(x FROM 'regex')
POSITION(sub IN x)  STRPOS(x, sub)
REPLACE(x, from, to)   TRANSLATE(x, from, to)
SPLIT_PART(x, delim, n)   STRING_TO_ARRAY   UNNEST
x ~ 're'   x ~* 're'   x !~ 're'
REGEXP_REPLACE(x, 're', 'to', 'g')
STRING_AGG(x, ', ' ORDER BY y)
```

`||` returns NULL if either side is NULL; `CONCAT_WS` skips NULLs. That's the one to remember.

## 20.8 Window functions

```sql
func() OVER (PARTITION BY a ORDER BY b ROWS BETWEEN x AND y)
```

| Function | Returns |
|---|---|
| `ROW_NUMBER()` | 1,2,3,4 — no ties |
| `RANK()` | 1,2,2,4 — ties share, then gap |
| `DENSE_RANK()` | 1,2,2,3 — ties share, no gap |
| `NTILE(n)` | equal-count buckets |
| `PERCENT_RANK()`, `CUME_DIST()` | relative position 0–1 |
| `LAG(x, n, default)` | value n rows back |
| `LEAD(x, n, default)` | value n rows forward |
| `FIRST_VALUE(x)` | first in frame |
| `LAST_VALUE(x)` | last in frame — **needs an explicit frame** |
| `NTH_VALUE(x, n)` | nth in frame |
| `SUM/AVG/COUNT/MIN/MAX ... OVER` | aggregate over the frame |

**Frames:**
```sql
ROWS  BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW      -- running total
ROWS  BETWEEN 6 PRECEDING AND CURRENT ROW              -- 7-row moving window
RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW  -- gap-safe by calendar
ROWS  BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING   -- whole partition
ROWS  BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING      -- everything before this row
```

**Defaults:** no ORDER BY → whole partition. With ORDER BY, no frame → `RANGE UNBOUNDED PRECEDING TO CURRENT ROW` (ties share a value — specify `ROWS` if you don't want that).

Window functions run after GROUP BY, so `SUM(COUNT(*)) OVER ()` is legal and useful. They cannot be used in WHERE or HAVING.

## 20.9 CTEs and subqueries

```sql
WITH a AS ( ... ),
     b AS ( SELECT ... FROM a ),
     c AS MATERIALIZED ( ... )      -- force single computation
SELECT ... FROM b JOIN c USING (k);

WITH RECURSIVE t AS (
    anchor_query
    UNION ALL
    recursive_query_referencing_t  -- add a depth guard
)
SELECT * FROM t;
```

| Need | Use |
|---|---|
| Presence/absence test | `EXISTS` / `NOT EXISTS` |
| Columns from the other table | `JOIN` |
| Aggregate before joining | CTE or derived table |
| Reuse a result | CTE |
| Per-row correlated logic | correlated subquery — but check a window function first |
| Top N per outer row | `LATERAL` |

Postgres 12+ inlines single-use CTEs. Older versions always materialise. Some cloud warehouses recompute a CTE per reference.

## 20.10 Common analytical patterns

```sql
-- latest per group
SELECT DISTINCT ON (k) * FROM t ORDER BY k, ts DESC, id DESC;

-- top N per group
... WHERE rn <= N  -- from ROW_NUMBER/DENSE_RANK OVER (PARTITION BY g ORDER BY m DESC)

-- deduplicate
... WHERE rn = 1   -- ROW_NUMBER OVER (PARTITION BY key ORDER BY updated_at DESC, id DESC)

-- running total
SUM(x) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING)

-- moving average
AVG(x) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)

-- percent of total
100.0 * x / SUM(x) OVER ()

-- period-over-period
x - LAG(x) OVER (ORDER BY period)

-- gaps and islands
d - ROW_NUMBER() OVER (PARTITION BY k ORDER BY d)   -- constant within a run

-- sessionise / group on change
SUM(is_new_group) OVER (PARTITION BY k ORDER BY ts)

-- anti-join
WHERE NOT EXISTS (SELECT 1 FROM b WHERE b.k = a.k)

-- relational division ("bought every X")
HAVING COUNT(DISTINCT x) = (SELECT COUNT(*) FROM all_x)

-- zero-fill a series
generate_series(...) LEFT JOIN data ON ...  → COALESCE(...,0)
```

## 20.11 KPI formulas

| Metric | Formula | Watch |
|---|---|---|
| Revenue | Σ qty × price × (1 − discount) | which statuses; gross vs net; shipping |
| Gross profit | revenue − (qty × cost) | cost at time of sale vs current cost |
| Gross margin % | gross profit ÷ revenue | non-additive — recompute, don't average |
| AOV | revenue ÷ orders | aggregate to order grain first |
| Conversion rate | converters ÷ eligible | sessions or users?; `100.0 *` |
| Retention (month N) | active in N ÷ cohort size | LEFT JOIN; censoring |
| Churn rate | lost ÷ active at start | define "lost" before writing SQL |
| CAC | spend ÷ new customers | attribution model dependent |
| LTV (historic) | Σ revenue per customer | biased by tenure — normalise by cohort age |
| Repeat rate | customers with ≥2 orders ÷ all | must be cohorted |
| DAU / MAU | distinct actives per period | distinct counts aren't additive |
| Stickiness | DAU ÷ MAU | interpret against product type |
| Growth % | (curr − prev) ÷ prev | meaningless off a tiny base |
| Share of total | part ÷ `SUM(part) OVER ()` | internal share ≠ market share |
| Mean wait | Σ (end − start) ÷ n | completed only = survivorship bias |
| SLA compliance | within-target ÷ completed | what about still-open cases? |
| Breach rate | over-target ÷ completed | consider `COALESCE(end, now())` |

Every rate needs `NULLIF(denominator, 0)` and a minimum-denominator guard.

## 20.12 Dialect differences

| Task | Postgres | SQL Server | MySQL | BigQuery |
|---|---|---|---|---|
| Limit rows | `LIMIT n` | `TOP n` / `OFFSET…FETCH` | `LIMIT n` | `LIMIT n` |
| String concat | `\|\|` / `CONCAT` | `+` / `CONCAT` | `CONCAT` | `\|\|` / `CONCAT` |
| Case-insensitive match | `ILIKE` | `LIKE` (collation) | `LIKE` (collation) | `LOWER()` |
| Current date | `CURRENT_DATE` | `GETDATE()` | `CURDATE()` | `CURRENT_DATE()` |
| Date add | `+ INTERVAL '1 day'` | `DATEADD(day,1,d)` | `DATE_ADD(d,INTERVAL 1 DAY)` | `DATE_ADD(d,INTERVAL 1 DAY)` |
| Date diff | `d2 - d1` | `DATEDIFF(day,d1,d2)` | `DATEDIFF(d2,d1)` | `DATE_DIFF(d2,d1,DAY)` |
| Truncate to month | `DATE_TRUNC('month',d)` | `DATEFROMPARTS(...)` | `DATE_FORMAT(d,'%Y-%m-01')` | `DATE_TRUNC(d, MONTH)` |
| Null fallback | `COALESCE` | `ISNULL`/`COALESCE` | `IFNULL`/`COALESCE` | `IFNULL`/`COALESCE` |
| Conditional aggregate | `FILTER (WHERE …)` | `SUM(CASE …)` | `SUM(CASE …)` | `COUNTIF()` |
| Latest per group | `DISTINCT ON` | `ROW_NUMBER` | `ROW_NUMBER` (8+) | `ARRAY_AGG(… LIMIT 1)[OFFSET(0)]` |
| Split string | `SPLIT_PART` | `STRING_SPLIT` | `SUBSTRING_INDEX` | `SPLIT` |
| Regex | `~`, `REGEXP_REPLACE` | limited | `REGEXP` | `REGEXP_CONTAINS` |
| String aggregation | `STRING_AGG` | `STRING_AGG` | `GROUP_CONCAT` | `STRING_AGG` |

`COALESCE`, `CASE`, window functions, CTEs and standard joins work everywhere — build your habits on those and treat the rest as translation.

---

# FINAL SQL MASTERY CHECKLIST

Five levels. Each one names exactly what you should be able to solve **unaided, without notes, from a written problem statement**. Don't move on until the previous level is automatic — interviews test recall under pressure, and half-known material collapses.

---

## Level 1 — Basic SQL

*Target: you can answer simple questions about a single table.*

You can, without help:

- [ ] Read a schema and state the grain of each table ("one row per what?")
- [ ] Write SELECT / FROM / WHERE / ORDER BY / LIMIT fluently
- [ ] Filter with `=`, `<>`, `>`, `<`, `IN`, `BETWEEN`, `LIKE`, `IS NULL`
- [ ] Combine conditions with AND/OR/NOT and parenthesise OR correctly
- [ ] Use `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`
- [ ] Group with `GROUP BY` and filter groups with `HAVING`
- [ ] Explain the difference between WHERE and HAVING
- [ ] Explain the difference between `COUNT(*)` and `COUNT(column)`
- [ ] Explain why `x = NULL` never matches
- [ ] Use `DISTINCT` and say when it's masking a problem

**Test yourself:** questions 1–20 of the beginner bank, in under two minutes each.

---

## Level 2 — Job-ready SQL

*Target: you can produce correct numbers from a real multi-table schema.*

Everything above, plus:

- [ ] INNER and LEFT JOIN across three or four tables without hesitation
- [ ] Explain why a LEFT JOIN filter belongs in ON, not WHERE
- [ ] Use `COUNT(right.key)` rather than `COUNT(*)` after a LEFT JOIN
- [ ] Recognise fan-out and aggregate to a common grain before combining measures
- [ ] Write CASE for segmentation, banding and conditional aggregation
- [ ] Handle NULLs with `COALESCE`, `NULLIF`, `IS DISTINCT FROM`
- [ ] Explain the `NOT IN` NULL trap and write the `NOT EXISTS` alternative
- [ ] Use `DATE_TRUNC` and `EXTRACT` correctly, and know which merges years
- [ ] Write half-open date ranges by default
- [ ] Structure a query with CTEs instead of nested subqueries
- [ ] Guard every rate with `NULLIF(denominator, 0)` and `100.0 *`
- [ ] Self-check a result: row counts, uniqueness, one entity verified by hand

**Test yourself:** the whole beginner bank, plus intermediate questions 1–20.

---

## Level 3 — Interview-ready SQL

*Target: you can pass the technical round for a Data Analyst role.*

Everything above, plus:

- [ ] Window functions: `OVER`, `PARTITION BY`, `ORDER BY`, and frames
- [ ] `ROW_NUMBER` vs `RANK` vs `DENSE_RANK` — and when each is right
- [ ] Latest-record-per-group three ways, and pick one with a reason
- [ ] Top N per group, including the ties conversation
- [ ] `LAG`/`LEAD` for period-over-period change
- [ ] Running totals and moving averages, with the correct frame
- [ ] Percentage of total via a window aggregate
- [ ] Deduplicate with `ROW_NUMBER`, including a deterministic tie-breaker
- [ ] `EXISTS`/`NOT EXISTS` and when to prefer them over joins
- [ ] Explain SQL's logical evaluation order and what follows from it
- [ ] Explain the `LAST_VALUE` frame trap
- [ ] Debug someone else's broken query and name each problem
- [ ] Say "that definition is ambiguous — here's what I'd confirm" naturally

**Test yourself:** the full intermediate bank. Mock interviews 1–5, out loud.

---

## Level 4 — Strong Data Analyst SQL

*Target: you stand out against other candidates for the same role.*

Everything above, plus:

- [ ] Build a cohort retention table from scratch, and name the month-0 sanity check
- [ ] Compute retention, churn and repeat rate, and say what each definition assumes
- [ ] Build a funnel at the right grain, ordered or unordered, and know the difference
- [ ] Solve gaps and islands two ways and explain both
- [ ] Sessionise raw events with an inactivity timeout
- [ ] Pareto and contribution analysis, with the parts summing to the whole
- [ ] Anomaly detection that accounts for day-of-week seasonality
- [ ] RFM segmentation, with the NTILE directions right
- [ ] Recognise censoring, survivorship bias and mix effects — unprompted
- [ ] Translate a business KPI definition into SQL and challenge the definition
- [ ] Read `EXPLAIN ANALYZE` well enough to name the bottleneck
- [ ] Know why a query is slow *and* whether it's also wrong
- [ ] Assemble a wide customer-360 table with no fan-out

**Test yourself:** advanced bank questions 1–40. Mock interviews 6–8.

---

## Level 5 — Advanced SQL

*Target: you could take a senior analyst's technical round, or lead analysis independently.*

Everything above, plus:

- [ ] Recursive CTEs for hierarchies, with depth guards and cycle detection
- [ ] Point-in-time joins against SCD Type 2 dimensions
- [ ] Price/volume decomposition of a revenue change
- [ ] Cohort-normalised LTV that's fairly comparable across cohorts
- [ ] Market basket lift, not just raw co-occurrence
- [ ] Reconciliation between two sources with `FULL OUTER JOIN` and `IS DISTINCT FROM`
- [ ] Fuzzy deduplication with blocking, and know why blocking is mandatory
- [ ] Multi-touch attribution, and articulate what each model distorts
- [ ] Design a summary table and an incremental refresh strategy
- [ ] Explain normalisation, star schemas, grain and additivity confidently
- [ ] Explain CTE materialisation behaviour and how it differs across engines
- [ ] Investigate an open-ended business question end to end — decompose, localise, rule out measurement artefacts, and check whether the change is even outside normal variation
- [ ] Know when SQL is the wrong tool and say so

**Test yourself:** the full advanced bank. Mock interviews 9 and 10, out loud, with someone pushing back.

---

## The last word

The queries in this handbook are the easy part; you'll internalise them with practice. What actually separates candidates in Data Analyst interviews is smaller and less technical:

Asking what counts as revenue before computing it. Noticing the grain changed after a join. Saying "the average only covers completed pathways, which excludes the longest waiters." Checking whether a metric dropped or the tracking broke. Reporting a median next to a mean. Refusing to give a percentage when the base is four.

Those instincts come from doing the work, not from reading about it. Take the RetailCo schema, load it into a local Postgres, invent your own questions, and get things wrong in private until the checks in Part 19.4 become reflexive.

Then, in the room, think out loud. An interviewer cannot see a silent correct answer any better than a silent wrong one.
