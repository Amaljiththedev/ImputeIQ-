# Part 16c — 75 Advanced SQL Interview Questions

These are what you get in a second-round technical, a take-home task, or an interview for a role that says "junior" but expects real analytical work. Many have no single right answer — the assessment is as much about the questions you ask and the caveats you volunteer as the SQL you write.

★ = fuller treatment.

---

### ★ 1. Full cohort retention table

**Problem.** Monthly cohort retention: rows are cohorts by first-purchase month, columns are months since acquisition, values are the percentage still active.

**Solution.** See Part 12.9 for the complete query. The structure to reproduce under pressure:

```sql
WITH first_purchase AS (
    SELECT customer_id, DATE_TRUNC('month', MIN(order_ts))::date AS cohort_month
    FROM orders WHERE status='completed' GROUP BY customer_id
),
activity AS (
    SELECT DISTINCT customer_id, DATE_TRUNC('month', order_ts)::date AS activity_month
    FROM orders WHERE status='completed'
),
joined AS (
    SELECT f.cohort_month, a.customer_id,
           (EXTRACT(YEAR FROM a.activity_month)-EXTRACT(YEAR FROM f.cohort_month))*12
         + (EXTRACT(MONTH FROM a.activity_month)-EXTRACT(MONTH FROM f.cohort_month)) AS month_number
    FROM first_purchase f JOIN activity a USING (customer_id)
),
sizes AS (SELECT cohort_month, COUNT(*) AS cohort_size FROM first_purchase GROUP BY 1)
SELECT j.cohort_month, s.cohort_size, j.month_number,
       COUNT(DISTINCT j.customer_id) AS active,
       ROUND(100.0*COUNT(DISTINCT j.customer_id)/s.cohort_size,1) AS retention_pct
FROM joined j JOIN sizes s USING (cohort_month)
GROUP BY 1,2,3 ORDER BY 1,3;
```

**Sanity check.** Month 0 must be 100% for every cohort. If it isn't, your cohort assignment and your activity table disagree.

**Common mistakes.** Computing month offset as `(date - date)/30`, which drifts and eventually misassigns months. Dividing by the current cohort size rather than the original. Forgetting DISTINCT and counting orders rather than customers.

**Follow-up.** *"Month 3 retention for the newest cohort is blank — is retention collapsing?"* → No, three months haven't elapsed. Right-censoring. Only compare cohorts at equal maturity; this mistake has caused real, expensive misreadings.

---

### 2. Revenue cohorts rather than count cohorts
```sql
SELECT cohort_month, month_number,
       ROUND(SUM(revenue),2) AS cohort_revenue,
       ROUND(SUM(revenue)/MAX(cohort_size),2) AS revenue_per_original_customer
FROM cohort_revenue_base GROUP BY 1,2 ORDER BY 1,2;
```
**Explanation.** Dividing by the *original* cohort size, not by active customers, gives cumulative value per acquired customer — which is what you compare against CAC.

---

### 3. Gaps and islands: longest active streak
See Part 12.4 for both methods. Be able to explain the `date - ROW_NUMBER()` trick in one sentence: consecutive dates and consecutive row numbers increase in step, so their difference is constant within a run.

---

### 4. Find missing dates in a series
```sql
WITH d AS (SELECT DISTINCT order_ts::date AS day FROM orders),
     bounds AS (SELECT MIN(day) lo, MAX(day) hi FROM d)
SELECT g::date AS missing_day
FROM bounds, generate_series(bounds.lo, bounds.hi, INTERVAL '1 day') g
WHERE NOT EXISTS (SELECT 1 FROM d WHERE d.day = g::date);
```
**Alternative using LEAD** to find gap ranges rather than individual days:
```sql
SELECT day AS gap_starts_after, next_day, next_day - day - 1 AS days_missing
FROM (SELECT day, LEAD(day) OVER (ORDER BY day) AS next_day FROM d) t
WHERE next_day - day > 1;
```

---

### 5. Sessionise with a 30-minute inactivity timeout
See Part 12.17. Expect a follow-up on why the cumulative sum of a boolean flag produces a group id.

---

### 6. Nth order per customer, generalised
```sql
SELECT * FROM (
  SELECT o.*, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts, order_id) AS n
  FROM orders o WHERE status='completed') t
WHERE n = 3;
```

---

### 7. Customers whose spend increased every month
```sql
WITH m AS (
  SELECT o.customer_id, DATE_TRUNC('month',o.order_ts)::date AS month,
         SUM(oi.quantity*oi.unit_price) AS spend
  FROM orders o JOIN order_items oi USING (order_id) WHERE o.status='completed'
  GROUP BY 1,2),
flagged AS (
  SELECT *, spend > LAG(spend) OVER (PARTITION BY customer_id ORDER BY month) AS increased
  FROM m)
SELECT customer_id FROM flagged
GROUP BY customer_id
HAVING COUNT(*) FILTER (WHERE increased IS FALSE) = 0 AND COUNT(*) >= 3;
```
**Explanation.** `increased` is NULL for the first month (no previous), so counting FALSE rather than NOT TRUE correctly ignores it.

---

### 8. Median by group without PERCENTILE_CONT
```sql
SELECT category, AVG(unit_price) AS median FROM (
  SELECT category, unit_price,
         ROW_NUMBER() OVER (PARTITION BY category ORDER BY unit_price) rn,
         COUNT(*)     OVER (PARTITION BY category) n
  FROM products) t
WHERE rn IN ((n+1)/2, (n+2)/2) GROUP BY category;
```
**Explanation.** The `(n+1)/2, (n+2)/2` pair uses integer division to select the single middle row for odd n and the two middle rows for even n.

