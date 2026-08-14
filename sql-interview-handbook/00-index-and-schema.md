# SQL Data Analyst Interview Handbook (PostgreSQL)

Built for UK Data Analyst / Junior Analyst / Graduate Analyst / Insight Analyst interviews.

Every example in this handbook uses one of two schemas defined below. Learn these two schemas once and you can read any query in the handbook without scrolling back.

## How to use it

Read Parts 1–11 in order. They are cumulative. Parts 12–15 are the difference between "can write SQL" and "is a analyst". Part 16 is drill material — do not read the solutions first. Part 17 is what you revise the night before. Part 18 is rehearsal out loud.

| File | Contents |
|---|---|
| `01-fundamentals-to-case.md` | Parts 1–5: fundamentals, filtering, aggregation, joins, CASE |
| `02-cleaning-strings-dates.md` | Parts 6–8: NULLs & cleaning, strings, dates |
| `03-subqueries-ctes-windows.md` | Parts 9–11: subqueries, CTEs, window functions |
| `04-advanced-analytical-sql.md` | Part 12: the 22 analyst patterns |
| `05-kpis-performance-design.md` | Parts 13–15: KPI SQL, optimisation, schema design |
| `06-question-bank-beginner.md` | Part 16a: 50 beginner questions |
| `07-question-bank-intermediate.md` | Part 16b: 75 intermediate questions |
| `08-question-bank-advanced.md` | Part 16c: 75 advanced questions |
| `09-patterns-mocks-debugging.md` | Parts 17–19: pattern recognition, 10 mock interviews, debugging |
| `10-cheatsheets-and-checklist.md` | Part 20 + the five-level mastery checklist |

Dialect note: everything is PostgreSQL unless flagged. Blocks marked **Dialect** tell you what changes in SQL Server, MySQL, BigQuery or Snowflake — UK analyst roles are split roughly between Postgres, SQL Server and Snowflake, and interviewers frequently ask "how would that differ in T-SQL?"

---

## Schema A — RetailCo (e-commerce)

This is the workhorse. Most retail, marketing, fintech and product-analyst interviews use a schema shaped like this.

```sql
CREATE TABLE customers (
    customer_id   integer PRIMARY KEY,
    first_name    text        NOT NULL,
    last_name     text        NOT NULL,
    email         text        UNIQUE,
    signup_date   date        NOT NULL,
    country       text,               -- 'UK', 'IE', 'FR', ...
    city          text,
    marketing_opt_in boolean   DEFAULT false,
    channel       text                -- 'organic','paid_search','email','referral'
);

CREATE TABLE products (
    product_id    integer PRIMARY KEY,
    product_name  text        NOT NULL,
    category      text,               -- 'Electronics','Home','Apparel','Grocery'
    subcategory   text,
    unit_price    numeric(10,2) NOT NULL,
    unit_cost     numeric(10,2) NOT NULL,
    is_active     boolean     DEFAULT true
);

CREATE TABLE orders (
    order_id      integer PRIMARY KEY,
    customer_id   integer REFERENCES customers(customer_id),
    order_ts      timestamp   NOT NULL,
    status        text        NOT NULL,   -- 'completed','cancelled','refunded','pending'
    channel       text,                   -- 'web','app','phone'
    shipping_cost numeric(10,2) DEFAULT 0,
    discount_code text
);

CREATE TABLE order_items (
    order_item_id integer PRIMARY KEY,
    order_id      integer REFERENCES orders(order_id),
    product_id    integer REFERENCES products(product_id),
    quantity      integer     NOT NULL,
    unit_price    numeric(10,2) NOT NULL,  -- price AT TIME OF SALE
    discount_pct  numeric(5,4)  DEFAULT 0  -- 0.15 = 15% off
);

CREATE TABLE web_events (
    event_id      bigint PRIMARY KEY,
    customer_id   integer,               -- NULL for anonymous visitors
    session_id    text        NOT NULL,
    event_ts      timestamp   NOT NULL,
    event_name    text        NOT NULL,  -- 'page_view','product_view','add_to_cart','checkout_start','purchase'
    page_url      text,
    device        text                   -- 'desktop','mobile','tablet'
);

CREATE TABLE employees (
    employee_id   integer PRIMARY KEY,
    full_name     text NOT NULL,
    department    text,
    manager_id    integer REFERENCES employees(employee_id),  -- self-referencing
    hire_date     date,
    salary        numeric(10,2),
    location      text
);
```

Key facts to internalise, because interview questions hinge on them:

- `orders` is one row per order; `order_items` is one row per product line. **Joining orders to order_items multiplies order rows.** This single fact causes more wrong answers than anything else in analyst interviews.
- Revenue lives in `order_items`, not `orders`. Line revenue = `quantity * unit_price * (1 - discount_pct)`.
- `orders.status` matters. "Revenue" nearly always means `status = 'completed'`. If you don't filter it, an interviewer will ask why.
- `web_events.customer_id` is nullable — anonymous traffic. Counting customers off this table without handling NULL is a trap.
- `employees.manager_id` is a self-referencing FK, which is what self-join questions are built on.

## Schema B — NHS Trust service data

UK public-sector and healthcare analyst roles (NHS trusts, ICBs, local authorities, care providers) interview on this shape. Waiting times, breaches and SLA compliance are the standard questions.

