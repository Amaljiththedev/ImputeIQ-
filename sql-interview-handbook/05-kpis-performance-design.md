# Parts 13–15: Business KPIs, Performance, Database Design

---

# PART 13 — BUSINESS KPI SQL

The skill this section teaches isn't SQL. It's translating a business definition into a query, and — more importantly — noticing where the definition is ambiguous and saying so. Interviewers ask "how would you calculate retention rate?" specifically to see whether you ask a clarifying question or just start typing.

Every KPI below is given as: **definition → decisions → SQL → what to challenge.**

## 13.1 Revenue

**Definition.** Value of goods sold in a period.

**Decisions.** Which order statuses count? Gross or net of discounts? Does shipping count as revenue? Are refunds deducted in the month of the order or the month of the refund? Ex-VAT or inc-VAT? Every one of these changes the number, and finance will have a fixed answer.

```sql
SELECT DATE_TRUNC('month', o.order_ts)::date AS month,
       ROUND(SUM(oi.quantity * oi.unit_price), 2)                        AS gross_revenue,
       ROUND(SUM(oi.quantity * oi.unit_price * oi.discount_pct), 2)      AS discounts,
       ROUND(SUM(oi.quantity * oi.unit_price * (1-oi.discount_pct)), 2)  AS net_product_revenue,
       ROUND(SUM(DISTINCT_SHIPPING.shipping), 2)                         AS shipping_revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN LATERAL (SELECT o.shipping_cost AS shipping) DISTINCT_SHIPPING ON true
WHERE o.status = 'completed'
GROUP BY 1 ORDER BY 1;
```

Shipping is order-level, so summing it after the item join double-counts. The correct version separates the grains:

```sql
WITH order_revenue AS (
    SELECT o.order_id,
           DATE_TRUNC('month', o.order_ts)::date AS month,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS product_revenue,
           MAX(o.shipping_cost) AS shipping_revenue
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed'
    GROUP BY o.order_id, 2
)
SELECT month,
       ROUND(SUM(product_revenue),2)                    AS product_revenue,
       ROUND(SUM(shipping_revenue),2)                   AS shipping_revenue,
       ROUND(SUM(product_revenue+shipping_revenue),2)   AS total_revenue
FROM order_revenue GROUP BY month ORDER BY month;
```

**Challenge.** "Revenue is up 5% but net revenue is flat" — you're discounting more heavily to hold volume. Always report gross, discount and net together; a single revenue line hides the mechanism.

## 13.2 Profit and gross margin

**Definition.** Gross profit = revenue − cost of goods sold. Gross margin % = gross profit ÷ revenue.

**Decision.** Which costs? Gross margin uses direct product cost only. Including shipping, payment fees or marketing gives contribution margin, a different metric.

```sql
SELECT p.category,
       ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)), 2)                 AS revenue,
       ROUND(SUM(oi.quantity*p.unit_cost), 2)                                       AS cogs,
       ROUND(SUM(oi.quantity*(oi.unit_price*(1-oi.discount_pct) - p.unit_cost)), 2) AS gross_profit,
       ROUND(100.0*SUM(oi.quantity*(oi.unit_price*(1-oi.discount_pct) - p.unit_cost))
             / NULLIF(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),0), 1)     AS gross_margin_pct
FROM order_items oi
JOIN products p USING (product_id)
JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
GROUP BY p.category
ORDER BY gross_profit DESC;
```

**Challenge.** `products.unit_cost` is the *current* cost, but `order_items.unit_price` is the price *at time of sale*. Margins on historical orders are computed against today's costs, which is wrong when costs move. The proper fix is a cost history table or a cost snapshot on the order line. Spotting this asymmetry in a schema is a genuinely senior observation and this schema contains it deliberately.

## 13.3 Average order value

```sql
WITH order_totals AS (
    SELECT o.order_id, DATE_TRUNC('month',o.order_ts)::date AS month,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS order_value
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed' GROUP BY 1,2
)
SELECT month,
       COUNT(*) AS orders,
       ROUND(AVG(order_value),2) AS aov,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_value)::numeric,2) AS median_order_value
FROM order_totals GROUP BY month ORDER BY month;
```

**Challenge.** Report the median alongside. Order values are right-skewed; one £5,000 B2B order moves the mean and nothing else. If mean and median diverge sharply, the mean is not describing a typical order.

## 13.4 Conversion rate

**Definition.** Converting units ÷ eligible units.

**Decision.** Sessions or users? A user with five sessions and one purchase is 20% at session level and 100% at user level. Both are legitimate; they answer different questions.

```sql
SELECT DATE_TRUNC('week', event_ts)::date AS week,
       COUNT(DISTINCT session_id) AS sessions,
       COUNT(DISTINCT session_id) FILTER (WHERE event_name='purchase') AS converting_sessions,
       ROUND(100.0*COUNT(DISTINCT session_id) FILTER (WHERE event_name='purchase')
             / NULLIF(COUNT(DISTINCT session_id),0),2) AS session_cvr_pct,
       COUNT(DISTINCT customer_id) FILTER (WHERE event_name='purchase') AS converting_users
FROM web_events GROUP BY 1 ORDER BY 1;
```