---

### 9. Mode (most common value) per group
```sql
SELECT category, MODE() WITHIN GROUP (ORDER BY subcategory) AS most_common_subcategory
FROM products GROUP BY category;
```

---

### 10. ★ Year-on-year growth with missing periods handled

**Problem.** Monthly revenue with YoY growth, robust to months with no sales.

**Solution.**
```sql
WITH calendar AS (
    SELECT generate_series(DATE '2023-01-01', DATE '2024-12-01', INTERVAL '1 month')::date AS month
),
actual AS (
    SELECT DATE_TRUNC('month', o.order_ts)::date AS month,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status='completed' GROUP BY 1
),
filled AS (
    SELECT c.month, COALESCE(a.revenue, 0) AS revenue
    FROM calendar c LEFT JOIN actual a USING (month)
)
SELECT f.month, ROUND(f.revenue,2) AS revenue,
       ROUND(p.revenue,2) AS same_month_last_year,
       ROUND(100.0*(f.revenue - p.revenue)/NULLIF(p.revenue,0),1) AS yoy_pct
FROM filled f
LEFT JOIN filled p ON p.month = f.month - INTERVAL '1 year'
WHERE f.month >= DATE '2024-01-01'
ORDER BY f.month;
```

**Explanation.** Three defences against the same failure mode: generate the calendar so gaps become explicit zeros; join on the date offset rather than `LAG(12)` so a missing row can't shift the comparison; `NULLIF` on the denominator so a zero prior year doesn't error.

**Common mistakes.** `LAG(revenue, 12)` on a table with gaps. Dividing by a zero baseline. Reporting "+∞%" growth when the prior period was zero — better to show the absolute values and suppress the percentage.

**Follow-up.** *"Prior year was zero. What do you display?"* → Not a percentage. Show "n/a (no prior year activity)" and the absolute figures. A percentage change from zero is undefined, not infinite.

---

### 11. Rolling 12-month revenue
```sql
SELECT month, ROUND(SUM(revenue) OVER (ORDER BY month
       RANGE BETWEEN INTERVAL '11 months' PRECEDING AND CURRENT ROW),2) AS rolling_12m
FROM monthly_revenue;
```

---

### 12. Rank with custom tie handling
```sql
SELECT product_name, revenue,
       RANK() OVER (ORDER BY revenue DESC) AS competition_rank,
       DENSE_RANK() OVER (ORDER BY revenue DESC) AS dense,
       ROW_NUMBER() OVER (ORDER BY revenue DESC, product_id) AS deterministic_row
FROM product_revenue;
```

---

### 13. Top N per group with ties included
```sql
SELECT * FROM (
  SELECT p.*, DENSE_RANK() OVER (PARTITION BY category ORDER BY unit_price DESC) r
  FROM products p) t WHERE r <= 3;
```

---

### 14. Customers ranked within multiple dimensions at once
```sql
SELECT customer_id, country, channel, lifetime_value,
       RANK() OVER (ORDER BY lifetime_value DESC)                        AS overall,
       RANK() OVER (PARTITION BY country ORDER BY lifetime_value DESC)   AS in_country,
       RANK() OVER (PARTITION BY channel ORDER BY lifetime_value DESC)   AS in_channel,
       ROUND(100*PERCENT_RANK() OVER (ORDER BY lifetime_value),1)        AS percentile
FROM customer_ltv;
```

---

### 15. Pareto: customers driving 80% of revenue
See Part 12.20. The off-by-one on the crossing row is the detail being tested.

---

### 16. Contribution analysis of a revenue decline
See Part 12.21. Be ready to distinguish a segment's growth rate from its contribution to the total change.

---

### 17. Price/volume decomposition
```sql
WITH m AS (
  SELECT DATE_TRUNC('month',o.order_ts)::date AS month, p.category,
         SUM(oi.quantity) AS units,
         SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct))/NULLIF(SUM(oi.quantity),0) AS avg_price,
         SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS revenue
  FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
  WHERE o.status='completed' GROUP BY 1,2)
SELECT month, category,
       ROUND(revenue - LAG(revenue) OVER w, 2) AS total_change,
       ROUND((units - LAG(units) OVER w) * LAG(avg_price) OVER w, 2) AS volume_effect,
       ROUND((avg_price - LAG(avg_price) OVER w) * LAG(units) OVER w, 2) AS price_effect,
       ROUND((units - LAG(units) OVER w) * (avg_price - LAG(avg_price) OVER w), 2) AS interaction
FROM m WINDOW w AS (PARTITION BY category ORDER BY month) ORDER BY month, category;
```
**Explanation.** The three effects sum exactly to the total change. Being able to derive that decomposition is a genuine commercial-analysis skill and rare in candidates.

---

### 18. Ordered funnel with time constraints
See Part 12.12, the timestamp-comparison version.

---

### 19. Funnel with a 7-day attribution window
```sql
WITH first_touch AS (
  SELECT customer_id, MIN(event_ts) AS first_view
  FROM web_events WHERE event_name='product_view' GROUP BY customer_id)
SELECT COUNT(*) AS viewers,
       COUNT(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM orders o WHERE o.customer_id=f.customer_id AND o.status='completed'
           AND o.order_ts BETWEEN f.first_view AND f.first_view + INTERVAL '7 days')) AS converted_7d
FROM first_touch f;
```

