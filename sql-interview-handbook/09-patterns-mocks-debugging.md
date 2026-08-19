# Parts 17–19: Pattern Recognition, Mock Interviews, Debugging

---

# PART 17 — SQL INTERVIEW PATTERN RECOGNITION

Interview questions are phrased in business language. The skill is mapping the phrase to the technique before you start typing. Read the left column until the right column is automatic.

## 17.1 Master cheat sheet

### Selection and ranking

| When you hear | Think | Core construct |
|---|---|---|
| "latest / most recent record per X" | greatest-per-group | `ROW_NUMBER() OVER (PARTITION BY x ORDER BY ts DESC) = 1`, or `DISTINCT ON (x)` |
| "first / earliest per X" | same, ascending | `ROW_NUMBER() ... ORDER BY ts` |
| "top 3 per department/category" | top N per group | `ROW_NUMBER`/`DENSE_RANK() <= 3` in a subquery |
| "the single highest/lowest" | argmax | `ORDER BY ... LIMIT 1`, or `DISTINCT ON` |
| "second highest" | offset ranking | `DENSE_RANK() = 2`, or `LIMIT 1 OFFSET 1` |
| "including ties" | RANK family | `DENSE_RANK()` not `ROW_NUMBER` |
| "top 10%" | percentile | `NTILE(10) = 1` or `PERCENT_RANK() <= 0.1` |
| "rank them" | ranking window | `RANK()`, and ask about tie behaviour |
| "nth record" | positional | `ROW_NUMBER() = n` |

### Comparison across rows

| When you hear | Think | Core construct |
|---|---|---|
| "previous month / prior value" | offset | `LAG(x) OVER (ORDER BY month)` |
| "next transaction" | forward offset | `LEAD(x) OVER (...)` |
| "month-on-month change" | LAG + arithmetic | `(x - LAG(x))/NULLIF(LAG(x),0)` |
| "year-on-year" | date self-join | join on `month - INTERVAL '1 year'`, **not** `LAG(12)` |
| "compared to their first order" | FIRST_VALUE | `FIRST_VALUE(x) OVER (PARTITION BY c ORDER BY ts)` |
| "compared to the group average" | partitioned aggregate | `AVG(x) OVER (PARTITION BY g)` |
| "days between events" | LAG on a date | `d - LAG(d) OVER (...)` |
| "consecutive / streak / in a row" | gaps and islands | `d - ROW_NUMBER()` grouping, or flag-and-cumsum |

### Aggregation shapes

| When you hear | Think | Core construct |
|---|---|---|
| "running / cumulative total" | window sum | `SUM(x) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING)` |
| "moving / rolling average" | framed window | `AVG(x) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)` |
| "percentage of total" | window aggregate | `x / SUM(x) OVER ()` |
| "share within each group" | partitioned window | `x / SUM(x) OVER (PARTITION BY g)` |
| "cumulative share / 80-20" | Pareto | running sum ÷ grand total, both as windows |
| "customers who have more than N..." | group filter | `GROUP BY ... HAVING COUNT(*) > N` |
| "average per customer" | two-stage aggregation | aggregate to customer grain in a CTE, then average |
| "count of X and Y in one row" | conditional aggregation | `COUNT(*) FILTER (WHERE ...)` |
| "pivot months into columns" | conditional aggregation | `SUM(x) FILTER (WHERE month = ...)` |

### Presence and absence

| When you hear | Think | Core construct |
|---|---|---|
| "customers who never..." | anti-join | `NOT EXISTS`, or `LEFT JOIN ... WHERE key IS NULL` |
| "who have at least one..." | semi-join | `EXISTS` |
| "bought X but not Y" | EXISTS + NOT EXISTS | two correlated subqueries |
| "bought both X and Y" | two EXISTS, or HAVING | `HAVING COUNT(DISTINCT category) = 2` with a filter |
| "bought every product in..." | relational division | `HAVING COUNT(DISTINCT p) = (SELECT COUNT(*) FROM targets)` |
| "including those with zero" | outer join | `LEFT JOIN` + `COALESCE(...,0)`, filter in ON not WHERE |
| "missing dates / gaps" | calendar scaffold | `generate_series` + `LEFT JOIN`, or `LEAD` to find jumps |

### Business metrics

| When you hear | Think | Watch out for |
|---|---|---|
| "cohort" | first-event month + activity months + offset | month 0 must be 100% |
| "retention" | self-join on period offset | LEFT JOIN, or you get 100% |
| "churn" | define the rule first | no cancel event in retail — it's a threshold you choose |
| "funnel" | flags per session, then step ratios | collapse to session grain first |
| "conversion rate" | numerator ÷ denominator | sessions or users? `100.0 *` for float division |
| "AOV" | order-grain aggregate then average | not line-level average |
| "LTV" | sum per customer | biased by tenure — normalise by cohort age |
| "DAU/MAU" | distinct counts at two grains | distinct counts are not additive |
| "growth rate" | LAG or date self-join | tiny base makes percentages meaningless |
| "market share" | window sum as denominator | internal share ≠ market share |
| "SLA / breach rate" | interval comparison | what about still-open cases? |
| "waiting time" | date difference | completed-only averages hide the longest waits |

