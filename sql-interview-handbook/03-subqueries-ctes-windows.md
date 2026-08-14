# Parts 9–11: Subqueries, CTEs, Window Functions

---

# PART 9 — SUBQUERIES

A subquery is a query nested inside another. Classify them two ways, because the two classifications answer different questions:

- **By what they return**: scalar (one value), row, or table.
- **By dependency**: uncorrelated (runs once, standalone) or correlated (references the outer query, conceptually runs per outer row).

## 9.1 Scalar subqueries

Return exactly one row and one column. Usable anywhere a single value is legal.

```sql
-- in SELECT: attach a global figure to every row
SELECT product_name, unit_price,
       (SELECT ROUND(AVG(unit_price),2) FROM products) AS avg_price,
       ROUND(unit_price - (SELECT AVG(unit_price) FROM products), 2) AS diff_from_avg
FROM products;

-- in WHERE: compare against an aggregate
SELECT product_name, unit_price FROM products
WHERE unit_price > (SELECT AVG(unit_price) FROM products);
```

If a scalar subquery returns more than one row, Postgres raises an error at runtime — which is safer than silently picking one, but it means a subquery that works on test data can fail in production when the data grows a duplicate. Add `LIMIT 1` with an explicit `ORDER BY` if "any one of them" is genuinely acceptable, but usually the multiple rows mean your logic is wrong.

If it returns no rows, you get NULL, not an error, and the NULL propagates silently.

## 9.2 Subqueries in FROM (derived tables)

A subquery in FROM acts as a temporary table. It **must** have an alias in Postgres.

```sql
SELECT country, ROUND(AVG(order_count),1) AS avg_orders_per_customer
FROM (
    SELECT c.customer_id, c.country, COUNT(o.order_id) AS order_count
    FROM customers c
    LEFT JOIN orders o ON o.customer_id = c.customer_id AND o.status='completed'
    GROUP BY c.customer_id, c.country
) AS per_customer
GROUP BY country;
```

This is the standard solution to "aggregate an aggregate" — you cannot nest aggregate functions directly (`AVG(COUNT(*))` is illegal outside a window context), so you aggregate once in the inner query and again in the outer.

Derived tables and CTEs are interchangeable here. Prefer CTEs (Part 10) for readability; derived tables are fine for a single small nesting.

## 9.3 Subqueries in WHERE

**With IN:**

```sql
SELECT * FROM customers
WHERE customer_id IN (
    SELECT customer_id FROM orders WHERE status='completed' AND order_ts >= '2024-01-01'
);
```

**With a comparison operator and an aggregate:**

```sql
SELECT * FROM orders
WHERE order_ts > (SELECT MAX(order_ts) FROM orders WHERE customer_id = 1);
```

**With ANY / ALL** — less common but they appear in exams:

```sql
WHERE unit_price > ALL (SELECT unit_price FROM products WHERE category='Grocery')
WHERE unit_price > ANY (SELECT unit_price FROM products WHERE category='Grocery')
```

`> ALL` means greater than the maximum; `> ANY` means greater than the minimum. `= ANY` is exactly `IN`. Note `ALL` has the same NULL problem as `NOT IN`, and both return true vacuously over an empty set — `> ALL (empty)` is true.

## 9.4 Correlated subqueries

A correlated subquery references a column from the outer query, so it is logically evaluated once per outer row.

```sql
-- customers who spent more than their country's average
SELECT c.customer_id, c.country, c.lifetime_value
FROM customer_summary c
WHERE c.lifetime_value > (
    SELECT AVG(c2.lifetime_value)
    FROM customer_summary c2
    WHERE c2.country = c.country          -- <-- the correlation
);
```

Readable, and for small tables perfectly fine. For large tables a window function does the same job in one pass:

```sql
SELECT * FROM (
    SELECT customer_id, country, lifetime_value,
           AVG(lifetime_value) OVER (PARTITION BY country) AS country_avg
    FROM customer_summary
) t WHERE lifetime_value > country_avg;
```

That rewrite — correlated aggregate subquery to window function — is one of the highest-value optimisations an analyst can know, and interviewers love asking for it. Postgres's planner often rewrites simple correlated subqueries into joins itself, but not reliably, and not when the subquery is in SELECT.

**Correlated subquery in SELECT:**

```sql
SELECT c.customer_id, c.first_name,
       (SELECT COUNT(*) FROM orders o
        WHERE o.customer_id = c.customer_id AND o.status='completed') AS orders,
       (SELECT MAX(o.order_ts) FROM orders o
        WHERE o.customer_id = c.customer_id) AS last_order
FROM customers c;
```

Each extra correlated column is another pass over `orders`. Two subqueries here means scanning orders twice; a single LEFT JOIN with GROUP BY does it once. Recognising that is worth saying out loud.

## 9.5 EXISTS and NOT EXISTS

`EXISTS` tests whether a subquery returns *any* row. It returns a boolean and **short-circuits** — the database stops as soon as it finds one match, which is why it's usually the fastest way to express "has at least one".

```sql
-- customers who have ordered
SELECT c.* FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o
              WHERE o.customer_id = c.customer_id AND o.status='completed');

-- customers who never ordered  (the anti-join)
SELECT c.* FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id);
```

