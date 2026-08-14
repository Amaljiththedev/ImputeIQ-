# Parts 1–5: Fundamentals, Filtering, Aggregation, Joins, CASE

---

# PART 1 — SQL FUNDAMENTALS

## 1.1 What SQL is

SQL is a declarative language for asking a relational database for a set of rows. Declarative means you describe the result you want, not the steps to compute it. You write "give me completed orders from March grouped by customer"; the database's query planner decides whether to scan the table, use an index, hash the join or sort-merge it.

That has a practical consequence for interviews. When an interviewer asks "how would you make this faster?", they are asking what you can do to make the planner's job easier — filter earlier, avoid functions on indexed columns, reduce the rows entering a join. You are never optimising by rewriting loops, because there are no loops.

SQL is also **set-based**. A query operates on whole sets of rows at once, not row by row. Analysts coming from Excel tend to think one row at a time and reach for correlated subqueries where a window function or join is the natural tool. Breaking that habit is most of what Parts 9–11 are about.

**Real analyst use case.** Ninety percent of an analyst's SQL is: pull a filtered slice of transactional data, aggregate it to a business grain (customer, month, region), and hand it to a dashboard or a stakeholder.

**Interview question.** *"What does it mean that SQL is declarative, and why does it matter to you as an analyst?"* — Answer: you specify the what, the planner chooses the how; it matters because performance work is about giving the planner better options (indexes, selective filters, sensible join order) rather than micro-managing execution.

## 1.2 Relational databases

A relational database stores data as a collection of tables (relations) linked by shared key values, with the engine enforcing rules about those links. The point of the model is that each fact is stored once, in the table where it belongs, and assembled at query time by joining.

Customer name lives in `customers`, once. If it lived on every order row, changing a surname would mean updating thousands of rows and risking half of them disagreeing. That is the entire argument for normalisation (Part 15).

**Common mistake.** Assuming the database is one big flat table because that's how the CSV export looks. Always ask for, or inspect, the schema before writing a query. In an interview, asking "can I confirm the grain of this table — one row per what?" is a strong opening move.

**Interview question.** *"Why is data split across multiple tables rather than stored in one wide table?"* — Avoid duplication, keep updates consistent, enforce integrity with foreign keys, and let each table have a single clear grain. Then note the counter-case: analytical warehouses deliberately denormalise into star schemas because read performance and simplicity beat update efficiency when nothing is being updated.

## 1.3 Tables, rows, columns, and grain

- A **table** is a set of rows with a fixed set of typed columns.
- A **row** (tuple, record) is one instance of the thing the table describes.
- A **column** (field, attribute) is one property, with one data type, the same for every row.
- The **grain** is the answer to "one row per what?" — `orders` is one row per order; `order_items` is one row per product line within an order.

Grain is the single most useful concept in this handbook. Nearly every wrong analytical answer comes from computing a metric at the wrong grain.

```sql
-- grain: one row per order
SELECT order_id, customer_id, order_ts FROM orders;

-- grain: one row per order line
SELECT order_item_id, order_id, product_id, quantity FROM order_items;
```

**Real analyst use case.** Before writing anything, establish grain:

```sql
SELECT COUNT(*) AS rows, COUNT(DISTINCT order_id) AS orders FROM order_items;
```

If those two numbers differ, the table is not one row per order, and `SUM(shipping_cost)` after joining to it will double-count.

**Common mistake.** Summing an order-level column (`shipping_cost`) after joining to `order_items`. Shipping gets counted once per line, so a 3-line order contributes 3× its shipping.

**Interview question.** *"You join orders to order_items and total revenue looks right but total shipping cost has tripled. What happened?"* — The join changed the grain from one row per order to one row per line; order-level measures must be aggregated at order grain before or separately from line-level measures.

## 1.4 Primary keys

A primary key uniquely identifies a row. It cannot be NULL and cannot repeat. It may be a single column (`customer_id`) or several together (a composite key).

```sql
CREATE TABLE customers (
    customer_id integer PRIMARY KEY,
    ...
);

-- composite: one row per customer per month
CREATE TABLE customer_monthly_summary (
    customer_id integer,
    month_start date,
    order_count integer,
    PRIMARY KEY (customer_id, month_start)
);
```

A **surrogate key** is a meaningless generated id (`customer_id serial`). A **natural key** is a real-world identifier (`nhs_number`, `email`). Warehouses prefer surrogate keys because natural keys change — people change email addresses and surnames, NHS numbers get corrected — and a key that changes breaks every reference to it.

**Real analyst use case.** Checking whether a table you have been given actually has the key someone claims:

```sql
SELECT customer_id, COUNT(*)
FROM customers
GROUP BY customer_id
HAVING COUNT(*) > 1;
```

Zero rows means the key holds. On an extract from a source system rather than a real table, it often doesn't.

**Common mistake.** Trusting that a column called `id` is unique in an extract, staging table, or CSV. Verify.

**Interview question.** *"Difference between a primary key and a unique constraint?"* — Both enforce uniqueness; a primary key additionally forbids NULL, there is only one per table, and it is the row's canonical identity. A unique column can be nullable, and in Postgres multiple NULLs are permitted in a unique column because NULLs are not equal to each other.

## 1.5 Foreign keys and referential integrity

A foreign key is a column whose values must exist as a primary key in another table. `orders.customer_id` references `customers.customer_id`, so an order cannot reference a customer who does not exist.

```sql
CREATE TABLE orders (
    order_id integer PRIMARY KEY,
    customer_id integer REFERENCES customers(customer_id),
    ...
);
```

Foreign keys can be NULL, which means "no relationship" — `employees.manager_id` is NULL for the CEO, `web_events.customer_id` is NULL for anonymous visitors. That distinction (no relationship vs unknown relationship) matters when you're deciding between an INNER and a LEFT JOIN.

**Real analyst use case.** Orphan detection in a warehouse where FKs were never enforced:

```sql
SELECT o.order_id, o.customer_id
FROM orders o
LEFT JOIN customers c ON c.customer_id = o.customer_id
WHERE c.customer_id IS NULL;
```

Any rows returned are orders pointing at customers that don't exist. In a properly constrained OLTP database this is impossible; in a warehouse fed by nightly loads it happens constantly, usually because the dimension load ran before the fact load.

**Common mistake.** Assuming referential integrity holds in an analytics warehouse. It usually doesn't. Run the orphan check before you promise a stakeholder that an inner join loses nothing.

**Interview question.** *"You inner-join fact to dimension and row count drops by 3%. What do you check?"* — Orphan foreign keys (late-arriving or missing dimension rows), NULL join keys, type mismatches between the key columns, and trailing whitespace or case differences if the key is text.

## 1.6 Relationships

**One-to-one.** Each row in A matches at most one row in B. Rare; usually a table split for security or sparsity — `patients` and `patient_sensitive_details`. Joining does not change row count.

**One-to-many.** One customer, many orders. This is the common case. Joining from the "one" side to the "many" side multiplies the one-side rows.

**Many-to-many.** Orders and products: an order has many products, a product appears in many orders. Relational databases cannot represent this directly, so a junction (bridge) table sits between them — that is exactly what `order_items` is. The junction table typically carries its own attributes (`quantity`, `unit_price` at time of sale), which is why it is a real table and not just plumbing.

```
customers ──1:M──> orders ──1:M──> order_items <──M:1── products
```

Reading that diagram tells you the answer to most join questions before you write anything. Going left to right, row counts multiply. `customers` joined all the way to `order_items` gives one row per customer per order line.

**Interview question.** *"How do you model a many-to-many relationship?"* — With a junction table holding a foreign key to each side, ideally with a composite primary key across both, plus any attributes specific to the pairing.

## 1.7 NULL

NULL is not zero, not an empty string, and not "false". It means *unknown or not applicable*. This gets its own full treatment in Part 6 because it accounts for a large share of interview traps, but three rules to hold from the start:

1. Any comparison with NULL yields NULL, not true or false. `NULL = NULL` is NULL. Use `IS NULL`.
2. WHERE keeps only rows where the condition is **true**. NULL is not true, so rows with NULL conditions are dropped.
3. Aggregate functions ignore NULLs — except `COUNT(*)`.

```sql
SELECT NULL = NULL;        -- NULL, not true
SELECT NULL IS NULL;       -- true
SELECT 100 + NULL;         -- NULL: any arithmetic with NULL is NULL
SELECT COUNT(*), COUNT(email) FROM customers;  -- 7, 6 — Priya's email is NULL
```

**Interview question.** *"What's the difference between COUNT(\*) and COUNT(column)?"* — `COUNT(*)` counts rows; `COUNT(col)` counts rows where `col` is not NULL. Asked in some form in most junior interviews.

## 1.8 Data types

| Postgres type | Use for | Notes |
|---|---|---|
| `integer` / `bigint` | ids, counts | `bigint` past ~2.1 billion |
| `numeric(p,s)` | money | exact decimal; **use this for currency** |
| `real` / `double precision` | measurements, scientific | binary floating point, inexact |
| `text` / `varchar(n)` | strings | in Postgres `text` is not slower; length limits are validation, not performance |
| `boolean` | true/false/NULL | three-valued |
| `date` | calendar day | no time component |
| `timestamp` | date + time, no zone | "naive" |
| `timestamptz` | date + time, zone-aware | stores UTC, renders in session zone |
| `interval` | duration | `interval '4 hours'` |
| `jsonb` | semi-structured | indexable, common in event tables |