---

### 20. ★ Customer lifetime value with cohort normalisation

**Problem.** Compare LTV across acquisition cohorts fairly, given that older cohorts have had longer to spend.

**Solution.**
```sql
WITH orders_with_age AS (
    SELECT c.customer_id,
           DATE_TRUNC('month', c.signup_date)::date AS cohort,
           c.channel,
           o.order_ts::date - c.signup_date AS days_since_signup,
           oi.quantity*oi.unit_price*(1-oi.discount_pct) AS line_revenue
    FROM customers c
    JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
    JOIN order_items oi ON oi.order_id=o.order_id
),
cohort_sizes AS (
    SELECT DATE_TRUNC('month', signup_date)::date AS cohort, channel, COUNT(*) AS customers
    FROM customers GROUP BY 1,2
)
SELECT o.cohort, o.channel, s.customers,
       ROUND(SUM(o.line_revenue) FILTER (WHERE o.days_since_signup <= 30)/s.customers, 2) AS ltv_30d,
       ROUND(SUM(o.line_revenue) FILTER (WHERE o.days_since_signup <= 90)/s.customers, 2) AS ltv_90d,
       ROUND(SUM(o.line_revenue) FILTER (WHERE o.days_since_signup <= 365)/s.customers, 2) AS ltv_365d
FROM orders_with_age o
JOIN cohort_sizes s ON s.cohort=o.cohort AND s.channel=o.channel
GROUP BY o.cohort, o.channel, s.customers
ORDER BY o.cohort, o.channel;
```

**Explanation.** LTV is measured at fixed ages since signup, so every cohort is compared at the same maturity. Dividing by cohort size (all acquired customers, not just buyers) makes it directly comparable to CAC.

**Common mistakes.** Raw lifetime totals — older cohorts always "win". Dividing by buyers rather than acquired customers, which silently removes the conversion rate from the comparison.

**Follow-up.** *"The newest cohort has a blank ltv_365d."* → It's censored. Only compare columns where every cohort has had time to mature, and grey out the rest rather than treating blanks as zeros.

---

### 21. Predicted LTV from cadence
```sql
WITH c AS (
  SELECT customer_id, COUNT(*) AS orders, AVG(order_value) AS aov,
         MAX(order_ts)::date - MIN(order_ts)::date AS span_days
  FROM order_values GROUP BY customer_id HAVING COUNT(*) >= 2)
SELECT customer_id, orders, ROUND(aov,2) AS aov,
       ROUND(orders::numeric/NULLIF(span_days,0)*365,2) AS predicted_annual_orders,
       ROUND(aov * orders::numeric/NULLIF(span_days,0)*365,2) AS predicted_annual_value
FROM c ORDER BY predicted_annual_value DESC;
```
**Caveat to volunteer.** Extrapolating from a short span is unstable — two orders a week apart implies 52 orders a year. Require a minimum span and order count before trusting it.

---

### 22. Churn prediction features
```sql
SELECT c.customer_id,
       COUNT(DISTINCT o.order_id)                          AS orders,
       CURRENT_DATE - MAX(o.order_ts)::date                AS recency,
       AVG(ov.order_value)                                 AS aov,
       STDDEV(ov.order_value)                              AS order_value_variability,
       COUNT(DISTINCT DATE_TRUNC('month',o.order_ts))      AS active_months,
       COUNT(DISTINCT p.category)                          AS categories_bought,
       COUNT(*) FILTER (WHERE o.status='refunded')         AS refunds,
       MAX(o.order_ts)::date - MIN(o.order_ts)::date       AS tenure_days
FROM customers c
LEFT JOIN orders o ON o.customer_id=c.customer_id
LEFT JOIN order_values ov ON ov.order_id=o.order_id
LEFT JOIN order_items oi ON oi.order_id=o.order_id
LEFT JOIN products p ON p.product_id=oi.product_id
GROUP BY c.customer_id;
```
**Follow-up.** *"Any leakage risk?"* → Yes, if features are computed over a window that includes the churn label's period. Features must come strictly from before the prediction date. Spotting leakage is a strong answer for any analyst role touching modelling.

---

### 23. Market basket lift
```sql
WITH totals AS (SELECT COUNT(DISTINCT order_id)::numeric AS n FROM order_items),
pair AS (
  SELECT i1.product_id a, i2.product_id b, COUNT(DISTINCT i1.order_id)::numeric AS together
  FROM order_items i1 JOIN order_items i2 ON i2.order_id=i1.order_id AND i2.product_id>i1.product_id
  GROUP BY 1,2),
single AS (SELECT product_id, COUNT(DISTINCT order_id)::numeric AS cnt FROM order_items GROUP BY 1)
SELECT pa.product_name, pb.product_name, p.together,
       ROUND((p.together/t.n) / ((sa.cnt/t.n)*(sb.cnt/t.n)), 2) AS lift
FROM pair p
CROSS JOIN totals t
JOIN single sa ON sa.product_id=p.a JOIN single sb ON sb.product_id=p.b
JOIN products pa ON pa.product_id=p.a JOIN products pb ON pb.product_id=p.b
WHERE p.together >= 5
ORDER BY lift DESC;
```
**Explanation.** Lift > 1 means the pair co-occurs more than chance. Raw co-occurrence counts just rank popular products; lift is what you'd act on.

---

### 24. Recursive: full organisational hierarchy
See Part 10.5. Include the depth guard and be able to say why `UNION ALL` rather than `UNION`.