Points that come up:

- `SELECT 1` vs `SELECT *` inside EXISTS makes no difference — the select list is never evaluated. `SELECT 1` just signals intent.
- EXISTS is **NULL-safe**, unlike `NOT IN`. This is the headline reason to prefer it.
- EXISTS never multiplies rows. `JOIN` to a many-side to test existence duplicates the outer rows and forces you into DISTINCT; EXISTS doesn't.

**Multi-condition existence** is where EXISTS really earns its place:

```sql
-- customers who bought Electronics AND also bought Home, but never returned anything
SELECT c.customer_id FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o JOIN order_items oi USING (order_id)
              JOIN products p USING (product_id)
              WHERE o.customer_id=c.customer_id AND p.category='Electronics'
                AND o.status='completed')
  AND EXISTS (SELECT 1 FROM orders o JOIN order_items oi USING (order_id)
              JOIN products p USING (product_id)
              WHERE o.customer_id=c.customer_id AND p.category='Home'
                AND o.status='completed')
  AND NOT EXISTS (SELECT 1 FROM orders o
                  WHERE o.customer_id=c.customer_id AND o.status='refunded');
```

Doing that with joins would require three joins, careful DISTINCT handling, and would be much harder to read or amend.

## 9.6 Subquery vs JOIN — when to use which

| Use | Because |
|---|---|
| `EXISTS` / `NOT EXISTS` | testing presence/absence without duplicating rows; NULL-safe |
| `JOIN` | you need **columns** from the other table |
| `IN` with a small static list | simple, readable |
| `IN` with a subquery | fine when the subquery key can't be NULL; otherwise EXISTS |
| Derived table / CTE | you need to aggregate before joining, or reuse a result |
| Correlated subquery | per-row logic that's genuinely hard to express otherwise — but check whether a window function does it |
| `LATERAL` | top-N per group, or a correlated subquery returning multiple columns |

The decisive question is: **do I need data from the other table, or just a yes/no?** Need data → join. Yes/no → EXISTS.

Three ways to write "customers who ordered in 2024", all correct:

```sql
-- JOIN + DISTINCT: works, but DISTINCT is doing damage control after fan-out
SELECT DISTINCT c.* FROM customers c
JOIN orders o ON o.customer_id=c.customer_id
WHERE o.order_ts >= '2024-01-01';

-- IN: clear, safe here because orders.customer_id is a non-null FK
SELECT * FROM customers
WHERE customer_id IN (SELECT customer_id FROM orders WHERE order_ts >= '2024-01-01');

-- EXISTS: usually the best plan, no fan-out, no NULL risk
SELECT c.* FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o
              WHERE o.customer_id=c.customer_id AND o.order_ts >= '2024-01-01');
```

Say "I'd write EXISTS: it can't duplicate rows, it's NULL-safe, and it short-circuits" and you've answered the question behind the question.

## 9.7 Subquery exercises

1. Products priced above the overall average.
2. Products priced above their own category's average.
3. Customers who have ordered but never had a refund.
4. The most recent order for each customer, using a correlated subquery.
5. Customers whose spend is above the average customer spend.
6. Categories where every product is active.
7. Employees earning more than the average in their department.
8. Products that have never been ordered — three ways.
9. Customers who ordered in both 2023 and 2024.
10. The order containing the single most expensive line.

```sql
-- 1
SELECT * FROM products WHERE unit_price > (SELECT AVG(unit_price) FROM products);

-- 2  correlated
SELECT p.* FROM products p
WHERE p.unit_price > (SELECT AVG(p2.unit_price) FROM products p2 WHERE p2.category=p.category);
-- window equivalent
SELECT * FROM (SELECT *, AVG(unit_price) OVER (PARTITION BY category) AS cat_avg FROM products) t
WHERE unit_price > cat_avg;

-- 3
SELECT c.* FROM customers c
WHERE EXISTS     (SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id AND o.status='completed')
  AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id AND o.status='refunded');

-- 4
SELECT o.* FROM orders o
WHERE o.order_ts = (SELECT MAX(o2.order_ts) FROM orders o2 WHERE o2.customer_id=o.customer_id);
-- caveat: ties return multiple rows; ROW_NUMBER guarantees exactly one

-- 5
WITH spend AS (
  SELECT o.customer_id, SUM(oi.quantity*oi.unit_price) AS total
  FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
  GROUP BY o.customer_id)
SELECT * FROM spend WHERE total > (SELECT AVG(total) FROM spend);

-- 6
SELECT DISTINCT category FROM products p
WHERE NOT EXISTS (SELECT 1 FROM products p2 WHERE p2.category=p.category AND NOT p2.is_active);

-- 7
SELECT e.* FROM employees e
WHERE e.salary > (SELECT AVG(e2.salary) FROM employees e2 WHERE e2.department=e.department);

-- 8
SELECT * FROM products p WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id=p.product_id);
SELECT p.* FROM products p LEFT JOIN order_items oi USING (product_id) WHERE oi.order_item_id IS NULL;
SELECT * FROM products WHERE product_id NOT IN (SELECT product_id FROM order_items WHERE product_id IS NOT NULL);

-- 9
SELECT customer_id FROM orders WHERE status='completed'
GROUP BY customer_id
HAVING COUNT(*) FILTER (WHERE order_ts >= '2023-01-01' AND order_ts < '2024-01-01') > 0
   AND COUNT(*) FILTER (WHERE order_ts >= '2024-01-01' AND order_ts < '2025-01-01') > 0;

-- 10
SELECT * FROM orders WHERE order_id = (
  SELECT order_id FROM order_items ORDER BY quantity*unit_price DESC LIMIT 1);
```

