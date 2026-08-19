# Part 12 — Advanced Analytical SQL

Twenty-two patterns. Each one: the problem, how to think about it, the SQL, why it works, an alternative, and the variation an interviewer will throw at you.

---

## 12.1 Top N

**Problem.** The 5 highest-spending customers.

**Thought process.** Aggregate to customer grain, order, limit. The only real decision is ties — `LIMIT` cuts them arbitrarily.

```sql
WITH customer_spend AS (
    SELECT o.customer_id, SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS spend
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed'
    GROUP BY o.customer_id
)
SELECT customer_id, ROUND(spend,2) AS spend
FROM customer_spend
ORDER BY spend DESC
LIMIT 5;
```

**Explanation.** Aggregate first, sort second, cut third. The status filter goes in WHERE because it's a row-level condition.

**Alternative — ties included:**

```sql
SELECT * FROM (SELECT *, RANK() OVER (ORDER BY spend DESC) r FROM customer_spend) t WHERE r <= 5;
```

**Interview variation.** "What if two customers tie for fifth?" Answer: `LIMIT` returns one of them arbitrarily and non-deterministically; `RANK() <= 5` returns both. Which is right depends on whether the output feeds a fixed-size report or a fair ranking — ask.

---

## 12.2 Greatest-per-group

**Problem.** The single most expensive product in each category, with its name.

**Thought process.** `MAX(price)` per category gives the value but not the row. You need the whole row that carries the max — that's an argmax, and window functions are the general answer.

```sql
SELECT category, product_name, unit_price
FROM (
    SELECT category, product_name, unit_price,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY unit_price DESC, product_id) AS rn
    FROM products
) t
WHERE rn = 1;
```

**Explanation.** Partition by the group, order by the metric descending, keep row 1. The `product_id` tie-breaker makes it deterministic.

**Alternatives:**

```sql
-- Postgres
SELECT DISTINCT ON (category) category, product_name, unit_price
FROM products ORDER BY category, unit_price DESC, product_id;

-- portable, no window function — returns ALL tied rows
SELECT p.* FROM products p
JOIN (SELECT category, MAX(unit_price) mx FROM products GROUP BY category) m
  ON m.category=p.category AND m.mx=p.unit_price;

-- correlated
SELECT p.* FROM products p
WHERE p.unit_price = (SELECT MAX(p2.unit_price) FROM products p2 WHERE p2.category=p.category);
```

**Interview variation.** "Now the top 3 per category" — change `= 1` to `<= 3` and pick your ranking function. "Now do it without a window function" — the self-join to the MAX subquery is the answer they're looking for.

---

## 12.3 Deduplication

**Problem.** A staging table has duplicate customer records. Keep the most recently updated one for each customer.

**Thought process.** Define the key that should be unique, define the rule for which duplicate wins, rank within the key, keep rank 1.

```sql
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id
                                 ORDER BY updated_at DESC NULLS LAST, id DESC) AS rn
    FROM customers_staging
)
SELECT * FROM ranked WHERE rn = 1;
```

**Explanation.** `ROW_NUMBER` not `RANK` — RANK would return all tied rows and you'd still have duplicates. `NULLS LAST` so a record with a missing timestamp doesn't win. The `id DESC` tie-breaker guarantees reproducibility.

**Alternative — exact duplicates only:** `SELECT DISTINCT *`. **Deleting in place:**

```sql
DELETE FROM customers_staging WHERE id IN (
    SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY customer_id
                                                  ORDER BY updated_at DESC, id DESC) rn
                    FROM customers_staging) t WHERE rn > 1);
```

**Interview variation.** "The duplicates aren't identical — one has an email, the other a phone. What now?" That's a merge, not a dedupe: group by the key and coalesce column by column.

```sql
SELECT customer_id,
       MAX(email) FILTER (WHERE email IS NOT NULL) AS email,
       MAX(phone) FILTER (WHERE phone IS NOT NULL) AS phone,
       MIN(created_at) AS created_at
FROM customers_staging GROUP BY customer_id;
```

---

## 12.4 Gaps and islands

**Problem.** Find each customer's longest streak of consecutive days with activity.

**Thought process.** Consecutive dates increase by 1; so does ROW_NUMBER. Their difference is therefore **constant within a consecutive run** and changes at every gap. Group by that difference and each group is one island.

```sql
WITH activity AS (
    SELECT DISTINCT customer_id, order_ts::date AS activity_date
    FROM orders WHERE status='completed'
),
grouped AS (
    SELECT customer_id, activity_date,
           activity_date - (ROW_NUMBER() OVER (PARTITION BY customer_id
                                               ORDER BY activity_date))::int AS island_key
    FROM activity
),
islands AS (
    SELECT customer_id, island_key,
           MIN(activity_date) AS streak_start,
           MAX(activity_date) AS streak_end,
           COUNT(*)           AS streak_length
    FROM grouped GROUP BY customer_id, island_key
)
SELECT DISTINCT ON (customer_id) customer_id, streak_start, streak_end, streak_length
FROM islands ORDER BY customer_id, streak_length DESC, streak_start;
```