## 13.5 Retention rate

**Definition.** Proportion of a starting group still active after a period.

**Decisions.** Cohort by signup or first purchase? Calendar month or rolling window? Does "active" mean logged in, or purchased? N-day retention (active exactly on day N) or unbounded (active at any point since)?

See Part 12.9–12.10 for the full queries. The one-line version:

```sql
ROUND(100.0 * COUNT(DISTINCT returning.customer_id) / NULLIF(COUNT(DISTINCT base.customer_id),0), 1)
```

**Challenge.** "Retention improved from 40% to 55%" — check whether the cohort composition changed. Stopping a bad paid-acquisition channel raises retention without any product improvement, because you removed the customers who were never going to stay.

## 13.6 Churn rate

Churn = 1 − retention, when measured over the same population and window. Not interchangeable when the denominators differ (retention often measured on a cohort, churn on the active base).

```sql
WITH ma AS (SELECT DISTINCT customer_id, DATE_TRUNC('month',order_ts)::date AS month
            FROM orders WHERE status='completed')
SELECT c.month,
       COUNT(DISTINCT c.customer_id) AS active,
       COUNT(DISTINCT c.customer_id) FILTER (WHERE n.customer_id IS NULL) AS churned,
       ROUND(100.0*COUNT(DISTINCT c.customer_id) FILTER (WHERE n.customer_id IS NULL)
             / NULLIF(COUNT(DISTINCT c.customer_id),0),1) AS churn_rate_pct
FROM ma c LEFT JOIN ma n ON n.customer_id=c.customer_id AND n.month=c.month+INTERVAL '1 month'
GROUP BY c.month ORDER BY c.month;
```

**Challenge.** The most recent month always shows 100% churn because next month hasn't happened. Exclude incomplete periods, or your dashboard will terrify someone.

## 13.7 Customer acquisition

```sql
SELECT DATE_TRUNC('month', signup_date)::date AS month,
       channel,
       COUNT(*) AS new_customers,
       COUNT(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id AND o.status='completed'))
           AS activated,
       ROUND(100.0*COUNT(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id AND o.status='completed'))
             / COUNT(*),1) AS activation_rate_pct
FROM customers c
GROUP BY 1,2 ORDER BY 1,2;
```

CAC needs marketing spend, which isn't in this schema:

```sql
SELECT m.month, m.channel, m.spend, a.new_customers,
       ROUND(m.spend/NULLIF(a.new_customers,0),2) AS cac
FROM marketing_spend m JOIN acquisitions a USING (month, channel);
```

**Challenge.** Attribution. Last-click credits the final touch, first-click the first; a customer who saw a paid ad then searched the brand name is attributed entirely differently under each. Say that CAC by channel is only as good as the attribution model behind it.

## 13.8 Customer lifetime value

**Historic LTV** — what they've actually spent, and the version you can compute from this schema:

```sql
SELECT c.customer_id, c.channel AS acquisition_channel,
       COUNT(DISTINCT o.order_id) AS orders,
       ROUND(COALESCE(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),0),2) AS historic_ltv,
       ROUND(COALESCE(SUM(oi.quantity*(oi.unit_price*(1-oi.discount_pct)-p.unit_cost)),0),2)
           AS gross_profit_ltv,
       CURRENT_DATE - c.signup_date AS tenure_days
FROM customers c
LEFT JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
LEFT JOIN order_items oi USING (order_id)
LEFT JOIN products p USING (product_id)
GROUP BY c.customer_id, c.channel, c.signup_date;
```

**Predicted LTV**, simple version: `AOV × purchase frequency × expected lifespan`, ideally on gross profit not revenue.

```sql
WITH metrics AS (
    SELECT AVG(order_value) AS aov,
           COUNT(*)::numeric / COUNT(DISTINCT customer_id) AS orders_per_customer
    FROM order_values
)
SELECT ROUND(aov * orders_per_customer / NULLIF(churn_rate,0), 2) AS predicted_ltv
FROM metrics CROSS JOIN (SELECT 0.15 AS churn_rate) c;
```

**Challenge.** Historic LTV is biased by tenure — a customer who joined last month cannot have high LTV. Always compare LTV within cohorts of similar age, or normalise to LTV-at-90-days. Volunteering that is the difference between reciting a formula and understanding it.

## 13.9 Repeat purchase rate