### Data quality

| When you hear | Think | Core construct |
|---|---|---|
| "duplicates" | ROW_NUMBER dedupe | define the key and the winner rule |
| "clean this data" | standardise → validate → dedupe | one CTE per step |
| "missing values" | COALESCE / NULLIF | is NULL a zero, or genuinely unknown? |
| "the numbers don't match" | reconciliation | `FULL OUTER JOIN` + `IS DISTINCT FROM` |
| "row counts are too high" | fan-out | pre-aggregate to a common grain before joining |
| "this query is slow" | EXPLAIN ANALYZE | estimated vs actual rows first |

## 17.2 Reflexes worth drilling

Five things to say without thinking, because each one signals experience:

1. **"What's the grain of this table?"** before writing any join.
2. **"Should cancelled and refunded orders count?"** before any revenue figure.
3. **"I'd use NOT EXISTS rather than NOT IN, because NOT IN returns nothing if the subquery has a NULL."**
4. **"I'll put that filter in the ON clause so the LEFT JOIN stays a LEFT JOIN."**
5. **"That'll be integer division — I'll multiply by 100.0."**

## 17.3 Phrase → clause quick map

- "for each" → `GROUP BY` or `PARTITION BY`
- "per" → same
- "at least / more than N" → `HAVING`
- "only / exclusively" → `NOT EXISTS` on the complement
- "in the last 30 days" → `>= CURRENT_DATE - INTERVAL '30 days'`
- "by month" → `DATE_TRUNC('month', ...)`
- "in March" (all years) → `EXTRACT(MONTH ...) = 3`
- "excluding" → `NOT EXISTS` or `<>` with a NULL check
- "including zero" → `LEFT JOIN` + `COALESCE`
- "consecutive" → gaps and islands
- "compared to" → window function or self-join
- "trend" → `LAG` or moving average
- "distribution" → `GROUP BY` the bucketed value, or percentiles

---

# PART 18 — TEN MOCK SQL INTERVIEWS

Do these out loud. Say your reasoning as you would in the room, then write the query, then read the follow-up before looking at the improved solution.

---

## Mock 1 — Junior: retail basics

**Interviewer.** "Here's our orders and customers tables. Can you tell me how many orders each customer placed last month, and include customers who didn't order?"

**Schema.** `customers(customer_id, first_name, last_name, country)`, `orders(order_id, customer_id, order_ts, status)`.

**Candidate thinking.** Every customer must appear, so LEFT JOIN from customers. "Last month" is a date range on the orders side, so it belongs in the ON clause, not WHERE, otherwise I lose the zero-order customers. Count the order id, not `*`.

**Candidate SQL.**
```sql
SELECT c.customer_id, c.first_name, c.last_name,
       COUNT(o.order_id) AS orders_last_month
FROM customers c
LEFT JOIN orders o
       ON o.customer_id = c.customer_id
      AND o.order_ts >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
      AND o.order_ts <  DATE_TRUNC('month', CURRENT_DATE)
GROUP BY c.customer_id, c.first_name, c.last_name
ORDER BY orders_last_month DESC;
```

**Expected output.** Every customer, with 0 for the inactive ones.

**Follow-up.** "What would happen if you'd put the date conditions in WHERE?"

**Answer.** Customers with no matching order get NULL in every `orders` column; `NULL >= date` is UNKNOWN, so WHERE drops those rows and the LEFT JOIN silently becomes an INNER JOIN.

**Junior vs strong.** A junior writes `COUNT(*)` and reports that everyone placed at least one order. A strong candidate uses `COUNT(o.order_id)`, explains the ON-vs-WHERE choice before being asked, and mentions that `DATE_TRUNC` makes "last month" reproducible regardless of when it's run.

---

## Mock 2 — Junior: aggregation and filtering

**Interviewer.** "Which product categories generated more than £10,000 in revenue this year?"

**Candidate thinking.** Revenue is on `order_items`. Categories are on `products`. Status is on `orders` — I should check whether cancelled and refunded orders count. I'll ask.

**Candidate.** *"Should I include refunded orders in revenue?"* — Interviewer: *"No, completed only."*

**Candidate SQL.**
```sql
SELECT p.category,
       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)), 2) AS revenue
FROM order_items oi
JOIN products p ON p.product_id = oi.product_id
JOIN orders   o ON o.order_id   = oi.order_id
WHERE o.status = 'completed'
  AND o.order_ts >= DATE_TRUNC('year', CURRENT_DATE)
GROUP BY p.category
HAVING SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) > 10000
ORDER BY revenue DESC;
```

**Follow-up.** "Why HAVING and not WHERE?"

**Answer.** The threshold is on an aggregate, which doesn't exist until after GROUP BY. WHERE runs first and can only see individual rows.