**Explanation.** Trace it: dates 1,2,3,7,8 get row numbers 1,2,3,4,5; differences are 0,0,0,3,3. Two groups. `DISTINCT` on the activity dates first is essential — two orders on one day would break the arithmetic.

**Alternative — the LAG method**, which generalises to non-daily gaps:

```sql
WITH marked AS (
    SELECT customer_id, activity_date,
           CASE WHEN activity_date - LAG(activity_date) OVER
                     (PARTITION BY customer_id ORDER BY activity_date) = 1
                THEN 0 ELSE 1 END AS is_new_streak
    FROM activity
),
numbered AS (
    SELECT *, SUM(is_new_streak) OVER (PARTITION BY customer_id ORDER BY activity_date) AS streak_id
    FROM marked
)
SELECT customer_id, streak_id, MIN(activity_date), MAX(activity_date), COUNT(*)
FROM numbered GROUP BY customer_id, streak_id;
```

The "flag then cumulative-sum the flag to create a group id" idiom is worth learning on its own — it solves sessionisation, status-change grouping, and anything of the form "start a new group when X happens".

**Interview variations.** "Gaps instead of islands" — find missing dates by LEAD-ing and looking for jumps > 1. "Consecutive months, not days" — convert to a month index (`year*12 + month`) so consecutive months differ by 1. "Consecutive logins allowing a one-day gap" — change the LAG condition to `<= 2`.

---

## 12.5 Running totals

**Problem.** Cumulative revenue by day, for the year to date.

```sql
WITH daily AS (
    SELECT o.order_ts::date AS d, SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed' AND o.order_ts >= DATE_TRUNC('year', CURRENT_DATE)
    GROUP BY 1
)
SELECT d, ROUND(revenue,2) AS revenue,
       ROUND(SUM(revenue) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING),2) AS cumulative
FROM daily ORDER BY d;
```

**Explanation.** `ROWS UNBOUNDED PRECEDING` is shorthand for `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`. Specifying ROWS rather than relying on the RANGE default matters if the ORDER BY column has ties.

**Alternative — the self-join version**, which is what you'd write in a very old engine and is O(n²):

```sql
SELECT a.d, SUM(b.revenue) FROM daily a JOIN daily b ON b.d <= a.d GROUP BY a.d;
```

**Interview variation.** "Running total per customer, resetting each year" — `PARTITION BY customer_id, DATE_TRUNC('year', d)`. "Running total that resets when a target is hit" — that needs recursion or procedural logic; say so rather than contorting a window function.

---

## 12.6 Rolling averages

**Problem.** 7-day and 28-day moving averages of daily orders.

```sql
WITH daily AS (
    SELECT d::date, COALESCE(COUNT(o.order_id),0) AS orders
    FROM generate_series(CURRENT_DATE - 89, CURRENT_DATE, INTERVAL '1 day') d
    LEFT JOIN orders o ON o.order_ts::date = d::date AND o.status='completed'
    GROUP BY 1
)
SELECT d, orders,
       ROUND(AVG(orders) OVER (ORDER BY d ROWS BETWEEN  6 PRECEDING AND CURRENT ROW),1) AS ma7,
       ROUND(AVG(orders) OVER (ORDER BY d ROWS BETWEEN 27 PRECEDING AND CURRENT ROW),1) AS ma28
FROM daily ORDER BY d;
```

**Explanation.** The `generate_series` LEFT JOIN is doing real work: without it, days with zero orders are absent and `ROWS 6 PRECEDING` spans more than a week. Zero-fill first, then window.

**Alternative — gap-safe without zero-filling:**

```sql
AVG(orders) OVER (ORDER BY d RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW)
```

This still differs subtly: it averages only the days that exist, so a week with three missing days averages 4 values, not 7. Zero-filling and RANGE answer different questions — say which you mean.

**Interview variation.** "Why is the 7-day average smoother than the daily figure?" Because it removes day-of-week seasonality — which is also the reason to use 7 and 28 rather than 5 and 30.

---

## 12.7 Percent of total

**Problem.** Each category's share of total revenue.

```sql
SELECT p.category,
       ROUND(SUM(oi.quantity*oi.unit_price),2) AS revenue,
       ROUND(100.0*SUM(oi.quantity*oi.unit_price)
             / SUM(SUM(oi.quantity*oi.unit_price)) OVER (), 1) AS pct_of_total
FROM order_items oi
JOIN products p USING (product_id)
JOIN orders o ON o.order_id=oi.order_id AND o.status='completed'
GROUP BY p.category
ORDER BY revenue DESC;
```