---

### 25. Count all reports beneath each manager (direct and indirect)
```sql
WITH RECURSIVE tree AS (
    SELECT employee_id AS root, employee_id, 0 AS depth FROM employees
    UNION ALL
    SELECT t.root, e.employee_id, t.depth+1
    FROM employees e JOIN tree t ON e.manager_id = t.employee_id
    WHERE t.depth < 20
)
SELECT e.full_name, COUNT(*)-1 AS total_reports
FROM tree t JOIN employees e ON e.employee_id = t.root
GROUP BY e.employee_id, e.full_name ORDER BY total_reports DESC;
```

---

### 26. Detect cycles in a hierarchy
```sql
WITH RECURSIVE walk AS (
    SELECT employee_id, manager_id, ARRAY[employee_id] AS path, false AS cycle
    FROM employees
    UNION ALL
    SELECT e.employee_id, e.manager_id, w.path || e.employee_id, e.employee_id = ANY(w.path)
    FROM employees e JOIN walk w ON e.employee_id = w.manager_id
    WHERE NOT w.cycle
)
SELECT DISTINCT path FROM walk WHERE cycle;
```

---

### 27. Slowly changing dimension: point-in-time join
```sql
SELECT f.order_id, f.order_ts, d.country AS country_at_time_of_order
FROM orders f
JOIN dim_customer d
  ON d.customer_id = f.customer_id
 AND f.order_ts >= d.valid_from
 AND f.order_ts <  COALESCE(d.valid_to, TIMESTAMP 'infinity');
```
**Mistake.** Joining on the key alone against a Type 2 dimension multiplies every fact row by the number of versions. This is a real and expensive production bug.

---

### 28. Reconcile two data sources
```sql
SELECT COALESCE(a.order_id,b.order_id) AS order_id, a.total AS system, b.total AS finance,
       CASE WHEN a.order_id IS NULL THEN 'Missing from system'
            WHEN b.order_id IS NULL THEN 'Missing from finance'
            WHEN a.total IS DISTINCT FROM b.total THEN 'Value mismatch'
       END AS issue
FROM system_totals a FULL OUTER JOIN finance_totals b USING (order_id)
WHERE a.order_id IS NULL OR b.order_id IS NULL OR a.total IS DISTINCT FROM b.total;
```
**Explanation.** `IS DISTINCT FROM` so a NULL on one side registers as a mismatch instead of being skipped.

---

### 29. Deduplicate with fuzzy matching
```sql
SELECT a.patient_id, b.patient_id, a.nhs_number, b.nhs_number,
       SIMILARITY(a.surname, b.surname) AS name_similarity
FROM patients a JOIN patients b ON a.patient_id < b.patient_id
WHERE a.date_of_birth = b.date_of_birth
  AND LEFT(a.postcode_sector,3) = LEFT(b.postcode_sector,3)
  AND SIMILARITY(a.surname, b.surname) > 0.7;
```
**Explanation.** Block on exact fields first (DOB, partial postcode), then fuzzy-match within blocks. Without blocking, this is O(n²) and will never finish.

---

### 30. ★ Identify and quantify the impact of duplicate rows

**Problem.** You inherit a revenue report you suspect is inflated by duplicates. Quantify it.

**Solution.**
```sql
WITH dup_check AS (
    SELECT order_id, product_id, quantity, unit_price,
           COUNT(*) AS copies,
           SUM(quantity*unit_price) AS reported_value,
           MIN(quantity*unit_price) AS true_value
    FROM order_items
    GROUP BY order_id, product_id, quantity, unit_price
)
SELECT COUNT(*) FILTER (WHERE copies > 1)                     AS duplicated_groups,
       SUM(copies - 1) FILTER (WHERE copies > 1)              AS excess_rows,
       ROUND(SUM(reported_value),2)                           AS reported_total,
       ROUND(SUM(true_value),2)                               AS deduplicated_total,
       ROUND(SUM(reported_value) - SUM(true_value),2)         AS overstatement,
       ROUND(100.0*(SUM(reported_value)-SUM(true_value))/NULLIF(SUM(true_value),0),2) AS overstatement_pct
FROM dup_check;
```

**Explanation.** Group by every column that defines a genuine business record, count copies, and compare the reported sum against one-copy-per-group.

**The judgement call.** Two identical lines might be a genuine duplicate load, or a customer legitimately ordering the same product on two lines. Without a reliable unique key you cannot distinguish them from the data alone — you have to ask whether the source system permits split lines. Saying that, rather than assuming, is the answer.

**Follow-up.** *"How would you stop it recurring?"* → A unique constraint on the natural key, an idempotent load (delete-then-insert by batch, or upsert on the key), and a row-count reconciliation check in the pipeline that fails loudly.

---

### 31. Data quality scorecard
```sql
SELECT 'customers' AS table_name, COUNT(*) AS rows,
       ROUND(100.0*COUNT(email)/COUNT(*),1)                          AS pct_email_populated,
       ROUND(100.0*COUNT(country)/COUNT(*),1)                        AS pct_country_populated,
       COUNT(*) - COUNT(DISTINCT customer_id)                        AS duplicate_keys,
       COUNT(*) FILTER (WHERE signup_date > CURRENT_DATE)            AS future_dates,
       COUNT(*) FILTER (WHERE email !~* '^[^@\s]+@[^@\s]+\.[a-z]{2,}$') AS malformed_emails
FROM customers;
```

---