---

# PART 10 — COMMON TABLE EXPRESSIONS (CTEs)

## 10.1 Why analysts live in CTEs

A CTE is a named subquery defined before the main query with `WITH`. Functionally it's a derived table with a name — but the naming is the whole point.

Analytical questions are pipelines: filter, aggregate to a grain, join to another aggregate, rank, filter again. Nesting that as subqueries produces a query you read inside-out. CTEs let you write it top-down, in the order you thought of it, with each step named after what it means.

```sql
-- nested: read from the inside out, and good luck debugging it
SELECT * FROM (
  SELECT customer_id, total, RANK() OVER (ORDER BY total DESC) AS r
  FROM (
    SELECT customer_id, SUM(revenue) AS total
    FROM (SELECT o.customer_id, oi.quantity*oi.unit_price AS revenue
          FROM orders o JOIN order_items oi USING (order_id)
          WHERE o.status='completed') a
    GROUP BY customer_id) b
) c WHERE r <= 10;

-- CTEs: read top to bottom, each step named
WITH line_revenue AS (
    SELECT o.customer_id, oi.quantity * oi.unit_price * (1-oi.discount_pct) AS revenue
    FROM orders o
    JOIN order_items oi USING (order_id)
    WHERE o.status = 'completed'
),
customer_totals AS (
    SELECT customer_id, SUM(revenue) AS lifetime_value
    FROM line_revenue GROUP BY customer_id
),
ranked AS (
    SELECT *, RANK() OVER (ORDER BY lifetime_value DESC) AS value_rank
    FROM customer_totals
)
SELECT * FROM ranked WHERE value_rank <= 10;
```

Same result. The second is reviewable, and — the practical benefit — you can debug it by replacing the final SELECT with `SELECT * FROM line_revenue LIMIT 20` to inspect any stage.

Reasons to give in an interview: readability, step-by-step debuggability, reuse of a result in multiple places, and they make the analytical logic legible to a reviewer who isn't a SQL expert. Then add the caveat about materialisation below, which shows you know the trade-off.

## 10.2 Syntax and multiple CTEs

```sql
WITH first_cte AS ( ... ),
     second_cte AS ( SELECT ... FROM first_cte ... ),   -- can reference earlier CTEs
     third_cte  AS ( SELECT ... FROM first_cte JOIN second_cte ... )
SELECT ... FROM third_cte;
```

`WITH` once, CTEs comma-separated, no comma before the final SELECT. A CTE can reference any CTE defined **before** it, not after (unless recursive). Each CTE can be referenced multiple times.

## 10.3 Chained CTEs — a full analytical pipeline

```sql
WITH completed_orders AS (
    SELECT order_id, customer_id, order_ts, channel
    FROM orders
    WHERE status = 'completed'
      AND order_ts >= DATE '2024-01-01'
),
order_values AS (
    SELECT co.order_id, co.customer_id, co.order_ts, co.channel,
           SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS order_value
    FROM completed_orders co
    JOIN order_items oi ON oi.order_id = co.order_id
    GROUP BY co.order_id, co.customer_id, co.order_ts, co.channel
),
customer_metrics AS (
    SELECT customer_id,
           COUNT(*)                AS orders,
           SUM(order_value)        AS lifetime_value,
           AVG(order_value)        AS avg_order_value,
           MIN(order_ts)::date     AS first_order,
           MAX(order_ts)::date     AS last_order
    FROM order_values
    GROUP BY customer_id
),
segmented AS (
    SELECT cm.*, c.country, c.channel AS acquisition_channel,
           NTILE(4) OVER (ORDER BY cm.lifetime_value DESC) AS value_quartile,
           CASE WHEN cm.orders = 1 THEN 'One-time' ELSE 'Repeat' END AS repeat_status
    FROM customer_metrics cm
    JOIN customers c USING (customer_id)
)
SELECT country, acquisition_channel, repeat_status,
       COUNT(*) AS customers,
       ROUND(AVG(lifetime_value), 2) AS avg_ltv,
       ROUND(AVG(avg_order_value), 2) AS avg_aov
FROM segmented
GROUP BY 1,2,3
ORDER BY avg_ltv DESC;
```

Five named stages, each doing one thing. This is what "readable analytical pipeline" means, and being able to produce something with this shape under interview pressure is what a strong candidate looks like.

## 10.4 Materialisation and performance

