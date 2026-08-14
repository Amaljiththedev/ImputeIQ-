# Parts 6–8: NULLs & Data Cleaning, Strings, Dates

---

# PART 6 — NULLS AND DATA CLEANING

## 6.1 What NULL actually means

NULL is a marker for "no value here". It is not a value itself, which is why it doesn't behave like one. There are at least four distinct real-world situations that all arrive in your table as NULL, and conflating them is where analysts go wrong:

| Meaning | Example | Correct handling |
|---|---|---|
| Unknown | patient's date of birth not recorded | keep NULL, report separately |
| Not applicable | `manager_id` for the CEO | keep NULL, LEFT JOIN |
| Not yet | `departure_ts` for a patient still in A&E | keep NULL, it's a live state |
| Genuinely zero | no orders this month | should be 0, not NULL |

The last row is the one that causes reporting errors. A month with no sales *has* revenue of £0. If your query returns NULL because no rows existed to sum, you must convert it.

## 6.2 NULL vs 0 vs empty string

Three different things, and interviewers ask about the distinction explicitly.

```sql
SELECT
  COUNT(*)                    AS rows,      -- 3
  COUNT(val)                  AS non_null,  -- 2 (NULL excluded)
  SUM(val)                    AS total,     -- 5 (NULL ignored)
  AVG(val)                    AS mean       -- 2.5, NOT 1.67
FROM (VALUES (5),(0),(NULL)) AS t(val);
```

`AVG` here divides 5 by 2, not by 3. If the NULL genuinely means zero, your average is 50% too high. That single example is worth memorising as your answer to "what's the difference between NULL and 0?".

Empty string is a *value*, and a different one from NULL:

```sql
SELECT '' IS NULL;              -- false
SELECT LENGTH('');              -- 0
SELECT LENGTH(NULL);            -- NULL
SELECT COUNT(*) FROM customers WHERE email = '';       -- counts empties only
SELECT COUNT(*) FROM customers WHERE email IS NULL;    -- counts nulls only
```

Real extracts contain all of: NULL, `''`, `'   '`, `'NULL'` (the literal string), `'N/A'`, `'-'`, `'unknown'`. Standardising them is step one of any cleaning job:

```sql
NULLIF(NULLIF(NULLIF(TRIM(email), ''), 'N/A'), 'NULL') AS email_clean
-- or more readably
CASE WHEN TRIM(COALESCE(email,'')) IN ('', 'N/A', 'NULL', '-', 'unknown') THEN NULL
     ELSE TRIM(email) END AS email_clean
```

**Dialect.** Oracle famously treats the empty string as NULL, so `'' IS NULL` is true there. Postgres, SQL Server and MySQL keep them distinct. Mention it if you're asked about portability.

## 6.3 NULL propagation in arithmetic and concatenation

Any operation involving NULL yields NULL.

```sql
SELECT 100 + NULL;                    -- NULL
SELECT 'abc' || NULL;                 -- NULL  (!!)
SELECT CONCAT('abc', NULL);           -- 'abc' (CONCAT skips NULLs)
SELECT GREATEST(1, NULL, 3);          -- 3     (GREATEST/LEAST skip NULLs in Postgres)
```

The `||` case bites constantly. Building an address by concatenating five fields returns NULL for any customer missing one of them — so a missing county wipes out the entire address. Use `CONCAT_WS` (Part 7) or `COALESCE` each part.

```sql
-- broken: any NULL component nulls the whole thing
SELECT address_line_1 || ', ' || city || ', ' || postcode FROM customers;

-- fine
SELECT CONCAT_WS(', ', address_line_1, NULLIF(TRIM(city),''), postcode) FROM customers;
```

## 6.4 COALESCE

Returns the first non-NULL argument. Takes any number of arguments; they must be type-compatible.

```sql
COALESCE(email, 'no email on file')
COALESCE(discount_pct, 0)
COALESCE(preferred_name, first_name, 'Customer')      -- fallback chain
COALESCE(removed_date, CURRENT_DATE)                  -- treat "still open" as today
COALESCE(SUM(revenue), 0)                             -- empty groups report zero
```

The `COALESCE(end_date, CURRENT_DATE)` idiom is how you compute durations for open-ended records — waiting list time for patients still waiting, tenure for current employees, session length for a session still in progress.

```sql
-- current waiting time, including people still on the list
SELECT w.waiting_id,
       COALESCE(w.removed_date, CURRENT_DATE) - w.added_date AS days_waiting,
       (w.removed_date IS NULL) AS still_waiting
FROM waiting_list w;
```

Be careful: COALESCE inside a WHERE clause on an indexed column blocks the index. `WHERE COALESCE(status,'x') <> 'cancelled'` will scan. Rewrite as `WHERE status IS NULL OR status <> 'cancelled'`.

**Dialect.** `COALESCE` is standard and works everywhere. `ISNULL()` is SQL Server's two-argument version, `IFNULL()` is MySQL's, `NVL()` is Oracle's. Use COALESCE.

## 6.5 NULLIF

`NULLIF(a, b)` returns NULL if `a = b`, otherwise returns `a`. It has exactly two everyday uses.

**Guarding division by zero** — the important one:

```sql
SELECT category,
       SUM(revenue) / NULLIF(SUM(units), 0) AS revenue_per_unit
FROM sales GROUP BY category;
```

Division by zero raises an error and kills the whole query; dividing by NULL returns NULL and lets the rest of the report through. Every rate, ratio and percentage you write should have `NULLIF(denominator, 0)`. This is one of the fastest ways to look experienced.

**Converting sentinel values to NULL**:

```sql
NULLIF(TRIM(city), '')          -- blank becomes NULL
NULLIF(age, -1)                 -- -1 used as "not recorded"
NULLIF(imd_decile, 0)           -- 0 is not a valid decile
```

## 6.6 Aggregates, joins and NULL

Recap the behaviours that get tested:

```sql
-- 1. aggregates ignore NULL, COUNT(*) doesn't
SELECT COUNT(*), COUNT(email) FROM customers;

-- 2. GROUP BY treats all NULLs as ONE group
SELECT country, COUNT(*) FROM customers GROUP BY country;  -- one row where country IS NULL

-- 3. DISTINCT treats all NULLs as one value
SELECT COUNT(DISTINCT country) FROM customers;             -- NULL not counted at all

-- 4. NULL keys never join
-- 5. UNION deduplicates NULLs as if equal
-- 6. ORDER BY: NULLs last for ASC, first for DESC (Postgres default)
```

Points 2 and 3 look contradictory and are worth stating carefully: GROUP BY puts all NULLs in one group *and shows it*, while `COUNT(DISTINCT col)` excludes NULLs entirely. So a table with 3 countries plus some NULLs gives 4 groups from GROUP BY but `COUNT(DISTINCT country) = 3`.

## 6.7 The classic NULL interview traps

**Trap 1 — NOT IN with NULLs.** Covered in Part 2.4. Returns zero rows. Use NOT EXISTS.

**Trap 2 — the inequality that loses rows.**

```sql
SELECT COUNT(*) FROM orders WHERE discount_code <> 'SPRING10';
```
Excludes every order where `discount_code IS NULL` — usually the majority. The stakeholder asked "how many orders didn't use SPRING10?" and you've undercounted badly.
```sql
WHERE discount_code IS DISTINCT FROM 'SPRING10'
```

**Trap 3 — NOT (condition) doesn't complement the condition.** `WHERE x > 10` and `WHERE NOT (x > 10)` together do not return every row, because NULLs satisfy neither.

**Trap 4 — CHECK constraints pass on NULL.** `CHECK (age >= 0)` accepts NULL ages, because the check must evaluate to false to reject and NULL isn't false.

**Trap 5 — LEFT JOIN then COUNT(\*).** Returns 1 for unmatched rows. Count the right table's key.

**Trap 6 — LEFT JOIN then filter in WHERE.** Turns it into an inner join. Part 4.3.

**Trap 7 — UNIQUE allows multiple NULLs.** In Postgres a unique column may contain many NULL rows, because NULLs aren't equal to each other. So a UNIQUE email column does not prevent 500 customers with no email.

**Trap 8 — AVG excludes rather than zeroes.** Part 6.2.

**Trap 9 — NULL in a boolean.** `WHERE is_active` drops rows where `is_active IS NULL` and rows where it's false, identically. If NULL means "not yet decided", use `WHERE is_active IS NOT FALSE` or be explicit.

**Trap 10 — string concatenation with `||`.** Part 6.3.

## 6.8 Duplicate records

There are two kinds of duplicate and they need different fixes.

**Exact duplicates** — every column identical, typically from a load run twice.

```sql
-- detect
SELECT order_id, customer_id, order_ts, COUNT(*) AS copies
FROM orders_staging
GROUP BY order_id, customer_id, order_ts
HAVING COUNT(*) > 1;

-- count how bad it is
SELECT COUNT(*) AS rows, COUNT(DISTINCT order_id) AS distinct_orders FROM orders_staging;
```

**Business duplicates** — different rows representing the same real thing. Same customer registered twice with different emails; the same referral entered under two IDs. These are harder and need fuzzy matching on name + DOB + postcode, or a defined match key.

```sql
-- candidate duplicate customers on a normalised key
SELECT LOWER(TRIM(last_name)) AS ln, date_of_birth, postcode_sector,
       COUNT(*) AS records, ARRAY_AGG(patient_id) AS ids
FROM patients
GROUP BY 1,2,3
HAVING COUNT(*) > 1;
```

## 6.9 Deduplication techniques

**Keep one row per key — ROW_NUMBER, the general answer.**

```sql
WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY customer_id           -- the key that should be unique
               ORDER BY updated_at DESC, id DESC  -- which copy wins: newest, tie-broken by id
           ) AS rn
    FROM customer_staging
)
SELECT * FROM ranked WHERE rn = 1;
```

The ORDER BY inside the window is the business rule — "keep the most recently updated record" — made explicit. Always include a deterministic tie-breaker (`id`), otherwise the same query can return different rows on different runs and your pipeline becomes non-reproducible. Interviewers who have been burned by this will ask.

**Postgres shortcut:**

```sql
SELECT DISTINCT ON (customer_id) *
FROM customer_staging
ORDER BY customer_id, updated_at DESC, id DESC;
```

**Exact duplicates only — DISTINCT or GROUP BY:**

```sql
SELECT DISTINCT * FROM orders_staging;
```

**Deleting duplicates in place, keeping the lowest ctid** (Postgres physical row identifier — useful when there is genuinely no unique column):

```sql
DELETE FROM orders_staging a
USING orders_staging b
WHERE a.ctid > b.ctid
  AND a.order_id = b.order_id;
```

**Comparing the three approaches** — an interviewer may ask which you'd use:

| Method | When | Caveat |
|---|---|---|
| `DISTINCT` | whole rows identical | can't choose which copy to keep |
| `GROUP BY` + aggregates | want to merge values across copies | must aggregate every column |
| `ROW_NUMBER` | need a rule for which copy wins | portable, most flexible |
| `DISTINCT ON` | same, Postgres only | shortest, fastest |

## 6.10 Invalid values and standardisation

Real data validation checks, all of which make good things to volunteer in an interview:

```sql
SELECT
  COUNT(*) FILTER (WHERE quantity <= 0)                              AS bad_quantity,
  COUNT(*) FILTER (WHERE unit_price < 0)                             AS negative_price,
  COUNT(*) FILTER (WHERE discount_pct < 0 OR discount_pct > 1)       AS impossible_discount,
  COUNT(*) FILTER (WHERE unit_price < 0.01)                          AS suspicious_free
FROM order_items;

SELECT
  COUNT(*) FILTER (WHERE date_of_birth > CURRENT_DATE)               AS future_dob,
  COUNT(*) FILTER (WHERE date_of_birth < DATE '1900-01-01')          AS implausible_dob,
  COUNT(*) FILTER (WHERE imd_decile NOT BETWEEN 1 AND 10)            AS bad_decile,
  COUNT(*) FILTER (WHERE nhs_number !~ '^[0-9]{10}$')                AS malformed_nhs_no
FROM patients;

-- referential and temporal sanity
SELECT COUNT(*) FROM ae_attendances WHERE departure_ts < arrival_ts;   -- time travel
SELECT COUNT(*) FROM appointments  WHERE attended_ts < scheduled_ts - INTERVAL '1 day';
```