**Explanation.** `SUM(SUM(x)) OVER ()` — inner SUM is the group aggregate, outer window SUM totals the groups. One pass, no self-join, no subquery.

**Alternative:** a CROSS JOIN to a scalar total, or a CTE plus a second aggregation. Both work; the window version is shorter and faster.

**Interview variation.** "Share within each country rather than overall" — `OVER (PARTITION BY country)`. "Cumulative share" — add `ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING` to the numerator's window. That's Pareto (12.22).

---

## 12.8 Ranking

**Problem.** Rank sales reps within their region, showing joint positions correctly.

```sql
SELECT region, rep_name, sales,
       RANK()       OVER (PARTITION BY region ORDER BY sales DESC) AS rank_with_gaps,
       DENSE_RANK() OVER (PARTITION BY region ORDER BY sales DESC) AS rank_no_gaps,
       ROUND(100*PERCENT_RANK() OVER (PARTITION BY region ORDER BY sales DESC),1) AS pct_rank,
       COUNT(*) OVER (PARTITION BY region) AS reps_in_region
FROM rep_sales;
```

**Interview variation.** "Rank across regions but show the region rank too" — two windows, one partitioned, one not. "Reps in the top 10% of their region" — `PERCENT_RANK() <= 0.1`.

---

## 12.9 Cohort analysis

**Problem.** Group customers by the month of their first purchase, then track how many are still active in each subsequent month.

**Thought process.** Three steps, and naming them is half the interview answer: (1) assign each customer a cohort — their first-purchase month; (2) find every month each customer was active; (3) join the two and count distinct customers per cohort per month-offset.

```sql
WITH first_purchase AS (
    SELECT customer_id,
           DATE_TRUNC('month', MIN(order_ts))::date AS cohort_month
    FROM orders WHERE status='completed'
    GROUP BY customer_id
),
activity AS (
    SELECT DISTINCT customer_id,
           DATE_TRUNC('month', order_ts)::date AS activity_month
    FROM orders WHERE status='completed'
),
cohort_activity AS (
    SELECT f.cohort_month,
           a.activity_month,
           (EXTRACT(YEAR FROM a.activity_month) - EXTRACT(YEAR FROM f.cohort_month)) * 12
         + (EXTRACT(MONTH FROM a.activity_month) - EXTRACT(MONTH FROM f.cohort_month)) AS month_number,
           a.customer_id
    FROM first_purchase f
    JOIN activity a USING (customer_id)
),
cohort_sizes AS (
    SELECT cohort_month, COUNT(*) AS cohort_size FROM first_purchase GROUP BY cohort_month
)
SELECT ca.cohort_month,
       cs.cohort_size,
       ca.month_number,
       COUNT(DISTINCT ca.customer_id) AS active_customers,
       ROUND(100.0 * COUNT(DISTINCT ca.customer_id) / cs.cohort_size, 1) AS retention_pct
FROM cohort_activity ca
JOIN cohort_sizes cs USING (cohort_month)
GROUP BY ca.cohort_month, cs.cohort_size, ca.month_number
ORDER BY ca.cohort_month, ca.month_number;
```

**Explanation.** `month_number` is computed as a month difference, not `(date - date)/30`, which drifts. Month 0 is always 100% by construction — that's the sanity check that your query is right. The output is a long-format cohort table; pivot it in the BI tool, or with conditional aggregation if the interviewer wants the triangle:

```sql
SELECT cohort_month, cohort_size,
       MAX(retention_pct) FILTER (WHERE month_number=1) AS m1,
       MAX(retention_pct) FILTER (WHERE month_number=2) AS m2,
       MAX(retention_pct) FILTER (WHERE month_number=3) AS m3
FROM cohort_retention GROUP BY 1,2 ORDER BY 1;
```

**Interview variations.** "Cohort by signup month rather than first purchase" — use `customers.signup_date`; this measures activation as well as retention, and the two answer different questions. "Revenue cohorts" — sum revenue instead of counting customers, and divide by cohort size for revenue-per-original-customer. "Why is the most recent cohort's month-3 retention blank?" Because three months haven't elapsed — right-censoring, and mistaking it for a collapse in retention is a classic bad-analysis story.

---

## 12.10 Retention

**Problem.** What proportion of customers active in month N are still active in month N+1?

```sql
WITH monthly_active AS (
    SELECT DISTINCT customer_id, DATE_TRUNC('month', order_ts)::date AS month
    FROM orders WHERE status='completed'
)
SELECT curr.month,
       COUNT(DISTINCT curr.customer_id) AS active_this_month,
       COUNT(DISTINCT nxt.customer_id)  AS retained_next_month,
       ROUND(100.0 * COUNT(DISTINCT nxt.customer_id)
             / NULLIF(COUNT(DISTINCT curr.customer_id),0), 1) AS retention_pct
FROM monthly_active curr
LEFT JOIN monthly_active nxt
       ON nxt.customer_id = curr.customer_id
      AND nxt.month = curr.month + INTERVAL '1 month'
GROUP BY curr.month
ORDER BY curr.month;
```