The important caveat. **Before Postgres 12**, CTEs were always materialised — computed once into a temporary result, with no predicate push-down. That made them an "optimisation fence": a filter in the outer query couldn't be pushed into the CTE, so a CTE selecting a billion rows computed all billion even if you then filtered to ten.

**Postgres 12+** inlines CTEs that are referenced exactly once and are not recursive and have no side effects, treating them like derived tables. You can force either behaviour:

```sql
WITH big AS MATERIALIZED     ( SELECT ... )   -- compute once, reuse
WITH big AS NOT MATERIALIZED ( SELECT ... )   -- inline, allow push-down
```

Use `MATERIALIZED` when a CTE is expensive and referenced several times. Use `NOT MATERIALIZED` when a CTE is a simple scan referenced once and you want filters pushed in.

**Dialect.** SQL Server and Oracle always inline CTEs (they're purely syntactic there). MySQL 8+ behaves similarly to modern Postgres. In BigQuery and Snowflake a multiply-referenced CTE may be recomputed each time — if a CTE is used three times and is expensive, consider a temp table. Knowing this distinction is a real senior-level answer.

A CTE is **not** a temporary table: it exists only for the duration of the statement, isn't indexed, and isn't visible to other queries.

## 10.5 Recursive CTEs

For hierarchies and generated sequences. Structure:

```sql
WITH RECURSIVE cte_name AS (
    -- anchor: the starting rows
    SELECT ...
    UNION ALL
    -- recursive term: references cte_name, produces the next level
    SELECT ... FROM table JOIN cte_name ON ...
)
SELECT * FROM cte_name;
```

**Org hierarchy** — the standard interview example:

```sql
WITH RECURSIVE org AS (
    SELECT employee_id, full_name, manager_id, 1 AS level,
           full_name::text AS path
    FROM employees
    WHERE manager_id IS NULL                    -- anchor: the top of the tree

    UNION ALL

    SELECT e.employee_id, e.full_name, e.manager_id, o.level + 1,
           o.path || ' > ' || e.full_name
    FROM employees e
    JOIN org o ON o.employee_id = e.manager_id  -- recursive: children of known nodes
)
SELECT level, REPEAT('  ', level-1) || full_name AS org_chart, path
FROM org
ORDER BY path;
```

`UNION ALL` not `UNION` — `UNION` deduplicates on every iteration, which is slow and usually wrong. If the hierarchy might contain a cycle (bad data where A manages B manages A), add a depth guard: `WHERE o.level < 20`. Volunteering that guard is the thing that marks out someone who's actually run one of these in anger.

**Generating a date series** without `generate_series` (useful in engines that lack it):

```sql
WITH RECURSIVE dates AS (
    SELECT DATE '2024-01-01' AS d
    UNION ALL
    SELECT d + 1 FROM dates WHERE d < DATE '2024-12-31'
)
SELECT * FROM dates;
```

In Postgres just use `generate_series(DATE '2024-01-01', DATE '2024-12-31', INTERVAL '1 day')`.

**Patient pathway / referral chains** — following linked records:

```sql
WITH RECURSIVE pathway AS (
    SELECT referral_id, patient_id, referral_date, onward_referral_id, 1 AS step
    FROM referrals WHERE source <> 'Consultant'          -- pathway starts

    UNION ALL

    SELECT r.referral_id, r.patient_id, r.referral_date, r.onward_referral_id, p.step + 1
    FROM referrals r JOIN pathway p ON r.referral_id = p.onward_referral_id
    WHERE p.step < 10
)
SELECT patient_id, COUNT(*) AS steps_in_pathway,
       MAX(referral_date) - MIN(referral_date) AS pathway_length_days
FROM pathway GROUP BY patient_id;
```

For a junior analyst role, being able to write the org-chart recursion and explain anchor/recursive/termination is enough. Nobody expects graph algorithms.

## 10.6 CTE exercises

1. Rewrite the nested query in 10.1 from scratch using CTEs.
2. Build a pipeline: monthly revenue → month-on-month change → flag months that fell.
3. Use one CTE twice in the same query.
4. Compute each customer's LTV, then their quartile, then average LTV per quartile.
5. Write the org chart recursion with indentation.
6. Generate every month of 2024 and LEFT JOIN revenue to it.
7. Build a cleaning pipeline: standardise → validate → dedupe → output.
8. Find the top 3 products per category using CTEs plus a window function.

```sql
-- 2
WITH monthly AS (
  SELECT DATE_TRUNC('month',o.order_ts)::date AS month,
         SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
  FROM orders o JOIN order_items oi USING (order_id)
  WHERE o.status='completed' GROUP BY 1),
with_change AS (
  SELECT month, revenue,
         LAG(revenue) OVER (ORDER BY month) AS prev,
         revenue - LAG(revenue) OVER (ORDER BY month) AS delta
  FROM monthly)
SELECT month, ROUND(revenue,2) AS revenue, ROUND(delta,2) AS change,
       ROUND(100.0*delta/NULLIF(prev,0),1) AS pct_change,
       CASE WHEN delta < 0 THEN 'Declined' WHEN delta > 0 THEN 'Grew' ELSE 'Flat' END AS direction
FROM with_change ORDER BY month;

-- 3  same CTE referenced twice: this month vs the same month last year
WITH monthly AS (
  SELECT DATE_TRUNC('month',order_ts)::date AS month, COUNT(*) AS orders
  FROM orders WHERE status='completed' GROUP BY 1)
SELECT m.month, m.orders, p.orders AS last_year,
       ROUND(100.0*(m.orders-p.orders)/NULLIF(p.orders,0),1) AS yoy_pct
FROM monthly m LEFT JOIN monthly p ON p.month = m.month - INTERVAL '1 year'
ORDER BY m.month;

-- 4
WITH ltv AS (
  SELECT o.customer_id, SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS lifetime_value
  FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
  GROUP BY o.customer_id),
quartiles AS (
  SELECT *, NTILE(4) OVER (ORDER BY lifetime_value DESC) AS quartile FROM ltv)
SELECT quartile, COUNT(*) AS customers,
       ROUND(AVG(lifetime_value),2) AS avg_ltv,
       ROUND(SUM(lifetime_value),2) AS total_ltv,
       ROUND(100.0*SUM(lifetime_value)/SUM(SUM(lifetime_value)) OVER (),1) AS pct_of_revenue
FROM quartiles GROUP BY quartile ORDER BY quartile;

-- 6
WITH months AS (
  SELECT generate_series(DATE '2024-01-01', DATE '2024-12-01', INTERVAL '1 month')::date AS month),
rev AS (
  SELECT DATE_TRUNC('month',o.order_ts)::date AS month,
         SUM(oi.quantity*oi.unit_price) AS revenue
  FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed' GROUP BY 1)
SELECT m.month, COALESCE(ROUND(r.revenue,2),0) AS revenue
FROM months m LEFT JOIN rev r USING (month) ORDER BY m.month;

-- 8
WITH product_sales AS (
  SELECT p.category, p.product_id, p.product_name,
         SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
  FROM order_items oi
  JOIN products p USING (product_id)
  JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
  GROUP BY 1,2,3),
ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY category ORDER BY revenue DESC) AS rn
  FROM product_sales)
SELECT category, product_name, ROUND(revenue,2) AS revenue, rn
FROM ranked WHERE rn <= 3 ORDER BY category, rn;
```

---

# PART 11 — WINDOW FUNCTIONS

The single biggest differentiator in analyst interviews. Candidates who are fluent here get offers.

## 11.1 The core idea

A window function computes a value across a set of rows related to the current row, **without collapsing them**. GROUP BY gives you one row per group; a window function gives you every row, with the group-level value attached.

```sql
-- GROUP BY: 4 rows out (one per category)
SELECT category, AVG(unit_price) FROM products GROUP BY category;

-- window: 6 rows out, each with its category's average alongside
SELECT product_name, category, unit_price,
       AVG(unit_price) OVER (PARTITION BY category) AS category_avg
FROM products;
```

That difference — keeping row-level detail while adding group-level context — is what makes comparisons like "this order versus the customer's average" possible in one pass.

**Evaluation order matters.** Window functions run *after* WHERE, GROUP BY and HAVING, and *before* ORDER BY and LIMIT. Two consequences tested constantly:

- You cannot filter on a window function in WHERE. `WHERE ROW_NUMBER() OVER (...) = 1` is a syntax error. Wrap it in a subquery or CTE and filter outside. There is no `HAVING` equivalent for windows.
- Because windows run after grouping, you can apply one *to an aggregate*: `SUM(COUNT(*)) OVER ()` is legal and useful (Part 3.5).

## 11.2 OVER, PARTITION BY, ORDER BY

```sql
function() OVER (
    PARTITION BY col1, col2      -- optional: split into independent groups
    ORDER BY col3                -- optional: order within each partition
    [frame]                      -- optional: which rows in the partition count
)
```

- **`OVER ()`** — empty: the whole result set is one window.
- **`PARTITION BY`** — restart the calculation for each group. Like GROUP BY, but non-collapsing.
- **`ORDER BY`** — order within the partition. Required for ranking and offset functions. Adding it to an aggregate **changes its meaning** — see 11.3.

```sql
SELECT customer_id, order_id, order_ts, order_value,
       SUM(order_value) OVER ()                            AS grand_total,
       SUM(order_value) OVER (PARTITION BY customer_id)    AS customer_total,
       SUM(order_value) OVER (PARTITION BY customer_id ORDER BY order_ts) AS running_total
FROM order_values;
```

Three windows, three different numbers, one pass. Reading that block and understanding why the third differs from the second is the core skill.

**Named windows** keep repeated definitions DRY:

```sql
SELECT customer_id, order_ts,
       ROW_NUMBER() OVER w AS seq,
       LAG(order_value) OVER w AS prev_value,
       SUM(order_value) OVER w AS running_total
FROM order_values
WINDOW w AS (PARTITION BY customer_id ORDER BY order_ts);
```

## 11.3 Window frames

The frame defines which rows within the partition the function sees. This is the concept most candidates skip and most interviewers probe.

```sql
ROWS   BETWEEN <start> AND <end>    -- counts physical rows
RANGE  BETWEEN <start> AND <end>    -- counts by value of the ORDER BY column
GROUPS BETWEEN <start> AND <end>    -- counts peer groups (Postgres 11+)
```

Bounds: `UNBOUNDED PRECEDING`, `n PRECEDING`, `CURRENT ROW`, `n FOLLOWING`, `UNBOUNDED FOLLOWING`.

**The defaults, which cause real bugs:**

- No `ORDER BY` in the window → frame is the entire partition. `SUM(x) OVER (PARTITION BY c)` is the partition total.
- `ORDER BY` present, no explicit frame → the default is `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`. That's a running total — **but** with `RANGE`, "current row" means "all rows with the same ORDER BY value", so tied rows all get the same cumulative value.

```sql
-- ties: with RANGE (default), two orders on the same day share one running total
SUM(v) OVER (ORDER BY order_date)
-- with ROWS, each row increments separately
SUM(v) OVER (ORDER BY order_date ROWS UNBOUNDED PRECEDING)
```

If you want a strict row-by-row running total, say `ROWS` explicitly. This is exactly the sort of detail that separates a strong answer.

Common frames:

```sql
-- running total
SUM(x) OVER (ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)

-- 7-day moving average (dense series)
AVG(x) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)

-- 7-day moving average (gap-safe, calendar-based)
AVG(x) OVER (ORDER BY d RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW)

-- centred 3-period average
AVG(x) OVER (ORDER BY d ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING)

-- partition total on every row
SUM(x) OVER (PARTITION BY c ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)

-- remaining total from here on
SUM(x) OVER (ORDER BY d ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)
```

## 11.4 Ranking: ROW_NUMBER, RANK, DENSE_RANK

The difference is entirely about how they handle ties, and you will be asked.

| values | ROW_NUMBER | RANK | DENSE_RANK |
|---|---|---|---|
| 100 | 1 | 1 | 1 |
| 90 | 2 | 2 | 2 |
| 90 | 3 | 2 | 2 |
| 80 | 4 | 4 | 3 |

- **ROW_NUMBER** — always 1,2,3,4. No ties, arbitrary tie-breaking. Use for deduplication and "pick exactly one".
- **RANK** — ties share a rank, then it skips. Use for competition-style ranking, "joint second".
- **DENSE_RANK** — ties share a rank, no gaps. Use for "top 3 distinct values".

```sql
SELECT product_name, category, unit_price,
       ROW_NUMBER()  OVER (PARTITION BY category ORDER BY unit_price DESC) AS rn,
       RANK()        OVER (PARTITION BY category ORDER BY unit_price DESC) AS rnk,
       DENSE_RANK()  OVER (PARTITION BY category ORDER BY unit_price DESC) AS dense,
       PERCENT_RANK()OVER (PARTITION BY category ORDER BY unit_price DESC) AS pct_rank,
       CUME_DIST()   OVER (PARTITION BY category ORDER BY unit_price DESC) AS cume
FROM products;
```

**Determinism.** `ROW_NUMBER()` over tied values assigns arbitrarily, and the assignment can change between runs. Always add a unique tie-breaker to the ORDER BY when the result must be reproducible:

```sql
ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts DESC, order_id DESC)
```

**NTILE(n)** splits a partition into n roughly equal buckets:

```sql
SELECT customer_id, lifetime_value,
       NTILE(4)   OVER (ORDER BY lifetime_value DESC) AS quartile,
       NTILE(10)  OVER (ORDER BY lifetime_value DESC) AS decile
FROM customer_ltv;
```

NTILE distributes by row count, not by value, so bucket boundaries fall at odd places when values are lumpy and identical values can land in different buckets. For value-based bands use CASE or `PERCENT_RANK`. Mention it; it shows you know the tool's limits.

## 11.5 Offset functions: LAG, LEAD, FIRST_VALUE, LAST_VALUE

```sql
LAG(expr, offset, default)   OVER (PARTITION BY ... ORDER BY ...)
LEAD(expr, offset, default)  OVER (...)
FIRST_VALUE(expr)            OVER (...)
LAST_VALUE(expr)             OVER (...)
NTH_VALUE(expr, n)           OVER (...)
```

`offset` defaults to 1, `default` to NULL — supplying a default (`LAG(revenue,1,0)`) saves a COALESCE.

```sql
SELECT customer_id, order_ts::date AS order_date, order_value,
       LAG(order_value)  OVER w AS previous_order_value,
       LEAD(order_value) OVER w AS next_order_value,
       order_ts::date - LAG(order_ts::date) OVER w AS days_since_previous,
       FIRST_VALUE(order_value) OVER w AS first_ever_order_value
FROM order_values
WINDOW w AS (PARTITION BY customer_id ORDER BY order_ts);
```

**The LAST_VALUE trap**, asked often. With the default frame (`UNBOUNDED PRECEDING TO CURRENT ROW`), `LAST_VALUE` returns the current row — because the current row is the last one in the frame so far.

```sql
-- WRONG: returns the current row's value every time
LAST_VALUE(order_value) OVER (PARTITION BY customer_id ORDER BY order_ts)

-- RIGHT: extend the frame to the end of the partition
LAST_VALUE(order_value) OVER (PARTITION BY customer_id ORDER BY order_ts
                              ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)

-- or sidestep it entirely
FIRST_VALUE(order_value) OVER (PARTITION BY customer_id ORDER BY order_ts DESC)
```

`FIRST_VALUE` is unaffected because the frame's start is already the partition's start. Being able to explain *why* — not just recite the fix — is the strong answer.

## 11.6 Aggregate window functions

Any aggregate can be a window function: `SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, plus `FILTER`.

```sql
SELECT order_id, customer_id, order_ts::date AS d, order_value,
       SUM(order_value)   OVER (PARTITION BY customer_id ORDER BY order_ts
                                ROWS UNBOUNDED PRECEDING)         AS cumulative_spend,
       AVG(order_value)   OVER (PARTITION BY customer_id)         AS customer_avg_order,
       COUNT(*)           OVER (PARTITION BY customer_id)         AS total_orders,
       MAX(order_value)   OVER (PARTITION BY customer_id)         AS biggest_order,
       ROUND(100.0 * order_value
             / SUM(order_value) OVER (PARTITION BY customer_id), 1) AS pct_of_customer_spend,
       ROUND(100.0 * order_value
             / SUM(order_value) OVER (), 2)                       AS pct_of_all_revenue
FROM order_values;
```

`COUNT(*) FILTER (WHERE ...) OVER (...)` works too, and is the neat way to do a running count of a subset.

## 11.7 The problem patterns

These are the shapes that appear in interviews. Learn to recognise each from its phrasing.

### Top N per group

> *"Top 3 products by revenue in each category."*

```sql
WITH product_revenue AS (
    SELECT p.category, p.product_name,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
    FROM order_items oi
    JOIN products p USING (product_id)
    JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
    GROUP BY 1,2
)
SELECT * FROM (
    SELECT *, DENSE_RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS rnk
    FROM product_revenue
) t WHERE rnk <= 3
ORDER BY category, rnk;
```

Choose the ranking function deliberately and say why: `ROW_NUMBER` gives exactly 3 and arbitrarily cuts ties; `DENSE_RANK` gives all products at the top 3 revenue levels. Ask the interviewer which they want — that question alone is worth marks.

### Latest record per group

> *"Each customer's most recent order."*

```sql
-- portable
SELECT * FROM (
    SELECT o.*, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts DESC, order_id DESC) rn
    FROM orders o WHERE status='completed'
) t WHERE rn = 1;