Two things that come up in real UK analyst work:

**Money must be `numeric`, never float.** `0.1 + 0.2 = 0.30000000000000004` in floating point. Finance will notice.

```sql
SELECT 0.1::double precision + 0.2::double precision;  -- 0.30000000000000004
SELECT 0.1::numeric + 0.2::numeric;                    -- 0.3
```

**`timestamp` vs `timestamptz` and British Summer Time.** UK data spans BST (UTC+1, late March to late October) and GMT (UTC). If your timestamps are naive `timestamp` in UTC and you group by day, summer events between 23:00 and 00:00 UK time land on the previous day. That quietly shifts daily figures for seven months of the year.

```sql
SELECT DATE_TRUNC('day', event_ts AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/London')
FROM web_events;
```

**Integer division** catches people out. In Postgres `integer / integer` truncates:

```sql
SELECT 7 / 2;              -- 3
SELECT 7.0 / 2;            -- 3.5
SELECT 7::numeric / 2;     -- 3.5
```

Conversion rate computed as `COUNT(purchases) / COUNT(sessions)` returns 0 for anything under 100%. Cast the numerator.

**Interview question.** *"Why store currency as numeric rather than float?"* — Floats are binary approximations of decimal fractions; repeated addition accumulates error and totals will not reconcile to the penny. `numeric` is exact decimal arithmetic.

## 1.9 SELECT and FROM

```sql
SELECT column_list
FROM table;
```

Column aliases with `AS`; double-quote them only if they need spaces or capitals. Postgres folds unquoted identifiers to lower case, so `SELECT x AS Revenue` gives you a column named `revenue`, while `AS "Revenue"` preserves the capital and then requires quoting forever after. Prefer `snake_case`.

```sql
SELECT
    first_name || ' ' || last_name AS customer_name,
    signup_date,
    country
FROM customers;
```

Table aliases keep multi-table queries readable. Use short meaningful ones (`o`, `oi`, `c`), and once you use an alias you must use it everywhere in that query.

**Common mistake.** `SELECT *` in production queries and saved views. It pulls columns you don't need, breaks when the upstream schema adds a column, makes the query's dependencies invisible to anyone reading it, and prevents index-only scans. Fine while exploring, wrong in anything anyone else will run.

**Interview question.** *"Why avoid SELECT \*?"* — Network and memory cost of unused columns, brittleness to schema change, loss of index-only scans, and it hides what the query actually depends on.

## 1.10 Logical order of evaluation

Written order and execution order differ, and this explains most "why can't I use my alias there?" confusion.

**Written:** SELECT → FROM → WHERE → GROUP BY → HAVING → ORDER BY → LIMIT

**Logically evaluated:**

```
1. FROM      (and JOINs)  -- build the working set
2. WHERE                  -- filter individual rows
3. GROUP BY               -- collapse into groups
4. HAVING                 -- filter groups
5. SELECT                 -- compute output expressions, assign aliases
6. DISTINCT
7. ORDER BY               -- aliases are now visible
8. LIMIT / OFFSET
```

Consequences you will be asked about:

- You cannot reference a SELECT alias in WHERE — WHERE runs before SELECT.
- You *can* reference a SELECT alias in ORDER BY and GROUP BY in Postgres, because those are resolved after (GROUP BY alias support is a Postgres extension, not standard).
- You cannot put an aggregate in WHERE, because groups don't exist yet. That's what HAVING is for.
- LIMIT applies last, so `LIMIT 10` after an aggregation gives 10 groups, not 10 rows of input.

```sql
-- fails: revenue does not exist yet at WHERE time
SELECT quantity * unit_price AS revenue
FROM order_items
WHERE revenue > 50;

-- works
SELECT quantity * unit_price AS revenue
FROM order_items
WHERE quantity * unit_price > 50;

-- also works, and is more readable at scale
SELECT * FROM (
    SELECT quantity * unit_price AS revenue FROM order_items
) t
WHERE revenue > 50;
```

**Interview question.** *"Why can I use an alias in ORDER BY but not WHERE?"* — This is the answer they want, in one sentence: WHERE is evaluated before SELECT so the alias doesn't exist yet; ORDER BY is evaluated after.

## 1.11 WHERE

Filters rows before grouping. Keeps rows where the condition evaluates to true — not false, and not NULL.

```sql
SELECT order_id, customer_id, order_ts
FROM orders
WHERE status = 'completed'
  AND order_ts >= DATE '2024-03-01'
  AND order_ts <  DATE '2024-04-01';
```

Note the half-open date range. `BETWEEN '2024-03-01' AND '2024-03-31'` on a *timestamp* column silently drops everything after midnight on the 31st, because `'2024-03-31'` is read as `2024-03-31 00:00:00`. That is a full day of data lost, and it is a genuinely common production bug. Half-open `>= start AND < next_start` is always right, for dates and timestamps alike.

**Common mistake.** Wrapping the filtered column in a function: `WHERE DATE(order_ts) = '2024-03-15'` cannot use an index on `order_ts`. Rewrite as a range: `WHERE order_ts >= '2024-03-15' AND order_ts < '2024-03-16'`.

## 1.12 ORDER BY

```sql
SELECT customer_id, order_ts
FROM orders
ORDER BY order_ts DESC, order_id ASC;
```

`ASC` is default. `NULLS FIRST`/`NULLS LAST` controls NULL placement — in Postgres, NULLs sort last for ASC and first for DESC by default, which is the opposite of some other engines and will silently change "top N" results.

```sql
SELECT product_name, unit_price
FROM products
ORDER BY unit_price DESC NULLS LAST;
```

**Dialect.** Ordering by position (`ORDER BY 2 DESC`) works widely but is fragile — inserting a column silently changes the sort. Fine in a scratch query, avoid in anything saved.

**Common mistake.** Assuming rows come back in a stable order without ORDER BY. There is no default order. A query that "always" returned data sorted will reorder the day the planner switches to a parallel scan.

## 1.13 LIMIT and OFFSET

```sql
SELECT product_name, unit_price
FROM products
ORDER BY unit_price DESC
LIMIT 3;

-- pagination: rows 11–20
SELECT ... ORDER BY order_ts DESC LIMIT 10 OFFSET 10;
```

`LIMIT` without `ORDER BY` returns an arbitrary 3 rows, not the top 3.

Ties are the interview point. `LIMIT 3` on prices 90, 90, 85, 85 gives you three rows arbitrarily, cutting a tie in half. If the question says "the top 3 most expensive products", ask whether ties should all be returned — and if so use `RANK() <= 3` (Part 11) rather than LIMIT.

**Dialect.** SQL Server uses `SELECT TOP 3 ...` or `OFFSET n ROWS FETCH NEXT m ROWS ONLY`. Oracle (12c+) uses `FETCH FIRST n ROWS ONLY`, which Postgres also supports. `LIMIT` is Postgres/MySQL/SQLite.

**Interview question.** *"How do you return the top 3 products by price including ties?"* — `DENSE_RANK() OVER (ORDER BY unit_price DESC) <= 3`; explain the difference between RANK and DENSE_RANK when you do.

## 1.14 DISTINCT

Removes duplicate rows across **all** selected columns, not just the first one.

```sql
SELECT DISTINCT country FROM customers;
SELECT DISTINCT country, city FROM customers;  -- distinct combinations
```

`DISTINCT ON` is a Postgres-specific tool worth knowing cold, because it answers "latest record per group" in three lines:

```sql
SELECT DISTINCT ON (customer_id)
       customer_id, order_id, order_ts
FROM orders
ORDER BY customer_id, order_ts DESC;
```

Keeps the first row per `customer_id` after sorting. The leading ORDER BY columns must match the DISTINCT ON columns. Faster than a window function for this task and a nice thing to know in a Postgres shop — but say "the portable version is ROW_NUMBER" in an interview, because it doesn't exist outside Postgres.

**Common mistake.** Reaching for `SELECT DISTINCT` to fix duplicate rows caused by a bad join. It hides the symptom and leaves the wrong join in place; the moment you add a column with genuinely varying values, the duplicates come back. Find the join causing the fan-out instead.

**Interview question.** *"Your query returns duplicates. Would you add DISTINCT?"* — Only after diagnosing the source. Duplicates are either genuine data duplication (fix with deduplication logic, Part 12) or join fan-out (fix the join grain). DISTINCT is a last resort and also expensive — it forces a sort or hash of the entire result.

---

# PART 2 — FILTERING AND LOGICAL OPERATIONS

## 2.1 Three-valued logic

SQL logic has three values: TRUE, FALSE, UNKNOWN. Any comparison involving NULL returns UNKNOWN. WHERE keeps a row only when the whole condition is TRUE.

**AND**

| | TRUE | FALSE | NULL |
|---|---|---|---|
| **TRUE** | TRUE | FALSE | NULL |
| **FALSE** | FALSE | FALSE | FALSE |
| **NULL** | NULL | FALSE | NULL |

**OR**

| | TRUE | FALSE | NULL |
|---|---|---|---|
| **TRUE** | TRUE | TRUE | TRUE |
| **FALSE** | TRUE | FALSE | NULL |
| **NULL** | TRUE | NULL | NULL |

**NOT**: NOT TRUE = FALSE, NOT FALSE = TRUE, **NOT NULL = NULL**.