**Standardisation** — collapsing variant spellings to one canonical value:

```sql
SELECT
    CASE
      WHEN UPPER(TRIM(country)) IN ('UK','GB','GBR','UNITED KINGDOM','GREAT BRITAIN','ENGLAND',
                                     'SCOTLAND','WALES','NORTHERN IRELAND') THEN 'UK'
      WHEN UPPER(TRIM(country)) IN ('IE','IRL','IRELAND','REPUBLIC OF IRELAND','EIRE') THEN 'IE'
      WHEN TRIM(COALESCE(country,'')) = '' THEN NULL
      ELSE INITCAP(TRIM(country))
    END AS country_clean,
    COUNT(*)
FROM customers
GROUP BY 1;
```

In production this belongs in a lookup/mapping table joined at load time, not a CASE statement buried in one query — otherwise every analyst writes their own slightly different version and the numbers stop agreeing. Saying that shows you think about maintainability, which is exactly what distinguishes an analyst from someone who writes queries.

## 6.11 A complete cleaning pipeline

Worth reading end to end; it's the shape of a real staging-to-clean transformation and a strong thing to sketch on a whiteboard.

```sql
WITH standardised AS (
    SELECT
        customer_id,
        INITCAP(TRIM(first_name))                        AS first_name,
        INITCAP(TRIM(last_name))                         AS last_name,
        NULLIF(LOWER(TRIM(email)), '')                   AS email,
        CASE WHEN UPPER(TRIM(country)) IN ('UK','GB','UNITED KINGDOM') THEN 'UK'
             WHEN TRIM(COALESCE(country,'')) = ''        THEN NULL
             ELSE UPPER(TRIM(country)) END               AS country,
        signup_date,
        COALESCE(marketing_opt_in, false)                AS marketing_opt_in,
        updated_at
    FROM customers_raw
),
validated AS (
    SELECT *,
        CASE WHEN email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' THEN false ELSE true END AS email_valid,
        (signup_date <= CURRENT_DATE)                                            AS signup_plausible
    FROM standardised
),
deduplicated AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id
                                 ORDER BY updated_at DESC NULLS LAST, customer_id) AS rn
    FROM validated
)
SELECT customer_id, first_name, last_name,
       CASE WHEN email_valid THEN email ELSE NULL END AS email,
       country, signup_date, marketing_opt_in
FROM deduplicated
WHERE rn = 1
  AND signup_plausible;
```

Each CTE does one job: standardise, validate, deduplicate, select. That structure is readable, individually testable (run any CTE alone to inspect it), and easy for a reviewer to follow — which is the argument for CTEs generally, made in Part 10.

## 6.12 NULL and cleaning exercises

1. Count customers with a missing email, and separately those with a blank one.
2. Compute the average feedback score twice — excluding non-responses, and treating them as zero.
3. Find orders whose discount code isn't SPRING10, including those with no code.
4. Safely compute conversion rate where some days have zero sessions.
5. Find duplicate patients on name + DOB + postcode sector.
6. Keep only the latest record per customer from a staging table with an `updated_at`.
7. Build a full display address from four possibly-NULL components.
8. Find order lines with impossible values.
9. Compute days waiting for everyone on the waiting list, including those still waiting.
10. Report customers per country, showing 'Unknown' rather than a blank row for missing countries.

```sql
-- 1
SELECT COUNT(*) FILTER (WHERE email IS NULL)      AS missing,
       COUNT(*) FILTER (WHERE TRIM(email) = '')   AS blank
FROM customers;

-- 2
SELECT AVG(score) AS excluding_nonresponse,
       AVG(COALESCE(score,0)) AS treating_as_zero,
       COUNT(*) AS surveyed, COUNT(score) AS responded
FROM survey;

-- 3
SELECT * FROM orders WHERE discount_code IS DISTINCT FROM 'SPRING10';

-- 4
SELECT day, ROUND(100.0 * purchases / NULLIF(sessions,0), 2) AS conversion_pct
FROM daily_funnel;

-- 5
SELECT LOWER(TRIM(p.postcode_sector)) AS pc, p.date_of_birth,
       COUNT(*) AS n, ARRAY_AGG(p.patient_id) AS patient_ids
FROM patients p GROUP BY 1,2 HAVING COUNT(*) > 1;

-- 6
SELECT DISTINCT ON (customer_id) *
FROM customer_staging ORDER BY customer_id, updated_at DESC, customer_id;

-- 7
SELECT CONCAT_WS(', ', NULLIF(TRIM(line1),''), NULLIF(TRIM(line2),''),
                       NULLIF(TRIM(city),''),  NULLIF(TRIM(postcode),'')) AS address
FROM addresses;

-- 8
SELECT * FROM order_items
WHERE quantity <= 0 OR unit_price < 0 OR discount_pct NOT BETWEEN 0 AND 1
   OR quantity IS NULL OR unit_price IS NULL;

-- 9
SELECT waiting_id, added_date,
       COALESCE(removed_date, CURRENT_DATE) - added_date AS days_waiting,
       removed_date IS NULL AS still_waiting
FROM waiting_list;

-- 10
SELECT COALESCE(NULLIF(TRIM(country),''), 'Unknown') AS country, COUNT(*)
FROM customers GROUP BY 1 ORDER BY 2 DESC;
```

---

# PART 7 — STRING FUNCTIONS

Analysts spend more time on strings than they expect: cleaning names, parsing URLs, extracting postcode areas, splitting delimited fields, matching messy free text.

## 7.1 Concatenation

```sql
SELECT first_name || ' ' || last_name          AS full_name;       -- NULL if either is NULL
SELECT CONCAT(first_name, ' ', last_name)      AS full_name;       -- NULLs become ''
SELECT CONCAT_WS(', ', city, county, postcode) AS address;         -- separator, skips NULLs
```

`CONCAT_WS` is the one to reach for with optional components: it puts the separator only between the values that exist, so a missing county doesn't leave a doubled comma.