-- Postgres, shorter and often faster
SELECT DISTINCT ON (customer_id) *
FROM orders WHERE status='completed'
ORDER BY customer_id, order_ts DESC, order_id DESC;

-- correlated, no window function
SELECT o.* FROM orders o
WHERE o.order_ts = (SELECT MAX(o2.order_ts) FROM orders o2 WHERE o2.customer_id=o.customer_id);
```

The third returns duplicates on ties — a real difference, not a stylistic one.

### Running total

```sql
SELECT order_ts::date AS d, order_value,
       SUM(order_value) OVER (ORDER BY order_ts ROWS UNBOUNDED PRECEDING) AS cumulative
FROM order_values ORDER BY order_ts;
```

### Moving average

```sql
SELECT d, orders,
       ROUND(AVG(orders) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS ma7
FROM daily_orders;
```

The first six rows average fewer than seven days. If the report shouldn't show a partial window, null them out:

```sql
CASE WHEN COUNT(*) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) = 7
     THEN AVG(orders) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) END
```

### Percentage of total

```sql
SELECT category,
       ROUND(SUM(revenue), 2) AS revenue,
       ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 1) AS pct_of_total,
       ROUND(100.0 * SUM(SUM(revenue)) OVER (ORDER BY SUM(revenue) DESC
                                             ROWS UNBOUNDED PRECEDING)
             / SUM(SUM(revenue)) OVER (), 1) AS cumulative_pct