**Explanation.** Self-join on the same table offset by one month. LEFT JOIN so that non-returning customers still count in the denominator — an inner join would give you 100% retention every month, which is the seeded error.

**Alternative — new/retained/resurrected/churned decomposition**, which is what a product analyst actually reports:

```sql
WITH ma AS (SELECT DISTINCT customer_id, DATE_TRUNC('month',order_ts)::date AS month
            FROM orders WHERE status='completed'),
first_month AS (SELECT customer_id, MIN(month) AS first_month FROM ma GROUP BY customer_id),
classified AS (
  SELECT m.month, m.customer_id,
     CASE WHEN m.month = f.first_month THEN 'new'
          WHEN EXISTS (SELECT 1 FROM ma p WHERE p.customer_id=m.customer_id
                        AND p.month = m.month - INTERVAL '1 month') THEN 'retained'
          ELSE 'resurrected' END AS status
  FROM ma m JOIN first_month f USING (customer_id))
SELECT month, COUNT(*) FILTER (WHERE status='new')          AS new_customers,
              COUNT(*) FILTER (WHERE status='retained')     AS retained,
              COUNT(*) FILTER (WHERE status='resurrected')  AS resurrected
FROM classified GROUP BY month ORDER BY month;
```

**Interview variation.** "Rolling 30-day retention rather than calendar month" — replace calendar months with day-offset windows relative to each customer's own first activity.

---

## 12.11 Churn

**Problem.** Which customers have churned, and what's the monthly churn rate?

**Thought process.** Churn needs a definition before it needs SQL. For a subscription business it's an explicit cancellation. For retail there is no cancel event, so churn is a rule: no purchase in N days, where N comes from the observed repurchase distribution.

```sql
-- pick N from the data rather than guessing
WITH gaps AS (
    SELECT customer_id,
           order_ts::date - LAG(order_ts::date) OVER (PARTITION BY customer_id ORDER BY order_ts) AS gap
    FROM orders WHERE status='completed'
)
SELECT PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY gap) AS median_gap,
       PERCENTILE_CONT(0.9)  WITHIN GROUP (ORDER BY gap) AS p90_gap
FROM gaps WHERE gap IS NOT NULL;
```

```sql
-- classify against a 180-day rule
WITH last_order AS (
    SELECT customer_id, MAX(order_ts)::date AS last_order_date, COUNT(*) AS lifetime_orders
    FROM orders WHERE status='completed' GROUP BY customer_id
)
SELECT CASE WHEN last_order_date >= CURRENT_DATE - 180 THEN 'Active'
            WHEN lifetime_orders = 1                   THEN 'Churned - never repeated'
            ELSE 'Churned - lapsed repeat buyer' END AS churn_status,
       COUNT(*) AS customers,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),1) AS pct
FROM last_order GROUP BY 1;
```

**Monthly churn rate:**

```sql
WITH ma AS (SELECT DISTINCT customer_id, DATE_TRUNC('month',order_ts)::date AS month
            FROM orders WHERE status='completed')
SELECT curr.month,
       COUNT(DISTINCT curr.customer_id) AS active_start,
       COUNT(DISTINCT curr.customer_id) FILTER (WHERE nxt.customer_id IS NULL) AS churned,
       ROUND(100.0*COUNT(DISTINCT curr.customer_id) FILTER (WHERE nxt.customer_id IS NULL)
             / NULLIF(COUNT(DISTINCT curr.customer_id),0),1) AS churn_rate_pct
FROM ma curr
LEFT JOIN ma nxt ON nxt.customer_id=curr.customer_id AND nxt.month=curr.month+INTERVAL '1 month'
GROUP BY curr.month ORDER BY curr.month;
```

**Interview variation.** "Churn rate is rising but revenue is flat — explain." Possible: churn concentrated in low-value customers; or high-value customers buying more to compensate; or the denominator shrank. Segment churn by value decile before concluding anything. That answer demonstrates analytical thinking rather than SQL, which is what a senior interviewer is testing at this point.

---

## 12.12 Funnel analysis

**Problem.** Conversion through page view → product view → add to cart → checkout → purchase.

**Thought process.** Two kinds of funnel and you must ask which: **unordered** (did the user ever do each step?) or **ordered** (did they do them in sequence, each after the previous?). Unordered is much easier and often what's wanted.