Read the two shaded corners: `FALSE AND NULL` is FALSE (one false condemns the whole AND), but `TRUE OR NULL` is TRUE (one true saves the whole OR). Those are the short-circuits, and they're why some NULL-containing conditions still behave sensibly.

The killer consequence: a row where the condition is UNKNOWN is excluded from `WHERE cond` **and** from `WHERE NOT cond`. The two do not partition your data.

```sql
SELECT COUNT(*) FROM customers WHERE email = 'x@y.com';      -- excludes Priya (NULL email)
SELECT COUNT(*) FROM customers WHERE email <> 'x@y.com';     -- ALSO excludes Priya
-- Priya appears in neither. To include her:
SELECT COUNT(*) FROM customers WHERE email IS DISTINCT FROM 'x@y.com';
```

`IS DISTINCT FROM` is NULL-safe inequality — it treats NULL as a comparable value. `IS NOT DISTINCT FROM` is NULL-safe equality. Knowing these two operators is a genuine differentiator in a Postgres interview.

**Dialect.** MySQL's NULL-safe equality is `<=>`. SQL Server has no direct equivalent; you write `WHERE (a = b OR (a IS NULL AND b IS NULL))` or use `EXCEPT`/`INTERSECT`.

## 2.2 Comparison operators

| Operator | Meaning | Notes |
|---|---|---|
| `=` | equal | never true for NULL |
| `!=` or `<>` | not equal | `<>` is the standard; identical in Postgres |
| `>` `<` | greater / less | works on dates, timestamps, text (collation order) |
| `>=` `<=` | inclusive | |

Text comparison uses the database collation. In a typical UK Postgres install with `en_GB.UTF-8`, sorting is case-insensitive-ish for ordering purposes but `=` remains case-**sensitive**: `'UK' = 'uk'` is false. This is why country and status filters need normalising (Part 6).

```sql
SELECT * FROM orders WHERE shipping_cost > 0;
SELECT * FROM orders WHERE order_ts >= CURRENT_DATE - INTERVAL '30 days';
SELECT * FROM customers WHERE last_name >= 'M';   -- M to Z
```

## 2.3 AND, OR, NOT — and precedence

`NOT` binds tighter than `AND`, which binds tighter than `OR`. Missing parentheses around an OR is one of the most damaging silent bugs in analyst SQL, because the query runs and returns plausible numbers.

```sql
-- WRONG: reads as (country='UK' AND status='completed') OR (country='IE')
SELECT * FROM orders o
JOIN customers c USING (customer_id)
WHERE c.country = 'UK' AND o.status = 'completed'
   OR c.country = 'IE';
-- returns every Irish order including cancelled ones

-- RIGHT
WHERE (c.country = 'UK' OR c.country = 'IE')
  AND o.status = 'completed';
```

Rule for life: whenever a WHERE clause contains both AND and OR, parenthesise the OR. Reviewers should not have to remember precedence.

## 2.4 IN and NOT IN

```sql
SELECT * FROM orders WHERE status IN ('completed','refunded');
SELECT * FROM customers WHERE country NOT IN ('UK','IE');
```

`IN` is shorthand for a chain of ORs. `NOT IN` is shorthand for a chain of ANDs — and that is where it breaks.

**The NOT IN NULL trap.** This is asked constantly, at every level.

```sql
-- if ANY row in the subquery returns NULL customer_id, this returns ZERO rows
SELECT * FROM customers
WHERE customer_id NOT IN (SELECT customer_id FROM orders);
```

Why: `x NOT IN (1, 2, NULL)` expands to `x <> 1 AND x <> 2 AND x <> NULL`. The last term is UNKNOWN, so the whole AND is at best UNKNOWN, never TRUE. No row can qualify. And it fails *silently* — an empty result, no error.

Three fixes, best first:

```sql
-- 1. NOT EXISTS — NULL-safe by construction, and usually the fastest
SELECT * FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id);

-- 2. LEFT JOIN ... IS NULL (anti-join)
SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id = c.customer_id
WHERE o.customer_id IS NULL;

-- 3. NOT IN with the NULLs explicitly removed
SELECT * FROM customers
WHERE customer_id NOT IN (
    SELECT customer_id FROM orders WHERE customer_id IS NOT NULL
);
```

Say "I'd use NOT EXISTS because NOT IN returns no rows if the subquery contains a NULL" and you have demonstrably passed the mid-level filter.

## 2.5 BETWEEN

Inclusive on both ends: `x BETWEEN a AND b` is `x >= a AND x <= b`.

Perfectly safe on integers and `date` columns. Dangerous on `timestamp`:

```sql
-- silently loses everything on 31 March after 00:00:00
WHERE order_ts BETWEEN '2024-03-01' AND '2024-03-31'

-- correct
WHERE order_ts >= DATE '2024-03-01' AND order_ts < DATE '2024-04-01'
```

Make half-open ranges your default habit and the class of bug disappears — it also handles month lengths, leap years and future timestamp precision changes without thought.

## 2.6 LIKE and ILIKE

`LIKE` is case-sensitive pattern matching; `ILIKE` is the Postgres case-insensitive version. `%` matches any sequence of characters (including none), `_` matches exactly one.

```sql
WHERE email LIKE '%@gmail.com'      -- ends with
WHERE product_name ILIKE 'wireless%'-- starts with, any case
WHERE postcode_sector LIKE 'LS_ %'  -- LS1 , LS2 , ... single char then space
WHERE discount_code LIKE 'SPRING%'
```

To match a literal `%` or `_`, escape it: `LIKE '100!%' ESCAPE '!'`.

**Performance.** A leading wildcard (`'%gmail.com'`) cannot use a normal B-tree index; the database must scan every row. A trailing wildcard (`'wireless%'`) can use an index if the column's collation permits it (`text_pattern_ops` in Postgres). For serious text search, use full-text search (`tsvector`) or a trigram index (`pg_trgm`) — knowing that these exist is enough for an analyst interview.

**Dialect.** `ILIKE` is Postgres-only. Portable equivalent: `WHERE LOWER(col) LIKE LOWER('pattern')` — but note this disables plain index use unless you have a functional index on `LOWER(col)`.

## 2.7 IS NULL / IS NOT NULL

The only correct way to test for NULL.

```sql
SELECT * FROM appointments WHERE attended_ts IS NULL;   -- did not attend (yet)
SELECT * FROM waiting_list WHERE removed_date IS NULL;  -- still waiting
SELECT * FROM ae_attendances WHERE departure_ts IS NULL; -- still in department
```

That last pattern — NULL as an open-ended "still in progress" marker — is everywhere in service data, and it's why `AVG(departure_ts - arrival_ts)` quietly excludes exactly the longest-staying patients. Part 6 covers the consequences.

## 2.8 Progressive exercises

Solutions are at the end of this section. Attempt them before looking.

**Level 1**
1. All customers who signed up in 2023.
2. All products priced over £30 that are still active.
3. Orders that are not completed.
4. Customers with no email recorded.
5. Products in Electronics or Home.

**Level 2**
6. UK or Irish customers who opted into marketing.
7. Orders placed in March 2024 that were completed, with a discount code applied.
8. Products where the margin (`unit_price - unit_cost`) exceeds £20.
9. Customers whose email is not a gmail address — including those with no email at all.
10. Orders with shipping cost of exactly zero, excluding cancelled orders.

**Level 3**
11. Products where the markup is more than 150% of cost.
12. Customers who signed up in Q1 of any year.
13. A&E attendances that breached the four-hour standard, excluding those still in the department.
14. Two Week Wait referrals from A&E or GP made in the last 90 days.
15. Order lines with a discount applied where the discounted line value still exceeds £40.

**Level 4 (thinking required)**
16. Customers in the UK, or customers anywhere who came through the email channel — completed orders only. Write it so no reviewer could misread the precedence.
17. Customers who have never placed an order. Do it three different ways and say which you'd ship.
18. Products whose name contains a digit.
19. Patients whose recorded sex is anything other than 'F', including where it is missing.
20. Orders where the discount code is either absent or is not one of the known-valid codes ('SPRING10','WELCOME5').

### Solutions