**Follow-up 2.** "Can you reference the alias `revenue` in HAVING?"

**Answer.** Not portably. Postgres allows aliases in GROUP BY and ORDER BY but not HAVING; repeat the expression, or wrap the aggregation in a CTE and filter outside — which reads better anyway.

**Junior vs strong.** The strong candidate asks about statuses before writing, and uses a CTE to avoid repeating the revenue expression twice.

---

## Mock 3 — Intermediate: the grain trap

**Interviewer.** "Give me total revenue and total shipping cost by month."

**Candidate thinking.** Revenue is on the line, shipping is on the order. If I join them and sum both, shipping gets multiplied by the number of lines. I need to aggregate lines to order grain first.

**Candidate SQL.**
```sql
WITH order_lines AS (
    SELECT order_id, SUM(quantity * unit_price * (1 - discount_pct)) AS product_revenue
    FROM order_items
    GROUP BY order_id
)
SELECT DATE_TRUNC('month', o.order_ts)::date AS month,
       ROUND(SUM(l.product_revenue), 2) AS product_revenue,
       ROUND(SUM(o.shipping_cost), 2)   AS shipping_revenue,
       COUNT(*) AS orders
FROM orders o
JOIN order_lines l ON l.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY 1 ORDER BY 1;
```

**Follow-up.** "What would the naive version have given you?"

**Answer.** Correct revenue, inflated shipping — each order's shipping counted once per line. A three-line order contributes triple.

**Follow-up 2.** "How would you have caught that in review?"

**Answer.** Compare `SUM(shipping_cost)` from `orders` alone against the joined version. Any difference means fan-out. More generally: check `COUNT(*)` before and after every join and know why it changed.

**Junior vs strong.** A junior writes the single join and ships a number that's 2.4× too high with no way of noticing. A strong candidate names the grain problem before writing and volunteers the reconciliation check.

---

## Mock 4 — Intermediate: window functions

**Interviewer.** "For each customer, show their orders in sequence with the value of the previous order and the change."

**Candidate SQL.**
```sql
WITH order_values AS (
    SELECT o.order_id, o.customer_id, o.order_ts,
           SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS order_value
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status = 'completed'
    GROUP BY o.order_id, o.customer_id, o.order_ts
)
SELECT customer_id, order_id, order_ts::date AS order_date,
       ROW_NUMBER() OVER w AS order_number,
       ROUND(order_value, 2) AS order_value,
       ROUND(LAG(order_value) OVER w, 2) AS previous_order_value,
       ROUND(order_value - LAG(order_value) OVER w, 2) AS change,
       order_ts::date - LAG(order_ts::date) OVER w AS days_since_previous
FROM order_values
WINDOW w AS (PARTITION BY customer_id ORDER BY order_ts)
ORDER BY customer_id, order_ts;
```

**Follow-up.** "Why is the first row's change NULL, and is that right?"

**Answer.** There's no previous order, so LAG returns NULL. It's correct — a change of zero would be a lie. If a default is needed for a dashboard, `LAG(order_value, 1, 0)` supplies one, but I'd only do that if the business wants it.

**Follow-up 2.** "Now flag customers whose most recent order was smaller than the one before."

**Answer.** Add `ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts DESC) AS rn_desc`, wrap in a subquery, filter `rn_desc = 1 AND order_value < previous_order_value`.

**Junior vs strong.** The `WINDOW` clause, naming the window once instead of repeating it four times, is a small thing that reads as fluency. So is knowing LAG's third argument exists.

---

## Mock 5 — Intermediate: the NULL trap

**Interviewer.** "Find customers who have never placed an order. Here's what a colleague wrote — it returns nothing. Why?"

```sql
SELECT * FROM customers
WHERE customer_id NOT IN (SELECT customer_id FROM orders);
```

**Candidate.** "If any row in `orders` has a NULL `customer_id`, `NOT IN` returns no rows at all. `x NOT IN (1,2,NULL)` expands to `x<>1 AND x<>2 AND x<>NULL`; the last comparison is UNKNOWN, so the whole AND can never be TRUE. It fails silently — an empty result, no error."

**Candidate SQL.**
```sql
SELECT c.* FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id);
```

**Follow-up.** "Any other way?"

**Answer.** LEFT JOIN with `WHERE o.order_id IS NULL` — an anti-join, same plan usually. Or keep NOT IN and add `WHERE customer_id IS NOT NULL` to the subquery, though I'd still prefer NOT EXISTS because it can't break again if the data changes.

**Follow-up 2.** "Which is fastest?"

**Answer.** Usually NOT EXISTS or the anti-join — both let the planner use a hash anti-join. NOT IN often can't, because it has to preserve the NULL semantics.

**Junior vs strong.** The junior says "add DISTINCT" or "I'm not sure". The strong candidate explains three-valued logic in two sentences and, unprompted, checks whether `orders.customer_id` actually contains NULLs.

---

## Mock 6 — Strong: cohort retention