```sql
-- unordered funnel by session
WITH session_steps AS (
    SELECT session_id,
           MAX(CASE WHEN event_name='page_view'      THEN 1 ELSE 0 END) AS s1,
           MAX(CASE WHEN event_name='product_view'   THEN 1 ELSE 0 END) AS s2,
           MAX(CASE WHEN event_name='add_to_cart'    THEN 1 ELSE 0 END) AS s3,
           MAX(CASE WHEN event_name='checkout_start' THEN 1 ELSE 0 END) AS s4,
           MAX(CASE WHEN event_name='purchase'       THEN 1 ELSE 0 END) AS s5
    FROM web_events
    WHERE event_ts >= CURRENT_DATE - 30
    GROUP BY session_id
)
SELECT SUM(s1) AS visited,
       SUM(s2) AS viewed_product,
       SUM(s3) AS added_to_cart,
       SUM(s4) AS started_checkout,
       SUM(s5) AS purchased,
       ROUND(100.0*SUM(s2)/NULLIF(SUM(s1),0),1) AS pct_view_product,
       ROUND(100.0*SUM(s3)/NULLIF(SUM(s2),0),1) AS pct_add_given_view,
       ROUND(100.0*SUM(s4)/NULLIF(SUM(s3),0),1) AS pct_checkout_given_add,
       ROUND(100.0*SUM(s5)/NULLIF(SUM(s4),0),1) AS pct_purchase_given_checkout,
       ROUND(100.0*SUM(s5)/NULLIF(SUM(s1),0),1) AS overall_conversion
FROM session_steps;
```

**Ordered funnel** — each step must occur after the previous one:

```sql
WITH steps AS (
    SELECT session_id,
           MIN(event_ts) FILTER (WHERE event_name='product_view')   AS t_view,
           MIN(event_ts) FILTER (WHERE event_name='add_to_cart')    AS t_cart,
           MIN(event_ts) FILTER (WHERE event_name='checkout_start') AS t_checkout,
           MIN(event_ts) FILTER (WHERE event_name='purchase')       AS t_purchase
    FROM web_events GROUP BY session_id
)
SELECT COUNT(*) FILTER (WHERE t_view IS NOT NULL)                        AS viewed,
       COUNT(*) FILTER (WHERE t_cart     > t_view)                       AS carted_after_view,
       COUNT(*) FILTER (WHERE t_checkout > t_cart)                       AS checkout_after_cart,
       COUNT(*) FILTER (WHERE t_purchase > t_checkout)                   AS purchased_after_checkout
FROM steps;
```

**Explanation.** `MIN(ts) FILTER (WHERE ...)` gives the first occurrence of each step; comparing timestamps enforces order. NULLs propagate correctly — a comparison with a NULL step is UNKNOWN, so the row isn't counted, which is what you want.

**Interview variations.** "Where's the biggest drop-off?" Report step-to-step rates, not just overall — the largest absolute loss and the worst rate can be different steps. "Funnel by device" — add `device` to the GROUP BY and compare. "What if a user adds to cart on Monday and buys on Thursday?" Then session-level funnelling undercounts; switch the grain to customer and define an attribution window.

---

## 12.13 Conversion rates

```sql
SELECT DATE_TRUNC('week', e.event_ts)::date AS week,
       e.device,
       COUNT(DISTINCT e.session_id) AS sessions,
       COUNT(DISTINCT e.session_id) FILTER (WHERE e.event_name='purchase') AS converting,
       ROUND(100.0*COUNT(DISTINCT e.session_id) FILTER (WHERE e.event_name='purchase')
             / NULLIF(COUNT(DISTINCT e.session_id),0), 2) AS conversion_rate_pct
FROM web_events e
GROUP BY 1,2 ORDER BY 1,2;
```

**Interview variation.** "Mobile converts at 1.2%, desktop at 3.4% — should we deprioritise mobile?" No: mobile likely has more top-of-funnel browsing traffic, and users may research on mobile and buy on desktop. Cross-device attribution and traffic-source mix are confounders. Recognising Simpson's paradox risk here is the answer that lands.

---

## 12.14 Customer segmentation (RFM)

```sql
WITH rfm_base AS (
    SELECT o.customer_id,
           CURRENT_DATE - MAX(o.order_ts)::date            AS recency_days,
           COUNT(DISTINCT o.order_id)                      AS frequency,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS monetary
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed'
    GROUP BY o.customer_id
),
scored AS (
    SELECT *,
           NTILE(5) OVER (ORDER BY recency_days ASC)  AS r_score,   -- lower recency = better
           NTILE(5) OVER (ORDER BY frequency DESC)    AS f_score,
           NTILE(5) OVER (ORDER BY monetary  DESC)    AS m_score
    FROM rfm_base
)
SELECT customer_id, recency_days, frequency, ROUND(monetary,2) AS monetary,
       r_score, f_score, m_score,
       CASE WHEN r_score<=2 AND f_score<=2 AND m_score<=2 THEN 'Champions'
            WHEN r_score<=2 AND f_score<=3               THEN 'Loyal'
            WHEN r_score<=2                              THEN 'Promising'
            WHEN r_score>=4 AND f_score<=2               THEN 'At risk - was valuable'
            WHEN r_score>=4                              THEN 'Hibernating'
            ELSE 'Needs attention' END AS segment
FROM scored;
```