```sql
SELECT CONCAT_WS(', ', 'Leeds', NULL, 'LS1 4AB');   -- 'Leeds, LS1 4AB'
SELECT 'Leeds' || ', ' || NULL || ', ' || 'LS1 4AB'; -- NULL
```

**Dialect.** `||` is standard SQL and works in Postgres, Oracle, SQLite. SQL Server uses `+` (and `CONCAT`). MySQL's `||` means OR by default — use `CONCAT` there.

## 7.2 Case and trimming

```sql
LOWER(x)   UPPER(x)   INITCAP(x)     -- INITCAP: 'john SMITH' -> 'John Smith'
TRIM(x)    LTRIM(x)   RTRIM(x)       -- whitespace by default
TRIM(BOTH '0' FROM '00123')          -- '123' — trim specific characters
BTRIM(x, ' .,')                      -- Postgres: trim any of these chars from both ends
```

`TRIM(LOWER(x))` before comparing text is the default defensive move — `'UK '` and `'uk'` are different values and will fail to join, fail to group together, and quietly split your totals in two.

`INITCAP` is naive about real names: 'o'neill' becomes 'O'Neill' correctly by luck, but 'mcdonald' becomes 'Mcdonald' and 'ABC LTD' becomes 'Abc Ltd'. Don't apply it to company names or use it as a data fix; use it for display only.

## 7.3 Length, padding, position

```sql
LENGTH('hello')                -- 5 characters
OCTET_LENGTH('hello')          -- 5 bytes (differs for non-ASCII)
LPAD('7', 3, '0')              -- '007'
RPAD('ab', 5, '.')             -- 'ab...'
POSITION('@' IN email)         -- 1-based index, 0 if not found
STRPOS(email, '@')             -- Postgres synonym
```

`LPAD` fixes the classic problem of numeric codes stored as text losing leading zeros in Excel — cost centre '00123' arriving as '123'.

```sql
SELECT LPAD(cost_centre::text, 5, '0') FROM finance_extract;
```

## 7.4 Substring extraction

```sql
LEFT(str, n)                   -- first n characters
RIGHT(str, n)                  -- last n
SUBSTRING(str FROM 3 FOR 4)    -- standard syntax
SUBSTRING(str, 3, 4)           -- Postgres shorthand: from position 3, 4 chars
SUBSTRING(str FROM '[0-9]+')   -- regex form: first match
```

UK postcode handling, which comes up in any local-authority or NHS role:

```sql
SELECT
    postcode,
    UPPER(REPLACE(postcode,' ','')) AS normalised,
    SUBSTRING(UPPER(postcode) FROM '^[A-Z]{1,2}')                  AS area,      -- 'LS'
    SPLIT_PART(UPPER(TRIM(postcode)), ' ', 1)                      AS outcode,   -- 'LS1'
    LEFT(SPLIT_PART(UPPER(TRIM(postcode)), ' ', 2), 1)             AS sector_digit
FROM addresses;
```

Postcodes vary in length (`M1 1AA` to `EC1A 1BB`), so fixed-position slicing is wrong. Split on the space, or regex it.

## 7.5 REPLACE and TRANSLATE

```sql
REPLACE('01234 567 890', ' ', '')          -- strip spaces from a phone number
REPLACE(product_name, '&amp;', '&')        -- undo HTML escaping
TRANSLATE('£1,234.00', '£,', '')           -- delete multiple chars at once -> '1234.00'
```

`TRANSLATE` maps characters one-to-one; when the "to" string is shorter, the extra "from" characters are deleted. It's the neat way to strip a set of characters without chaining REPLACEs.

```sql
-- currency string to numeric
SELECT TRANSLATE('£1,234.56', '£,', '')::numeric;   -- 1234.56
```

## 7.6 SPLIT_PART and string_to_array

```sql
SPLIT_PART('leeds/cardiology/routine', '/', 2)     -- 'cardiology'
SPLIT_PART(email, '@', 2)                          -- domain
STRING_TO_ARRAY('a,b,c', ',')                      -- {a,b,c}
UNNEST(STRING_TO_ARRAY(tags, ','))                 -- one row per tag
```

`SPLIT_PART` returns an empty string, not an error, when the part doesn't exist — convenient, but wrap in `NULLIF(..., '')` if absence should read as NULL.

Exploding a delimited column into rows is a common cleaning task:

```sql
SELECT product_id, TRIM(tag) AS tag
FROM products, UNNEST(STRING_TO_ARRAY(tags, ',')) AS tag;
```

**Dialect.** `SPLIT_PART` is Postgres. SQL Server has `STRING_SPLIT` (returns rows, ordinal only from 2022), Snowflake has `SPLIT_PART` too, BigQuery has `SPLIT` returning an array.

## 7.7 Regular expressions

Postgres regex operators and functions:

```sql
str ~ pattern            -- matches, case sensitive
str ~* pattern           -- matches, case insensitive
str !~ pattern           -- does not match
REGEXP_REPLACE(str, pattern, replacement, 'g')   -- 'g' = replace all occurrences
REGEXP_MATCHES(str, pattern)                     -- returns array of capture groups
SUBSTRING(str FROM pattern)                      -- first match as text
REGEXP_SPLIT_TO_TABLE(str, pattern)              -- split to rows
```

Practical cleaning:

```sql
-- keep digits only (phone numbers, NHS numbers, reference codes)
REGEXP_REPLACE(phone, '[^0-9]', '', 'g')

-- collapse runs of whitespace to a single space
REGEXP_REPLACE(TRIM(free_text), '\s+', ' ', 'g')

-- validate email shape
WHERE email ~* '^[^@\s]+@[^@\s]+\.[a-z]{2,}$'

-- validate UK postcode (simplified but practical)
WHERE UPPER(REPLACE(postcode,' ','')) ~ '^[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2}$'

-- extract the first number from free text
SUBSTRING(notes FROM '[0-9]+')

-- strip everything except letters and spaces from a name
REGEXP_REPLACE(full_name, '[^A-Za-z '' -]', '', 'g')
```

Regex is slow on large tables and cannot use a standard index. For filtering millions of rows prefer `LIKE` with a trailing wildcard where possible, or precompute a cleaned column.