**Interviewer.** "Build me a monthly cohort retention table. Talk me through it as you go."

**Candidate thinking, spoken.** "Three pieces. First, each customer's cohort — the month of their first completed order. Second, every month each customer was active. Third, join those and compute the offset in months, then count distinct customers per cohort per offset, divided by the original cohort size. Month 0 should come out at 100% for every cohort, which is my check that it's right."

**Candidate SQL.** As in Part 12.9.

**Follow-up.** "The most recent cohort has nothing beyond month 0. Has retention collapsed?"

**Answer.** No — those months haven't happened yet. Right-censoring. I'd only compare cohorts at ages every cohort has reached, and grey out or blank the immature cells rather than letting them read as zeros. Treating censored cells as zeros is how people conclude a product is dying when it isn't.

**Follow-up 2.** "Cohort by signup date instead of first purchase — what changes?"

**Answer.** It becomes activation plus retention combined. Customers who never buy are in the denominator, so month 0 is no longer 100% and the figures drop. Both are legitimate; signup cohorts are right for evaluating acquisition, purchase cohorts for evaluating the product experience.

**Follow-up 3.** "Retention improved from 40% to 55% between two cohorts. What would you check before celebrating?"

**Answer.** Cohort composition. If a poor-quality paid channel was switched off, retention improves without anything getting better — you just stopped buying customers who were never going to stay. I'd segment by acquisition channel and see whether within-channel retention moved at all.

**Junior vs strong.** The junior produces a correct table. The strong candidate produces the table, states the month-0 sanity check unprompted, and immediately identifies censoring and mix effects. The third answer is what gets the offer.

---

## Mock 7 — Strong: funnel and drop-off

**Interviewer.** "Our checkout conversion has dropped. Investigate with SQL."

**Candidate thinking.** First, quantify the drop and locate the step. Then segment to find where it's concentrated. Then check whether it's real or a tracking artefact.

**Step 1 — funnel by week.**
```sql
WITH session_steps AS (
    SELECT session_id, DATE_TRUNC('week', MIN(event_ts))::date AS week,
           MAX((event_name='product_view')::int)   AS viewed,
           MAX((event_name='add_to_cart')::int)    AS carted,
           MAX((event_name='checkout_start')::int) AS checkout,
           MAX((event_name='purchase')::int)       AS purchased,
           MAX(device) AS device
    FROM web_events
    WHERE event_ts >= CURRENT_DATE - 84
    GROUP BY session_id
)
SELECT week,
       SUM(viewed) AS viewed, SUM(carted) AS carted,
       SUM(checkout) AS checkout, SUM(purchased) AS purchased,
       ROUND(100.0*SUM(carted)/NULLIF(SUM(viewed),0),1)      AS view_to_cart,
       ROUND(100.0*SUM(checkout)/NULLIF(SUM(carted),0),1)    AS cart_to_checkout,
       ROUND(100.0*SUM(purchased)/NULLIF(SUM(checkout),0),1) AS checkout_to_purchase
FROM session_steps GROUP BY week ORDER BY week;
```

**Step 2 — segment the failing step by device and channel.** Add `device` to the GROUP BY; join sessions to acquisition source if available.

**Step 3 — rule out tracking.** Did total event volume for that step drop at the same time? If `checkout_start` events fell but purchases held steady, the event stopped firing rather than users stopping.

```sql
SELECT DATE_TRUNC('day', event_ts)::date AS day, event_name, COUNT(*) AS events
FROM web_events WHERE event_ts >= CURRENT_DATE - 60
GROUP BY 1,2 ORDER BY 1,2;
```

**Follow-up.** "Checkout-to-purchase fell from 60% to 45% on mobile only, three weeks ago. Next steps?"

**Answer.** Correlate with a release date. Check whether it's all mobile or specific browsers/OS versions if that's tracked. Check payment failure rates if there's a payments table. And check whether mobile traffic *mix* changed — a surge of low-intent paid mobile traffic lowers the rate without anything breaking.

**Junior vs strong.** The junior computes one overall conversion number. The strong candidate segments to localise the drop, and — the differentiator — checks whether the metric broke rather than the product. Instrumentation failures cause a large share of apparent metric drops, and knowing to rule that out first saves everyone a week.

---

## Mock 8 — Strong: NHS waiting times

**Interviewer.** "Report the average wait from referral to first appointment by specialty."

**Candidate.** *"Before I write it — do you want completed pathways only, or should patients still waiting be included? And by 'first appointment', do you mean the first attended one, or the first booked, including DNAs?"*

**Interviewer.** "Good question. First attended. And let's see both completed and incomplete."