```sql
-- 1
SELECT * FROM customers
WHERE signup_date >= DATE '2023-01-01' AND signup_date < DATE '2024-01-01';

-- 2
SELECT * FROM products WHERE unit_price > 30 AND is_active;

-- 3
SELECT * FROM orders WHERE status <> 'completed';   -- status is NOT NULL, so safe here

-- 4
SELECT * FROM customers WHERE email IS NULL;

-- 5
SELECT * FROM products WHERE category IN ('Electronics','Home');

-- 6
SELECT * FROM customers
WHERE country IN ('UK','IE') AND marketing_opt_in;

-- 7
SELECT * FROM orders
WHERE order_ts >= DATE '2024-03-01' AND order_ts < DATE '2024-04-01'
  AND status = 'completed'
  AND discount_code IS NOT NULL;

-- 8
SELECT product_name, unit_price - unit_cost AS margin
FROM products WHERE unit_price - unit_cost > 20;

-- 9  the "including NULLs" is the whole point
SELECT * FROM customers
WHERE email IS NULL OR email NOT LIKE '%@gmail.com';
-- or, more elegantly:
SELECT * FROM customers
WHERE COALESCE(email,'') NOT LIKE '%@gmail.com';

-- 10
SELECT * FROM orders WHERE shipping_cost = 0 AND status <> 'cancelled';

-- 11
SELECT product_name FROM products WHERE unit_price > unit_cost * 2.5;

-- 12
SELECT * FROM customers WHERE EXTRACT(MONTH FROM signup_date) BETWEEN 1 AND 3;

-- 13
SELECT * FROM ae_attendances
WHERE departure_ts IS NOT NULL
  AND departure_ts - arrival_ts > INTERVAL '4 hours';

-- 14
SELECT * FROM referrals
WHERE priority = 'Two Week Wait'
  AND source IN ('A&E','GP')
  AND referral_date >= CURRENT_DATE - INTERVAL '90 days';

-- 15
SELECT * FROM order_items
WHERE discount_pct > 0
  AND quantity * unit_price * (1 - discount_pct) > 40;

-- 16
SELECT o.*
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status = 'completed'
  AND (c.country = 'UK' OR c.channel = 'email');

-- 17  three ways; ship NOT EXISTS
SELECT c.* FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id);

SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id = c.customer_id
WHERE o.order_id IS NULL;

SELECT * FROM customers
WHERE customer_id NOT IN (SELECT customer_id FROM orders WHERE customer_id IS NOT NULL);

-- 18
SELECT product_name FROM products WHERE product_name ~ '[0-9]';

-- 19  NULL-safe inequality
SELECT * FROM patients WHERE sex IS DISTINCT FROM 'F';

-- 20
SELECT * FROM orders
WHERE discount_code IS NULL
   OR discount_code NOT IN ('SPRING10','WELCOME5');
```

---

# PART 3 — AGGREGATIONS

## 3.1 The aggregate functions

An aggregate collapses many rows into one value. **All aggregates except `COUNT(*)` ignore NULLs.** Internalise that; it drives every subtlety below.

| Function | Ignores NULL? | Returns on zero rows |
|---|---|---|
| `COUNT(*)` | no — counts rows | `0` |
| `COUNT(col)` | yes | `0` |
| `COUNT(DISTINCT col)` | yes | `0` |
| `SUM(col)` | yes | **NULL** |
| `AVG(col)` | yes | **NULL** |
| `MIN`/`MAX(col)` | yes | **NULL** |

`SUM` over no rows returning NULL rather than 0 is a real reporting bug: a month with no sales shows blank, not £0, and then any arithmetic on it becomes NULL. Wrap in `COALESCE(SUM(x), 0)` whenever the output goes to a dashboard.

### COUNT variants

```sql
SELECT
    COUNT(*)                    AS all_rows,       -- 7
    COUNT(email)                AS with_email,     -- 6
    COUNT(DISTINCT country)     AS countries,      -- 3
    COUNT(DISTINCT customer_id) AS customers       -- 7
FROM customers;
```

`COUNT(1)` and `COUNT(*)` are identical in Postgres — same plan, same speed. Anyone claiming otherwise is repeating folklore from a different engine and a different decade.

`COUNT(DISTINCT ...)` is expensive: it must deduplicate, which means sorting or hashing. On very large tables, approximate counting (`HyperLogLog` via the `postgresql-hll` extension, or `APPROX_COUNT_DISTINCT` in BigQuery/Snowflake) trades exactness for speed. Worth mentioning if asked about scale.

### AVG and the NULL-vs-zero distinction

This is the most important aggregation trap and it appears in interviews constantly.

```sql
-- suppose feedback_score is NULL for customers who never responded
SELECT AVG(feedback_score) FROM survey;
```

`AVG` divides by the count of **non-NULL** values. If half your respondents didn't answer, you get the average of those who did — which may be what you want, or may be badly wrong. If a non-response should count as zero:

```sql
SELECT AVG(COALESCE(feedback_score, 0)) FROM survey;
```

These give materially different numbers, and the correct choice is a business decision, not a technical one. In an interview: "Should non-responses be excluded or treated as zero?" is exactly the clarifying question they want to hear.

### SUM

```sql
SELECT SUM(quantity * unit_price * (1 - discount_pct)) AS gross_revenue
FROM order_items;
```

Note the calculation happens per row, then sums. `SUM(quantity) * AVG(unit_price)` is not the same thing and is wrong whenever prices vary — a classic seeded error.

### MIN / MAX

Work on numbers, dates, timestamps and text. On text they use collation order.

```sql
SELECT customer_id,
       MIN(order_ts) AS first_order,
       MAX(order_ts) AS latest_order
FROM orders
WHERE status = 'completed'
GROUP BY customer_id;
```

This is the cheapest way to get first/last **dates**. It does *not* give you the first/last **row** — for the product bought on the first order you need `DISTINCT ON` or `ROW_NUMBER` (Part 11), or the argmin trick:

```sql
-- product from each customer's earliest order, no window function
SELECT customer_id,
       (ARRAY_AGG(product_id ORDER BY order_ts))[1] AS first_product
FROM orders JOIN order_items USING (order_id)
GROUP BY customer_id;
```

## 3.2 GROUP BY

GROUP BY collapses rows into one row per distinct combination of the grouping columns.

```sql
SELECT
    c.country,
    COUNT(DISTINCT o.customer_id) AS customers,
    COUNT(*)                      AS orders,
    ROUND(AVG(o.shipping_cost), 2) AS avg_shipping
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status = 'completed'
GROUP BY c.country
ORDER BY orders DESC;
```

**The rule.** Every column in SELECT must either appear in GROUP BY or be inside an aggregate. Postgres enforces this and errors out. MySQL historically allowed it and returned an arbitrary value from the group — the source of countless silent errors, now disabled by default under `ONLY_FULL_GROUP_BY`.

The one exception in Postgres: if you group by a table's primary key, you may select any other column from that table, since the key functionally determines them.

```sql
-- legal in Postgres: customer_id is the PK of customers
SELECT c.customer_id, c.first_name, c.last_name, COUNT(o.order_id)
FROM customers c LEFT JOIN orders o USING (customer_id)
GROUP BY c.customer_id;
```

**GROUP BY with no rows in a group.** Groups that don't exist in the data don't appear in the output. A month with zero orders produces no row at all, not a zero. If a dashboard needs a continuous series, generate the calendar and LEFT JOIN to it:

```sql
SELECT d.month, COALESCE(COUNT(o.order_id), 0) AS orders
FROM generate_series(DATE '2024-01-01', DATE '2024-06-01', INTERVAL '1 month') AS d(month)
LEFT JOIN orders o
       ON DATE_TRUNC('month', o.order_ts) = d.month
      AND o.status = 'completed'
GROUP BY d.month
ORDER BY d.month;
```

Note the join condition, not a WHERE: putting `o.status='completed'` in WHERE would turn the LEFT JOIN back into an inner join and delete the empty months again. That mechanism is explained fully in Part 4.

**GROUPING SETS, ROLLUP, CUBE.** Multiple grouping levels in one pass — useful for subtotal rows.

```sql
SELECT c.country, p.category, SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_items oi
JOIN orders o   ON o.order_id = oi.order_id
JOIN customers c ON c.customer_id = o.customer_id
JOIN products p  ON p.product_id = oi.product_id
WHERE o.status = 'completed'
GROUP BY ROLLUP (c.country, p.category);
-- gives country+category, country subtotal, and grand total rows
```

Distinguish a subtotal NULL from a genuine data NULL with `GROUPING(c.country)`, which returns 1 for aggregated levels.

## 3.3 HAVING, and WHERE vs HAVING

WHERE filters rows before grouping. HAVING filters groups after aggregation. That is the entire distinction, and it follows directly from the evaluation order in 1.10.

```sql
SELECT customer_id, COUNT(*) AS completed_orders
FROM orders
WHERE status = 'completed'          -- row filter: happens first
GROUP BY customer_id
HAVING COUNT(*) >= 2;               -- group filter: happens after
```

- `WHERE COUNT(*) > 2` → error: aggregates aren't allowed in WHERE.
- Anything expressible in WHERE should be in WHERE, because it reduces rows before the (expensive) grouping. `HAVING country = 'UK'` works if country is grouped, but it filters later and does more work.

The classic exam question distils to: *"Find customers with more than 2 completed orders."* Both the status filter (WHERE, it's about individual orders) and the count filter (HAVING, it's about the group) are needed, and choosing correctly demonstrates you understand order of evaluation.

Compare these two — they answer different questions:

```sql
-- A: customers whose COMPLETED orders number 2+
SELECT customer_id FROM orders
WHERE status='completed' GROUP BY customer_id HAVING COUNT(*) >= 2;

-- B: customers with 2+ orders of any status, of which at least one completed
SELECT customer_id FROM orders
GROUP BY customer_id
HAVING COUNT(*) >= 2 AND COUNT(*) FILTER (WHERE status='completed') >= 1;
```

`FILTER (WHERE ...)` is the Postgres way to aggregate a subset — cleaner than `SUM(CASE WHEN ... THEN 1 ELSE 0 END)` and it works on any aggregate. Portable code needs the CASE form (Part 5).

## 3.4 Worked business examples

**Revenue by month, completed only.**

```sql
SELECT
    DATE_TRUNC('month', o.order_ts)::date AS month,
    COUNT(DISTINCT o.order_id)            AS orders,
    ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)), 2) AS revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY 1
ORDER BY 1;
```

`COUNT(DISTINCT o.order_id)` and not `COUNT(*)`: after the join, each order appears once per line.

**Average order value.** AOV is order revenue averaged across orders, so aggregate to order grain first.