### 32. Detect a broken data pipeline
```sql
WITH daily AS (SELECT order_ts::date AS d, COUNT(*) AS rows FROM orders GROUP BY 1)
SELECT d, rows,
       ROUND(AVG(rows) OVER (ORDER BY d ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING),1) AS baseline,
       CASE WHEN rows = 0 THEN 'No data loaded'
            WHEN rows < 0.5*AVG(rows) OVER (ORDER BY d ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING)
                 THEN 'Suspiciously low'
            WHEN rows > 2.0*AVG(rows) OVER (ORDER BY d ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING)
                 THEN 'Suspiciously high - possible double load'
       END AS alert
FROM daily ORDER BY d DESC LIMIT 30;
```

---

### 33. Anomaly detection with seasonality
```sql
WITH daily AS (SELECT order_ts::date AS d, COUNT(*) AS orders FROM orders
               WHERE status='completed' GROUP BY 1),
seasonal AS (
  SELECT d, orders, EXTRACT(ISODOW FROM d) AS dow,
         AVG(orders) OVER (PARTITION BY EXTRACT(ISODOW FROM d)
                           ORDER BY d ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING) AS same_dow_baseline,
         STDDEV(orders) OVER (PARTITION BY EXTRACT(ISODOW FROM d)
                              ORDER BY d ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING) AS same_dow_sd
  FROM daily)
SELECT d, orders, ROUND(same_dow_baseline,1) AS expected,
       ROUND((orders-same_dow_baseline)/NULLIF(same_dow_sd,0),2) AS z
FROM seasonal
WHERE same_dow_sd > 0 AND ABS(orders-same_dow_baseline) > 2*same_dow_sd
ORDER BY d DESC;
```
**Explanation.** Comparing each Saturday to the last four Saturdays removes day-of-week seasonality, which otherwise flags every weekend as anomalous.

---

### 34. A/B test results with confidence
```sql
SELECT variant,
       COUNT(*) AS users,
       COUNT(*) FILTER (WHERE converted) AS conversions,
       ROUND(100.0*COUNT(*) FILTER (WHERE converted)/COUNT(*),2) AS cvr_pct,
       ROUND(100.0*1.96*SQRT(
           (COUNT(*) FILTER (WHERE converted)::numeric/COUNT(*))
         * (1 - COUNT(*) FILTER (WHERE converted)::numeric/COUNT(*)) / COUNT(*)),2) AS ci_half_width_pp
FROM experiment_assignments GROUP BY variant;
```
**Follow-up.** *"Confidence intervals overlap — what do you conclude?"* → Not significant at this sample size; report the observed difference with its interval and the power to detect the minimum effect worth caring about. Also check for sample ratio mismatch (unequal assignment counts) before trusting anything, since that usually indicates a broken experiment.

---

### 35. Sample ratio mismatch check
```sql
SELECT variant, COUNT(*) AS users,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),2) AS pct,
       ROUND(POWER(COUNT(*) - SUM(COUNT(*)) OVER ()/2.0, 2)
             / (SUM(COUNT(*)) OVER ()/2.0), 3) AS chi_sq_component
FROM experiment_assignments GROUP BY variant;
```

---

### 36. Attribution: first touch vs last touch
```sql
WITH touches AS (
  SELECT customer_id, event_ts, SUBSTRING(page_url FROM 'utm_source=([^&]+)') AS source
  FROM web_events WHERE page_url LIKE '%utm_source=%' AND customer_id IS NOT NULL),
conv AS (SELECT customer_id, MIN(order_ts) AS conversion_ts FROM orders
         WHERE status='completed' GROUP BY customer_id)
SELECT c.customer_id,
       (SELECT source FROM touches t WHERE t.customer_id=c.customer_id
         AND t.event_ts <= c.conversion_ts ORDER BY t.event_ts LIMIT 1)      AS first_touch,
       (SELECT source FROM touches t WHERE t.customer_id=c.customer_id
         AND t.event_ts <= c.conversion_ts ORDER BY t.event_ts DESC LIMIT 1) AS last_touch
FROM conv c;
```

---

### 37. Multi-touch attribution, linear
```sql
WITH touches AS (
  SELECT customer_id, source, COUNT(*) OVER (PARTITION BY customer_id) AS touch_count
  FROM marketing_touches)
SELECT source, ROUND(SUM(1.0/touch_count),2) AS attributed_conversions
FROM touches GROUP BY source ORDER BY attributed_conversions DESC;
```

---

### 38. Rolling retention (day N)
```sql
WITH signups AS (SELECT customer_id, signup_date FROM customers),
acts AS (SELECT DISTINCT customer_id, order_ts::date AS d FROM orders WHERE status='completed')
SELECT s.signup_date,
       COUNT(DISTINCT s.customer_id) AS cohort,
       COUNT(DISTINCT a.customer_id) FILTER (WHERE a.d - s.signup_date BETWEEN 1 AND 7)  AS active_d1_7,
       COUNT(DISTINCT a.customer_id) FILTER (WHERE a.d - s.signup_date BETWEEN 28 AND 34) AS active_d28_34
FROM signups s LEFT JOIN acts a USING (customer_id)
GROUP BY s.signup_date ORDER BY s.signup_date;
```

---

### 39. Customer journey: order of categories purchased
```sql
SELECT customer_id, STRING_AGG(category, ' > ' ORDER BY first_bought) AS journey
FROM (SELECT o.customer_id, p.category, MIN(o.order_ts) AS first_bought
      FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
      WHERE o.status='completed' GROUP BY 1,2) t
GROUP BY customer_id;
```
**Follow-up.** *"Most common journey?"* → Group by the aggregated string and count. Useful for spotting typical cross-sell paths.