**Dialect.** Regex support varies more than anything else in SQL. SQL Server has essentially none before 2025 (you use `LIKE` with bracket classes or CLR functions); MySQL uses `REGEXP`/`RLIKE`; BigQuery uses `REGEXP_CONTAINS`/`REGEXP_EXTRACT`. Flag this if asked about portability.

## 7.8 Practical cleaning examples

**Parsing a URL into path and query parameters:**

```sql
SELECT page_url,
       SPLIT_PART(SPLIT_PART(page_url, '?', 1), '://', 2)  AS host_and_path,
       NULLIF(SPLIT_PART(page_url, '?', 2), '')            AS query_string,
       SUBSTRING(page_url FROM 'utm_source=([^&]+)')       AS utm_source,
       SUBSTRING(page_url FROM 'utm_campaign=([^&]+)')     AS utm_campaign
FROM web_events
WHERE event_name = 'page_view';
```

**Splitting a single name field:**

```sql
SELECT full_name,
       SPLIT_PART(TRIM(full_name), ' ', 1) AS first_name,
       NULLIF(REGEXP_REPLACE(TRIM(full_name), '^\S+\s*', ''), '') AS rest_of_name
FROM employees;
```

Caveat worth voicing in an interview: name splitting is culturally naive and loses information (double-barrelled surnames, patronymics, name orders where the family name comes first). If the source system has separate fields, use them.

**Fuzzy matching for deduplication** — Postgres ships `fuzzystrmatch` and `pg_trgm`:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

SELECT a.patient_id, b.patient_id, a.surname, b.surname,
       SIMILARITY(a.surname, b.surname) AS score
FROM patients a JOIN patients b ON a.patient_id < b.patient_id
WHERE a.date_of_birth = b.date_of_birth
  AND SIMILARITY(a.surname, b.surname) > 0.6;

SELECT SOUNDEX('Smith'), SOUNDEX('Smyth');            -- both S530
SELECT LEVENSHTEIN('Smith','Smyth');                  -- 1 edit
```

Restricting the pairing by an exact key first (`date_of_birth` here) is essential — comparing every row to every other row is quadratic and will never finish on a real table.

## 7.9 String exercises

1. Build a full name from first and last, handling missing parts.
2. Extract the email domain and count customers per domain.
3. Normalise phone numbers to digits only.
4. Find products whose name contains a number.
5. Extract the UK postcode area (letters at the start).
6. Standardise country names to uppercase, trimmed, with blanks as NULL.
7. Split a comma-separated tag column into one row per tag.
8. Find customers whose email doesn't look valid.
9. Mask emails for a shared export: first character, then asterisks, then the domain.
10. Extract the campaign name from a URL query string.

```sql
-- 1
SELECT CONCAT_WS(' ', NULLIF(TRIM(first_name),''), NULLIF(TRIM(last_name),'')) FROM customers;

-- 2
SELECT LOWER(SPLIT_PART(email,'@',2)) AS domain, COUNT(*) AS customers
FROM customers WHERE email IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;

-- 3
SELECT phone, REGEXP_REPLACE(phone, '[^0-9]', '', 'g') AS digits FROM contacts;

-- 4
SELECT product_name FROM products WHERE product_name ~ '[0-9]';

-- 5
SELECT postcode, SUBSTRING(UPPER(TRIM(postcode)) FROM '^[A-Z]{1,2}') AS area FROM addresses;

-- 6
SELECT NULLIF(UPPER(TRIM(country)), '') AS country_clean, COUNT(*) FROM customers GROUP BY 1;

-- 7
SELECT p.product_id, TRIM(t) AS tag
FROM products p, UNNEST(STRING_TO_ARRAY(p.tags, ',')) AS t;

-- 8
SELECT customer_id, email FROM customers
WHERE email IS NOT NULL AND email !~* '^[^@\s]+@[^@\s]+\.[a-z]{2,}$';

-- 9
SELECT email,
       LEFT(email,1) || REPEAT('*', GREATEST(POSITION('@' IN email)-2, 0))
                     || SUBSTRING(email FROM POSITION('@' IN email)) AS masked
FROM customers WHERE email IS NOT NULL;

-- 10
SELECT DISTINCT SUBSTRING(page_url FROM 'utm_campaign=([^&]+)') AS campaign
FROM web_events WHERE page_url LIKE '%utm_campaign=%';
```

---

# PART 8 — DATE AND TIME ANALYSIS

Almost every analytical question has a time dimension. This section is long because dates generate more interview questions than any topic except joins.

## 8.1 Types

| Type | Contains | Example |
|---|---|---|
| `date` | calendar day | `2024-03-15` |
| `time` | clock time | `14:30:00` |
| `timestamp` | date + time, no zone | `2024-03-15 14:30:00` |
| `timestamptz` | date + time, zone-aware | stored UTC, displayed in session zone |
| `interval` | a duration | `3 days 04:00:00` |

Subtracting two dates gives an **integer** (days). Subtracting two timestamps gives an **interval**. That difference trips people up constantly:

```sql
SELECT DATE '2024-03-15' - DATE '2024-03-01';                          -- 14 (integer)
SELECT TIMESTAMP '2024-03-15 10:00' - TIMESTAMP '2024-03-01 08:00';    -- 14 days 02:00:00
SELECT EXTRACT(EPOCH FROM (t2 - t1)) / 3600 AS hours_between;          -- numeric hours
```

`EXTRACT(EPOCH FROM interval)` gives seconds, and is how you turn an interval into a number you can average. `AVG` of an interval works in Postgres, but converting to a number first is more portable and easier to format.

## 8.2 Current date and time

```sql
CURRENT_DATE                      -- 2024-03-15
CURRENT_TIMESTAMP / NOW()         -- start of the current transaction, with zone
LOCALTIMESTAMP                    -- without zone
STATEMENT_TIMESTAMP()             -- start of the current statement
CLOCK_TIMESTAMP()                 -- actual wall clock, changes within a statement
```

`NOW()` is fixed for the whole transaction, so every row in a long query gets the same value — which is what you want for reproducibility.

**Reproducibility warning.** A saved query using `CURRENT_DATE` gives different answers on different days, which makes results impossible to reconcile with a report someone ran last week. For anything that will be re-run or audited, parameterise the reporting date rather than hardcoding "today":

```sql
WITH params AS (SELECT DATE '2024-03-31' AS as_at)
SELECT ... FROM orders, params WHERE order_ts < params.as_at;
```

## 8.3 INTERVAL and date arithmetic

```sql
CURRENT_DATE + INTERVAL '30 days'
CURRENT_DATE - INTERVAL '1 year'
order_ts + INTERVAL '2 hours 30 minutes'
DATE '2024-01-31' + INTERVAL '1 month'      -- 2024-02-29 (clamps to month end)
CURRENT_DATE + 7                            -- date + integer = date, days
```

Month arithmetic clamps rather than overflowing: 31 January plus one month is 29 February in a leap year, 28 February otherwise. That's usually what you want, but note it isn't reversible — adding a month then subtracting one doesn't always return the start date.

Common windows:

```sql
WHERE order_ts >= CURRENT_DATE - INTERVAL '30 days'                       -- rolling 30 days
WHERE order_ts >= DATE_TRUNC('month', CURRENT_DATE)                       -- month to date
WHERE order_ts >= DATE_TRUNC('year', CURRENT_DATE)                        -- year to date
WHERE order_ts >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
  AND order_ts <  DATE_TRUNC('month', CURRENT_DATE)                       -- last full month