FROM category_sales GROUP BY category
ORDER BY revenue DESC;
```

That cumulative percentage column is Pareto analysis — "which categories make up 80% of revenue" — in one expression. `SUM(SUM(x)) OVER ()` looks strange the first time; the inner SUM is the GROUP BY aggregate, the outer is the window over those results.

### Purchase sequence and first/repeat

```sql
SELECT customer_id, order_id, order_ts,
       ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts) AS purchase_number,
       CASE WHEN ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts) = 1
            THEN 'First' ELSE 'Repeat' END AS purchase_type,
       COUNT(*) OVER (PARTITION BY customer_id) AS lifetime_orders
FROM orders WHERE status='completed';
```

### Month-over-month change

```sql
WITH monthly AS (
    SELECT DATE_TRUNC('month',order_ts)::date AS month, SUM(order_value) AS revenue
    FROM order_values GROUP BY 1)
SELECT month, revenue,
       LAG(revenue) OVER (ORDER BY month) AS prev,
       ROUND(100.0*(revenue - LAG(revenue) OVER (ORDER BY month))
             / NULLIF(LAG(revenue) OVER (ORDER BY month),0), 1) AS mom_pct
FROM monthly;
```

### Comparing a row to its group

```sql
SELECT e.full_name, e.department, e.salary,
       ROUND(AVG(e.salary) OVER (PARTITION BY e.department)) AS dept_avg,
       ROUND(e.salary - AVG(e.salary) OVER (PARTITION BY e.department)) AS vs_dept_avg,
       RANK() OVER (PARTITION BY e.department ORDER BY e.salary DESC) AS salary_rank_in_dept,
       ROUND(100.0*e.salary / SUM(e.salary) OVER (PARTITION BY e.department),1) AS pct_of_dept_paybill
