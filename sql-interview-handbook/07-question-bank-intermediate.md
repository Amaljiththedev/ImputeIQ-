# Part 16b — 75 Intermediate SQL Interview Questions

Same schemas as before. These are the questions that decide most Data Analyst interviews — joins with grain traps, window functions, date logic, and metrics with ambiguous definitions.

★ = fuller treatment (sample data, expected output, alternatives, performance).

---

### ★ 1. Revenue per customer including customers who never bought

**Problem.** Every customer with their total completed revenue; zero if they never bought.

**Expected output.** All 7 customers. Customers 3 (refunded only), 5 (pending only) and 6 (cancelled only) show 0.00 — that's the point of the question.

**Solution.**
```sql
SELECT c.customer_id,
       c.first_name || ' ' || c.last_name AS customer,
       COALESCE(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)), 0) AS revenue
FROM customers c
LEFT JOIN orders o
       ON o.customer_id = c.customer_id
      AND o.status = 'completed'
LEFT JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY c.customer_id, c.first_name, c.last_name
ORDER BY revenue DESC;
```

**Explanation.** The status filter sits in the **ON clause**, not WHERE. In WHERE it would eliminate the NULL rows the LEFT JOIN created, converting it into an inner join and dropping customers 3, 5, 6 entirely. `COALESCE(SUM(...), 0)` turns the NULL sum for non-buyers into 0.

**Alternative.** Pre-aggregate then LEFT JOIN — often clearer and avoids double LEFT JOIN chains:
```sql
WITH rev AS (
  SELECT o.customer_id, SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
  FROM orders o JOIN order_items oi USING (order_id)
  WHERE o.status='completed' GROUP BY o.customer_id)
SELECT c.customer_id, COALESCE(r.revenue,0) AS revenue
FROM customers c LEFT JOIN rev r USING (customer_id);
```

**Performance.** The alternative is usually faster: it aggregates the large table first and joins a small result to a small table.

**Common mistakes.** Status filter in WHERE (the big one). `COUNT(*)` instead of `COUNT(o.order_id)` if counting orders. Forgetting COALESCE and shipping NULLs to a dashboard.

**Follow-up.** *"How would you tell 'never ordered' apart from 'ordered but nothing completed'?"* → Add `COUNT(o_all.order_id)` from a second LEFT JOIN without the status filter, or a boolean `EXISTS` flag.

---

### 2. Customers with more than 2 completed orders
```sql
SELECT customer_id, COUNT(*) AS completed_orders
FROM orders WHERE status='completed'
GROUP BY customer_id HAVING COUNT(*) > 2;
```
**Explanation.** Row filter in WHERE, group filter in HAVING. Both are needed and choosing correctly is the test.

---

### 3. Second-highest product price
```sql
SELECT MAX(unit_price) FROM products
WHERE unit_price < (SELECT MAX(unit_price) FROM products);
```
**Alternatives.** `ORDER BY unit_price DESC LIMIT 1 OFFSET 1`, or `DENSE_RANK() = 2`.
**Follow-up.** *"What if the top two prices are equal?"* → The subquery version and DENSE_RANK return the true second distinct price; OFFSET returns the duplicate top price. Say which the business wants.

---

### 4. Month-on-month revenue growth
```sql
WITH monthly AS (
  SELECT DATE_TRUNC('month',o.order_ts)::date AS month,
         SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
  FROM orders o JOIN order_items oi USING (order_id)
  WHERE o.status='completed' GROUP BY 1)
SELECT month, ROUND(revenue,2) AS revenue,
       ROUND(LAG(revenue) OVER (ORDER BY month),2) AS prev_month,
       ROUND(100.0*(revenue-LAG(revenue) OVER (ORDER BY month))
             /NULLIF(LAG(revenue) OVER (ORDER BY month),0),1) AS mom_pct
FROM monthly ORDER BY month;
```
**Mistake.** Missing months break LAG — it compares to the previous *row*, not the previous month. Zero-fill with `generate_series` when gaps are possible.

---

### 5. Top 3 products by revenue in each category
```sql
WITH pr AS (
  SELECT p.category, p.product_name,
         SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
  FROM order_items oi JOIN products p USING (product_id)
  JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
  GROUP BY 1,2)
SELECT * FROM (SELECT *, DENSE_RANK() OVER (PARTITION BY category ORDER BY revenue DESC) r
               FROM pr) t
WHERE r <= 3 ORDER BY category, r;
```
**Follow-up.** *"ROW_NUMBER or DENSE_RANK?"* → ROW_NUMBER gives exactly 3 and cuts ties arbitrarily; DENSE_RANK keeps all products at the top 3 revenue levels. Ask which is wanted.

---

### 6. Each customer's most recent order
```sql
SELECT DISTINCT ON (customer_id) customer_id, order_id, order_ts, channel
FROM orders WHERE status='completed'
ORDER BY customer_id, order_ts DESC, order_id DESC;
```

---

### 7. Running total of daily revenue
```sql
WITH daily AS (
  SELECT o.order_ts::date AS d, SUM(oi.quantity*oi.unit_price) AS revenue
  FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed' GROUP BY 1)
SELECT d, ROUND(revenue,2) AS revenue,
       ROUND(SUM(revenue) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING),2) AS cumulative
FROM daily ORDER BY d;
```