```sql
WITH order_revenue AS (
    SELECT o.order_id,
           SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.order_id
    WHERE o.status = 'completed'
    GROUP BY o.order_id
)
SELECT ROUND(AVG(revenue), 2) AS aov FROM order_revenue;
```

Doing `AVG(oi.quantity * oi.unit_price)` on the joined table gives average *line* value, a different and usually much smaller number. Interviewers seed this deliberately.

**Employees: headcount and pay by department.**

```sql
SELECT department,
       COUNT(*)                     AS headcount,
       ROUND(AVG(salary), 0)        AS mean_salary,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) AS median_salary,
       MIN(hire_date)               AS longest_serving_hire
FROM employees
GROUP BY department
HAVING COUNT(*) >= 3
ORDER BY mean_salary DESC;
```

`PERCENTILE_CONT` is an ordered-set aggregate — the standard way to get a median in Postgres, and a good thing to have in your pocket, since salary and waiting-time distributions are skewed and the mean misleads.

**NHS: DNA rate by specialty.**

```sql
SELECT r.specialty,
       COUNT(*)                                                AS appointments,
       COUNT(*) FILTER (WHERE a.outcome = 'DNA')               AS dnas,
       ROUND(100.0 * COUNT(*) FILTER (WHERE a.outcome = 'DNA') / COUNT(*), 1) AS dna_rate_pct
FROM appointments a
JOIN referrals r ON r.referral_id = a.referral_id
WHERE a.scheduled_ts >= DATE '2024-01-01'
GROUP BY r.specialty
HAVING COUNT(*) >= 50
ORDER BY dna_rate_pct DESC;
```

Two things a strong candidate says unprompted: `100.0 *` forces numeric division (integer division would floor to 0), and the `HAVING COUNT(*) >= 50` suppresses tiny denominators where a 100% DNA rate means one missed appointment. Rate metrics on small denominators are how bad dashboards get built.

**A&E four-hour performance by site.**

```sql
SELECT site_code,
       COUNT(*) AS attendances,
       COUNT(*) FILTER (WHERE departure_ts - arrival_ts > INTERVAL '4 hours') AS breaches,
       ROUND(100.0 * COUNT(*) FILTER (WHERE departure_ts - arrival_ts <= INTERVAL '4 hours')
             / NULLIF(COUNT(*) FILTER (WHERE departure_ts IS NOT NULL), 0), 1) AS pct_within_4h
FROM ae_attendances
WHERE arrival_ts >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY site_code;
```

`NULLIF(x, 0)` prevents division by zero by turning a zero denominator into NULL, which propagates to a NULL result instead of an error. Standard defensive practice for any rate.

## 3.5 Aggregation exercises