**Note on NTILE direction.** With `ORDER BY recency_days ASC`, bucket 1 is the *most recent* customers — good. Getting the direction backwards on any of the three silently inverts your segments, and the output still looks plausible, so state the direction in a comment as done above.

**Interview variation.** "Segment sizes are wildly uneven — why?" NTILE forces equal *counts*, so uneven sizes mean you used CASE thresholds rather than quintiles, or ties are collapsing buckets. "How would you validate the segmentation?" Check that Champions have materially higher forward-looking revenue than other segments over the next quarter — a segmentation that doesn't predict anything is decoration.

---

## 12.15 Repeat purchases

```sql
WITH customer_orders AS (
    SELECT customer_id, COUNT(*) AS orders,
           MIN(order_ts)::date AS first_order, MAX(order_ts)::date AS last_order
    FROM orders WHERE status='completed' GROUP BY customer_id
)
SELECT COUNT(*)                                                       AS all_customers,
       COUNT(*) FILTER (WHERE orders >= 2)                            AS repeat_customers,
       ROUND(100.0*COUNT(*) FILTER (WHERE orders>=2)/COUNT(*),1)      AS repeat_rate_pct,
       ROUND(AVG(orders),2)                                           AS avg_orders_per_customer,
       ROUND(AVG(last_order - first_order) FILTER (WHERE orders>=2),0) AS avg_days_between_first_and_last
FROM customer_orders;
```

**Time to second purchase**, which is the actionable version:

```sql
WITH seq AS (
    SELECT customer_id, order_ts,
           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts) AS n
    FROM orders WHERE status='completed'
)
SELECT ROUND(AVG(s2.order_ts::date - s1.order_ts::date),1) AS mean_days_to_second,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s2.order_ts::date - s1.order_ts::date)
           AS median_days_to_second
FROM seq s1 JOIN seq s2 ON s2.customer_id=s1.customer_id AND s1.n=1 AND s2.n=2;
```

**Interview variation.** "Repeat rate is 30% — is that good?" It's meaningless without a cohort: customers who signed up last week haven't had time to repeat. Compute repeat rate by cohort with a fixed observation window (e.g. repeat within 90 days of first purchase) so cohorts are comparable. That's the answer.

---

## 12.16 First and last purchase

```sql
SELECT DISTINCT ON (o.customer_id)
       o.customer_id, o.order_id AS first_order_id, o.order_ts::date AS first_order_date,
       p.product_name AS first_product, p.category AS first_category
FROM orders o
JOIN order_items oi USING (order_id)
JOIN products p USING (product_id)
WHERE o.status='completed'
ORDER BY o.customer_id, o.order_ts, oi.order_item_id;
```

**Interview variation.** "Which first-purchase category leads to the highest lifetime value?" Join first category to total LTV and group — a genuinely useful acquisition insight, and a natural follow-up they'll enjoy you volunteering.

```sql
WITH first_cat AS (
    SELECT DISTINCT ON (o.customer_id) o.customer_id, p.category
    FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
    WHERE o.status='completed' ORDER BY o.customer_id, o.order_ts, oi.order_item_id),
ltv AS (
    SELECT o.customer_id, SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS lifetime_value
    FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
    GROUP BY o.customer_id)
SELECT f.category, COUNT(*) AS customers, ROUND(AVG(l.lifetime_value),2) AS avg_ltv
FROM first_cat f JOIN ltv l USING (customer_id)
GROUP BY f.category ORDER BY avg_ltv DESC;
```

---

## 12.17 Session analysis (sessionisation)

**Problem.** Events have no session id; define a session as activity with no more than 30 minutes between consecutive events.

**Thought process.** Same idiom as gaps and islands: flag the rows that start a new session, then cumulative-sum the flag to produce a session id.

```sql
WITH ordered AS (
    SELECT customer_id, event_ts, event_name,
           LAG(event_ts) OVER (PARTITION BY customer_id ORDER BY event_ts) AS prev_ts
    FROM web_events WHERE customer_id IS NOT NULL
),
flagged AS (
    SELECT *, CASE WHEN prev_ts IS NULL
                     OR event_ts - prev_ts > INTERVAL '30 minutes'
                   THEN 1 ELSE 0 END AS is_session_start
    FROM ordered
),
sessionised AS (
    SELECT *, SUM(is_session_start) OVER (PARTITION BY customer_id ORDER BY event_ts)
                  AS session_number
    FROM flagged
)
SELECT customer_id, session_number,
       MIN(event_ts) AS session_start,
       MAX(event_ts) AS session_end,
       ROUND(EXTRACT(EPOCH FROM (MAX(event_ts)-MIN(event_ts)))/60,1) AS duration_minutes,
       COUNT(*) AS events,
       BOOL_OR(event_name='purchase') AS converted
FROM sessionised
GROUP BY customer_id, session_number
ORDER BY customer_id, session_number;
```