---

### 8. Customers who bought Electronics but never Home
```sql
SELECT DISTINCT o.customer_id FROM orders o
JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
WHERE p.category='Electronics' AND o.status='completed'
  AND NOT EXISTS (
    SELECT 1 FROM orders o2 JOIN order_items oi2 USING (order_id) JOIN products p2 USING (product_id)
    WHERE o2.customer_id=o.customer_id AND o2.status='completed' AND p2.category='Home');
```

---

### 9. Percentage of orders by channel
```sql
SELECT channel, COUNT(*) AS orders,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),1) AS pct
FROM orders GROUP BY channel ORDER BY orders DESC;
```
**Explanation.** `SUM(COUNT(*)) OVER ()` — the window runs after grouping, summing the group counts. Avoids a subquery entirely.

---

### 10. ★ Average order value by month with order count

**Solution.**
```sql
WITH order_totals AS (
    SELECT o.order_id,
           DATE_TRUNC('month', o.order_ts)::date AS month,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS order_value
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed'
    GROUP BY o.order_id, 2
)
SELECT month,
       COUNT(*) AS orders,
       ROUND(AVG(order_value),2) AS aov,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_value)::numeric,2) AS median,
       ROUND(SUM(order_value),2) AS revenue
FROM order_totals GROUP BY month ORDER BY month;
```
**Explanation.** Aggregate to order grain first, then to month. The month must be in the first GROUP BY so it survives to the second stage.
**Performance.** One scan of the join, two hash aggregates. Fine to tens of millions of rows.
**Mistake.** Averaging line values. Also: `AVG` of already-averaged values (averaging monthly AOVs to get a yearly AOV) is wrong unless the months have equal order counts — a genuinely common reporting error.
**Follow-up.** *"AOV rose but revenue fell — explain."* → Fewer, larger orders. Decompose: revenue = orders × AOV, and check which factor moved.

---

### 11. Customers whose spend is above average
```sql
WITH spend AS (
  SELECT o.customer_id, SUM(oi.quantity*oi.unit_price) AS total
  FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
  GROUP BY o.customer_id)
SELECT * FROM spend WHERE total > (SELECT AVG(total) FROM spend) ORDER BY total DESC;
```

---

### 12. Days between each customer's consecutive orders
```sql
SELECT customer_id, order_ts::date AS order_date,
       order_ts::date - LAG(order_ts::date) OVER (PARTITION BY customer_id ORDER BY order_ts) AS days_since_prev
FROM orders WHERE status='completed' ORDER BY customer_id, order_ts;
```

---

### 13. Products bought together most often
```sql
SELECT p1.product_name AS a, p2.product_name AS b, COUNT(*) AS times
FROM order_items i1
JOIN order_items i2 ON i2.order_id=i1.order_id AND i2.product_id > i1.product_id
JOIN products p1 ON p1.product_id=i1.product_id
JOIN products p2 ON p2.product_id=i2.product_id
GROUP BY 1,2 ORDER BY times DESC LIMIT 10;
```
**Explanation.** `>` on product_id prevents self-pairs and stops each pair appearing twice.

---

### 14. Revenue and shipping by month, both correct
```sql
WITH li AS (SELECT order_id, SUM(quantity*unit_price*(1-discount_pct)) AS revenue
            FROM order_items GROUP BY order_id)
SELECT DATE_TRUNC('month',o.order_ts)::date AS month,
       ROUND(SUM(li.revenue),2) AS revenue, ROUND(SUM(o.shipping_cost),2) AS shipping
FROM orders o JOIN li USING (order_id) WHERE o.status='completed'
GROUP BY 1 ORDER BY 1;
```
**Explanation.** The grain fix. Joining `order_items` directly would multiply shipping by the line count.

---

### 15. Customers who ordered in consecutive months
```sql
WITH m AS (SELECT DISTINCT customer_id, DATE_TRUNC('month',order_ts)::date AS month
           FROM orders WHERE status='completed')
SELECT DISTINCT customer_id FROM (
  SELECT customer_id, month, LAG(month) OVER (PARTITION BY customer_id ORDER BY month) AS prev
  FROM m) t
WHERE month - INTERVAL '1 month' = prev;
```

---

### 16. Each order's value as a share of its customer's total
```sql
SELECT order_id, customer_id, ROUND(order_value,2) AS order_value,
       ROUND(100.0*order_value/SUM(order_value) OVER (PARTITION BY customer_id),1) AS pct_of_customer
FROM order_values;
```

---

### 17. Rank customers by spend within their country
```sql
WITH spend AS (
  SELECT c.customer_id, c.country, SUM(oi.quantity*oi.unit_price) AS total
  FROM customers c JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
  JOIN order_items oi USING (order_id) GROUP BY 1,2)
SELECT *, RANK() OVER (PARTITION BY country ORDER BY total DESC) AS country_rank,
          RANK() OVER (ORDER BY total DESC) AS overall_rank
FROM spend;
```

---