```sql
SELECT DATE_TRUNC('month', first_order)::date AS cohort,
       COUNT(*) AS customers,
       COUNT(*) FILTER (WHERE orders >= 2) AS repeaters,
       ROUND(100.0*COUNT(*) FILTER (WHERE orders>=2)/COUNT(*),1) AS repeat_rate_pct
FROM (SELECT customer_id, COUNT(*) AS orders, MIN(order_ts)::date AS first_order
      FROM orders WHERE status='completed' GROUP BY customer_id) t
GROUP BY 1 ORDER BY 1;
```

Cohorting is essential here for the reason in 12.15 — recent cohorts haven't had time to repeat, so an uncohorted repeat rate falls every month you grow.

## 13.10 Active users — DAU, MAU, stickiness

```sql
-- DAU
SELECT event_ts::date AS day, COUNT(DISTINCT customer_id) AS dau
FROM web_events WHERE customer_id IS NOT NULL GROUP BY 1;

-- MAU, calendar month
SELECT DATE_TRUNC('month',event_ts)::date AS month, COUNT(DISTINCT customer_id) AS mau
FROM web_events WHERE customer_id IS NOT NULL GROUP BY 1;

-- rolling 28-day MAU and the DAU/MAU stickiness ratio
WITH dau AS (
    SELECT event_ts::date AS day, COUNT(DISTINCT customer_id) AS dau
    FROM web_events WHERE customer_id IS NOT NULL GROUP BY 1
),
rolling AS (
    SELECT d.day, d.dau,
           (SELECT COUNT(DISTINCT e.customer_id) FROM web_events e
            WHERE e.event_ts::date > d.day - 28 AND e.event_ts::date <= d.day) AS mau_28d
    FROM dau d
)
SELECT day, dau, mau_28d, ROUND(100.0*dau/NULLIF(mau_28d,0),1) AS stickiness_pct
FROM rolling ORDER BY day;
```

**Note.** MAU is *not* the sum or average of DAU — a user active 20 days counts once in MAU and 20 times across DAU. `COUNT(DISTINCT)` must be recomputed at each grain, which is why rolling MAU needs a correlated subquery or a self-join rather than a window function. Explaining why distinct counts aren't additive is a good interview moment.

**Challenge.** DAU/MAU near 100% means daily-habit usage; near 3% means monthly. Neither is inherently good — it depends on what the product is for. A tax-filing app with 5% stickiness is fine.

## 13.11 Growth rate

```sql
WITH monthly AS (
    SELECT DATE_TRUNC('month',order_ts)::date AS month, COUNT(*) AS orders
    FROM orders WHERE status='completed' GROUP BY 1)
SELECT month, orders,
       ROUND(100.0*(orders - LAG(orders) OVER (ORDER BY month))
             / NULLIF(LAG(orders) OVER (ORDER BY month),0),1) AS mom_growth_pct,
       ROUND(100.0*(orders - LAG(orders,12) OVER (ORDER BY month))
             / NULLIF(LAG(orders,12) OVER (ORDER BY month),0),1) AS yoy_growth_pct,
       ROUND((POWER(orders::numeric / NULLIF(FIRST_VALUE(orders) OVER (ORDER BY month),0),
              1.0/NULLIF(ROW_NUMBER() OVER (ORDER BY month)-1,0)) - 1)*100, 2) AS cagr_pct
FROM monthly ORDER BY month;
```

**Challenge.** Percentage growth off a small base is meaningless — 2 orders to 6 is "200% growth". Always show the absolute numbers next to the percentage, and suppress percentages below a minimum base.

## 13.12 Market share

```sql
SELECT p.category, p.product_name,
       ROUND(SUM(oi.quantity*oi.unit_price),2) AS revenue,
       ROUND(100.0*SUM(oi.quantity*oi.unit_price)
             / SUM(SUM(oi.quantity*oi.unit_price)) OVER (PARTITION BY p.category),1)
             AS share_of_category_pct,
       ROUND(100.0*SUM(oi.quantity*oi.unit_price)
             / SUM(SUM(oi.quantity*oi.unit_price)) OVER (),1) AS share_of_total_pct
FROM order_items oi JOIN products p USING (product_id)
JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
GROUP BY p.category, p.product_name
ORDER BY p.category, revenue DESC;
```

True market share needs competitor data you don't have; internal share of category is what's computable. Be precise about which you're reporting.

## 13.13 Average waiting time

```sql
SELECT r.specialty,
       COUNT(*) AS completed_pathways,
       ROUND(AVG(a.attended_ts::date - r.referral_date),1) AS mean_wait_days,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a.attended_ts::date - r.referral_date)
           AS median_wait_days,
       PERCENTILE_CONT(0.92) WITHIN GROUP (ORDER BY a.attended_ts::date - r.referral_date)
           AS p92_wait_days,
       MAX(a.attended_ts::date - r.referral_date) AS longest_wait
FROM referrals r
JOIN LATERAL (SELECT attended_ts FROM appointments x
              WHERE x.referral_id=r.referral_id AND x.outcome='Attended'
              ORDER BY attended_ts LIMIT 1) a ON true
GROUP BY r.specialty ORDER BY median_wait_days DESC;
```