```sql
CREATE TABLE patients (
    patient_id      integer PRIMARY KEY,
    nhs_number      text UNIQUE,
    date_of_birth   date,
    sex             text,        -- 'M','F','Other','Unknown'
    postcode_sector text,        -- 'LS1 4', partial postcode
    imd_decile      integer,     -- 1 = most deprived, 10 = least
    registered_gp   integer
);

CREATE TABLE referrals (
    referral_id     integer PRIMARY KEY,
    patient_id      integer REFERENCES patients(patient_id),
    specialty       text,        -- 'Cardiology','Trauma & Orthopaedics','Dermatology'
    referral_date   date NOT NULL,
    source          text,        -- 'GP','A&E','Consultant','Self'
    priority        text,        -- 'Routine','Urgent','Two Week Wait'
    site_code       text
);

CREATE TABLE appointments (
    appointment_id  integer PRIMARY KEY,
    referral_id     integer REFERENCES referrals(referral_id),
    patient_id      integer REFERENCES patients(patient_id),
    scheduled_ts    timestamp,
    attended_ts     timestamp,   -- NULL if not attended
    outcome         text,        -- 'Attended','DNA','Cancelled by patient','Cancelled by provider'
    clinician_id    integer
);

CREATE TABLE ae_attendances (
    attendance_id   integer PRIMARY KEY,
    patient_id      integer REFERENCES patients(patient_id),
    arrival_ts      timestamp NOT NULL,
    departure_ts    timestamp,   -- NULL if still in department
    triage_category integer,     -- 1 (immediate) to 5 (non-urgent)
    admitted        boolean,
    site_code       text
);

CREATE TABLE waiting_list (
    waiting_id      integer PRIMARY KEY,
    referral_id     integer REFERENCES referrals(referral_id),
    added_date      date NOT NULL,
    removed_date    date,        -- NULL = still waiting
    removal_reason  text         -- 'Treated','Removed - died','Removed - declined','Transferred'
);
```

Domain rules used throughout:

- **A&E four-hour standard**: patient should be admitted, transferred or discharged within 4 hours of `arrival_ts`. A breach is `departure_ts - arrival_ts > interval '4 hours'`.
- **RTT 18-week standard**: referral-to-treatment within 18 weeks of `referral_date`.
- **Two Week Wait**: suspected cancer referrals must be seen within 14 days.
- **DNA** = Did Not Attend. DNA rate is a standard reported metric and is deliberately ambiguous — see Part 13.

---

## Sample data

Enough rows to reason about, small enough to trace by hand. Load this if you want to run the handbook's queries.

```sql
INSERT INTO customers VALUES
 (1,'Aisha','Khan','aisha@example.com','2023-01-15','UK','Leeds',true,'organic'),
 (2,'Tom','Brady','tom@example.com','2023-01-20','UK','Leeds',false,'paid_search'),
 (3,'Marie','Dubois','marie@example.com','2023-02-03','FR','Lyon',true,'email'),
 (4,'Sean','O''Neill','sean@example.com','2023-02-18','IE','Cork',false,'organic'),
 (5,'Priya','Patel',NULL,'2023-03-01','UK','London',true,'referral'),
 (6,'Jack','Wilson','jack@example.com','2023-03-14','UK','Manchester',false,'paid_search'),
 (7,'Nina','Rossi','nina@example.com','2024-01-09','UK','London',true,'email');

INSERT INTO products VALUES
 (10,'Wireless Mouse','Electronics','Accessories',24.99,9.50,true),
 (11,'USB-C Hub','Electronics','Accessories',49.99,22.00,true),
 (12,'Desk Lamp','Home','Lighting',34.50,14.00,true),
 (13,'Cotton Throw','Home','Textiles',29.00,11.25,false),
 (14,'Running Shoes','Apparel','Footwear',89.99,38.00,true),
 (15,'Coffee Beans 1kg','Grocery','Beverages',18.75,7.10,true);

INSERT INTO orders VALUES
 (1001,1,'2024-01-05 10:12:00','completed','web',3.99,NULL),
 (1002,1,'2024-02-11 14:03:00','completed','app',0,'SPRING10'),
 (1003,2,'2024-01-19 09:45:00','completed','web',3.99,NULL),
 (1004,3,'2024-02-02 16:30:00','refunded','web',5.99,NULL),
 (1005,4,'2024-02-20 11:00:00','completed','app',0,NULL),
 (1006,1,'2024-03-08 19:22:00','completed','web',3.99,'SPRING10'),
 (1007,6,'2024-03-15 08:05:00','cancelled','web',3.99,NULL),
 (1008,2,'2024-03-28 13:40:00','completed','web',0,NULL),
 (1009,7,'2024-04-02 12:15:00','completed','app',0,NULL),
 (1010,5,'2024-04-19 17:55:00','pending','web',3.99,NULL);

INSERT INTO order_items VALUES
 (1,1001,10,2,24.99,0),
 (2,1001,15,1,18.75,0),
 (3,1002,11,1,49.99,0.10),
 (4,1003,14,1,89.99,0),
 (5,1004,12,2,34.50,0),
 (6,1005,15,3,18.75,0),
 (7,1006,10,1,24.99,0.10),
 (8,1006,12,1,34.50,0.10),
 (9,1007,13,1,29.00,0),
 (10,1008,14,2,89.99,0),
 (11,1009,11,1,49.99,0),
 (12,1010,15,2,18.75,0);
```

Customer 5 has only a pending order. Customer 3's only order was refunded. Customer 6's only order was cancelled. Those three rows are what separate a correct answer from a plausible one on most of the questions in Part 16 — an interviewer seeds edge cases exactly like this.