### 18. 7-day moving average of orders
```sql
WITH d AS (
  SELECT g::date AS day, COUNT(o.order_id) AS orders
  FROM generate_series(CURRENT_DATE-89, CURRENT_DATE, INTERVAL '1 day') g
  LEFT JOIN orders o ON o.order_ts::date=g::date AND o.status='completed'
  GROUP BY 1)
SELECT day, orders,
       ROUND(AVG(orders) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),1) AS ma7
FROM d ORDER BY day;
```
**Explanation.** The generate_series zero-fill is load-bearing — without it, `ROWS 6 PRECEDING` reaches back further than seven calendar days.

---

### 19. Customers whose latest order was smaller than their previous one
```sql
WITH seq AS (
  SELECT customer_id, order_id, order_value, order_ts,
         LAG(order_value) OVER (PARTITION BY customer_id ORDER BY order_ts) AS prev,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts DESC) AS rn
  FROM order_values)
SELECT customer_id, order_value, prev FROM seq
WHERE rn=1 AND prev IS NOT NULL AND order_value < prev;
```

---

### 20. Monthly new vs returning customers
```sql
WITH first_order AS (
  SELECT customer_id, DATE_TRUNC('month',MIN(order_ts))::date AS first_month
  FROM orders WHERE status='completed' GROUP BY customer_id),
activity AS (
  SELECT DISTINCT customer_id, DATE_TRUNC('month',order_ts)::date AS month
  FROM orders WHERE status='completed')
SELECT a.month,
       COUNT(*) FILTER (WHERE a.month = f.first_month) AS new_customers,
       COUNT(*) FILTER (WHERE a.month > f.first_month) AS returning_customers
FROM activity a JOIN first_order f USING (customer_id)
GROUP BY a.month ORDER BY a.month;
```

---

### ★ 21. Monthly retention rate

**Problem.** Of customers active in a month, what proportion are active the following month?

**Solution.**
```sql
WITH monthly_active AS (
    SELECT DISTINCT customer_id, DATE_TRUNC('month', order_ts)::date AS month
    FROM orders WHERE status = 'completed'
)
SELECT curr.month,
       COUNT(DISTINCT curr.customer_id) AS active,
       COUNT(DISTINCT nxt.customer_id)  AS retained,
       ROUND(100.0*COUNT(DISTINCT nxt.customer_id)
             / NULLIF(COUNT(DISTINCT curr.customer_id),0), 1) AS retention_pct
FROM monthly_active curr
LEFT JOIN monthly_active nxt
       ON nxt.customer_id = curr.customer_id
      AND nxt.month = curr.month + INTERVAL '1 month'
GROUP BY curr.month ORDER BY curr.month;
```

**Explanation.** Self-join offset by a month. `DISTINCT` in the CTE reduces multiple orders per month to one row. LEFT JOIN keeps non-returners in the denominator.

**Alternative.** `EXISTS` instead of the self-join, which avoids any risk of fan-out:
```sql
SELECT month, COUNT(*) AS active,
       COUNT(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM monthly_active n
         WHERE n.customer_id=m.customer_id AND n.month=m.month+INTERVAL '1 month')) AS retained
FROM monthly_active m GROUP BY month;
```

**Common mistakes.** INNER JOIN → always 100%. Forgetting the final month is structurally incomplete (no "next month" exists yet) and reporting it as 0% retention.

**Follow-up.** *"Why does the last month show 0%?"* → Censoring. Exclude incomplete periods from the output.

---

### 22. Cohort retention by first-purchase month
See Part 12.9 for the full query. Expect this as a whiteboard question; practise saying the three steps aloud before writing: assign cohort, list activity months, compute month offset.

---

### 23. Customers who spent more than £500 lifetime
```sql
SELECT o.customer_id, ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),2) AS ltv
FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
GROUP BY o.customer_id
HAVING SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) > 500;
```

---

### 24. Gross margin by category
```sql
SELECT p.category,
       ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),2) AS revenue,
       ROUND(SUM(oi.quantity*p.unit_cost),2) AS cogs,
       ROUND(100.0*SUM(oi.quantity*(oi.unit_price*(1-oi.discount_pct)-p.unit_cost))
             /NULLIF(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),0),1) AS margin_pct
FROM order_items oi JOIN products p USING (product_id)
JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
GROUP BY p.category ORDER BY margin_pct DESC;
```
**Follow-up.** *"Any concern with this?"* → `unit_cost` is current, `unit_price` is historic. Margins on old orders are computed against today's costs.

---

### 25. Products whose price is above their category average
```sql
SELECT * FROM (
  SELECT p.*, AVG(unit_price) OVER (PARTITION BY category) AS cat_avg FROM products p) t
WHERE unit_price > cat_avg;
```

---

### 26. Orders containing more than 2 distinct products
```sql
SELECT order_id, COUNT(DISTINCT product_id) AS products
FROM order_items GROUP BY order_id HAVING COUNT(DISTINCT product_id) > 2;
```

---

### 27. Employees earning more than their department average
```sql
SELECT * FROM (
  SELECT e.*, AVG(salary) OVER (PARTITION BY department) AS dept_avg FROM employees e) t
WHERE salary > dept_avg;
```

---

### 28. Employees earning more than their manager
```sql
SELECT e.full_name, e.salary, m.full_name AS manager, m.salary AS manager_salary
FROM employees e JOIN employees m ON m.employee_id=e.manager_id
WHERE e.salary > m.salary;
```

