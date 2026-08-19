# Part 16a — 50 Beginner SQL Interview Questions

All questions use the schemas in `00-index-and-schema.md`. Sample data and expected outputs refer to the seed rows there, so load them if you want to check your answers by running them.

**Format.** Every question gives: problem, solution, line-by-line explanation, common mistakes, and a follow-up. Questions marked ★ get the full treatment including sample data, expected output, alternative solution and performance notes — those are the ones most likely to be asked verbatim, so work through them properly.

**Use it as drill material.** Cover the solution. Write your answer. Then compare. Reading solutions builds recognition, not recall, and interviews test recall.

---

### ★ 1. Select all customers from the UK

**Problem.** Return every customer based in the UK.

**Sample data.** 7 customers: 5 UK, 1 FR, 1 IE.

**Expected output.** 5 rows — Aisha, Tom, Priya, Jack, Nina.

**Solution.**
```sql
SELECT customer_id, first_name, last_name, city
FROM customers
WHERE country = 'UK';
```

**Explanation.** `SELECT` names the columns to return — listing them rather than `*` documents intent. `FROM customers` is the source. `WHERE country = 'UK'` keeps rows where the condition is true; string literals use single quotes.

**Alternative.** If the data isn't clean, `WHERE UPPER(TRIM(country)) = 'UK'` handles `'uk '` and `'Uk'`. Costs the index unless you have a functional index on that expression.

**Performance.** With an index on `country` and UK being a minority, an index scan. If most customers are UK, the planner correctly picks a sequential scan.

**Common mistakes.** Double quotes around `'UK'` — in Postgres double quotes mean an identifier, so `"UK"` is read as a column name and errors. Assuming case-insensitive matching.

**Follow-up.** *"What if country is sometimes 'United Kingdom'?"* → Normalise with a CASE or a mapping table, and note that this belongs upstream in the pipeline, not in every analyst's query.

---

### 2. Count the total number of orders

```sql
SELECT COUNT(*) AS total_orders FROM orders;
```
**Explanation.** `COUNT(*)` counts rows including those with NULLs in any column. Output: 10.
**Mistake.** `COUNT(discount_code)` would return 3 — it counts non-NULL values only.
**Follow-up.** *"Now count only completed orders."* → add `WHERE status='completed'`.

---

### 3. List products priced over £30

```sql
SELECT product_name, unit_price FROM products
WHERE unit_price > 30 ORDER BY unit_price DESC;
```
**Explanation.** Numeric comparison, no quotes on the number. ORDER BY DESC puts the most expensive first.
**Follow-up.** *"Include only active products."* → `AND is_active` — booleans need no `= true`.

---

### 4. Find the 3 most expensive products

```sql
SELECT product_name, unit_price FROM products
ORDER BY unit_price DESC LIMIT 3;
```
**Mistake.** `LIMIT 3` without `ORDER BY` returns three arbitrary rows.
**Follow-up.** *"What if two products tie for third?"* → LIMIT cuts arbitrarily; use `DENSE_RANK() <= 3` to include ties.

---

### 5. List the distinct order statuses

```sql
SELECT DISTINCT status FROM orders;
```
**Follow-up.** *"With a count of each."* → `SELECT status, COUNT(*) FROM orders GROUP BY status;` — and note that GROUP BY is usually better than DISTINCT because you get the counts for free.

---

### 6. Customers who signed up in 2023

```sql
SELECT * FROM customers
WHERE signup_date >= DATE '2023-01-01' AND signup_date < DATE '2024-01-01';
```
**Explanation.** Half-open range. Safe whether the column is `date` or `timestamp`.
**Mistake.** `BETWEEN '2023-01-01' AND '2023-12-31'` — correct for a `date` column, silently loses 31 December on a `timestamp` column. Build the habit now.
**Follow-up.** *"Use EXTRACT instead."* → `WHERE EXTRACT(YEAR FROM signup_date)=2023` — works, but wraps the column in a function and blocks index use.

---

### 7. Customers with no email

```sql
SELECT * FROM customers WHERE email IS NULL;
```
**Mistake.** `WHERE email = NULL` returns zero rows always — comparison with NULL yields UNKNOWN, never true.
**Follow-up.** *"Also catch blank strings."* → `WHERE email IS NULL OR TRIM(email)=''`.