The 92nd percentile is there because NHS RTT reporting uses a 92% within-18-weeks standard, so p92 is the number that tells you whether you're meeting it.

**Challenge — this one matters.** This measures *completed* pathways only. Patients still waiting are excluded, and they are the longest waiters. A trust can cut its average completed wait by treating the easy cases first while the queue lengthens. Always report incomplete-pathway waits alongside:

```sql
SELECT r.specialty,
       COUNT(*) AS still_waiting,
       ROUND(AVG(CURRENT_DATE - r.referral_date),1) AS mean_wait_so_far,
       COUNT(*) FILTER (WHERE CURRENT_DATE - r.referral_date > 126) AS over_18_weeks
FROM referrals r
JOIN waiting_list w ON w.referral_id=r.referral_id AND w.removed_date IS NULL
GROUP BY r.specialty;
```

## 13.14 SLA compliance and breach rate

```sql
SELECT site_code,
       DATE_TRUNC('month', arrival_ts)::date AS month,
       COUNT(*)                                                              AS attendances,
       COUNT(*) FILTER (WHERE departure_ts IS NULL)                          AS still_in_dept,
       COUNT(*) FILTER (WHERE departure_ts - arrival_ts <= INTERVAL '4 hours') AS within_standard,
       COUNT(*) FILTER (WHERE departure_ts - arrival_ts >  INTERVAL '4 hours') AS breaches,
       ROUND(100.0*COUNT(*) FILTER (WHERE departure_ts - arrival_ts <= INTERVAL '4 hours')
             / NULLIF(COUNT(*) FILTER (WHERE departure_ts IS NOT NULL),0),1)  AS pct_within_4h,
       ROUND(100.0*COUNT(*) FILTER (WHERE departure_ts - arrival_ts > INTERVAL '4 hours')
             / NULLIF(COUNT(*) FILTER (WHERE departure_ts IS NOT NULL),0),1)  AS breach_rate_pct
FROM ae_attendances
GROUP BY 1,2 ORDER BY 1,2;
```

**The decisions embedded here, all worth raising:**

- Patients still in the department are excluded from the denominator. If someone has been waiting six hours and hasn't left, they've already breached — arguably they should count as a breach immediately. This choice flatters performance.
- Is the clock measured to departure, or to a decision to admit? Different definitions exist and give different numbers.
- Should the standard apply equally to triage category 1 and category 5?

An interviewer asking for "the four-hour performance figure" is often testing whether you'll produce a number silently or interrogate the definition first. Interrogate it.

**A defensible version that counts current breaches:**

```sql
COUNT(*) FILTER (
    WHERE COALESCE(departure_ts, CURRENT_TIMESTAMP) - arrival_ts > INTERVAL '4 hours'
) AS breaches_including_current
```

---

# PART 14 — PERFORMANCE AND QUERY OPTIMISATION

What an analyst realistically needs: enough to write queries that don't melt the warehouse, read a query plan well enough to find the problem, and have a sensible conversation with a data engineer. Not index internals.

## 14.1 How a query executes

1. **Parse** — syntax check.
2. **Rewrite** — apply views, expand rules.
3. **Plan** — the optimiser estimates costs for alternative strategies and picks one, using table statistics gathered by `ANALYZE`.
4. **Execute** — run the chosen plan.

Two consequences worth knowing. First, *estimates* drive the plan: if statistics are stale, the planner picks badly, which is why a query can suddenly get 100× slower after a big data load. Second, the planner rewrites your SQL aggressively — subqueries become joins, filters move around — so cosmetic rewrites often change nothing.

## 14.2 Indexes

An index is a sorted structure mapping column values to row locations. It converts "scan every row" into "look it up".

```sql
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_ts       ON orders(order_ts);
CREATE INDEX idx_orders_cust_ts  ON orders(customer_id, order_ts);   -- composite
CREATE INDEX idx_orders_recent   ON orders(order_ts) WHERE status='completed';  -- partial
CREATE INDEX idx_cust_email_lower ON customers(LOWER(email));        -- functional
```

What an analyst needs to know:

- **Indexes speed reads, slow writes**, and consume disk. They're a trade-off, not free.
- **Column order in a composite index matters.** `(customer_id, order_ts)` serves queries filtering on `customer_id` alone, or both. It does *not* efficiently serve a query filtering only on `order_ts` — think of a phone book sorted by surname then first name.
- **Foreign key columns are usually worth indexing**; Postgres does not create these automatically (it does for primary keys and unique constraints).
- **Small tables don't benefit.** Scanning 500 rows is faster than an index lookup, and the planner knows it.

**What kills an index** — this is the practically useful part:

```sql
-- function on the column: index unusable
WHERE DATE(order_ts) = '2024-03-15'
WHERE UPPER(email) = 'X@Y.COM'
WHERE customer_id::text = '42'

-- rewrite as a sargable range/predicate: index usable
WHERE order_ts >= '2024-03-15' AND order_ts < '2024-03-16'
WHERE email = 'x@y.com'                    -- or index LOWER(email) and query LOWER(email)
WHERE customer_id = 42

-- leading wildcard: index unusable
WHERE email LIKE '%@gmail.com'
-- trailing wildcard: usable
WHERE product_name LIKE 'Wireless%'
```

"Sargable" (search-argument-able) is the term; using it correctly signals you've read beyond a tutorial.

## 14.3 Scan types

| Plan node | Meaning | When it's fine |
|---|---|---|
| **Seq Scan** | read every row | small tables, or when returning most rows anyway |
| **Index Scan** | walk the index, fetch matching rows | highly selective filters |
| **Index Only Scan** | answer entirely from the index | best case; needs all selected columns in the index |
| **Bitmap Heap Scan** | build a bitmap of matching pages, then read them | medium selectivity, several conditions |

A Seq Scan is not automatically bad. Fetching 60% of a table via an index is *slower* than scanning it, because of random I/O per row. The planner switching from Index Scan to Seq Scan as a filter gets less selective is correct behaviour. Saying "I saw a Seq Scan so I added an index" without checking selectivity is the junior answer.

Join algorithms you'll see:

- **Nested Loop** — for each row of A, look up matches in B. Great when A is tiny and B is indexed; catastrophic when both are large.
- **Hash Join** — build a hash table of the smaller side, probe with the larger. The workhorse for big equality joins.
- **Merge Join** — sort both sides, walk them together. Good when inputs are already sorted.

## 14.4 EXPLAIN and EXPLAIN ANALYZE

```sql
EXPLAIN SELECT ...;                                  -- estimated plan, doesn't run
EXPLAIN ANALYZE SELECT ...;                          -- actually runs it, shows real timings
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT ...;  -- adds I/O detail
```

**Warning:** `EXPLAIN ANALYZE` executes the statement. Never run it on an `UPDATE` or `DELETE` outside a transaction you intend to roll back.

Reading a plan:

```
Hash Join  (cost=1.16..2.34 rows=10 width=64) (actual time=0.05..0.09 rows=847 loops=1)
  Hash Cond: (o.customer_id = c.customer_id)
  ->  Seq Scan on orders o  (cost=0.00..1.10 rows=10 width=32) (actual ... rows=847 ...)
        Filter: (status = 'completed'::text)
        Rows Removed by Filter: 153
  ->  Hash  (cost=1.07..1.07 rows=7 width=36) (actual ...)
        ->  Seq Scan on customers c  ...
```

Read it inside-out and bottom-up: indented children run first, feeding their parents.

What to look for, in priority order:

1. **`rows` estimated vs actual.** The plan above estimates 10 rows and gets 847. An estimate off by 100× means the planner chose its strategy on bad information — usually stale statistics (`ANALYZE orders;`) or a correlation it can't see. This is the number one cause of mysteriously slow queries.
2. **The node with the largest actual time**, remembering that a child's time is included in its parent's.
3. **`Rows Removed by Filter`** in the millions — you're reading a lot of rows to throw them away. Candidate for an index.
4. **Nested Loop with a large outer row count** — often a missing index on the inner side.
5. **`loops=N`** — the node ran N times; the displayed time is *per loop*, so multiply.
6. **Sort or Hash spilling to disk** (`external merge Disk: 52428kB`) — the operation exceeded `work_mem`.

Practical advice for an interview: you're not expected to tune a plan. You're expected to say "I'd run EXPLAIN ANALYZE, compare estimated to actual rows to see whether the planner is misinformed, and find the node consuming the most time." That answer is entirely sufficient for an analyst role and better than most candidates give.

## 14.5 Filtering early

The single most effective thing an analyst can do.

```sql
-- BAD: join everything, then filter
SELECT ... FROM orders o
JOIN order_items oi USING (order_id)
JOIN products p USING (product_id)
JOIN customers c USING (customer_id)
WHERE o.order_ts >= '2024-01-01';

-- BETTER: reduce the driving table first
WITH recent_orders AS (
    SELECT order_id, customer_id, order_ts
    FROM orders
    WHERE order_ts >= '2024-01-01' AND status='completed'
)
SELECT ... FROM recent_orders o
JOIN order_items oi USING (order_id)
...
```

In practice Postgres's planner usually pushes that filter down itself, so the two often produce the same plan. Where it genuinely matters: distributed engines (Spark, BigQuery, Redshift) with poorer push-down, CTEs marked `MATERIALIZED`, filters involving non-inlinable functions, and partitioned tables where an early filter enables partition pruning.

**Partition pruning** is worth knowing by name: if a table is partitioned by month, a `WHERE order_ts >= '2024-03-01'` filter lets the engine skip every other partition entirely. But only if the filter is directly on the partition key and isn't wrapped in a function.