WHERE order_ts >= DATE_TRUNC('quarter', CURRENT_DATE)                     -- quarter to date
```

**Dialect.** SQL Server uses `DATEADD(day, -30, GETDATE())` and `DATEDIFF(day, a, b)`. MySQL uses `DATE_SUB(NOW(), INTERVAL 30 DAY)`. BigQuery uses `DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)`. The Postgres `INTERVAL` literal syntax is the standard one.

## 8.4 DATE_TRUNC — the workhorse

Rounds a timestamp down to the start of a period. It's how you build every time series.

```sql
DATE_TRUNC('hour',    ts)   -- 2024-03-15 14:00:00
DATE_TRUNC('day',     ts)   -- 2024-03-15 00:00:00
DATE_TRUNC('week',    ts)   -- Monday of that week  (ISO: weeks start Monday)
DATE_TRUNC('month',   ts)   -- 2024-03-01 00:00:00
DATE_TRUNC('quarter', ts)   -- 2024-01-01
DATE_TRUNC('year',    ts)   -- 2024-01-01
```

The result is a timestamp; cast to `::date` for tidy output.

Postgres weeks start on **Monday**, matching ISO 8601 and UK business convention. Many US-origin tools start weeks on Sunday. If a stakeholder's numbers disagree with yours by a day at week boundaries, this is why.

```sql
SELECT DATE_TRUNC('week', o.order_ts)::date AS week_commencing,
       COUNT(DISTINCT o.order_id) AS orders,
       ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),2) AS revenue
FROM orders o JOIN order_items oi USING (order_id)
WHERE o.status='completed'
GROUP BY 1 ORDER BY 1;
```

**UK financial year.** Companies often report April–March; the public sector always does. Shift the date before truncating:

```sql
-- FY starting 1 April: subtract 3 months, truncate to year, add 3 back
SELECT DATE_TRUNC('year', order_ts - INTERVAL '3 months') + INTERVAL '3 months' AS fy_start,
       EXTRACT(YEAR FROM order_ts - INTERVAL '3 months') AS fy_starting_year
FROM orders;
```

For the tax year starting 6 April, subtract `INTERVAL '3 months 5 days'`. Knowing this pattern is genuinely useful in UK analyst work and rarely known by candidates.

## 8.5 EXTRACT and DATE_PART

Pull a component out as a number.

```sql
EXTRACT(YEAR    FROM ts)      -- 2024
EXTRACT(QUARTER FROM ts)      -- 1
EXTRACT(MONTH   FROM ts)      -- 3
EXTRACT(DAY     FROM ts)      -- 15
EXTRACT(DOW     FROM ts)      -- 0=Sunday ... 6=Saturday
EXTRACT(ISODOW  FROM ts)      -- 1=Monday ... 7=Sunday   <- use this in the UK
EXTRACT(DOY     FROM ts)      -- day of year
EXTRACT(WEEK    FROM ts)      -- ISO week number
EXTRACT(HOUR    FROM ts)      -- 14
EXTRACT(EPOCH   FROM ts)      -- Unix seconds
```

`DATE_PART('month', ts)` is the function-call equivalent and returns `double precision`; cast to `int` if you're using it as a label.

**EXTRACT vs DATE_TRUNC — the distinction matters.** `EXTRACT(MONTH FROM ts) = 3` gives March in *every* year combined. `DATE_TRUNC('month', ts)` gives each March separately. Grouping by `EXTRACT(MONTH ...)` when you meant a monthly time series silently merges years, and the chart looks fine.

```sql
-- seasonality: all Marches together (correct use of EXTRACT)
SELECT EXTRACT(MONTH FROM order_ts) AS month_of_year, COUNT(*)
FROM orders GROUP BY 1 ORDER BY 1;

-- time series: each month separately (correct use of DATE_TRUNC)
SELECT DATE_TRUNC('month', order_ts)::date AS month, COUNT(*)
FROM orders GROUP BY 1 ORDER BY 1;
```

Weekday and business-hours analysis:

```sql
SELECT TO_CHAR(order_ts, 'Day') AS day_name,
       EXTRACT(ISODOW FROM order_ts) AS dow,
       COUNT(*) AS orders,
       COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM order_ts) BETWEEN 9 AND 17) AS in_hours