---

### 29. Duplicate customer records by email
```sql
SELECT LOWER(TRIM(email)) AS email, COUNT(*), ARRAY_AGG(customer_id) AS ids
FROM customers WHERE email IS NOT NULL
GROUP BY 1 HAVING COUNT(*) > 1;
```

---

### 30. ★ Deduplicate keeping the most recent record

**Problem.** A staging table has multiple rows per customer. Keep only the latest.

**Solution.**
```sql
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id
                                 ORDER BY updated_at DESC NULLS LAST, id DESC) AS rn
    FROM customers_staging
)
SELECT * FROM ranked WHERE rn = 1;
```

**Explanation.** PARTITION BY names the key that should be unique. The ORDER BY encodes the business rule for which copy wins. `NULLS LAST` stops a record with a missing timestamp winning. `id DESC` makes it deterministic.

**Alternatives.** `DISTINCT ON (customer_id)` in Postgres. `DELETE` where `rn > 1` to fix in place.

**Common mistakes.** `RANK` instead of `ROW_NUMBER` — ties keep all rows and you still have duplicates. No tie-breaker — non-reproducible output, which breaks pipelines subtly and is very hard to debug later.

**Follow-up.** *"What if duplicates hold complementary data?"* → Merge rather than dedupe: `GROUP BY customer_id` with `MAX(col) FILTER (WHERE col IS NOT NULL)` per column.

---

### 31. Customers by acquisition channel with conversion rate
```sql
SELECT c.channel,
       COUNT(*) AS customers,
       COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM orders o
                        WHERE o.customer_id=c.customer_id AND o.status='completed')) AS converted,
       ROUND(100.0*COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM orders o
             WHERE o.customer_id=c.customer_id AND o.status='completed'))/COUNT(*),1) AS conv_pct
FROM customers c GROUP BY c.channel ORDER BY conv_pct DESC;
```

---

### 32. Days from signup to first order
```sql
SELECT c.customer_id, c.signup_date, MIN(o.order_ts)::date AS first_order,
       MIN(o.order_ts)::date - c.signup_date AS days_to_activate
FROM customers c LEFT JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
GROUP BY c.customer_id, c.signup_date;
```

---

### 33. Revenue by day of week
```sql
SELECT TRIM(TO_CHAR(o.order_ts,'Day')) AS day_name, EXTRACT(ISODOW FROM o.order_ts) AS dow,
       ROUND(SUM(oi.quantity*oi.unit_price),2) AS revenue
FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
GROUP BY 1,2 ORDER BY 2;
```

---

### 34. Orders per customer distribution
```sql
SELECT orders_placed, COUNT(*) AS customers
FROM (SELECT customer_id, COUNT(*) AS orders_placed FROM orders
      WHERE status='completed' GROUP BY customer_id) t
GROUP BY orders_placed ORDER BY orders_placed;
```

---

### 35. Refund rate by category
```sql
SELECT p.category,
       COUNT(DISTINCT o.order_id) AS orders,
       COUNT(DISTINCT o.order_id) FILTER (WHERE o.status='refunded') AS refunded,
       ROUND(100.0*COUNT(DISTINCT o.order_id) FILTER (WHERE o.status='refunded')
             /NULLIF(COUNT(DISTINCT o.order_id),0),1) AS refund_rate_pct
FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
WHERE o.status IN ('completed','refunded')
GROUP BY p.category ORDER BY refund_rate_pct DESC;
```

---

### 36. Top customer in each country
```sql
SELECT DISTINCT ON (country) country, customer_id, total
FROM (SELECT c.country, c.customer_id, SUM(oi.quantity*oi.unit_price) AS total
      FROM customers c JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
      JOIN order_items oi USING (order_id) GROUP BY 1,2) t
ORDER BY country, total DESC, customer_id;
```

---

### 37. Cumulative revenue share by product (Pareto)
See Part 12.20. The key detail is the WHERE condition using the cumulative sum *excluding* the current row so the crossing row is included.

---

### 38. Customers active in 2023 but not 2024
```sql
SELECT customer_id FROM orders WHERE status='completed'
GROUP BY customer_id
HAVING COUNT(*) FILTER (WHERE order_ts >= '2023-01-01' AND order_ts < '2024-01-01') > 0
   AND COUNT(*) FILTER (WHERE order_ts >= '2024-01-01') = 0;
```

---

### 39. Average basket size (items per order)
```sql
SELECT ROUND(AVG(items),2) AS avg_items_per_order
FROM (SELECT o.order_id, SUM(oi.quantity) AS items
      FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
      GROUP BY o.order_id) t;
```

---

### 40. ★ Funnel conversion by step

**Problem.** Conversion from product view → add to cart → checkout → purchase, by session.