1. Number of customers per country.
2. Total quantity sold per product.
3. Average unit price by category, two decimal places.
4. Categories with more than 2 products.
5. For each customer: order count, first order date, last order date — completed only.
6. Products never ordered. (Aggregation isn't the tool — say why.)
7. Monthly revenue with month-on-month order counts, 2024 only.
8. Customers whose total completed spend exceeds £100.
9. Share of orders by channel as a percentage of all orders.
10. Specialties where the DNA rate exceeds 10% on at least 100 appointments.

```sql
-- 1
SELECT country, COUNT(*) FROM customers GROUP BY country;

-- 2
SELECT p.product_name, SUM(oi.quantity) AS units
FROM order_items oi JOIN products p USING (product_id)
GROUP BY p.product_name ORDER BY units DESC;

-- 3
SELECT category, ROUND(AVG(unit_price),2) FROM products GROUP BY category;

-- 4
SELECT category, COUNT(*) FROM products GROUP BY category HAVING COUNT(*) > 2;

-- 5
SELECT customer_id, COUNT(*) AS orders, MIN(order_ts)::date, MAX(order_ts)::date
FROM orders WHERE status='completed' GROUP BY customer_id;

-- 6  aggregation can't find absence; you need an anti-join
SELECT p.product_id, p.product_name FROM products p
WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id);

-- 7
SELECT DATE_TRUNC('month', o.order_ts)::date AS month,
       COUNT(DISTINCT o.order_id) AS orders,
       ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),2) AS revenue
FROM orders o JOIN order_items oi USING (order_id)
WHERE o.status='completed' AND o.order_ts >= DATE '2024-01-01'
GROUP BY 1 ORDER BY 1;

-- 8
SELECT o.customer_id, ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),2) AS spend
FROM orders o JOIN order_items oi USING (order_id)
WHERE o.status='completed'
GROUP BY o.customer_id HAVING SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) > 100;

-- 9  window aggregate for the denominator, see Part 11
SELECT channel, COUNT(*) AS orders,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_total
FROM orders GROUP BY channel;

-- 10
SELECT r.specialty,
       ROUND(100.0*COUNT(*) FILTER (WHERE a.outcome='DNA')/COUNT(*),1) AS dna_rate
FROM appointments a JOIN referrals r USING (referral_id)
GROUP BY r.specialty
HAVING COUNT(*) >= 100
   AND 100.0*COUNT(*) FILTER (WHERE a.outcome='DNA')/COUNT(*) > 10;
```

Exercise 9 is worth staring at. `SUM(COUNT(*)) OVER ()` is an aggregate of an aggregate — the window runs *after* the GROUP BY, so `COUNT(*)` is already the per-channel count and `SUM(...) OVER ()` totals them across all groups. It replaces a self-join or a subquery, and being comfortable with it marks you out.

---

# PART 4 — JOINS

Joins decide whether your numbers are right. Interviewers know this, so joins get more airtime than any other topic.

## 4.1 Mental model

A join takes two sets of rows and produces a new set by matching them on a condition. Start from the conceptual cross product (every row of A paired with every row of B), keep the pairs where the ON condition is true, then — depending on the join type — add back unmatched rows from one or both sides with NULLs in the other side's columns.

```
INNER      matched pairs only
LEFT       matched pairs + unmatched LEFT rows  (right cols NULL)
RIGHT      matched pairs + unmatched RIGHT rows (left cols NULL)
FULL OUTER matched pairs + unmatched from both sides
CROSS      every pair, no condition
```

## 4.2 INNER JOIN

```sql
SELECT o.order_id, c.first_name, c.country, o.order_ts
FROM orders o
INNER JOIN customers c ON c.customer_id = o.customer_id;
```

`JOIN` alone means `INNER JOIN`. Rows without a match on either side vanish. That is fine when you want only matched data, and a silent data-loss bug when you assumed everything matches. If you inner-join and the row count drops, you have found either orphans or NULL keys — never shrug it off.

`USING (customer_id)` is shorthand when the column names are identical on both sides; it also collapses the two key columns into one in the output, which is handy with `SELECT *`.

```sql
SELECT * FROM orders JOIN customers USING (customer_id);
```

`NATURAL JOIN` joins on *all* identically named columns automatically. Never use it. `orders` and `customers` both have a `channel` column, so a natural join would match on `customer_id` AND `channel` and return near-nonsense. It's a good interview answer to explain exactly this: natural joins break invisibly when someone adds a column upstream.

## 4.3 LEFT JOIN

Keeps every row from the left table.

```sql
SELECT c.customer_id, c.first_name, COUNT(o.order_id) AS orders
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.first_name
ORDER BY orders;
```

`COUNT(o.order_id)` not `COUNT(*)`: for a customer with no orders, the joined row still exists (with NULLs on the right), so `COUNT(*)` returns 1 and you'd report that everyone has at least one order. `COUNT(o.order_id)` ignores the NULL and correctly returns 0. This is the single most common LEFT JOIN mistake and a favourite interview trap.

### The WHERE-vs-ON rule for outer joins

Put the condition in the wrong place and your LEFT JOIN silently becomes an INNER JOIN.

```sql
-- INTENDED: all customers, with their 2024 order count (0 if none)
-- BROKEN: the WHERE clause drops the NULL rows the LEFT JOIN just created
SELECT c.customer_id, COUNT(o.order_id)
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.customer_id
WHERE o.order_ts >= DATE '2024-01-01'     -- <-- NULL >= date is UNKNOWN, row dropped
GROUP BY c.customer_id;

-- CORRECT: filter the right table inside the ON clause
SELECT c.customer_id, COUNT(o.order_id)
FROM customers c
LEFT JOIN orders o
       ON o.customer_id = c.customer_id
      AND o.order_ts >= DATE '2024-01-01'
GROUP BY c.customer_id;
```

The rule: **conditions on the outer (preserved) table go in WHERE; conditions on the optional table go in ON.** Say that sentence in an interview and it lands.

The exception is deliberate: `WHERE right_table.key IS NULL` after a LEFT JOIN is the **anti-join**, used on purpose to find non-matches.

```sql
-- customers who have never ordered
SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id = c.customer_id
WHERE o.order_id IS NULL;
```

Use a column that is NOT NULL in the right table for the IS NULL test — ideally its primary key. Testing a nullable column can't distinguish "no match" from "matched, value was NULL".

## 4.4 RIGHT JOIN

The mirror of LEFT. Keeps all rows from the right table.

```sql
SELECT c.first_name, o.order_id
FROM orders o
RIGHT JOIN customers c ON c.customer_id = o.customer_id;
```

Functionally there is no reason to use it — every RIGHT JOIN is a LEFT JOIN with the tables swapped, and LEFT reads better because the preserved table is the one you already named in FROM. In a chain of four joins, a stray RIGHT JOIN in the middle is very hard to reason about. Know what it does, don't write it.

## 4.5 FULL OUTER JOIN

Keeps unmatched rows from both sides. Its genuine use case is reconciliation — comparing two sources that should agree.

```sql
-- reconciling a finance extract against the order table
SELECT
    COALESCE(o.order_id, f.order_id) AS order_id,
    o.total  AS system_total,
    f.total  AS finance_total,
    CASE WHEN o.order_id IS NULL THEN 'missing from system'
         WHEN f.order_id IS NULL THEN 'missing from finance'
         WHEN o.total <> f.total THEN 'value mismatch'
         ELSE 'ok' END AS reconciliation_status
FROM order_totals o
FULL OUTER JOIN finance_extract f ON f.order_id = o.order_id
WHERE o.order_id IS NULL OR f.order_id IS NULL OR o.total IS DISTINCT FROM f.total;
```

Note `COALESCE` on the key — with a full outer join either side's key can be NULL — and `IS DISTINCT FROM` for the comparison, so that a NULL on one side registers as a mismatch instead of being silently skipped.

## 4.6 CROSS JOIN

Every row of A with every row of B. No ON clause. Output is `rows(A) × rows(B)`.

Deliberate uses:

```sql
-- 1. Scaffolding: every product × every month, so gaps become explicit zeroes
SELECT p.product_id, m.month, COALESCE(SUM(oi.quantity), 0) AS units
FROM products p
CROSS JOIN generate_series(DATE '2024-01-01', DATE '2024-06-01', INTERVAL '1 month') AS m(month)
LEFT JOIN order_items oi ON oi.product_id = p.product_id
LEFT JOIN orders o ON o.order_id = oi.order_id
       AND DATE_TRUNC('month', o.order_ts) = m.month
       AND o.status = 'completed'
GROUP BY p.product_id, m.month;

-- 2. Attaching a single scalar to every row
SELECT c.customer_id, c.country, t.grand_total
FROM customers c
CROSS JOIN (SELECT SUM(shipping_cost) AS grand_total FROM orders) t;
```

Accidental cross joins — a missing or mistyped ON — are how a query that should return 10,000 rows returns 40 million and takes down the warehouse. If a query is inexplicably slow and huge, suspect a missing join condition first.

`LATERAL` is the correlated cousin: a subquery on the right that can reference columns from the left. It's the neat way to do "top 2 per group" without a window function:

```sql
SELECT c.customer_id, r.order_id, r.order_ts
FROM customers c
CROSS JOIN LATERAL (
    SELECT o.order_id, o.order_ts
    FROM orders o
    WHERE o.customer_id = c.customer_id AND o.status = 'completed'
    ORDER BY o.order_ts DESC
    LIMIT 2
) r;
```

Use `LEFT JOIN LATERAL (...) ON true` if you want to keep customers with no orders. LATERAL is often faster than a window function when you need a small N per group and there's an index on the correlation column.

## 4.7 SELF JOIN

A table joined to itself, with two aliases. The canonical case is a hierarchy.

```sql
SELECT e.full_name AS employee,
       m.full_name AS manager
FROM employees e
LEFT JOIN employees m ON m.employee_id = e.manager_id;
```

LEFT, not INNER — the CEO has a NULL `manager_id` and an inner join would delete them from the org chart. Interviewers seed exactly this.

Self joins also do sequence work (though window functions usually do it better):

```sql
-- pairs of employees in the same department earning within £1,000 of each other
SELECT a.full_name, b.full_name, a.salary, b.salary
FROM employees a
JOIN employees b
  ON a.department = b.department
 AND a.employee_id < b.employee_id           -- avoids self-pairs and mirror duplicates
 AND ABS(a.salary - b.salary) <= 1000;
```

The `a.employee_id < b.employee_id` condition is the idiom that turns every pair from appearing twice (A-B and B-A) into once. Expect to be asked why it's there.

## 4.8 Join keys, duplicates and join explosion

**Fan-out.** Joining a one-side to a many-side multiplies the one-side rows by the number of matches. That is correct behaviour, not a bug — but any measure from the one-side is now duplicated.

```sql
-- WRONG: shipping counted once per line
SELECT SUM(o.shipping_cost) FROM orders o JOIN order_items oi USING (order_id);

-- RIGHT: aggregate each grain separately, then combine
WITH line_rev AS (
    SELECT order_id, SUM(quantity * unit_price * (1 - discount_pct)) AS revenue
    FROM order_items GROUP BY order_id
)
SELECT SUM(l.revenue) AS revenue, SUM(o.shipping_cost) AS shipping
FROM orders o JOIN line_rev l USING (order_id)
WHERE o.status = 'completed';
```

The pattern — **aggregate to a common grain first, then join** — is the general answer to fan-out, and it is what a strong candidate reaches for automatically.

**Join explosion.** Joining two many-side tables to a common parent multiplies them by each other. An order with 3 items and 2 shipments produces 6 rows, and both quantities and shipment weights are now wrong.

```sql
-- 3 items × 2 shipments = 6 rows; both sums inflated
SELECT o.order_id, SUM(oi.quantity), SUM(s.weight_kg)
FROM orders o
JOIN order_items oi USING (order_id)
JOIN shipments   s  USING (order_id)
GROUP BY o.order_id;
```

Fix: pre-aggregate each branch to order grain, then join the summaries. This comes up in nearly every mid-level interview in some disguise.

**Duplicate keys.** If the "one" side isn't actually unique — a slowly-changing dimension with multiple versions per customer, say — every join against it doubles rows. Always check:

```sql
SELECT customer_id, COUNT(*) FROM dim_customer GROUP BY customer_id HAVING COUNT(*) > 1;
```

For an SCD Type 2 dimension you must join on the key *and* the validity window:

```sql
JOIN dim_customer d
  ON d.customer_id = o.customer_id
 AND o.order_ts >= d.valid_from
 AND o.order_ts <  COALESCE(d.valid_to, 'infinity')
```

**NULL keys never match.** A NULL join key matches nothing, including other NULLs — `web_events.customer_id` being NULL for anonymous sessions means those events disappear from any inner join to `customers`, which is usually correct, but you must know it's happening.

**Type mismatches.** Joining `varchar` to `integer` errors in Postgres (more permissive engines coerce silently and match nothing). Joining text keys with trailing whitespace or different case is worse — it runs and returns fewer rows than it should. `TRIM(LOWER(x))` on both sides diagnoses it; fixing it upstream is the real answer.

## 4.9 Progressive join exercises

**Level 1**
1. Every order with the customer's name and country.
2. Every customer with their order count, including customers who never ordered.
3. Order lines with product names and category.
4. Employees with their manager's name, keeping the CEO.
5. Products never ordered.

**Level 2**
6. Revenue per customer, including zero for those who never bought.
7. For each category, the number of distinct customers who bought from it.
8. Customers who bought Electronics but never Home.
9. Orders alongside the count of lines they contain.
10. Each customer's most recent completed order date and the channel of that order.

**Level 3**
11. Total revenue and total shipping cost by month, both correct. (Watch the grain.)
12. Products bought together: pairs of products appearing in the same order, ordered by frequency.
13. Employees earning more than their manager.
14. For each patient, their first referral and whether they were ever seen.
15. Customers whose only orders are cancelled or refunded.

**Level 4**
16. Month-by-month table of every category, showing zero for months a category sold nothing.
17. Customers who bought every product in the Electronics category. (Relational division.)
18. For each order, revenue, shipping, and item count — no double counting anywhere.
19. Referrals with no corresponding appointment after 18 weeks — the RTT breach list.
20. The second-most-recent order per customer.

### Solutions

```sql
-- 1
SELECT o.order_id, c.first_name || ' ' || c.last_name AS customer, c.country, o.order_ts
FROM orders o JOIN customers c USING (customer_id);

-- 2
SELECT c.customer_id, c.first_name, COUNT(o.order_id) AS orders
FROM customers c LEFT JOIN orders o USING (customer_id)
GROUP BY c.customer_id, c.first_name;

-- 3
SELECT oi.order_item_id, p.product_name, p.category, oi.quantity
FROM order_items oi JOIN products p USING (product_id);

-- 4
SELECT e.full_name AS employee, COALESCE(m.full_name,'(no manager)') AS manager
FROM employees e LEFT JOIN employees m ON m.employee_id = e.manager_id;

-- 5
SELECT p.* FROM products p
WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id);

-- 6
SELECT c.customer_id,
       COALESCE(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),0) AS revenue
FROM customers c
LEFT JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
LEFT JOIN order_items oi ON oi.order_id=o.order_id
GROUP BY c.customer_id;

-- 7
SELECT p.category, COUNT(DISTINCT o.customer_id) AS customers
FROM products p
JOIN order_items oi USING (product_id)
JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
GROUP BY p.category;

-- 8
SELECT DISTINCT o.customer_id
FROM orders o
JOIN order_items oi USING (order_id)
JOIN products p USING (product_id)
WHERE p.category='Electronics' AND o.status='completed'
  AND NOT EXISTS (
      SELECT 1 FROM orders o2
      JOIN order_items oi2 USING (order_id)
      JOIN products p2 USING (product_id)
      WHERE o2.customer_id=o.customer_id AND p2.category='Home' AND o2.status='completed'
  );

-- 9
SELECT o.order_id, o.order_ts, COUNT(oi.order_item_id) AS lines
FROM orders o LEFT JOIN order_items oi USING (order_id)
GROUP BY o.order_id, o.order_ts;

-- 10  DISTINCT ON is the Postgres shortcut
SELECT DISTINCT ON (customer_id) customer_id, order_ts::date AS last_order, channel
FROM orders WHERE status='completed'
ORDER BY customer_id, order_ts DESC;

-- 11  pre-aggregate to avoid fan-out
WITH line_rev AS (
    SELECT order_id, SUM(quantity*unit_price*(1-discount_pct)) AS revenue
    FROM order_items GROUP BY order_id
)
SELECT DATE_TRUNC('month',o.order_ts)::date AS month,
       ROUND(SUM(l.revenue),2) AS revenue,
       ROUND(SUM(o.shipping_cost),2) AS shipping
FROM orders o JOIN line_rev l USING (order_id)
WHERE o.status='completed'
GROUP BY 1 ORDER BY 1;

-- 12  self join on order_items with the < idiom
SELECT p1.product_name AS product_a, p2.product_name AS product_b, COUNT(*) AS times_together
FROM order_items a
JOIN order_items b ON b.order_id=a.order_id AND b.product_id > a.product_id
JOIN products p1 ON p1.product_id=a.product_id
JOIN products p2 ON p2.product_id=b.product_id
GROUP BY 1,2 ORDER BY times_together DESC;

-- 13
SELECT e.full_name, e.salary, m.full_name AS manager, m.salary AS manager_salary
FROM employees e JOIN employees m ON m.employee_id=e.manager_id
WHERE e.salary > m.salary;

-- 14
SELECT DISTINCT ON (r.patient_id)
       r.patient_id, r.referral_id, r.referral_date,
       (a.appointment_id IS NOT NULL) AS ever_seen
FROM referrals r
LEFT JOIN appointments a ON a.referral_id=r.referral_id AND a.outcome='Attended'
ORDER BY r.patient_id, r.referral_date, a.attended_ts;

-- 15
SELECT c.customer_id FROM customers c
JOIN orders o ON o.customer_id=c.customer_id
GROUP BY c.customer_id
HAVING COUNT(*) FILTER (WHERE o.status='completed') = 0;

-- 16
SELECT cat.category, m.month, COALESCE(SUM(oi.quantity*oi.unit_price),0) AS revenue
FROM (SELECT DISTINCT category FROM products) cat
CROSS JOIN generate_series(DATE '2024-01-01', DATE '2024-04-01', INTERVAL '1 month') m(month)
LEFT JOIN products p ON p.category=cat.category
LEFT JOIN order_items oi ON oi.product_id=p.product_id
LEFT JOIN orders o ON o.order_id=oi.order_id
      AND o.status='completed'
      AND DATE_TRUNC('month',o.order_ts)=m.month
GROUP BY 1,2 ORDER BY 1,2;

-- 17  relational division: count distinct matches = count of targets
SELECT o.customer_id
FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
WHERE p.category='Electronics' AND o.status='completed'
GROUP BY o.customer_id
HAVING COUNT(DISTINCT p.product_id) =
       (SELECT COUNT(*) FROM products WHERE category='Electronics');

-- 18
WITH li AS (
    SELECT order_id,
           SUM(quantity*unit_price*(1-discount_pct)) AS revenue,
           SUM(quantity) AS items
    FROM order_items GROUP BY order_id
)
SELECT o.order_id, o.order_ts, li.revenue, o.shipping_cost, li.items
FROM orders o LEFT JOIN li USING (order_id);

-- 19
SELECT r.referral_id, r.patient_id, r.specialty, r.referral_date,
       CURRENT_DATE - r.referral_date AS days_waiting
FROM referrals r
WHERE r.referral_date < CURRENT_DATE - INTERVAL '18 weeks'
  AND NOT EXISTS (
      SELECT 1 FROM appointments a
      WHERE a.referral_id=r.referral_id AND a.outcome='Attended'
  )
ORDER BY days_waiting DESC;

-- 20
SELECT customer_id, order_id, order_ts FROM (
    SELECT customer_id, order_id, order_ts,
           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts DESC) AS rn
    FROM orders WHERE status='completed'
) t WHERE rn = 2;
```

---

# PART 5 — CASE AND CONDITIONAL LOGIC

## 5.1 Syntax

```sql
CASE WHEN condition1 THEN result1
     WHEN condition2 THEN result2
     ELSE default
END
```

Conditions are evaluated **top to bottom, first match wins**. Later branches implicitly exclude earlier ones, which means you don't need `WHEN x >= 100 AND x < 500` if `x >= 500` was already handled above.

Omitting `ELSE` means unmatched rows get NULL. That is sometimes intentional and often a bug — always write an explicit ELSE, even if it's `ELSE 'Unknown'`, so the intent is visible.

All branches must return compatible types. Mixing `THEN 0` with `THEN 'none'` errors.

There's also a simple form for equality against one expression:

```sql
CASE status
     WHEN 'completed' THEN 'Revenue'
     WHEN 'refunded'  THEN 'Reversal'
     ELSE 'Excluded'
END
```

It cannot express ranges or NULL tests, so the searched form above is what you'll use 90% of the time. Note `CASE x WHEN NULL THEN ...` never matches, because it compiles to `x = NULL`; use the searched form with `WHEN x IS NULL`.

## 5.2 Customer segmentation

```sql
WITH customer_spend AS (
    SELECT o.customer_id,
           SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS lifetime_value,
           COUNT(DISTINCT o.order_id) AS orders,
           MAX(o.order_ts)::date AS last_order
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status = 'completed'
    GROUP BY o.customer_id
)
SELECT customer_id, lifetime_value, orders, last_order,
    CASE
        WHEN lifetime_value >= 1000 AND last_order >= CURRENT_DATE - INTERVAL '90 days'
             THEN 'VIP Active'
        WHEN lifetime_value >= 1000
             THEN 'VIP At Risk'
        WHEN orders >= 3
             THEN 'Loyal'
        WHEN orders = 1 AND last_order >= CURRENT_DATE - INTERVAL '30 days'
             THEN 'New'
        WHEN last_order < CURRENT_DATE - INTERVAL '365 days'
             THEN 'Churned'
        ELSE 'Occasional'
    END AS segment
FROM customer_spend;
```

Order matters enormously here. 'VIP At Risk' only catches high-value customers who failed the recency test above it. Rewriting the branches in a different order gives a different segmentation from identical logic — and interviewers test this by asking "what happens if I move this WHEN to the top?"

## 5.3 Revenue bands and age groups

```sql
SELECT order_id, order_value,
    CASE WHEN order_value <  25 THEN 'Under £25'
         WHEN order_value <  50 THEN '£25–49'
         WHEN order_value < 100 THEN '£50–99'
         WHEN order_value < 250 THEN '£100–249'
         ELSE '£250+'
    END AS value_band
FROM order_totals;
```

Ascending non-overlapping bands with only an upper bound per branch: because the first match wins, each `WHEN` implicitly starts where the previous ended. Cleaner and less error-prone than repeating both bounds — and it makes gaps impossible.

Band labels sort alphabetically, not numerically, which mangles dashboards ('£100–249' before '£25–49'). Emit a sort key alongside:

```sql
SELECT band, sort_order, COUNT(*)
FROM (
    SELECT CASE WHEN v < 25 THEN 'Under £25' WHEN v < 50 THEN '£25–49' ELSE '£50+' END AS band,
           CASE WHEN v < 25 THEN 1           WHEN v < 50 THEN 2        ELSE 3      END AS sort_order
    FROM order_totals
) t GROUP BY band, sort_order ORDER BY sort_order;
```

Age bands from a date of birth, NHS style:

```sql
SELECT patient_id,
       DATE_PART('year', AGE(CURRENT_DATE, date_of_birth))::int AS age,
       CASE WHEN date_of_birth IS NULL THEN 'Unknown'
            WHEN AGE(CURRENT_DATE, date_of_birth) < INTERVAL '18 years' THEN '0-17'
            WHEN AGE(CURRENT_DATE, date_of_birth) < INTERVAL '40 years' THEN '18-39'
            WHEN AGE(CURRENT_DATE, date_of_birth) < INTERVAL '65 years' THEN '40-64'
            WHEN AGE(CURRENT_DATE, date_of_birth) < INTERVAL '80 years' THEN '65-79'
            ELSE '80+'
       END AS age_band
FROM patients;
```

The NULL branch goes **first**. Put it last and NULL dates fall through every comparison (all UNKNOWN) into the ELSE, silently labelling patients with unknown DOB as '80+'. This is a genuinely common real-world data quality error, and it's a great answer when asked "what would you check in this query?".

## 5.4 Conditional aggregation

This is the highest-value CASE technique. `SUM(CASE WHEN ... THEN 1 ELSE 0 END)` counts a subset; nest it inside aggregates to pivot rows into columns.

```sql
SELECT
    DATE_TRUNC('month', order_ts)::date AS month,
    COUNT(*)                                                   AS all_orders,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)      AS completed,
    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END)      AS cancelled,
    SUM(CASE WHEN status = 'refunded'  THEN 1 ELSE 0 END)      AS refunded,
    ROUND(100.0 * SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) / COUNT(*), 1)
                                                               AS completion_rate_pct
FROM orders
GROUP BY 1 ORDER BY 1;
```

Two idioms with different behaviour:

- `SUM(CASE WHEN c THEN 1 ELSE 0 END)` — counts matches, returns 0 when none.
- `COUNT(CASE WHEN c THEN 1 END)` — same result, relying on COUNT ignoring the implicit NULL ELSE.

Postgres has the cleaner `FILTER` clause, which does the same thing and reads better:

```sql
COUNT(*) FILTER (WHERE status = 'completed')
SUM(revenue) FILTER (WHERE country = 'UK')
AVG(price) FILTER (WHERE category = 'Electronics')
```

Use `FILTER` in Postgres, know the CASE form because it's portable, and be able to say which is which.

**Pivoting revenue by category into columns:**

```sql
SELECT c.country,
    ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE p.category='Electronics'), 2) AS electronics,
    ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE p.category='Home'), 2)        AS home,
    ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE p.category='Apparel'), 2)     AS apparel,
    ROUND(SUM(oi.quantity*oi.unit_price), 2)                                          AS total
FROM orders o
JOIN order_items oi USING (order_id)
JOIN products p USING (product_id)
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status='completed'
GROUP BY c.country;
```

SQL cannot pivot on values it doesn't know at parse time — the category names have to be hardcoded. Dynamic pivots need application code, `crosstab()` from the `tablefunc` extension, or a BI tool. Saying that plainly is the right answer when an interviewer asks "what if a new category is added?".

## 5.5 CASE elsewhere in the query

**In ORDER BY** — custom sort orders:

```sql
ORDER BY CASE priority WHEN 'Two Week Wait' THEN 1
                       WHEN 'Urgent'        THEN 2
                       ELSE 3 END,
         referral_date;
```

**In WHERE** — usually a sign you should use plain boolean logic instead, but legitimate for parameterised filters:

```sql
WHERE CASE WHEN :include_cancelled THEN true ELSE status <> 'cancelled' END
```

**In GROUP BY** — group by a derived band. Repeat the whole expression, or reference the output position/alias (Postgres allows the alias):

```sql
SELECT CASE WHEN imd_decile <= 3 THEN 'Most deprived'
            WHEN imd_decile <= 7 THEN 'Mid'
            WHEN imd_decile IS NULL THEN 'Unknown'
            ELSE 'Least deprived' END AS deprivation_group,
       COUNT(*)
FROM patients
GROUP BY deprivation_group;
```

**In a JOIN condition** — legal, and usually slow, because it defeats index use. Prefer restructuring.

## 5.6 Nested CASE

Nesting is legal but hurts readability. Usually a compound condition in a flat CASE says the same thing more clearly.

```sql
-- nested
CASE WHEN country = 'UK'
     THEN CASE WHEN lifetime_value > 500 THEN 'UK High' ELSE 'UK Standard' END
     ELSE CASE WHEN lifetime_value > 500 THEN 'Intl High' ELSE 'Intl Standard' END
END

-- flat, preferred
CASE WHEN country='UK'  AND lifetime_value > 500 THEN 'UK High'
     WHEN country='UK'                            THEN 'UK Standard'
     WHEN lifetime_value > 500                    THEN 'Intl High'
     ELSE 'Intl Standard'
END
```

Nesting earns its place when the inner logic is genuinely a sub-decision reused across branches, or when the outer branches have very different inner structures. Otherwise flatten.

## 5.7 Risk, KPI and pass/fail classification

```sql
-- NHS: RTT position with a RAG rating
SELECT r.referral_id, r.specialty,
       CURRENT_DATE - r.referral_date AS days_waiting,
       CASE WHEN CURRENT_DATE - r.referral_date > 126 THEN 'Red'      -- >18 weeks
            WHEN CURRENT_DATE - r.referral_date >  84 THEN 'Amber'    -- >12 weeks
            ELSE 'Green' END AS rag_status,
       CASE WHEN r.priority = 'Two Week Wait'
                 AND CURRENT_DATE - r.referral_date > 14 THEN true
            ELSE false END AS twow_breach
FROM referrals r
JOIN waiting_list w ON w.referral_id = r.referral_id
WHERE w.removed_date IS NULL;                                          -- still waiting
```

```sql
-- Active / inactive / dormant customers
SELECT customer_id,
       CASE WHEN last_order_date IS NULL                              THEN 'Never purchased'
            WHEN last_order_date >= CURRENT_DATE - INTERVAL '90 days' THEN 'Active'
            WHEN last_order_date >= CURRENT_DATE - INTERVAL '365 days'THEN 'Lapsing'
            ELSE 'Dormant' END AS status
FROM customer_last_order;
```

```sql
-- SLA compliance, pass/fail per ticket then rolled up
SELECT team,
       COUNT(*) AS tickets,
       COUNT(*) FILTER (WHERE resolved_ts - created_ts <= sla_target) AS met,
       ROUND(100.0 * COUNT(*) FILTER (WHERE resolved_ts - created_ts <= sla_target)
             / NULLIF(COUNT(*) FILTER (WHERE resolved_ts IS NOT NULL), 0), 1) AS sla_pct
FROM tickets GROUP BY team;
```

Note the denominator excludes unresolved tickets. Whether that's right is a business question — an open ticket that's already blown its SLA arguably should count as a failure. Raise it; don't just pick one. Analysts who surface the definitional ambiguity rather than silently choosing get hired.

## 5.8 CASE exercises

1. Label products 'Budget' (<£25), 'Mid' (<£60), 'Premium' otherwise.
2. Count orders by status in a single row using conditional aggregation.
3. Flag customers as 'Opted in'/'Opted out', handling NULL.
4. Revenue split by channel across columns, by month.
5. Classify order margin per line as 'Loss','Thin','Healthy' (<0, <20%, else).
6. Bucket A&E attendances by wait time: under 2h, 2–4h, 4–12h, over 12h, still in department.
7. For each customer, columns for orders in 2023 and orders in 2024, plus a growth flag.
8. Assign a customer priority score combining recency, frequency and value into High/Medium/Low.

```sql
-- 1
SELECT product_name, unit_price,
       CASE WHEN unit_price < 25 THEN 'Budget'
            WHEN unit_price < 60 THEN 'Mid'
            ELSE 'Premium' END AS tier
FROM products;

-- 2
SELECT COUNT(*) FILTER (WHERE status='completed') AS completed,
       COUNT(*) FILTER (WHERE status='cancelled') AS cancelled,
       COUNT(*) FILTER (WHERE status='refunded')  AS refunded,
       COUNT(*) FILTER (WHERE status='pending')   AS pending
FROM orders;

-- 3
SELECT customer_id,
       CASE WHEN marketing_opt_in IS NULL THEN 'Unknown'
            WHEN marketing_opt_in THEN 'Opted in'
            ELSE 'Opted out' END AS marketing_status
FROM customers;

-- 4
SELECT DATE_TRUNC('month',o.order_ts)::date AS month,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE o.channel='web'),2)   AS web,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE o.channel='app'),2)   AS app,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE o.channel='phone'),2) AS phone
FROM orders o JOIN order_items oi USING (order_id)
WHERE o.status='completed' GROUP BY 1 ORDER BY 1;

-- 5
SELECT oi.order_item_id,
       CASE WHEN oi.unit_price*(1-oi.discount_pct) < p.unit_cost THEN 'Loss'
            WHEN (oi.unit_price*(1-oi.discount_pct) - p.unit_cost)
                 / NULLIF(oi.unit_price*(1-oi.discount_pct),0) < 0.20 THEN 'Thin'
            ELSE 'Healthy' END AS margin_band
FROM order_items oi JOIN products p USING (product_id);

-- 6
SELECT CASE WHEN departure_ts IS NULL THEN 'Still in department'
            WHEN departure_ts - arrival_ts < INTERVAL '2 hours'  THEN 'Under 2h'
            WHEN departure_ts - arrival_ts <= INTERVAL '4 hours' THEN '2-4h'
            WHEN departure_ts - arrival_ts <= INTERVAL '12 hours' THEN '4-12h'
            ELSE 'Over 12h' END AS wait_band,
       COUNT(*)
FROM ae_attendances GROUP BY 1;

-- 7
SELECT customer_id,
       COUNT(*) FILTER (WHERE order_ts >= '2023-01-01' AND order_ts < '2024-01-01') AS orders_2023,
       COUNT(*) FILTER (WHERE order_ts >= '2024-01-01' AND order_ts < '2025-01-01') AS orders_2024,
       CASE WHEN COUNT(*) FILTER (WHERE order_ts >= '2024-01-01') >
                 COUNT(*) FILTER (WHERE order_ts >= '2023-01-01' AND order_ts < '2024-01-01')
            THEN 'Growing' ELSE 'Flat or declining' END AS trend
FROM orders WHERE status='completed' GROUP BY customer_id;

-- 8  simple RFM
WITH rfm AS (
  SELECT o.customer_id,
         CURRENT_DATE - MAX(o.order_ts)::date AS recency_days,
         COUNT(DISTINCT o.order_id) AS frequency,
         SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS monetary
  FROM orders o JOIN order_items oi USING (order_id)
  WHERE o.status='completed' GROUP BY o.customer_id
)
SELECT customer_id, recency_days, frequency, monetary,
   CASE WHEN recency_days <= 90 AND frequency >= 3 AND monetary >= 200 THEN 'High'
        WHEN recency_days <= 180 AND (frequency >= 2 OR monetary >= 100) THEN 'Medium'
        ELSE 'Low' END AS priority
FROM rfm;
```