FROM employees e;
```

### Gaps and islands — consecutive events

The hardest common pattern, covered fully in Part 12. The trick in one line: for consecutive integers or dates, `value - ROW_NUMBER()` is constant within a consecutive run, so grouping by that difference identifies each run.

```sql
WITH numbered AS (
    SELECT customer_id, activity_date,
           activity_date - (ROW_NUMBER() OVER (PARTITION BY customer_id
                                               ORDER BY activity_date))::int AS grp
    FROM daily_activity
)
SELECT customer_id, MIN(activity_date) AS streak_start, MAX(activity_date) AS streak_end,
       COUNT(*) AS consecutive_days
FROM numbered GROUP BY customer_id, grp
HAVING COUNT(*) >= 3
ORDER BY consecutive_days DESC;
```

## 11.8 Window function exercises

1. Rank customers by lifetime value.
2. For each product, its price and its category's average price.
3. Each customer's second order.
4. Running total of revenue by day.
5. 7-day moving average of orders.
6. Each order's value as a percentage of that customer's total.
7. Days between consecutive orders per customer.
8. Top 2 employees by salary in each department.
9. Month-on-month revenue growth percentage.
10. Each customer's first and last order value on every row.
11. Products in the top decile by revenue.
12. Cumulative share of revenue by category, ranked (Pareto).
13. Customers whose latest order is smaller than their previous one.
14. The longest streak of consecutive days with at least one order.
15. For each order, how many orders that customer had already placed.

```sql
-- 1
SELECT customer_id, lifetime_value, RANK() OVER (ORDER BY lifetime_value DESC) FROM customer_ltv;