---

### 8. Orders sorted by date, newest first

```sql
SELECT order_id, customer_id, order_ts FROM orders ORDER BY order_ts DESC;
```
**Follow-up.** *"Break ties consistently."* → add `, order_id DESC`. Without a tie-breaker the order of tied rows isn't guaranteed between runs.

---

### 9. Count customers per country

```sql
SELECT country, COUNT(*) AS customers FROM customers GROUP BY country ORDER BY customers DESC;
```
**Explanation.** GROUP BY collapses rows into one per distinct country. Any non-aggregated SELECT column must be in the GROUP BY.
**Mistake.** Selecting `city` without grouping by it → error in Postgres.
**Follow-up.** *"What happens to customers with a NULL country?"* → They form their own group, shown as an empty/NULL row. Use `COALESCE(country,'Unknown')` for a readable label.

---

### ★ 10. Total revenue from completed orders

**Problem.** Total revenue, where revenue is quantity × price less discount, counting only completed orders.

**Expected output.** One row, one number.

**Solution.**
```sql
SELECT ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)), 2) AS total_revenue
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
WHERE o.status = 'completed';
```

**Explanation.** Revenue lives on the line, so `order_items` drives. The join to `orders` exists solely to reach `status`. Multiplication happens per row, then SUM aggregates. ROUND to pennies for presentation.

**Alternative.** `WHERE oi.order_id IN (SELECT order_id FROM orders WHERE status='completed')` — same result, and a fine answer; the join is more conventional and lets you add more order-level filters easily.

**Performance.** Needs an index on `order_items.order_id` (the FK) for the join, and ideally on `orders.status` if completed orders are a minority.

**Common mistakes.** Using `orders` alone — it has no monetary column at all. Forgetting the status filter and including cancelled and refunded orders. Forgetting the discount. Using `SUM(quantity) * AVG(unit_price)`, which is wrong whenever prices differ.

**Follow-up.** *"Break it down by month."* → add `DATE_TRUNC('month', o.order_ts)::date` to SELECT and GROUP BY.

---

### 11. Average product price

```sql
SELECT ROUND(AVG(unit_price), 2) AS avg_price FROM products;
```
**Follow-up.** *"By category."* → `SELECT category, ROUND(AVG(unit_price),2) FROM products GROUP BY category;`

---

### 12. Cheapest and most expensive product in one row

```sql
SELECT MIN(unit_price) AS cheapest, MAX(unit_price) AS dearest FROM products;
```
**Follow-up.** *"Now show their names."* → MIN/MAX give the values, not the rows. You need `ORDER BY ... LIMIT 1`, `DISTINCT ON`, or `ROW_NUMBER`. This is the greatest-per-group problem (12.2).

---

### 13. Orders placed in March 2024

```sql
SELECT * FROM orders
WHERE order_ts >= DATE '2024-03-01' AND order_ts < DATE '2024-04-01';
```

---

### 14. Products in Electronics or Home

```sql
SELECT * FROM products WHERE category IN ('Electronics','Home');
```
**Follow-up.** *"Everything except those."* → `NOT IN` here is safe only because `category` has no NULLs in the list; if the column itself is NULL for a row, that row is excluded from both. Use `WHERE category IS NULL OR category NOT IN (...)` if NULLs should be kept.

---

### 15. Customers whose surname starts with 'K'

```sql
SELECT * FROM customers WHERE last_name LIKE 'K%';
```
**Follow-up.** *"Case-insensitively."* → `ILIKE 'k%'` in Postgres; `LOWER(last_name) LIKE 'k%'` portably.

---

### 16. Order count by status

```sql
SELECT status, COUNT(*) AS orders FROM orders GROUP BY status ORDER BY orders DESC;
```

---

### 17. Customers who have placed at least one order

```sql
SELECT DISTINCT c.customer_id, c.first_name, c.last_name
FROM customers c JOIN orders o ON o.customer_id = c.customer_id;
```
**Better.**
```sql
SELECT * FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id);
```
**Explanation.** The join version needs DISTINCT because a customer with 3 orders appears 3 times. EXISTS can't duplicate rows, so no DISTINCT and no sort.
**Follow-up.** *"Which is faster?"* → Usually EXISTS: it short-circuits at the first match and avoids the deduplication.