## 14.6 Join optimisation

- **Join on indexed keys.** Foreign key columns usually want an index.
- **Reduce before you join.** Aggregate or filter a large table down before joining it to another large table.
- **Avoid joining on expressions.** `ON UPPER(a.code)=UPPER(b.code)` can't use ordinary indexes; normalise the data or add functional indexes to both sides.
- **Match types.** A join between `text` and `integer` may force casts that defeat indexes.
- **Watch fan-out.** The cheapest optimisation is often producing fewer rows: pre-aggregating one side from 10 million rows to 100 thousand changes everything downstream.
- **Join order** is the planner's job, and it will reorder inner joins freely. Don't try to outsmart it by rewriting; give it good statistics instead. (`LEFT JOIN` order is semantically fixed, so it has less freedom there — another reason not to use outer joins where inner ones suffice.)

## 14.7 Aggregation optimisation

- `COUNT(DISTINCT x)` is expensive — it must deduplicate. If exactness isn't needed at scale, approximate counting is available (`postgresql-hll`; `APPROX_COUNT_DISTINCT` in BigQuery/Snowflake).
- `GROUP BY` on many columns, or on wide text columns, forces large hash tables. Group by ids and join to labels afterwards.
- Filter before grouping (WHERE, not HAVING) whenever the condition is row-level.
- Repeated heavy aggregations belong in a materialised view or a scheduled summary table, not re-run per dashboard load:

```sql
CREATE MATERIALIZED VIEW mv_daily_sales AS
SELECT order_ts::date AS d, COUNT(*) AS orders, SUM(order_value) AS revenue
FROM order_values GROUP BY 1;

CREATE UNIQUE INDEX ON mv_daily_sales(d);
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_sales;
```

`CONCURRENTLY` keeps the view readable during the refresh and requires that unique index. That's a nicely specific detail to have.

## 14.8 CTE considerations

Covered in Part 10.4. The short version for an interview: in Postgres 12+, single-use CTEs are inlined; multiply-used ones are materialised. Use `MATERIALIZED` deliberately when a CTE is expensive and reused, `NOT MATERIALIZED` when you want filters pushed in. In older Postgres, CTEs are always an optimisation fence. In some cloud warehouses a repeated CTE is *recomputed* each reference, so a temp table may be cheaper.

## 14.9 Avoiding SELECT *

- Transfers columns you don't need, over the network and through memory.
- Prevents index-only scans (the index can't cover columns it doesn't contain).
- Breaks views and downstream code when the schema changes.
- Hides the query's real dependencies from anyone reading it.

On wide tables — event tables with 200 columns and JSON blobs are common — selecting five columns instead of all of them can be an order of magnitude faster.

## 14.10 Large table considerations

- **Always bound by time.** An unbounded `SELECT ... FROM events` on a billion-row table is how analysts get their warehouse access reviewed.
- **`LIMIT` while exploring**, but remember `LIMIT` with `ORDER BY` on an unindexed column still sorts everything first.
- **Sample** rather than scan when exploring distributions: `TABLESAMPLE SYSTEM (1)` reads roughly 1% of pages, very fast.
- **Understand the storage model.** Columnar stores (Redshift, BigQuery, Snowflake, Parquet) read only the columns you select, so `SELECT *` is disproportionately expensive there and column pruning matters more than row filtering.
- **Know your cost model.** BigQuery bills by bytes scanned: selecting fewer columns and partitioning by date directly reduces the bill. That's a very concrete answer if asked "how do you optimise in BigQuery?".
- **Set a statement timeout** in your session so a runaway query fails instead of running for six hours: `SET statement_timeout = '5min';`

## 14.11 A realistic optimisation walkthrough

**Slow query:**

```sql
SELECT c.first_name, c.last_name, COUNT(*) AS orders
FROM customers c, orders o, order_items oi
WHERE c.customer_id = o.customer_id
  AND o.order_id = oi.order_id
  AND DATE(o.order_ts) >= '2024-01-01'
  AND UPPER(c.country) = 'UK'
GROUP BY c.first_name, c.last_name;
```

Problems, in order of impact:

1. `DATE(o.order_ts)` wraps the indexed column — no index use on the largest table.
2. `UPPER(c.country)` likewise, though `customers` is small so it matters less.
3. Joining `order_items` at all — it's never selected from, it only multiplies rows and inflates `COUNT(*)`. The count is *wrong*, not just slow.
4. Grouping by name rather than id — two customers named Tom Brady merge, and text grouping is more expensive.
5. Implicit comma joins — legal, but they hide the join conditions among the filters.

**Rewritten:**

```sql
SELECT c.customer_id, c.first_name, c.last_name, COUNT(*) AS orders
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
WHERE o.order_ts >= DATE '2024-01-01'
  AND c.country = 'UK'
  AND o.status = 'completed'
GROUP BY c.customer_id, c.first_name, c.last_name;
```