---

### 40. ★ Waiting list: current position and projected wait

**Problem.** For each patient still waiting, their queue position within their specialty and a projected wait based on recent throughput.

**Solution.**
```sql
WITH still_waiting AS (
    SELECT r.referral_id, r.patient_id, r.specialty, r.priority, r.referral_date,
           CURRENT_DATE - r.referral_date AS days_waiting
    FROM referrals r
    JOIN waiting_list w ON w.referral_id = r.referral_id AND w.removed_date IS NULL
),
positions AS (
    SELECT *, ROW_NUMBER() OVER (
                 PARTITION BY specialty
                 ORDER BY CASE priority WHEN 'Two Week Wait' THEN 1
                                        WHEN 'Urgent' THEN 2 ELSE 3 END,
                          referral_date) AS queue_position
    FROM still_waiting
),
throughput AS (
    SELECT r.specialty,
           COUNT(*)::numeric / 12.0 AS avg_weekly_removals
    FROM waiting_list w JOIN referrals r ON r.referral_id = w.referral_id
    WHERE w.removed_date >= CURRENT_DATE - 84       -- last 12 weeks
    GROUP BY r.specialty
)
SELECT p.specialty, p.priority, p.patient_id, p.days_waiting, p.queue_position,
       ROUND(t.avg_weekly_removals,1) AS weekly_throughput,
       ROUND(p.queue_position / NULLIF(t.avg_weekly_removals,0), 1) AS projected_weeks_to_treatment,
       CASE WHEN p.days_waiting > 126 THEN 'Already breached 18 weeks'
            WHEN p.days_waiting + 7*p.queue_position/NULLIF(t.avg_weekly_removals,0) > 126
                 THEN 'Projected to breach'
            ELSE 'On track' END AS rtt_outlook
FROM positions p LEFT JOIN throughput t USING (specialty)
ORDER BY p.specialty, p.queue_position;
```

**Explanation.** The queue order encodes clinical priority before referral date, which is how the list actually works. Throughput comes from observed removals over a recent window rather than a planning assumption. The projection is a simple queue model: position ÷ throughput.

**Caveats to state.** It assumes throughput stays constant and no one jumps the queue clinically — both false, and the projection is indicative rather than a promise to a patient. Removals include deaths, declines and transfers, not just treatments, so filtering `removal_reason='Treated'` gives a more honest throughput figure.

**Follow-up.** *"How would you improve this?"* → Split throughput by priority, use a percentile of recent waits rather than a mean, and validate the projection against what actually happened for patients who have since been treated.

---

### 41. Time-to-event with censoring
```sql
SELECT r.specialty,
       COUNT(*) AS total_referrals,
       COUNT(*) FILTER (WHERE a.attended_ts IS NOT NULL) AS seen,
       COUNT(*) FILTER (WHERE a.attended_ts IS NULL)     AS censored_still_waiting,
       ROUND(AVG(a.attended_ts::date - r.referral_date) FILTER (WHERE a.attended_ts IS NOT NULL),1)
           AS mean_wait_completed,
       ROUND(AVG(CURRENT_DATE - r.referral_date) FILTER (WHERE a.attended_ts IS NULL),1)
           AS mean_wait_so_far_incomplete
FROM referrals r
LEFT JOIN LATERAL (SELECT attended_ts FROM appointments x
                   WHERE x.referral_id=r.referral_id AND x.outcome='Attended'
                   ORDER BY attended_ts LIMIT 1) a ON true
GROUP BY r.specialty;
```
**Explanation.** Reporting both completed and incomplete waits is the correct treatment of censored data — averaging only completed pathways systematically understates the wait.

---

### 42. Repeat A&E attendances within 7 days
```sql
SELECT a1.patient_id, a1.attendance_id, a1.arrival_ts, a2.arrival_ts AS reattendance,
       ROUND(EXTRACT(EPOCH FROM (a2.arrival_ts-a1.arrival_ts))/86400,1) AS days_later
FROM ae_attendances a1
JOIN ae_attendances a2 ON a2.patient_id=a1.patient_id
     AND a2.arrival_ts > a1.arrival_ts
     AND a2.arrival_ts <= a1.arrival_ts + INTERVAL '7 days'
ORDER BY a1.patient_id, a1.arrival_ts;
```
**Follow-up.** *"Why is this a quality metric?"* → Unplanned reattendance suggests the first episode didn't resolve the problem. It's a standard NHS indicator.

---

### 43. Seasonal decomposition, simple
```sql
WITH d AS (SELECT order_ts::date AS day, COUNT(*) AS orders FROM orders
           WHERE status='completed' GROUP BY 1),
t AS (SELECT day, orders,
             AVG(orders) OVER (ORDER BY day ROWS BETWEEN 3 PRECEDING AND 3 FOLLOWING) AS trend
      FROM d)
SELECT day, orders, ROUND(trend,1) AS trend, ROUND(orders-trend,1) AS residual,
       ROUND(AVG(orders-trend) OVER (PARTITION BY EXTRACT(ISODOW FROM day)),1) AS dow_effect
FROM t ORDER BY day;
```
**Explanation.** A centred 7-day moving average estimates trend; the average residual by weekday estimates the seasonal component. Crude but genuinely useful and entirely doable in SQL.

---