**Candidate SQL.**
```sql
WITH first_seen AS (
    SELECT r.referral_id, r.specialty, r.priority, r.referral_date,
           (SELECT MIN(a.attended_ts)::date FROM appointments a
            WHERE a.referral_id = r.referral_id AND a.outcome = 'Attended') AS first_attended
    FROM referrals r
)
SELECT specialty,
       COUNT(*) FILTER (WHERE first_attended IS NOT NULL) AS completed_pathways,
       COUNT(*) FILTER (WHERE first_attended IS NULL)     AS still_waiting,
       ROUND(AVG(first_attended - referral_date) FILTER (WHERE first_attended IS NOT NULL),1)
           AS mean_wait_completed,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY first_attended - referral_date)
           FILTER (WHERE first_attended IS NOT NULL) AS median_wait_completed,
       ROUND(AVG(CURRENT_DATE - referral_date) FILTER (WHERE first_attended IS NULL),1)
           AS mean_wait_so_far_incomplete,
       COUNT(*) FILTER (WHERE COALESCE(first_attended, CURRENT_DATE) - referral_date > 126)
           AS over_18_weeks
FROM first_seen
GROUP BY specialty
ORDER BY median_wait_completed DESC;
```

**Follow-up.** "Why report the median as well as the mean?"

**Answer.** Waiting times are right-skewed. A handful of very long waits pull the mean up, so the mean overstates the typical wait while the median understates the tail. For a standard measured at the 92nd percentile, I'd report p92 too — that's the number that actually determines compliance.

**Follow-up 2.** "One specialty's average wait fell 20% this quarter. Is that good?"

**Answer.** Possibly, but check the queue. If they cleared a backlog of short-wait routine cases while long-waiters stayed on the list, the completed-pathway average falls while the situation gets worse. I'd look at the incomplete-pathway distribution and the total list size alongside it. Waiting time and list size have to be read together.

**Junior vs strong.** Asking the two clarifying questions up front is most of the marks. The rest is knowing that censored data flatters completed-only averages, and saying so before being asked.

---

## Mock 9 — Advanced: debugging someone else's query

**Interviewer.** "This is meant to give revenue per customer for 2024. Finance says it's wrong. Find the problems."

```sql
SELECT c.first_name, c.last_name,
       SUM(oi.quantity * oi.unit_price) AS revenue,
       COUNT(*) AS orders,
       o.shipping_cost
FROM customers c, orders o, order_items oi
WHERE c.customer_id = o.customer_id
  AND o.order_id = oi.order_id
  AND YEAR(o.order_ts) = 2024
GROUP BY c.first_name, c.last_name;
```

**Candidate, working through it.**

1. `YEAR()` doesn't exist in Postgres — it's `EXTRACT(YEAR FROM ...)`. So this doesn't even run. And wrapping the column in a function blocks index use; a half-open range is better.
2. `o.shipping_cost` is selected but not grouped or aggregated — that's a GROUP BY error in Postgres.
3. Grouping by name, not id — two customers with the same name merge into one row.
4. `COUNT(*)` counts order *lines*, not orders. Should be `COUNT(DISTINCT o.order_id)`.
5. No status filter — cancelled and refunded orders are counted as revenue.
6. `discount_pct` is ignored, so revenue is overstated on every discounted line.
7. Implicit comma joins hide the join conditions among the filters. Fine syntactically, poor practice.
8. Customers with no 2024 orders disappear entirely — may or may not be intended, worth confirming.

**Corrected.**
```sql
SELECT c.customer_id, c.first_name, c.last_name,
       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)), 2) AS revenue,
       COUNT(DISTINCT o.order_id) AS orders,
       ROUND(SUM(DISTINCT_SHIP.shipping), 2) AS shipping
FROM customers c
JOIN orders o  ON o.customer_id = c.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
JOIN LATERAL (SELECT o.shipping_cost AS shipping) DISTINCT_SHIP ON true
WHERE o.status = 'completed'
  AND o.order_ts >= DATE '2024-01-01' AND o.order_ts < DATE '2025-01-01'
GROUP BY c.customer_id, c.first_name, c.last_name;
```

**Candidate.** "Actually, that shipping column is still wrong — the LATERAL doesn't fix the fan-out. Shipping is order-level, so it needs a separate aggregation:"

```sql
WITH order_lines AS (
    SELECT order_id, SUM(quantity*unit_price*(1-discount_pct)) AS revenue
    FROM order_items GROUP BY order_id
)
SELECT c.customer_id, c.first_name, c.last_name,
       ROUND(SUM(l.revenue),2) AS revenue,
       COUNT(*) AS orders,
       ROUND(SUM(o.shipping_cost),2) AS shipping
FROM customers c
JOIN orders o ON o.customer_id=c.customer_id
JOIN order_lines l ON l.order_id=o.order_id
WHERE o.status='completed'
  AND o.order_ts >= DATE '2024-01-01' AND o.order_ts < DATE '2025-01-01'
GROUP BY c.customer_id, c.first_name, c.last_name;
```

**Junior vs strong.** The junior fixes the syntax error and stops. The strong candidate finds all eight issues, prioritises them by business impact (the status filter and the discount are the ones changing the number finance sees), and — notably — catches their own incomplete first fix rather than defending it.

---

## Mock 10 — Advanced: open-ended business problem