Faster *and* correct. That's the point worth making in an interview: the optimisation and the bug fix were the same edit. Performance problems and correctness problems come from the same root — not thinking about grain.

---

# PART 15 — DATABASE DESIGN FUNDAMENTALS

You won't design a production database as a junior analyst. You will be asked about normalisation and star schemas, because they explain why the tables you query look the way they do.

## 15.1 Normalisation

Organising data to eliminate redundancy and update anomalies.

**Unnormalised:**

| order_id | customer | customer_email | products | total |
|---|---|---|---|---|
| 1 | Aisha Khan | aisha@ex.com | Mouse, Coffee | 68.73 |

Three problems: the products column holds multiple values (can't query it); the customer's email is repeated on every order (update one, miss another, now they disagree); delete the only order for a customer and you lose their details entirely.

**1NF — atomic values, no repeating groups.** Each cell holds one value; each row is unique.

```
orders(order_id, customer_name, customer_email, order_date)
order_items(order_id, product_name, quantity, price)
```

**2NF — 1NF plus no partial dependencies.** Every non-key column depends on the *whole* primary key, not part of it. Only relevant with composite keys.

If `order_items` had key `(order_id, product_id)` and also carried `product_name`, that's a violation: `product_name` depends on `product_id` alone, not the pair. Move it to a `products` table.

**3NF — 2NF plus no transitive dependencies.** Non-key columns depend on the key and nothing but the key.

If `orders` carried `customer_name` and `customer_email`, those depend on `customer_id`, which depends on `order_id` — transitive. Move them to `customers`. Our RetailCo schema is in 3NF, which is why customer details live in exactly one place.

The shorthand that gets you through the question: *"every non-key attribute depends on the key, the whole key, and nothing but the key."*

Beyond 3NF: BCNF, 4NF, 5NF exist. Nobody will ask a junior analyst about them; knowing they exist and that 3NF is the practical stopping point for OLTP is enough.

## 15.2 Denormalisation

Deliberately reintroducing redundancy to make reads faster and simpler.

When it's right:
- Analytical warehouses where data is written once and read constantly.
- Avoiding a six-table join on every dashboard load.
- Storing a value that must not change with its source — `order_items.unit_price` is denormalised *on purpose*, because the price at the time of sale must survive a later price change. That's not a design flaw; it's a historical record.

Costs: more storage, and the risk of copies disagreeing. In a warehouse that's acceptable because the ETL is the single writer.

## 15.3 Star schema

The dominant analytical design. A central **fact** table surrounded by **dimension** tables.

```
        dim_date        dim_customer
             \             /
              \           /
   dim_product─── fact_sales ───dim_store
```

```sql
CREATE TABLE fact_sales (
    sale_id        bigserial PRIMARY KEY,
    date_key       integer REFERENCES dim_date(date_key),
    customer_key   integer REFERENCES dim_customer(customer_key),
    product_key    integer REFERENCES dim_product(product_key),
    store_key      integer REFERENCES dim_store(store_key),
    quantity       integer,        -- measures
    gross_amount   numeric(12,2),
    discount_amount numeric(12,2),
    net_amount     numeric(12,2),
    cost_amount    numeric(12,2)
);

CREATE TABLE dim_customer (
    customer_key   serial PRIMARY KEY,     -- surrogate key
    customer_id    integer,                -- natural/business key
    full_name      text,
    country        text,
    segment        text,
    valid_from     date,                   -- SCD Type 2
    valid_to       date,
    is_current     boolean
);
```

**Fact tables** hold measures (numeric, additive) and foreign keys to dimensions. Long and narrow — billions of rows, few columns. **Dimension tables** hold descriptive attributes you filter and group by. Short and wide — thousands of rows, many columns.

Why analysts should care: it makes queries uniform. Every question becomes "join fact to the dimensions I'm slicing by, filter, aggregate". No deep join chains, no guessing the path between tables.

**Snowflake schema** normalises the dimensions further (`dim_product` → `dim_category` → `dim_department`). It saves space and adds joins. Star is usually preferred for analytics precisely because the redundancy buys simplicity.

**Grain** is the first thing to define in a fact table: one row per what? Per order line, per order, per day per store? Every subsequent design decision follows from it, and mixing grains in one fact table is the classic warehouse design failure.

**Additivity** — worth knowing the vocabulary:
- *Additive* measures sum across every dimension (revenue, quantity).
- *Semi-additive* sum across some but not time (account balance, stock level — summing Monday's and Tuesday's stock is meaningless; you average or take the latest).
- *Non-additive* never sum (ratios, percentages, margin %) — you must recompute them from their components after aggregating.

That last point is a real and common analyst error: averaging a set of margin percentages gives a different, wrong answer versus recomputing total profit ÷ total revenue.

## 15.4 Slowly changing dimensions

A customer moves from Leeds to London. What happens to last year's orders?

- **Type 0** — never change it.
- **Type 1** — overwrite. History is lost; all past orders now appear to come from London.
- **Type 2** — add a new row with new validity dates, mark the old one not current. History preserved; the dimension grows. This is why you join on the key *and* the date range.
- **Type 3** — keep a `previous_country` column. Only remembers one change back.

Type 2 is the standard for anything where historical accuracy matters, and it's why `dim_customer` above has `valid_from`/`valid_to`/`is_current`.

```sql
-- as-at-the-time attributes
SELECT d.country, SUM(f.net_amount)
FROM fact_sales f
JOIN dim_date dt ON dt.date_key = f.date_key
JOIN dim_customer d
  ON d.customer_key = f.customer_key       -- surrogate key already points at the right version
GROUP BY d.country;

-- current attributes instead
JOIN dim_customer d ON d.customer_id = <business key> AND d.is_current
```

The distinction — "revenue by the country they lived in at the time" vs "by where they live now" — is a real business question with two different right answers, and knowing that the schema determines which you get is a strong thing to say.

## 15.5 Referential integrity

Foreign key constraints guarantee that references point at rows that exist. They also prevent deleting a parent that still has children, unless you specify `ON DELETE CASCADE` (delete the children too) or `ON DELETE SET NULL`.

In OLTP databases, constraints are enforced and you can trust them. In warehouses they're often declared but `NOT ENFORCED`, or absent entirely, because enforcement slows bulk loads. **So check for orphans yourself** before promising anyone that a join loses nothing:

```sql
SELECT COUNT(*) FROM fact_sales f
LEFT JOIN dim_customer d ON d.customer_key = f.customer_key
WHERE d.customer_key IS NULL;
```

A standard warehouse practice is an "unknown member" row (key = -1) in each dimension, so facts with a missing dimension reference still join and appear in reports as 'Unknown' rather than vanishing from an inner join. If you've seen that, say so — it's a detail that only comes from real exposure.

## 15.6 OLTP vs OLAP

| | OLTP | OLAP |
|---|---|---|
| Purpose | run the business | analyse the business |
| Workload | many small reads/writes | few large reads |
| Design | normalised (3NF) | denormalised (star) |
| Grain | one row per transaction | fact rows plus aggregates |
| Indexes | many, for point lookups | fewer; partitioning, clustering, columnar |
| Storage | row-oriented | column-oriented |
| Typical query | "get order 1234" | "revenue by region by month for 3 years" |
| Examples | Postgres, MySQL, SQL Server | BigQuery, Snowflake, Redshift, Databricks |

**Why column storage matters to you.** In a row store, reading one column still reads whole rows off disk. In a column store, `SELECT SUM(revenue)` reads only the revenue column — often 50× less I/O — and compresses far better because similar values sit together. This is why `SELECT *` is disproportionately punished in a warehouse, and why analysts get a columnar warehouse rather than access to the production OLTP database.

The other reason for the separation: analytical queries scanning millions of rows would lock up and slow down the database that's taking customer orders. Never run a heavy analytical query against a production OLTP system. Saying this out loud in an interview shows operational awareness.

## 15.7 How design affects your SQL

| Design fact | Effect on your query |
|---|---|
| Normalised source | more joins; watch fan-out and grain |
| Star schema | join fact to dimensions; grain is fixed by the fact table |
| SCD Type 2 dimension | must join on key **and** validity window, or you duplicate rows |
| No enforced FKs | check for orphans before trusting an inner join |
| Denormalised price on the line | historical accuracy preserved — use it, don't join to current price |
| Partitioned by date | filter on the partition key directly, unwrapped, to get pruning |
| Columnar storage | select only the columns you need; row filtering matters less |
| Pre-aggregated summary tables | use them instead of re-aggregating the fact table |

## 15.8 Design interview questions

1. *"What's the difference between OLTP and OLAP?"* — Table above; lead with purpose and workload, then design and storage.
2. *"Why is a star schema used for analytics rather than a fully normalised model?"* — Fewer joins, predictable query shape, better performance for scan-and-aggregate workloads; the redundancy is safe because ETL is the only writer.
3. *"What's the grain of a fact table and why does it matter?"* — What one row represents. It determines which measures are valid at that row, and mixing grains breaks every aggregate.
4. *"How would you handle a customer changing address?"* — Type 1 vs Type 2, and the business question of whether history matters.
5. *"When would you denormalise?"* — Read-heavy analytics, avoiding repeated expensive joins, and capturing point-in-time values that must not change.
6. *"What's 3NF in one sentence?"* — Every non-key attribute depends on the key, the whole key, and nothing but the key.
7. *"Why not put everything in one big table?"* — Update anomalies, storage, and the impossibility of maintaining consistency — then note that a wide denormalised table is exactly what many modern warehouses do build for consumption, because the trade-offs invert when nothing is being updated.