FROM orders
GROUP BY 1,2 ORDER BY 2;
```

`TO_CHAR` handles formatting: `'YYYY-MM'`, `'DD/MM/YYYY'` (UK format), `'Day'`, `'Mon'`, `'HH24:MI'`. Note `TO_CHAR(x,'Day')` pads with spaces to a fixed width — `TRIM` it.

## 8.6 AGE and durations

```sql
AGE(TIMESTAMP '2024-03-15', TIMESTAMP '1990-06-20')  -- 33 years 8 mons 23 days
AGE(date_of_birth)                                   -- from today
EXTRACT(YEAR FROM AGE(CURRENT_DATE, date_of_birth))  -- age in whole years
```

`AGE` returns a human-readable interval accounting for varying month lengths. For "age in years", extract the year part — do **not** compute `(CURRENT_DATE - dob)/365.25`, which is off by a day for many people and will make your patient age bands disagree with clinical systems.

Duration metrics:

```sql
-- A&E length of stay
SELECT attendance_id,
       departure_ts - arrival_ts                                        AS los_interval,
       ROUND(EXTRACT(EPOCH FROM (departure_ts - arrival_ts))/60, 0)     AS los_minutes,
       departure_ts - arrival_ts > INTERVAL '4 hours'                   AS breached
FROM ae_attendances
WHERE departure_ts IS NOT NULL;

-- average and median, by triage category
SELECT triage_category,
       ROUND(AVG(EXTRACT(EPOCH FROM (departure_ts-arrival_ts))/60)) AS mean_minutes,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
             ORDER BY EXTRACT(EPOCH FROM (departure_ts-arrival_ts))/60)) AS median_minutes,
       ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (
             ORDER BY EXTRACT(EPOCH FROM (departure_ts-arrival_ts))/60)) AS p95_minutes
FROM ae_attendances
WHERE departure_ts IS NOT NULL
GROUP BY triage_category ORDER BY triage_category;
```

Reporting mean *and* median *and* p95 for waiting times is what a good analyst does — these distributions are right-skewed, the mean flatters performance, and the p95 is what patients actually experience at the tail.

## 8.7 Working days

UK reporting frequently needs working days excluding weekends and bank holidays. There's no built-in function; you need a calendar table, which is the correct answer in an interview.

```sql
-- quick and dirty: weekdays only
SELECT COUNT(*) FROM generate_series(start_date, end_date, INTERVAL '1 day') d
WHERE EXTRACT(ISODOW FROM d) < 6;

-- proper: a date dimension with a bank holiday flag
CREATE TABLE dim_date (
    date_key       date PRIMARY KEY,
    is_weekend     boolean,
    is_bank_holiday boolean,
    is_working_day boolean,
    fy_start       date,
    fy_quarter     integer,
    iso_week       integer
);

SELECT COUNT(*) AS working_days
FROM dim_date
WHERE date_key >= r.referral_date AND date_key < a.attended_ts::date
  AND is_working_day;
```

A date dimension also solves the missing-periods problem for free: LEFT JOIN to it and every date exists whether or not there was activity.

## 8.8 Period-over-period analysis

The core skill this section exists for.

**Month-on-month growth using LAG:**

```sql
WITH monthly AS (
    SELECT DATE_TRUNC('month', o.order_ts)::date AS month,
           SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
    FROM orders o JOIN order_items oi USING (order_id)
    WHERE o.status = 'completed'
    GROUP BY 1
)
SELECT month,
       ROUND(revenue, 2) AS revenue,
       ROUND(LAG(revenue) OVER (ORDER BY month), 2) AS prev_month,
       ROUND(revenue - LAG(revenue) OVER (ORDER BY month), 2) AS change,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 1) AS mom_pct
FROM monthly
ORDER BY month;
```

The trap: if a month has no orders it produces no row, so `LAG` compares against two months ago while claiming it's last month. Generate the calendar and LEFT JOIN when gaps are possible.

**Year-on-year, comparing the same month across years:**

```sql
WITH monthly AS (
    SELECT DATE_TRUNC('month', order_ts)::date AS month, SUM(total) AS revenue
    FROM order_totals GROUP BY 1
)
SELECT m.month, m.revenue,
       p.revenue AS same_month_last_year,
       ROUND(100.0 * (m.revenue - p.revenue) / NULLIF(p.revenue, 0), 1) AS yoy_pct
FROM monthly m
LEFT JOIN monthly p ON p.month = m.month - INTERVAL '1 year'
ORDER BY m.month;
```

Self-join on a date offset is more robust than `LAG(revenue, 12)`, because LAG counts *rows*, not months — one missing month and every subsequent comparison is off by one. Say this if asked "why not just LAG 12?".

**Rolling 7-day and 28-day averages:**

```sql
SELECT day, orders,
       ROUND(AVG(orders) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1)
           AS rolling_7d,
       ROUND(AVG(orders) OVER (ORDER BY day
                               RANGE BETWEEN INTERVAL '27 days' PRECEDING AND CURRENT ROW), 1)
           AS rolling_28d_gapsafe
FROM daily_orders
ORDER BY day;
```

`ROWS` counts rows; `RANGE` with an interval counts calendar time. On a dense daily series they agree. On a sparse one — days with no orders missing entirely — `ROWS 6 PRECEDING` reaches back further than a week and quietly inflates the average. `RANGE ... INTERVAL` is gap-safe. This distinction is a genuine senior-level discriminator.

**Rolling 12-month total:**

```sql
SELECT month,
       SUM(revenue) OVER (ORDER BY month
                          RANGE BETWEEN INTERVAL '11 months' PRECEDING AND CURRENT ROW)
           AS rolling_12m_revenue
FROM monthly;
```

## 8.9 Recency, lifetime and time-to-event

**Days since last order per customer:**

```sql
SELECT customer_id,
       MAX(order_ts)::date AS last_order,
       CURRENT_DATE - MAX(order_ts)::date AS days_since,
       CASE WHEN CURRENT_DATE - MAX(order_ts)::date <= 30  THEN 'Active'
            WHEN CURRENT_DATE - MAX(order_ts)::date <= 90  THEN 'Recent'
            WHEN CURRENT_DATE - MAX(order_ts)::date <= 365 THEN 'Lapsing'
            ELSE 'Dormant' END AS recency_band
FROM orders WHERE status='completed'
GROUP BY customer_id;
```

**Customer lifetime and tenure:**

```sql
SELECT c.customer_id,
       c.signup_date,
       MIN(o.order_ts)::date AS first_order,
       MAX(o.order_ts)::date AS last_order,
       MIN(o.order_ts)::date - c.signup_date         AS days_to_first_order,
       MAX(o.order_ts)::date - MIN(o.order_ts)::date AS active_lifespan_days,
       CURRENT_DATE - c.signup_date                  AS tenure_days