**Interviewer.** "Revenue was down 12% last month. You have full data access. Walk me through what you'd do."

**Candidate.** "I'd decompose before I explain. Revenue is orders × average order value, so first: which one moved?"

```sql
WITH monthly AS (
    SELECT DATE_TRUNC('month', o.order_ts)::date AS month,
           COUNT(DISTINCT o.order_id) AS orders,
           SUM(ov.order_value) AS revenue
    FROM orders o JOIN order_values ov USING (order_id)
    WHERE o.status='completed' GROUP BY 1
)
SELECT month, orders, ROUND(revenue,2) AS revenue,
       ROUND(revenue/NULLIF(orders,0),2) AS aov,
       ROUND(100.0*(orders - LAG(orders) OVER (ORDER BY month))
             /NULLIF(LAG(orders) OVER (ORDER BY month),0),1) AS order_growth_pct,
       ROUND(100.0*(revenue/NULLIF(orders,0) - LAG(revenue/NULLIF(orders,0)) OVER (ORDER BY month))
             /NULLIF(LAG(revenue/NULLIF(orders,0)) OVER (ORDER BY month),0),1) AS aov_growth_pct
FROM monthly ORDER BY month;
```

"Then: is it volume or value, and where is it concentrated? I'd run contribution analysis by category, channel and customer segment — the version in Part 12.21 that decomposes the total change into parts that sum back to it, so I can say 'Electronics accounts for 9 of the 12 points' rather than 'Electronics is down'."

"Then: new versus returning customers. If new customer orders fell, it's acquisition. If returning fell, it's retention or a product problem."

```sql
SELECT DATE_TRUNC('month',o.order_ts)::date AS month,
       COUNT(*) FILTER (WHERE seq = 1) AS first_orders,
       COUNT(*) FILTER (WHERE seq > 1) AS repeat_orders,
       ROUND(SUM(ov.order_value) FILTER (WHERE seq=1),2) AS new_customer_revenue,
       ROUND(SUM(ov.order_value) FILTER (WHERE seq>1),2) AS returning_revenue
FROM (SELECT o.*, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts) AS seq
      FROM orders o WHERE status='completed') o
JOIN order_values ov USING (order_id)
GROUP BY 1 ORDER BY 1;
```

"Then the boring checks, which I'd actually do first in practice: was last month shorter? Did it have fewer weekends or a bank holiday? Is the data complete — did a load fail? Is this outside normal month-to-month variation at all, or is 12% within the usual range? A 12% drop against a series that routinely swings 10% is not a finding."

```sql
-- variation check
SELECT ROUND(STDDEV(mom_pct),1) AS typical_monthly_swing, ROUND(AVG(mom_pct),1) AS mean_growth
FROM (SELECT 100.0*(revenue-LAG(revenue) OVER (ORDER BY month))
             /NULLIF(LAG(revenue) OVER (ORDER BY month),0) AS mom_pct
      FROM monthly) t WHERE mom_pct IS NOT NULL;

-- completeness check
SELECT order_ts::date AS d, COUNT(*) FROM orders
WHERE order_ts >= CURRENT_DATE - 60 GROUP BY 1 ORDER BY 1;
```

**Follow-up.** "You find paid search orders fell 40% and everything else is flat. What now?"

**Answer.** That localises it to one channel. Check spend — if the budget was cut, that's the whole story and it's a finance question, not an analytics one. If spend held, look at cost per click and impressions for a bidding or tracking change, and check whether the UTM tagging changed, which would move orders into 'unattributed' rather than losing them. I'd want to distinguish "we sold less" from "we labelled it differently" before anyone reacts.

**Junior vs strong.** The junior writes one query showing revenue by month and says revenue is down. The strong candidate decomposes systematically, checks the boring explanations before the interesting ones, quantifies whether the change is even outside normal variation, and separates a real decline from a measurement change. Notice how little of that answer is SQL technique.

---

# PART 19 — SQL DEBUGGING

## 19.1 A debugging method

1. **Does it run?** Syntax errors are the easy case — read the position marker in the error.
2. **Is the row count plausible?** Compare against the base table. More rows than expected means fan-out; fewer means an inner join or a filter dropping things.
3. **Is the grain right?** "One row per what?" applied to your output.
4. **Spot-check one entity.** Pick one customer, compute their number by hand from the raw rows, compare. This catches more real bugs than anything else.
5. **Check the edges.** Zero, NULL, ties, the first and last period, entities with no activity.
6. **Reconcile totals.** Your revenue total should match the total from a simpler query.
7. **Only then worry about speed.**

## 19.2 Broken queries — find the bug

Work through each before reading the answer.

---

**Bug 1**
```sql
SELECT customer_id, COUNT(*) FROM orders
WHERE COUNT(*) > 5 GROUP BY customer_id;
```
<details><summary>Answer</summary>

Aggregates can't appear in WHERE, which runs before grouping. Use `HAVING COUNT(*) > 5`.
</details>

---