---

### ★ 18. Customers who have never placed an order

**Problem.** List customers with no orders at all.

**Expected output.** Any customer_id absent from `orders`.

**Solution.**
```sql
SELECT c.customer_id, c.first_name, c.last_name
FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id);
```

**Explanation.** `NOT EXISTS` returns true when the correlated subquery finds nothing. The correlation `o.customer_id = c.customer_id` links it to the current outer row.

**Alternatives.**
```sql
-- anti-join
SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id=c.customer_id
WHERE o.order_id IS NULL;

-- NOT IN, only safe with the null guard
SELECT * FROM customers
WHERE customer_id NOT IN (SELECT customer_id FROM orders WHERE customer_id IS NOT NULL);
```

**Performance.** NOT EXISTS and the LEFT JOIN anti-join usually produce the same plan (a hash anti-join). NOT IN can be worse because the planner can't use an anti-join when NULLs are possible.

**Common mistakes.** Plain `NOT IN` without the NULL guard — returns **zero rows** if any `customer_id` in `orders` is NULL, silently. Testing `IS NULL` on a nullable column of the right table instead of its primary key.

**Follow-up.** *"Explain the NOT IN trap."* → `x NOT IN (1,2,NULL)` expands to `x<>1 AND x<>2 AND x<>NULL`; the last is UNKNOWN so the whole AND can never be true. This is one of the two or three most-asked SQL interview questions anywhere.

---

### 19. Number of orders per customer

```sql
SELECT customer_id, COUNT(*) AS orders FROM orders GROUP BY customer_id ORDER BY orders DESC;
```
**Follow-up.** *"Include customers with zero."* → LEFT JOIN from `customers` and `COUNT(o.order_id)`, not `COUNT(*)`.

---

### 20. Customers with more than one order

```sql
SELECT customer_id, COUNT(*) AS orders
FROM orders GROUP BY customer_id HAVING COUNT(*) > 1;
```
**Mistake.** `WHERE COUNT(*) > 1` — aggregates aren't allowed in WHERE, which runs before grouping.
**Follow-up.** *"WHERE vs HAVING?"* → WHERE filters rows before grouping; HAVING filters groups after.

---

### 21. Each order with its customer's name

```sql
SELECT o.order_id, o.order_ts, c.first_name || ' ' || c.last_name AS customer
FROM orders o JOIN customers c ON c.customer_id = o.customer_id;
```
**Mistake.** `||` returns NULL if either name is NULL. Use `CONCAT_WS(' ', first_name, last_name)` when they're nullable.

---

### 22. Order lines with product names

```sql
SELECT oi.order_id, p.product_name, oi.quantity, oi.unit_price
FROM order_items oi JOIN products p ON p.product_id = oi.product_id;
```

---

### 23. Total quantity sold per product

```sql
SELECT p.product_name, SUM(oi.quantity) AS units_sold
FROM order_items oi JOIN products p USING (product_id)
GROUP BY p.product_name ORDER BY units_sold DESC;
```
**Follow-up.** *"Only completed orders."* → join `orders` and filter status. Without it you're counting cancelled orders as sales.

---

### 24. Products never ordered

```sql
SELECT p.* FROM products p
WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id);
```

---

### 25. Orders with no discount code

```sql
SELECT * FROM orders WHERE discount_code IS NULL;
```

---

### 26. Customers in Leeds or Manchester

```sql
SELECT * FROM customers WHERE city IN ('Leeds','Manchester');
```

---

### 27. Products between £20 and £50

```sql
SELECT * FROM products WHERE unit_price BETWEEN 20 AND 50;
```
**Explanation.** BETWEEN is inclusive at both ends. Safe here — the column is numeric, not a timestamp.

---

### 28. Count distinct customers who have ordered

```sql
SELECT COUNT(DISTINCT customer_id) AS ordering_customers FROM orders;
```
**Follow-up.** *"Why not COUNT(*)?"* → That counts orders, not customers. Distinct counts are the whole difference between "how much did we sell" and "how many people bought".

---

### 29. Full name and signup year