### 44. Correlation between two metrics
```sql
SELECT ROUND(CORR(discount_pct, quantity)::numeric,3) AS correlation,
       ROUND(REGR_SLOPE(quantity, discount_pct)::numeric,3) AS slope,
       COUNT(*) AS n
FROM order_items;
```
**Follow-up.** *"Does discounting cause higher volume?"* → Correlation isn't causation, and here it's confounded: discounts are applied to products that were already selling slowly, or during peaks when demand is high anyway. You'd need an experiment or a natural one.

---

### 45. Percentile bands with equal value ranges
```sql
SELECT WIDTH_BUCKET(lifetime_value, 0, 1000, 10) AS value_bucket,
       COUNT(*), ROUND(MIN(lifetime_value),2), ROUND(MAX(lifetime_value),2)
FROM customer_ltv GROUP BY 1 ORDER BY 1;
```
**Explanation.** `WIDTH_BUCKET` makes equal-width value bands; `NTILE` makes equal-count bands. Different tools for different questions, and confusing them produces misleading charts.

---

### 46. Cross join for a complete reporting matrix
```sql
SELECT c.category, m.month, COALESCE(r.revenue, 0) AS revenue
FROM (SELECT DISTINCT category FROM products) c
CROSS JOIN generate_series(DATE '2024-01-01', DATE '2024-06-01', INTERVAL '1 month') m(month)
LEFT JOIN category_monthly_revenue r ON r.category=c.category AND r.month=m.month
ORDER BY c.category, m.month;
```

---

### 47. Self-join to find overlapping date ranges
```sql
SELECT a.referral_id, b.referral_id, a.specialty
FROM referrals a JOIN referrals b
  ON a.patient_id=b.patient_id AND a.referral_id < b.referral_id
 AND a.referral_date <= b.referral_date + 30
 AND b.referral_date <= a.referral_date + 30;
```
**Explanation.** Two ranges overlap when each starts before the other ends — the general overlap condition, worth memorising.

---

### 48. Running distinct count (approximation)
```sql
SELECT d, COUNT(*) FILTER (WHERE is_first) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING) AS cumulative_customers
FROM (SELECT order_ts::date AS d, customer_id,
             ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts) = 1 AS is_first
      FROM orders WHERE status='completed') t;
```
**Explanation.** Cumulative distinct counts aren't windowable directly, but flagging each customer's first appearance and running-summing the flags gives an exact cumulative distinct count. A neat trick worth having.

---

### 49. Find the top N with a dynamic N per group
```sql
SELECT * FROM (
  SELECT p.*, ROW_NUMBER() OVER (PARTITION BY category ORDER BY revenue DESC) rn,
         COUNT(*) OVER (PARTITION BY category) cat_size
  FROM product_revenue p) t
WHERE rn <= GREATEST(1, CEIL(cat_size * 0.2));
```

---

### 50. ★ Build a complete customer 360 table

**Problem.** One row per customer with everything a stakeholder might ask for.

**Solution.**
```sql
WITH order_values AS (
    SELECT o.order_id, o.customer_id, o.order_ts, o.channel, o.status,
           SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)) AS order_value,
           SUM(oi.quantity) AS items
    FROM orders o JOIN order_items oi USING (order_id)
    GROUP BY o.order_id, o.customer_id, o.order_ts, o.channel, o.status
),
completed AS (SELECT * FROM order_values WHERE status='completed'),
core AS (
    SELECT customer_id,
           COUNT(*)                AS orders,
           SUM(order_value)        AS lifetime_value,
           AVG(order_value)        AS aov,
           SUM(items)              AS total_items,
           MIN(order_ts)::date     AS first_order,
           MAX(order_ts)::date     AS last_order,
           MODE() WITHIN GROUP (ORDER BY channel) AS preferred_channel
    FROM completed GROUP BY customer_id
),
categories AS (
    SELECT c.customer_id, COUNT(DISTINCT p.category) AS categories_bought,
           MODE() WITHIN GROUP (ORDER BY p.category) AS favourite_category
    FROM completed c JOIN order_items oi USING (order_id) JOIN products p USING (product_id)
    GROUP BY c.customer_id
),
returns AS (
    SELECT customer_id, COUNT(*) AS refunded_orders
    FROM order_values WHERE status='refunded' GROUP BY customer_id
),
cadence AS (
    SELECT customer_id, AVG(gap) AS avg_days_between_orders
    FROM (SELECT customer_id,
                 order_ts::date - LAG(order_ts::date) OVER (PARTITION BY customer_id ORDER BY order_ts) AS gap
          FROM completed) g
    WHERE gap IS NOT NULL GROUP BY customer_id
)
SELECT cu.customer_id, cu.first_name, cu.last_name, cu.country, cu.city,
       cu.channel AS acquisition_channel, cu.signup_date,
       COALESCE(co.orders,0)                                   AS orders,
       ROUND(COALESCE(co.lifetime_value,0),2)                  AS lifetime_value,
       ROUND(co.aov,2)                                         AS aov,
       co.first_order, co.last_order,
       co.first_order - cu.signup_date                         AS days_to_activate,
       CURRENT_DATE - co.last_order                            AS days_since_last_order,
       ROUND(ca.avg_days_between_orders,0)                     AS typical_gap_days,
       COALESCE(cat.categories_bought,0)                       AS categories_bought,
       cat.favourite_category, co.preferred_channel,
       COALESCE(r.refunded_orders,0)                           AS refunded_orders,
       NTILE(10) OVER (ORDER BY COALESCE(co.lifetime_value,0) DESC) AS value_decile,
       CASE WHEN co.orders IS NULL                                          THEN 'Never purchased'
            WHEN CURRENT_DATE - co.last_order <= 90                         THEN 'Active'
            WHEN CURRENT_DATE - co.last_order <= 365                        THEN 'Lapsing'
            ELSE 'Dormant' END                                  AS lifecycle_stage
FROM customers cu
LEFT JOIN core co       USING (customer_id)
LEFT JOIN categories cat USING (customer_id)
LEFT JOIN returns r     USING (customer_id)
LEFT JOIN cadence ca    USING (customer_id)
ORDER BY lifetime_value DESC;
```