**Bug 2**
```sql
SELECT category, product_name, AVG(unit_price) FROM products GROUP BY category;
```
<details><summary>Answer</summary>

`product_name` is neither grouped nor aggregated — an error in Postgres. Either add it to GROUP BY (changing the meaning entirely) or drop it. If you want the name alongside the category average, use a window function: `AVG(unit_price) OVER (PARTITION BY category)`.
</details>

---

**Bug 3**
```sql
SELECT c.customer_id, COUNT(*) AS orders
FROM customers c LEFT JOIN orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_id;
```
<details><summary>Answer</summary>

`COUNT(*)` returns 1 for customers with no orders, because the LEFT JOIN still produces a row. Use `COUNT(o.order_id)`.
</details>

---

**Bug 4**
```sql
SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id = c.customer_id
WHERE o.status = 'completed';
```
<details><summary>Answer</summary>

The WHERE filter on the right table eliminates the NULL-extended rows, so this is an inner join with extra steps. Move the condition into ON if you want to preserve all customers.
</details>

---

**Bug 5**
```sql
SELECT * FROM orders WHERE order_ts BETWEEN '2024-03-01' AND '2024-03-31';
```
<details><summary>Answer</summary>

`order_ts` is a timestamp; `'2024-03-31'` is midnight, so everything on 31 March after 00:00:00 is lost. Use `>= '2024-03-01' AND < '2024-04-01'`.
</details>

---

**Bug 6**
```sql
SELECT * FROM customers WHERE customer_id NOT IN (SELECT customer_id FROM orders);
```
<details><summary>Answer</summary>

Returns zero rows if any `orders.customer_id` is NULL. Use `NOT EXISTS`.
</details>

---

**Bug 7**
```sql
SELECT COUNT(*) FROM orders WHERE discount_code <> 'SPRING10';
```
<details><summary>Answer</summary>

Excludes every row where `discount_code IS NULL` — usually most of them. Use `IS DISTINCT FROM 'SPRING10'`.
</details>

---

**Bug 8**
```sql
SELECT o.order_id, SUM(oi.quantity), SUM(s.weight_kg)
FROM orders o
JOIN order_items oi USING (order_id)
JOIN shipments s USING (order_id)
GROUP BY o.order_id;
```
<details><summary>Answer</summary>

Join explosion. Two one-to-many joins off the same parent multiply each other: 3 items × 2 shipments = 6 rows, and both sums are inflated. Pre-aggregate each branch to order grain, then join the summaries.
</details>

---

**Bug 9**
```sql
SELECT COUNT(purchases) / COUNT(sessions) AS conversion_rate FROM funnel;
```
<details><summary>Answer</summary>

Two bugs. Integer division truncates to 0 for anything under 100% — multiply by `100.0`. And `COUNT(col)` counts non-NULL rows, not sums; if these are numeric columns you want `SUM`, not `COUNT`. Also add `NULLIF(denominator, 0)`.
</details>

---

**Bug 10**
```sql
SELECT customer_id, order_ts,
       LAST_VALUE(order_value) OVER (PARTITION BY customer_id ORDER BY order_ts) AS latest_value
FROM order_values;
```
<details><summary>Answer</summary>

The default frame ends at the current row, so `LAST_VALUE` returns the current row's own value on every row. Add `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`, or use `FIRST_VALUE(...) OVER (... ORDER BY order_ts DESC)`.
</details>

---

**Bug 11**
```sql
SELECT month, revenue, revenue - LAG(revenue) OVER (ORDER BY month) AS change
FROM monthly_revenue;
```
<details><summary>Answer</summary>

Only wrong if months can be missing. LAG returns the previous *row*, not the previous month, so a gap makes it compare across two months while labelling it as one. Zero-fill with `generate_series` first, or join on the date offset.
</details>

---

**Bug 12**
```sql
SELECT patient_id,
       CASE WHEN AGE(CURRENT_DATE, date_of_birth) < INTERVAL '18 years' THEN '0-17'
            WHEN AGE(CURRENT_DATE, date_of_birth) < INTERVAL '65 years' THEN '18-64'
            ELSE '65+' END AS age_band
FROM patients;
```
<details><summary>Answer</summary>

Patients with a NULL date of birth fail every comparison (all UNKNOWN) and fall into `ELSE`, silently labelled '65+'. Add `WHEN date_of_birth IS NULL THEN 'Unknown'` as the **first** branch.
</details>

---

**Bug 13**
```sql
SELECT * FROM (
  SELECT customer_id, order_ts,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts DESC) rn
  FROM orders) t
WHERE rn = 1;
```
<details><summary>Answer</summary>

Not wrong exactly, but non-deterministic: if a customer has two orders with identical timestamps, which one wins changes between runs. Add a unique tie-breaker: `ORDER BY order_ts DESC, order_id DESC`. Also, no status filter — is that intended?
</details>

---

**Bug 14**
```sql
SELECT AVG(feedback_score) FROM survey_responses;
```
<details><summary>Answer</summary>