```sql
SELECT first_name || ' ' || last_name AS full_name,
       EXTRACT(YEAR FROM signup_date) AS signup_year
FROM customers;
```

---

### 30. ★ Average order value

**Problem.** Average total value of a completed order.

**Solution.**
```sql
WITH order_totals AS (
    SELECT o.order_id, SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS order_value
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed'
    GROUP BY o.order_id
)
SELECT ROUND(AVG(order_value), 2) AS average_order_value,
       COUNT(*) AS orders
FROM order_totals;
```

**Explanation.** Two-step by necessity. Step one aggregates lines to order grain. Step two averages across orders. You cannot nest aggregates (`AVG(SUM(x))` is illegal outside a window context), so the CTE is doing structural work, not just cosmetics.

**Alternative.** `SELECT SUM(line_value)/COUNT(DISTINCT order_id) FROM ...` in one pass — mathematically identical, arguably harder to read, but a legitimate answer worth mentioning.

**Common mistakes.** `AVG(quantity*unit_price)` on the joined table gives average *line* value — a different, smaller number. This is the single most common seeded error in AOV questions.

**Follow-up.** *"Report the median too."* → `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_value)`. Order values are skewed; the mean alone misleads.

---

### 31. Orders in the last 30 days

```sql
SELECT * FROM orders WHERE order_ts >= CURRENT_DATE - INTERVAL '30 days';
```
**Follow-up.** *"Why might this be a problem in a saved report?"* → It's relative to today, so re-running it later gives different numbers and you can't reconcile against last week's output. Parameterise the as-at date.

---

### 32. Employees and their managers

```sql
SELECT e.full_name AS employee, m.full_name AS manager
FROM employees e LEFT JOIN employees m ON m.employee_id = e.manager_id;
```
**Mistake.** INNER JOIN drops the CEO (NULL `manager_id`).

---

### 33. Departments with more than 5 employees

```sql
SELECT department, COUNT(*) AS headcount
FROM employees GROUP BY department HAVING COUNT(*) > 5;
```

---

### 34. Highest-paid employee per department

```sql
SELECT DISTINCT ON (department) department, full_name, salary
FROM employees ORDER BY department, salary DESC, employee_id;
```
**Portable version.**
```sql
SELECT * FROM (
  SELECT e.*, ROW_NUMBER() OVER (PARTITION BY department ORDER BY salary DESC, employee_id) rn
  FROM employees e) t WHERE rn = 1;
```

---

### 35. Customers by signup date, most recent first, top 5

```sql
SELECT * FROM customers ORDER BY signup_date DESC, customer_id DESC LIMIT 5;
```

---

### 36. Products with 'Wireless' in the name

```sql
SELECT * FROM products WHERE product_name ILIKE '%wireless%';
```
**Note.** The leading wildcard prevents index use. Fine on a small products table; on millions of rows you'd want a trigram index or full-text search.

---

### 37. Total shipping cost collected

```sql
SELECT ROUND(SUM(shipping_cost),2) FROM orders WHERE status='completed';
```
**Mistake.** Joining `order_items` first — shipping is order-level and would be counted once per line.

---

### 38. Orders per month in 2024

```sql
SELECT DATE_TRUNC('month', order_ts)::date AS month, COUNT(*) AS orders
FROM orders
WHERE order_ts >= DATE '2024-01-01' AND order_ts < DATE '2025-01-01'
GROUP BY 1 ORDER BY 1;
```
**Follow-up.** *"Why DATE_TRUNC and not EXTRACT(MONTH)?"* → EXTRACT would merge March 2023 and March 2024 into one row.

---

### 39. Customers who opted into marketing

```sql
SELECT * FROM customers WHERE marketing_opt_in;
```
**Follow-up.** *"What about NULLs?"* → Excluded, same as false. If NULL means "not yet asked", use `IS NOT FALSE` or handle it explicitly.

---

### 40. Number of products per category

```sql
SELECT category, COUNT(*) AS products FROM products GROUP BY category ORDER BY products DESC;
```

---

### 41. First and last order date overall

```sql
SELECT MIN(order_ts)::date AS first_order, MAX(order_ts)::date AS last_order FROM orders;
```

---

### 42. Line value for each order item