**Explanation.** Each CTE computes one facet at customer grain, then a single LEFT JOIN chain assembles them. Because every branch is already at customer grain, nothing fans out. This is the correct general pattern for wide summary tables, and being able to produce it is close to a take-home-task-passing standard.

**Performance.** Several scans of `completed`. In production this becomes a materialised view or a nightly summary table with an index on `customer_id`, refreshed on a schedule.

**Follow-up.** *"How would you keep this fresh?"* → Incremental refresh: recompute only customers with activity since the last run, and merge into the target table. Full rebuild nightly is fine until it isn't.

---

### 51–75. Rapid-fire advanced problems

Each of these should take under ten minutes. Write your answer before reading the note.

**51.** Customers whose order values are consistently above average — every single order above the global mean. *(HAVING with MIN(order_value) > the global average.)*

**52.** The order that pushed cumulative revenue past £10,000. *(Running total, then filter where the running total crosses the threshold and the previous one didn't.)*

**53.** Rank products by revenue but exclude the top customer's contribution. *(Filter in the aggregate with FILTER, or anti-join the top customer first.)*

**54.** Products whose sales fell in three consecutive months. *(LAG twice, or gaps-and-islands on the "declined" flag.)*

**55.** Customers who have bought in every month since their first order. *(Count distinct active months = months elapsed since first order.)*

**56.** Median time between first and second order, by acquisition channel. *(ROW_NUMBER to pick orders 1 and 2, self-join, PERCENTILE_CONT grouped by channel.)*

**57.** Share of revenue from new vs returning customers each month. *(Classify each order by whether it's the customer's first, then conditional aggregation.)*

**58.** Products that are only ever bought alone. *(NOT EXISTS another line on the same order.)*

**59.** Orders where every line was discounted. *(GROUP BY order, HAVING COUNT(*) FILTER (WHERE discount_pct=0) = 0.)*

**60.** The most common pair of consecutive categories in a customer's purchase sequence. *(LAG the category over the customer's ordered purchases, group by the pair.)*

**61.** Customers whose spending is more variable than average. *(STDDEV per customer versus the average of those standard deviations.)*

**62.** Weekly cohort retention rather than monthly. *(Same as monthly with DATE_TRUNC('week') and a week offset.)*

**63.** Detect price changes over time from order history. *(DISTINCT product_id, unit_price with MIN/MAX order date per price; LAG to find changes.)*

**64.** Revenue per active customer per month. *(Monthly revenue ÷ monthly distinct active customers — note this is not the same as averaging customer-level values.)*

**65.** Customers who upgraded to a higher-value category over time. *(Compare first-purchase category average price against latest.)*

**66.** Longest gap between orders for each customer. *(MAX of the LAG-derived gaps.)*

**67.** Orders placed outside business hours by channel. *(EXTRACT(HOUR) and ISODOW filters, conditional aggregation.)*

**68.** Specialties where waiting times worsened month on month for three months. *(Monthly median wait, LAG twice or the islands method.)*

**69.** Patients appearing in both A&E and the elective waiting list within 30 days. *(Self-join across tables with an interval condition.)*

**70.** The proportion of revenue from customers acquired in the last 12 months. *(Conditional aggregation on signup date relative to the reporting date.)*

**71.** Products where revenue is concentrated in a single customer. *(Max customer share per product via a window over product totals — a concentration risk metric.)*

**72.** Simulate a "what if we removed all discounts" revenue figure. *(Sum quantity × unit_price without the discount factor, and state clearly that it assumes demand is unchanged, which it isn't.)*

**73.** Identify orders likely to be fraudulent by simple rules. *(Unusually high value versus the customer's history, new account, multiple orders within minutes — combine flags and score.)*

**74.** Build a daily snapshot table of the waiting list. *(CROSS JOIN a date series with the waiting list, keeping rows where the date falls between added and removed — this is how you reconstruct history from event data.)*

**75.** Given a query someone else wrote that runs for 40 minutes, describe your diagnostic process. *(EXPLAIN ANALYZE; compare estimated vs actual rows to spot bad statistics; find the node with the largest actual time; check for accidental cross joins, functions on filtered columns, unnecessary DISTINCT, and unbounded date ranges; check whether the result grain is even correct, because slow and wrong often share a cause.)*

---

## Self-check

By this point you should be able to:

- Build a cohort retention table from scratch without notes.
- Solve gaps and islands two different ways and explain both.
- Recognise censoring and survivorship bias in a metric and say so unprompted.
- Assemble a wide summary table without fan-out.
- Decompose a change into contributions that sum to the total.
- Read an EXPLAIN ANALYZE plan well enough to name the problem.
- Say "that metric definition is ambiguous, here's what I'd need to confirm" without it sounding like stalling.

That last one matters more than any query in this file.