**Solution.**
```sql
WITH session_steps AS (
    SELECT session_id,
           MAX(CASE WHEN event_name='product_view'   THEN 1 ELSE 0 END) AS viewed,
           MAX(CASE WHEN event_name='add_to_cart'    THEN 1 ELSE 0 END) AS carted,
           MAX(CASE WHEN event_name='checkout_start' THEN 1 ELSE 0 END) AS checkout,
           MAX(CASE WHEN event_name='purchase'       THEN 1 ELSE 0 END) AS purchased
    FROM web_events
    WHERE event_ts >= CURRENT_DATE - 30
    GROUP BY session_id
)
SELECT SUM(viewed) AS viewed, SUM(carted) AS carted,
       SUM(checkout) AS checkout, SUM(purchased) AS purchased,
       ROUND(100.0*SUM(carted)/NULLIF(SUM(viewed),0),1)      AS view_to_cart_pct,
       ROUND(100.0*SUM(checkout)/NULLIF(SUM(carted),0),1)    AS cart_to_checkout_pct,
       ROUND(100.0*SUM(purchased)/NULLIF(SUM(checkout),0),1) AS checkout_to_purchase_pct,
       ROUND(100.0*SUM(purchased)/NULLIF(SUM(viewed),0),1)   AS overall_pct
FROM session_steps;
```

**Explanation.** `MAX(CASE ...)` collapses many events per session into a 0/1 flag per step. Summing flags counts sessions reaching each step. Step-to-step percentages find the drop-off; the overall percentage alone hides where the problem is.

**Alternative.** Postgres `FILTER`, or timestamp comparison for a strictly ordered funnel (12.12).

**Common mistakes.** `COUNT(*)` per event name without collapsing to session grain — a user viewing 10 products counts 10 times. Assuming the funnel is ordered when this query doesn't enforce order.

**Follow-up.** *"Split by device."* → Add `device` to both GROUP BYs. *"A user adds to cart on mobile and buys on desktop — what breaks?"* → Session-level funnels miss cross-device journeys; switch to customer grain with an attribution window.

---

### 41. Sessionise events with a 30-minute timeout
See Part 12.17.

---

### 42. Customers who bought in 3 consecutive months
See Part 12.18.

---

### 43. Longest streak of consecutive active days
See Part 12.4.

---

### 44. Revenue by UK financial year
```sql
SELECT EXTRACT(YEAR FROM o.order_ts - INTERVAL '3 months')::int AS fy_starting,
       ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),2) AS revenue
FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
GROUP BY 1 ORDER BY 1;
```

---

### 45. Year-on-year monthly comparison
```sql
WITH m AS (SELECT DATE_TRUNC('month',order_ts)::date AS month, COUNT(*) AS orders
           FROM orders WHERE status='completed' GROUP BY 1)
SELECT c.month, c.orders, p.orders AS last_year,
       ROUND(100.0*(c.orders-p.orders)/NULLIF(p.orders,0),1) AS yoy_pct
FROM m c LEFT JOIN m p ON p.month = c.month - INTERVAL '1 year' ORDER BY c.month;
```
**Follow-up.** *"Why join rather than LAG(12)?"* → LAG counts rows; a missing month shifts every subsequent comparison.

---

### 46. Fill in months with no sales
```sql
SELECT g::date AS month, COALESCE(ROUND(SUM(oi.quantity*oi.unit_price),2),0) AS revenue
FROM generate_series(DATE '2024-01-01', DATE '2024-12-01', INTERVAL '1 month') g
LEFT JOIN orders o ON DATE_TRUNC('month',o.order_ts)=g AND o.status='completed'
LEFT JOIN order_items oi ON oi.order_id=o.order_id
GROUP BY 1 ORDER BY 1;
```

---

### 47. Customers whose only orders were cancelled or refunded
```sql
SELECT customer_id FROM orders GROUP BY customer_id
HAVING COUNT(*) FILTER (WHERE status='completed') = 0;
```

---

### 48. Median order value
```sql
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_value) AS median FROM order_values;
```
**Follow-up.** *"Without PERCENTILE_CONT?"* → Rank rows and take the middle one(s):
```sql
SELECT AVG(order_value) FROM (
  SELECT order_value, ROW_NUMBER() OVER (ORDER BY order_value) rn, COUNT(*) OVER () n
  FROM order_values) t
WHERE rn IN ((n+1)/2, (n+2)/2);
```

---

### 49. Percentile bands of customer value
```sql
SELECT customer_id, lifetime_value,
       NTILE(10) OVER (ORDER BY lifetime_value DESC) AS decile,
       ROUND(100*PERCENT_RANK() OVER (ORDER BY lifetime_value DESC),1) AS pct_rank
FROM customer_ltv;
```

---

### 50. ★ Customers at risk of churn

**Problem.** Flag customers whose silence exceeds their own typical purchase gap.

**Solution.**
```sql
WITH gaps AS (
    SELECT customer_id, order_ts::date AS d,
           order_ts::date - LAG(order_ts::date) OVER (PARTITION BY customer_id ORDER BY order_ts) AS gap
    FROM orders WHERE status='completed'
),
cadence AS (
    SELECT customer_id, AVG(gap) AS avg_gap, COUNT(*)+1 AS orders, MAX(d) AS last_order
    FROM gaps WHERE gap IS NOT NULL GROUP BY customer_id
)
SELECT customer_id, orders, last_order, ROUND(avg_gap,0) AS typical_gap_days,
       CURRENT_DATE - last_order AS days_silent,
       ROUND((CURRENT_DATE - last_order)/NULLIF(avg_gap,0),1) AS gap_ratio,
       CASE WHEN CURRENT_DATE - last_order > 3*avg_gap THEN 'High risk'
            WHEN CURRENT_DATE - last_order > 2*avg_gap THEN 'Medium risk'
            ELSE 'Healthy' END AS risk
FROM cadence
WHERE CURRENT_DATE - last_order > 2*avg_gap
ORDER BY gap_ratio DESC;
```