`AVG` ignores NULLs, so this averages only respondents. If non-response should count as zero, you need `AVG(COALESCE(feedback_score,0))`. Which is right is a business decision — but silently picking one without knowing is the bug.
</details>

---

**Bug 15**
```sql
SELECT DISTINCT c.customer_id, c.first_name, SUM(oi.quantity*oi.unit_price) AS revenue
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY c.customer_id, c.first_name;
```
<details><summary>Answer</summary>

The `DISTINCT` is pointless — GROUP BY already guarantees one row per group. Its presence suggests the author didn't understand why they had duplicates and added DISTINCT hopefully. Harmless here, but a red flag in review. Also missing a status filter.
</details>

---

**Bug 16**
```sql
SELECT e.full_name, m.full_name AS manager
FROM employees e JOIN employees m ON m.employee_id = e.manager_id;
```
<details><summary>Answer</summary>

Inner join drops the CEO, whose `manager_id` is NULL. Use LEFT JOIN. Any org chart missing exactly one person at the top is this bug.
</details>

---

**Bug 17**
```sql
SELECT category, SUM(revenue) / SUM(units) AS revenue_per_unit
FROM sales GROUP BY category;
```
<details><summary>Answer</summary>

Division by zero if any category has zero units — the whole query errors out, not just that row. `NULLIF(SUM(units), 0)`.
</details>

---

**Bug 18**
```sql
SELECT DATE_TRUNC('month', order_ts) AS month, COUNT(*)
FROM orders GROUP BY EXTRACT(MONTH FROM order_ts);
```
<details><summary>Answer</summary>

SELECT and GROUP BY disagree — grouping merges all Marches across years while the SELECT shows a specific month, so Postgres errors (the selected expression isn't grouped). Even if it ran, the intent is ambiguous. Pick one: `DATE_TRUNC` for a time series, `EXTRACT` for seasonality.
</details>

---

**Bug 19**
```sql
SELECT * FROM orders o
JOIN dim_customer d ON d.customer_id = o.customer_id;
```
<details><summary>Answer</summary>

If `dim_customer` is an SCD Type 2 dimension with one row per version, this multiplies every order by the number of versions of that customer. Join on the key **and** the validity window, or restrict to `d.is_current`.
</details>

---

**Bug 20**
```sql
SELECT ROUND(100 * COUNT(*) FILTER (WHERE outcome='DNA') / COUNT(*), 1) AS dna_rate
FROM appointments GROUP BY specialty;
```
<details><summary>Answer</summary>

Three problems. `100 *` with two integer counts gives integer division — every rate rounds to 0 unless it's exactly 100%. Use `100.0`. `specialty` isn't a column of `appointments` (it's on `referrals`) so this needs a join. And there's no minimum-denominator guard, so a specialty with two appointments and one DNA reports a 50% rate.
</details>

## 19.3 Error messages and what they usually mean

| Postgres error | Usual cause |
|---|---|
| `column "x" must appear in the GROUP BY clause` | selected a column that's neither grouped nor aggregated |
| `aggregate functions are not allowed in WHERE` | use HAVING |
| `column "revenue" does not exist` in WHERE | referencing a SELECT alias too early |
| `subquery must return only one column` | scalar subquery selecting several columns |
| `more than one row returned by a subquery used as an expression` | scalar subquery matched multiple rows — your key isn't unique |
| `division by zero` | missing `NULLIF(denominator, 0)` |
| `operator does not exist: text = integer` | type mismatch on a join or comparison |
| `syntax error at or near ")"` | trailing comma in a column list, or an unclosed bracket above |
| `subquery in FROM must have an alias` | derived table with no alias |
| `window functions are not allowed in WHERE` | wrap in a subquery/CTE and filter outside |
| `relation "x" does not exist` | typo, wrong schema, or missing `search_path` |
| `INSERT has more expressions than target columns` | column list and values out of step |

## 19.4 Sanity checks to run before shipping any query

```sql
-- 1. row counts before and after each join
SELECT COUNT(*) FROM orders;                                  -- baseline
SELECT COUNT(*) FROM orders JOIN order_items USING (order_id); -- expect more, know why

-- 2. is the key unique?
SELECT key, COUNT(*) FROM your_result GROUP BY key HAVING COUNT(*) > 1;

-- 3. any unexpected NULLs in the output?
SELECT COUNT(*) FILTER (WHERE metric IS NULL) FROM your_result;

-- 4. does the total reconcile to a simpler query?
SELECT SUM(revenue) FROM your_result;
SELECT SUM(quantity*unit_price*(1-discount_pct)) FROM order_items
WHERE order_id IN (SELECT order_id FROM orders WHERE status='completed');

-- 5. spot-check one entity by hand
SELECT * FROM orders WHERE customer_id = 1;
```

If you do nothing else before sending a number to a stakeholder, do check 5. Picking one customer and verifying their figure by hand catches grain errors, filter errors and join errors all at once, in about ninety seconds.