**Explanation.** `BOOL_OR` is the neat aggregate for "did any row in this group satisfy X". The cumulative sum of a 0/1 flag creating a group id is worth committing to memory — it's the same trick as 12.4.

**Interview variation.** "Single-event sessions have zero duration — is that right?" Technically yes, analytically misleading: bounce sessions have unknown duration, not zero, and including them drags the average down. Either exclude them or report bounce rate separately.

---

## 12.18 Consecutive events

**Problem.** Customers who placed orders in three consecutive months.

```sql
WITH monthly AS (
    SELECT DISTINCT customer_id, DATE_TRUNC('month', order_ts)::date AS month
    FROM orders WHERE status='completed'
),
indexed AS (
    SELECT customer_id, month,
           (EXTRACT(YEAR FROM month)*12 + EXTRACT(MONTH FROM month))::int AS month_index
    FROM monthly
),
grouped AS (
    SELECT *, month_index - ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY month_index)
                  AS island
    FROM indexed
)
SELECT customer_id, MIN(month) AS run_start, MAX(month) AS run_end, COUNT(*) AS consecutive_months
FROM grouped
GROUP BY customer_id, island
HAVING COUNT(*) >= 3;
```

**Alternative — LAG twice**, fine for a fixed run length and easier to read:

```sql
SELECT DISTINCT customer_id FROM (
    SELECT customer_id, month,
           LAG(month,1) OVER (PARTITION BY customer_id ORDER BY month) AS m1,
           LAG(month,2) OVER (PARTITION BY customer_id ORDER BY month) AS m2
    FROM monthly) t
WHERE month - INTERVAL '1 month' = m1 AND month - INTERVAL '2 months' = m2;
```

**Interview variation.** "Three consecutive *days* of login" — same shape, day index. "N consecutive, where N is a parameter" — the island method scales; the LAG method doesn't. Say that.

---

## 12.19 Anomaly detection

**Problem.** Flag days where orders deviate sharply from the recent norm.

```sql
WITH daily AS (
    SELECT order_ts::date AS d, COUNT(*) AS orders
    FROM orders WHERE status='completed' GROUP BY 1
),
stats AS (
    SELECT d, orders,
           AVG(orders)    OVER (ORDER BY d ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS baseline,
           STDDEV(orders) OVER (ORDER BY d ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS sd
    FROM daily
)
SELECT d, orders, ROUND(baseline,1) AS baseline_28d,
       ROUND((orders - baseline)/NULLIF(sd,0), 2) AS z_score,
       CASE WHEN ABS(orders - baseline) > 3*sd THEN 'Extreme'
            WHEN ABS(orders - baseline) > 2*sd THEN 'Unusual'
            ELSE 'Normal' END AS flag
FROM stats
WHERE sd IS NOT NULL AND ABS(orders - baseline) > 2*sd
ORDER BY d;
```

**Explanation.** The frame ends at `1 PRECEDING` so the day being tested isn't part of its own baseline — otherwise an extreme value pulls the mean towards itself and hides the anomaly. That detail is the whole point of the query.

**Interview variation.** "Every Saturday flags as an anomaly." Day-of-week seasonality: compare each day to the same weekday in prior weeks (`PARTITION BY EXTRACT(ISODOW FROM d)`), or use a 7-day-multiple lag. "Z-scores assume normality" — true; for count data, or heavily skewed metrics, prefer a median/MAD approach or percentile bounds. Raising that unprompted is a strong signal.

---

## 12.20 Pareto analysis

**Problem.** How many customers account for 80% of revenue?

```sql
WITH customer_revenue AS (
    SELECT o.customer_id, SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed' GROUP BY o.customer_id
),
ranked AS (
    SELECT customer_id, revenue,
           ROW_NUMBER() OVER (ORDER BY revenue DESC) AS rn,
           SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING) AS cumulative_revenue,
           SUM(revenue) OVER () AS total_revenue,
           COUNT(*)     OVER () AS total_customers
    FROM customer_revenue
)
SELECT customer_id, ROUND(revenue,2) AS revenue,
       ROUND(100.0*cumulative_revenue/total_revenue,1) AS cumulative_pct_revenue,
       ROUND(100.0*rn/total_customers,1)               AS pct_of_customers
FROM ranked
WHERE cumulative_revenue - revenue < 0.8*total_revenue     -- include the row that crosses 80%
ORDER BY rn;
```

**Explanation.** The WHERE condition uses the cumulative total *before* the current row, so the customer who tips the total past 80% is included rather than excluded. Off-by-one here is the standard mistake.