**Explanation.** Each customer is compared to their own cadence rather than a global threshold — a weekly buyer silent for a month is in trouble; an annual buyer isn't. Customers with one order have no gap and are excluded; handle them as a separate "failed to activate" segment.

**Common mistakes.** A single global "no order in 90 days" rule, which misclassifies both frequent and infrequent buyers. Dividing by a possibly-zero average gap without NULLIF.

**Follow-up.** *"How would you validate this?"* → Backtest: compute risk flags as at six months ago and check whether flagged customers actually stopped buying. A churn model nobody has validated is a guess with a query attached.

---

### 51. Discount impact on margin
```sql
SELECT CASE WHEN oi.discount_pct = 0 THEN 'No discount'
            WHEN oi.discount_pct <= 0.10 THEN 'Up to 10%'
            ELSE 'Over 10%' END AS discount_band,
       COUNT(*) AS lines,
       ROUND(AVG(oi.unit_price*(1-oi.discount_pct) - p.unit_cost),2) AS avg_unit_margin,
       ROUND(SUM(oi.quantity*(oi.unit_price*(1-oi.discount_pct)-p.unit_cost)),2) AS total_profit
FROM order_items oi JOIN products p USING (product_id)
JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
GROUP BY 1;
```

---

### 52. Repeat purchase rate by cohort
```sql
SELECT DATE_TRUNC('month',first_order)::date AS cohort, COUNT(*) AS customers,
       ROUND(100.0*COUNT(*) FILTER (WHERE orders>=2)/COUNT(*),1) AS repeat_rate_pct
FROM (SELECT customer_id, COUNT(*) AS orders, MIN(order_ts)::date AS first_order
      FROM orders WHERE status='completed' GROUP BY customer_id) t
GROUP BY 1 ORDER BY 1;
```

---

### 53. Time to second purchase
```sql
WITH seq AS (SELECT customer_id, order_ts, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts) n
             FROM orders WHERE status='completed')
SELECT ROUND(AVG(b.order_ts::date - a.order_ts::date),1) AS mean_days,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.order_ts::date - a.order_ts::date) AS median_days
FROM seq a JOIN seq b ON b.customer_id=a.customer_id AND a.n=1 AND b.n=2;
```

---

### 54. First product each customer bought
```sql
SELECT DISTINCT ON (o.customer_id) o.customer_id, p.product_name, p.category, o.order_ts::date
FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
WHERE o.status='completed'
ORDER BY o.customer_id, o.order_ts, oi.order_item_id;
```

---

### 55. Which first-purchase category drives highest LTV
See Part 12.16.

---

### 56. Weekly active customers with week-on-week change
```sql
WITH w AS (SELECT DATE_TRUNC('week',order_ts)::date AS week,
                  COUNT(DISTINCT customer_id) AS active
           FROM orders WHERE status='completed' GROUP BY 1)
SELECT week, active, active - LAG(active) OVER (ORDER BY week) AS change,
       ROUND(100.0*(active-LAG(active) OVER (ORDER BY week))
             /NULLIF(LAG(active) OVER (ORDER BY week),0),1) AS wow_pct
FROM w ORDER BY week;
```

---

### 57. Category revenue pivoted by month
```sql
SELECT p.category,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE DATE_TRUNC('month',o.order_ts)='2024-01-01'),2) AS jan,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE DATE_TRUNC('month',o.order_ts)='2024-02-01'),2) AS feb,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (WHERE DATE_TRUNC('month',o.order_ts)='2024-03-01'),2) AS mar
FROM order_items oi JOIN products p USING (product_id)
JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
GROUP BY p.category;
```
**Follow-up.** *"What if a new month is added?"* → SQL can't pivot on values unknown at parse time. Use the BI tool, `crosstab()`, or dynamic SQL from application code.

---

### 58. Customers who bought every Electronics product
```sql
SELECT o.customer_id
FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
WHERE p.category='Electronics' AND o.status='completed'
GROUP BY o.customer_id
HAVING COUNT(DISTINCT p.product_id) = (SELECT COUNT(*) FROM products WHERE category='Electronics');
```
**Explanation.** Relational division. Count distinct matches per customer and compare to the total number of targets.

---

### 59. Orders with above-average line count
```sql
SELECT order_id, lines FROM (
  SELECT order_id, COUNT(*) AS lines FROM order_items GROUP BY order_id) t
WHERE lines > (SELECT AVG(cnt) FROM (SELECT COUNT(*) cnt FROM order_items GROUP BY order_id) x);
```

---

### 60. ★ A&E four-hour performance by site and month

**Problem.** Percentage of A&E attendances within four hours, by site and month.