```sql
SELECT order_item_id, order_id, quantity, unit_price, discount_pct,
       ROUND(quantity * unit_price * (1 - discount_pct), 2) AS line_value
FROM order_items;
```
**Mistake.** `WHERE line_value > 50` fails — the alias doesn't exist at WHERE time. Repeat the expression or wrap in a subquery.

---

### 43. Orders not placed via the web

```sql
SELECT * FROM orders WHERE channel <> 'web';
```
**Follow-up.** *"What if channel can be NULL?"* → Those rows are excluded. Use `IS DISTINCT FROM 'web'` to include them.

---

### 44. Products by category then price

```sql
SELECT category, product_name, unit_price
FROM products ORDER BY category ASC, unit_price DESC;
```

---

### 45. Count patients by sex, handling missing values

```sql
SELECT COALESCE(NULLIF(TRIM(sex),''), 'Not recorded') AS sex, COUNT(*)
FROM patients GROUP BY 1 ORDER BY 2 DESC;
```

---

### 46. Referrals made in the last 90 days

```sql
SELECT * FROM referrals WHERE referral_date >= CURRENT_DATE - INTERVAL '90 days';
```

---

### 47. Appointments that were not attended

```sql
SELECT * FROM appointments WHERE outcome = 'DNA';
```
**Follow-up.** *"Is 'not attended' the same as DNA?"* → No. Cancellations by the patient or the provider are also non-attendances but are reported separately, and lumping them together inflates the DNA rate. Ask before you compute.

---

### 48. Patients still on the waiting list

```sql
SELECT * FROM waiting_list WHERE removed_date IS NULL;
```

---

### 49. A&E attendances lasting over four hours

```sql
SELECT * FROM ae_attendances
WHERE departure_ts IS NOT NULL
  AND departure_ts - arrival_ts > INTERVAL '4 hours';
```
**Explanation.** The `IS NOT NULL` guard is optional for correctness (a NULL comparison is UNKNOWN and excluded anyway) but stating it makes the intent explicit and forces you to think about the still-present patients.
**Follow-up.** *"What about patients still in the department who've already been there 6 hours?"* → They've breached but aren't counted. Use `COALESCE(departure_ts, CURRENT_TIMESTAMP)`.

---

### ★ 50. Revenue by product category

**Problem.** Total revenue by category, completed orders only, highest first.

**Expected output.** One row per category with a rounded revenue figure.

**Solution.**
```sql
SELECT p.category,
       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)), 2) AS revenue,
       COUNT(DISTINCT o.order_id) AS orders,
       SUM(oi.quantity) AS units
FROM order_items oi
JOIN products p ON p.product_id = oi.product_id
JOIN orders   o ON o.order_id   = oi.order_id
WHERE o.status = 'completed'
GROUP BY p.category
ORDER BY revenue DESC;
```

**Explanation.** Three tables: lines carry the money and quantity, products carry the category, orders carry the status. `COUNT(DISTINCT o.order_id)` because one order can contribute several lines within a category. Grouping happens after all joins and the WHERE filter.

**Alternative.** Add `ROUND(100.0*SUM(...)/SUM(SUM(...)) OVER (),1)` for share of total — a natural extension the interviewer may ask for next, so have it ready.

**Performance.** Indexes on `order_items.product_id`, `order_items.order_id`, and `orders.status` if completed is selective. Three-way hash join then a hash aggregate.

**Common mistakes.** `COUNT(*)` for orders (counts lines). Omitting the status filter. Omitting the discount. Joining products to orders directly — there is no relationship between them; the path runs through `order_items`.

**Follow-up.** *"Which category has the best margin?"* → Bring in `p.unit_cost` and compute gross profit and margin percentage — see Part 13.2, including the caveat that `unit_cost` is current cost rather than cost at time of sale.

---

## Self-check

You should be able to write questions 1–50 unaided in under three minutes each. If any of these still make you hesitate, that's your revision list:

- WHERE vs HAVING (20)
- COUNT(*) vs COUNT(col) (2, 19)
- NOT IN with NULLs (18)
- LEFT JOIN then COUNT (19, 32)
- Grain and fan-out (10, 37, 50)
- Alias visibility in WHERE (42)
- Half-open date ranges (6, 13, 38)