FROM customers c
LEFT JOIN orders o ON o.customer_id=c.customer_id AND o.status='completed'
GROUP BY c.customer_id, c.signup_date;
```

`days_to_first_order` is a genuinely useful activation metric, and the LEFT JOIN correctly leaves it NULL for customers who never converted.

**Time between consecutive orders** (the purchase cadence):

```sql
SELECT customer_id, order_ts::date AS order_date,
       order_ts::date - LAG(order_ts::date) OVER (PARTITION BY customer_id ORDER BY order_ts)
           AS days_since_previous
FROM orders WHERE status='completed';
```

Averaging that per customer gives their purchase frequency; the population median tells you what "overdue" means, which is how you build a churn-risk flag that isn't guesswork.

**Time-to-event, NHS style — referral to first appointment:**

```sql
SELECT r.specialty,
       COUNT(*) AS referrals,
       ROUND(AVG(a.attended_ts::date - r.referral_date), 1) AS mean_days_to_seen,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a.attended_ts::date - r.referral_date)
           AS median_days,
       COUNT(*) FILTER (WHERE a.attended_ts::date - r.referral_date > 126) AS over_18_weeks
FROM referrals r
JOIN LATERAL (
    SELECT attended_ts FROM appointments a2
    WHERE a2.referral_id = r.referral_id AND a2.outcome='Attended'
    ORDER BY attended_ts LIMIT 1
) a ON true
GROUP BY r.specialty;
```

The LATERAL picks the *first* attended appointment per referral, which is what "time to be seen" means — joining to all appointments and averaging would count follow-ups and understate nothing while overstating the count.

**Censoring.** Patients still waiting have no appointment and are excluded by that join. They are, by definition, the longest waiters. Reporting only completed pathways systematically flatters performance — this is survivorship bias, it's why NHS statistics report both "completed pathway" and "incomplete pathway" waits, and raising it unprompted in an interview is a strong signal.

## 8.10 Date exercises

1. Orders in the last 30 days.
2. Revenue by calendar quarter for 2024.
3. Each customer's first and last order date, and the gap between them.
4. Orders by day of the week.
5. Month-on-month revenue change with percentages.
6. Year-on-year comparison of the same month.
7. Rolling 7-day average order count.
8. Customers who haven't ordered in 90 days but had ordered before that.
9. A&E attendances breaching four hours, by month and site.
10. Average days from referral to first appointment by specialty, acknowledging still-waiting patients.
11. Revenue by UK financial year (April–March).
12. A daily series with zero-filled gaps for the last 30 days.

```sql
-- 1
SELECT * FROM orders WHERE order_ts >= CURRENT_DATE - INTERVAL '30 days';

-- 2
SELECT DATE_TRUNC('quarter', o.order_ts)::date AS quarter,
       ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct)),2) AS revenue
FROM orders o JOIN order_items oi USING (order_id)
WHERE o.status='completed' AND o.order_ts >= '2024-01-01' AND o.order_ts < '2025-01-01'
GROUP BY 1 ORDER BY 1;

-- 3
SELECT customer_id, MIN(order_ts)::date AS first, MAX(order_ts)::date AS last,
       MAX(order_ts)::date - MIN(order_ts)::date AS span_days
FROM orders WHERE status='completed' GROUP BY customer_id;

-- 4
SELECT TRIM(TO_CHAR(order_ts,'Day')) AS day, EXTRACT(ISODOW FROM order_ts) AS dow, COUNT(*)
FROM orders GROUP BY 1,2 ORDER BY 2;

-- 5  see 8.8

-- 6  see 8.8

-- 7
SELECT day, orders,
       ROUND(AVG(orders) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),1)
FROM (SELECT order_ts::date AS day, COUNT(*) AS orders FROM orders GROUP BY 1) d;

-- 8
SELECT customer_id, MAX(order_ts)::date AS last_order
FROM orders WHERE status='completed'
GROUP BY customer_id
HAVING MAX(order_ts) < CURRENT_DATE - INTERVAL '90 days';

-- 9
SELECT DATE_TRUNC('month',arrival_ts)::date AS month, site_code,
       COUNT(*) AS attendances,
       COUNT(*) FILTER (WHERE departure_ts - arrival_ts > INTERVAL '4 hours') AS breaches,
       ROUND(100.0*COUNT(*) FILTER (WHERE departure_ts - arrival_ts > INTERVAL '4 hours')
             / NULLIF(COUNT(*) FILTER (WHERE departure_ts IS NOT NULL),0),1) AS breach_pct
FROM ae_attendances GROUP BY 1,2 ORDER BY 1,2;

-- 10  see 8.9, and report the still-waiting count alongside
SELECT r.specialty,
       COUNT(*) FILTER (WHERE a.attended_ts IS NOT NULL) AS seen,
       COUNT(*) FILTER (WHERE a.attended_ts IS NULL)     AS still_waiting,
       ROUND(AVG(a.attended_ts::date - r.referral_date),1) AS mean_days_to_seen
FROM referrals r
LEFT JOIN LATERAL (
    SELECT attended_ts FROM appointments x
    WHERE x.referral_id=r.referral_id AND x.outcome='Attended'
    ORDER BY attended_ts LIMIT 1) a ON true
GROUP BY r.specialty;

-- 11
SELECT EXTRACT(YEAR FROM order_ts - INTERVAL '3 months')::int AS fy_start_year,
       ROUND(SUM(oi.quantity*oi.unit_price),2) AS revenue
FROM orders o JOIN order_items oi USING (order_id)
WHERE o.status='completed' GROUP BY 1 ORDER BY 1;

-- 12
SELECT d.day::date, COALESCE(COUNT(o.order_id),0) AS orders
FROM generate_series(CURRENT_DATE - 29, CURRENT_DATE, INTERVAL '1 day') d(day)
LEFT JOIN orders o ON o.order_ts::date = d.day::date AND o.status='completed'
GROUP BY 1 ORDER BY 1;
```