**Solution.**
```sql
SELECT site_code,
       DATE_TRUNC('month', arrival_ts)::date AS month,
       COUNT(*) AS attendances,
       COUNT(*) FILTER (WHERE departure_ts IS NULL) AS still_present,
       COUNT(*) FILTER (WHERE departure_ts - arrival_ts <= INTERVAL '4 hours') AS within_4h,
       ROUND(100.0 * COUNT(*) FILTER (WHERE departure_ts - arrival_ts <= INTERVAL '4 hours')
             / NULLIF(COUNT(*) FILTER (WHERE departure_ts IS NOT NULL), 0), 1) AS pct_within_4h
FROM ae_attendances
GROUP BY site_code, 2
ORDER BY site_code, 2;
```

**Explanation.** The denominator counts only completed attendances, since a patient still present has no measurable total time. Reporting `still_present` separately makes that exclusion visible rather than hidden.

**Alternative (arguably more honest).** Count anyone already past four hours as a breach whether or not they've left:
```sql
COUNT(*) FILTER (WHERE COALESCE(departure_ts, CURRENT_TIMESTAMP) - arrival_ts > INTERVAL '4 hours')
```

**Common mistakes.** Including still-present patients in the denominator with no departure time — they fail the `<= 4 hours` test (NULL comparison is UNKNOWN) and silently depress the percentage. Using `BETWEEN` on the month boundary. Ignoring that a NULL departure might mean a data quality problem rather than a live patient.

**Follow-up.** *"Performance improved 3 points this month — what would you check before reporting it?"* → Whether attendance volume changed, whether the case mix (triage categories) shifted, whether more records have missing departure times, and whether it's within normal month-to-month variation. Three points on a noisy metric may be nothing.

---

### 61. DNA rate by specialty and deprivation decile
```sql
SELECT r.specialty,
       CASE WHEN p.imd_decile <= 3 THEN 'Most deprived'
            WHEN p.imd_decile <= 7 THEN 'Mid'
            WHEN p.imd_decile IS NULL THEN 'Unknown'
            ELSE 'Least deprived' END AS deprivation,
       COUNT(*) AS appointments,
       ROUND(100.0*COUNT(*) FILTER (WHERE a.outcome='DNA')/COUNT(*),1) AS dna_rate_pct
FROM appointments a JOIN referrals r USING (referral_id) JOIN patients p ON p.patient_id=a.patient_id
GROUP BY 1,2 HAVING COUNT(*) >= 30
ORDER BY 1,2;
```

---

### 62. Referral to first appointment waiting times
See Part 13.13, including the completed-vs-incomplete pathway caveat.

---

### 63. Patients with multiple referrals to the same specialty
```sql
SELECT patient_id, specialty, COUNT(*) AS referrals,
       MIN(referral_date) AS first, MAX(referral_date) AS latest
FROM referrals GROUP BY 1,2 HAVING COUNT(*) > 1 ORDER BY referrals DESC;
```

---

### 64. RTT 18-week breaches, still waiting
```sql
SELECT r.specialty, COUNT(*) AS waiting,
       COUNT(*) FILTER (WHERE CURRENT_DATE - r.referral_date > 126) AS over_18_weeks,
       ROUND(100.0*COUNT(*) FILTER (WHERE CURRENT_DATE - r.referral_date <= 126)/COUNT(*),1) AS pct_within
FROM referrals r JOIN waiting_list w ON w.referral_id=r.referral_id AND w.removed_date IS NULL
GROUP BY r.specialty ORDER BY pct_within;
```

---

### 65. Two Week Wait compliance
```sql
SELECT DATE_TRUNC('month',r.referral_date)::date AS month,
       COUNT(*) AS twow_referrals,
       COUNT(*) FILTER (WHERE a.attended_ts::date - r.referral_date <= 14) AS seen_within_14d,
       ROUND(100.0*COUNT(*) FILTER (WHERE a.attended_ts::date - r.referral_date <= 14)
             /NULLIF(COUNT(*) FILTER (WHERE a.attended_ts IS NOT NULL),0),1) AS compliance_pct
FROM referrals r
LEFT JOIN LATERAL (SELECT attended_ts FROM appointments x
                   WHERE x.referral_id=r.referral_id AND x.outcome='Attended'
                   ORDER BY attended_ts LIMIT 1) a ON true
WHERE r.priority='Two Week Wait'
GROUP BY 1 ORDER BY 1;
```

---

### 66. Anomalous days in order volume
See Part 12.19. The key detail: the baseline frame must end at `1 PRECEDING` so the tested day isn't in its own baseline.

---

### 67. Contribution to revenue change by category
See Part 12.21. Be ready to explain the difference between a category's own growth rate and its contribution to the total change.

---

### 68. Basket analysis: what do buyers of X also buy?
```sql
SELECT p2.product_name, COUNT(DISTINCT o.order_id) AS co_occurrences
FROM orders o
JOIN order_items i1 ON i1.order_id=o.order_id AND i1.product_id=10
JOIN order_items i2 ON i2.order_id=o.order_id AND i2.product_id<>10
JOIN products p2 ON p2.product_id=i2.product_id
WHERE o.status='completed'
GROUP BY p2.product_name ORDER BY co_occurrences DESC;
```
**Follow-up.** *"Raw co-occurrence favours popular products."* → Compute lift: observed co-occurrence divided by what you'd expect if the two were independent.