-- 2
SELECT product_name, category, unit_price,
       ROUND(AVG(unit_price) OVER (PARTITION BY category),2) AS cat_avg,
       ROUND(unit_price - AVG(unit_price) OVER (PARTITION BY category),2) AS diff
FROM products;

-- 3
SELECT * FROM (SELECT o.*, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts) rn
               FROM orders o WHERE status='completed') t WHERE rn=2;

-- 4
SELECT d, revenue, SUM(revenue) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING) AS cumulative
FROM daily_revenue;

-- 5  see 11.7

-- 6
SELECT order_id, customer_id, order_value,
       ROUND(100.0*order_value/SUM(order_value) OVER (PARTITION BY customer_id),1) AS pct
FROM order_values;

-- 7
SELECT customer_id, order_ts::date,
       order_ts::date - LAG(order_ts::date) OVER (PARTITION BY customer_id ORDER BY order_ts) AS gap
FROM orders WHERE status='completed';

-- 8
SELECT * FROM (SELECT e.*, DENSE_RANK() OVER (PARTITION BY department ORDER BY salary DESC) r
               FROM employees e) t WHERE r <= 2;

-- 9  see 11.7

-- 10
SELECT customer_id, order_ts, order_value,
       FIRST_VALUE(order_value) OVER w AS first_order_value,
       LAST_VALUE(order_value)  OVER (PARTITION BY customer_id ORDER BY order_ts
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
                                       AS last_order_value
FROM order_values WINDOW w AS (PARTITION BY customer_id ORDER BY order_ts);

-- 11
SELECT * FROM (SELECT product_id, revenue, NTILE(10) OVER (ORDER BY revenue DESC) d
               FROM product_revenue) t WHERE d = 1;

-- 12  see 11.7 percentage of total

-- 13
WITH seq AS (
  SELECT customer_id, order_id, order_ts, order_value,
         LAG(order_value) OVER (PARTITION BY customer_id ORDER BY order_ts) AS prev_value,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts DESC) AS rn_desc
  FROM order_values)
SELECT * FROM seq WHERE rn_desc=1 AND prev_value IS NOT NULL AND order_value < prev_value;

-- 14
WITH days AS (SELECT DISTINCT order_ts::date AS d FROM orders WHERE status='completed'),
     grp  AS (SELECT d, d - (ROW_NUMBER() OVER (ORDER BY d))::int AS g FROM days)
SELECT MIN(d) AS streak_start, MAX(d) AS streak_end, COUNT(*) AS days
FROM grp GROUP BY g ORDER BY days DESC LIMIT 1;

-- 15
SELECT order_id, customer_id, order_ts,
       COUNT(*) OVER (PARTITION BY customer_id ORDER BY order_ts
                      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_orders
FROM orders WHERE status='completed';
```

Exercise 15's frame — `UNBOUNDED PRECEDING AND 1 PRECEDING` — excludes the current row, which is exactly "how many came before". Being able to construct a frame like that on demand means you actually understand frames rather than having memorised three recipes.