**Interview variation.** "Is it really 80/20?" Rarely exactly; report the actual figure ("the top 12% of customers drive 80% of revenue"). "Do it by product" — same query, group by product. "What's the risk?" Concentration: if the top 12% churn, revenue collapses. That framing turns a SQL answer into an analyst answer.

---

## 12.21 Contribution analysis

**Problem.** Revenue fell 8% month on month. Which categories caused it?

**Thought process.** Decompose the total change into per-segment contributions that sum back to the total. Each segment's contribution is its own change divided by the *previous total*, so the parts add up to the overall percentage change.

```sql
WITH monthly_category AS (
    SELECT DATE_TRUNC('month',o.order_ts)::date AS month, p.category,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
    FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
    WHERE o.status='completed' GROUP BY 1,2
),
with_prev AS (
    SELECT month, category, revenue,
           LAG(revenue) OVER (PARTITION BY category ORDER BY month) AS prev_revenue
    FROM monthly_category
),
totals AS (
    SELECT month, SUM(revenue) AS total_revenue, SUM(prev_revenue) AS prev_total
    FROM with_prev GROUP BY month
)
SELECT w.month, w.category,
       ROUND(w.revenue,2)                                   AS revenue,
       ROUND(w.prev_revenue,2)                              AS prev_revenue,
       ROUND(w.revenue - w.prev_revenue,2)                  AS absolute_change,
       ROUND(100.0*(w.revenue-w.prev_revenue)/NULLIF(w.prev_revenue,0),1) AS category_growth_pct,
       ROUND(100.0*(w.revenue-w.prev_revenue)/NULLIF(t.prev_total,0),2)   AS contribution_to_total_pct
FROM with_prev w JOIN totals t USING (month)
WHERE w.prev_revenue IS NOT NULL
ORDER BY w.month, contribution_to_total_pct;
```

**Explanation.** Two different percentages, and confusing them is the classic error. `category_growth_pct` says how much that category moved. `contribution_to_total_pct` says how much of the overall movement it accounts for — and those sum to the total change. A small category falling 60% may contribute almost nothing; a large category falling 4% may be the entire story.

**Interview variation.** "Separate price effect from volume effect." Decompose: revenue = units × average price, so change ≈ (Δunits × prior price) + (Δprice × prior units) + interaction. Being able to sketch that shows commercial literacy.

---

## 12.22 Putting it together — a churn early-warning query

The kind of thing that wins a take-home task. Every pattern above appears in it.

```sql
WITH order_values AS (
    SELECT o.order_id, o.customer_id, o.order_ts,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS order_value
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed'
    GROUP BY o.order_id, o.customer_id, o.order_ts
),
customer_history AS (
    SELECT customer_id,
           COUNT(*)                                  AS orders,
           SUM(order_value)                          AS lifetime_value,
           AVG(order_value)                          AS avg_order_value,
           MIN(order_ts)::date                       AS first_order,
           MAX(order_ts)::date                       AS last_order,
           CURRENT_DATE - MAX(order_ts)::date        AS days_since_last
    FROM order_values GROUP BY customer_id
),
cadence AS (
    SELECT customer_id,
           AVG(gap) AS avg_days_between_orders,
           STDDEV(gap) AS gap_variability
    FROM (SELECT customer_id,
                 order_ts::date - LAG(order_ts::date) OVER (PARTITION BY customer_id ORDER BY order_ts) AS gap
          FROM order_values) g
    WHERE gap IS NOT NULL
    GROUP BY customer_id
),
scored AS (
    SELECT h.*, c.avg_days_between_orders,
           NTILE(10) OVER (ORDER BY h.lifetime_value DESC) AS value_decile,
           CASE WHEN h.orders = 1 AND h.days_since_last > 90 THEN 'Failed to activate'
                WHEN c.avg_days_between_orders IS NULL       THEN 'Insufficient history'
                WHEN h.days_since_last > 3*c.avg_days_between_orders THEN 'High risk'
                WHEN h.days_since_last > 2*c.avg_days_between_orders THEN 'Medium risk'
                ELSE 'Healthy' END AS churn_risk
    FROM customer_history h LEFT JOIN cadence c USING (customer_id)
)
SELECT churn_risk, value_decile,
       COUNT(*) AS customers,
       ROUND(SUM(lifetime_value),2) AS revenue_at_risk,
       ROUND(AVG(days_since_last),0) AS avg_days_since_last
FROM scored
GROUP BY churn_risk, value_decile
HAVING churn_risk IN ('High risk','Medium risk')
ORDER BY value_decile, churn_risk;
```

The risk rule compares each customer's silence to *their own* purchase cadence rather than a single global threshold — a monthly buyer silent for 90 days is in trouble; an annual buyer isn't. Crossing that with value decile answers the question a commercial stakeholder actually has: not "who might churn" but "where should we spend retention budget".