---

### 69. Customers ranked by value with their percentile
```sql
SELECT customer_id, lifetime_value,
       RANK() OVER (ORDER BY lifetime_value DESC) AS rank,
       ROUND(100*CUME_DIST() OVER (ORDER BY lifetime_value),1) AS percentile
FROM customer_ltv;
```

---

### 70. Orders where the discount exceeded the margin
```sql
SELECT oi.order_item_id, p.product_name,
       ROUND(oi.unit_price*oi.discount_pct,2) AS discount_value,
       ROUND(oi.unit_price - p.unit_cost,2) AS full_margin
FROM order_items oi JOIN products p USING (product_id)
WHERE oi.unit_price*(1-oi.discount_pct) < p.unit_cost;
```

---

### 71. Active customer count on a rolling 28-day basis
```sql
SELECT d::date AS day,
       (SELECT COUNT(DISTINCT o.customer_id) FROM orders o
        WHERE o.status='completed' AND o.order_ts::date > d::date - 28
          AND o.order_ts::date <= d::date) AS rolling_28d_active
FROM generate_series(CURRENT_DATE-89, CURRENT_DATE, INTERVAL '1 day') d;
```
**Explanation.** A correlated subquery is needed because distinct counts aren't additive — you can't window-sum daily distinct counts into a rolling distinct count.

---

### 72. Compare two periods side by side
```sql
SELECT p.category,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (
             WHERE o.order_ts >= CURRENT_DATE-30),2) AS last_30d,
       ROUND(SUM(oi.quantity*oi.unit_price) FILTER (
             WHERE o.order_ts >= CURRENT_DATE-60 AND o.order_ts < CURRENT_DATE-30),2) AS prev_30d
FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
WHERE o.status='completed' AND o.order_ts >= CURRENT_DATE-60
GROUP BY p.category;
```

---

### 73. Identify orders with data quality problems
```sql
SELECT o.order_id,
       CASE WHEN NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id=o.order_id)
                 THEN 'No line items'
            WHEN o.order_ts > CURRENT_TIMESTAMP THEN 'Future dated'
            WHEN o.customer_id IS NULL THEN 'No customer'
            WHEN o.shipping_cost < 0 THEN 'Negative shipping'
       END AS issue
FROM orders o
WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id=o.order_id)
   OR o.order_ts > CURRENT_TIMESTAMP OR o.customer_id IS NULL OR o.shipping_cost < 0;
```

---

### 74. Customer segments by RFM
See Part 12.14. Be prepared to explain the NTILE direction for each of R, F and M — reversing one silently inverts the segments.

---

### 75. ★ Which channel produces the most valuable customers?

**Problem.** Compare acquisition channels on volume, conversion, AOV and lifetime value.

**Solution.**
```sql
WITH customer_value AS (
    SELECT c.customer_id, c.channel, c.signup_date,
           COUNT(DISTINCT o.order_id) AS orders,
           COALESCE(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),0) AS lifetime_value
    FROM customers c
    LEFT JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
    LEFT JOIN order_items oi ON oi.order_id=o.order_id
    GROUP BY c.customer_id, c.channel, c.signup_date
)
SELECT channel,
       COUNT(*)                                              AS customers,
       COUNT(*) FILTER (WHERE orders > 0)                    AS converted,
       ROUND(100.0*COUNT(*) FILTER (WHERE orders>0)/COUNT(*),1) AS conversion_pct,
       ROUND(AVG(lifetime_value),2)                          AS avg_ltv_all,
       ROUND(AVG(lifetime_value) FILTER (WHERE orders>0),2)  AS avg_ltv_buyers,
       ROUND(AVG(orders) FILTER (WHERE orders>0),2)          AS avg_orders_per_buyer,
       ROUND(AVG(CURRENT_DATE - signup_date),0)              AS avg_tenure_days
FROM customer_value
GROUP BY channel
ORDER BY avg_ltv_all DESC;
```

**Explanation.** Two LTV columns because they answer different questions: `avg_ltv_all` includes non-converters and is the right number for comparing acquisition spend; `avg_ltv_buyers` tells you about the quality of customers who do convert. A channel can win on one and lose on the other, and that's a real finding, not noise.

**Common mistakes.** Inner joining and thereby dropping non-converters, which flatters every channel equally but distorts their relative ranking. Ignoring tenure — an older channel's customers have had longer to accumulate value, so a fair comparison normalises to LTV at a fixed number of days since signup.

**Follow-up.** *"Referral has the highest LTV — should we shift all budget to it?"* → No. Referral volume is usually capped and not directly buyable; and there's selection bias, since referred customers are pre-qualified by an existing happy customer. Also compare CAC by channel, not just LTV. This question is testing commercial judgement, not SQL, and a purely technical answer scores badly.

---

## Self-check

You should be fluent in all of these. The ones that most often separate offers from rejections:

- LEFT JOIN with the filter in ON, not WHERE (1)
- Aggregating to the right grain before averaging (10, 14)
- Cohort and retention construction (21, 22, 52)
- Window functions for ranking, LAG and running totals (5, 7, 12, 19)
- Funnel construction at the right grain (40)
- Knowing when a metric definition is ambiguous and saying so (50, 60, 75)
