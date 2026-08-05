# Methods reference

Reference for the statistical tests and imputation methods used by ImputeIQ, with
the assumptions and limitations of each. Written in response to supervisor
feedback asking for exact summaries so that routing decisions can be justified
rather than assumed.

## Missingness mechanisms

The three mechanisms describe what the probability of a value being missing
depends on. Let `Y_obs` be the observed data, `Y_mis` the missing values, and `R`
the missingness indicator.

**MCAR (missing completely at random).** `P(R | Y_obs, Y_mis) = P(R)`. Missingness
is independent of everything, observed or not. Complete-case analysis is unbiased,
though it loses power.

**MAR (missing at random).** `P(R | Y_obs, Y_mis) = P(R | Y_obs)`. Missingness
depends on values that were recorded. Conditioning on those observed variables
recovers unbiased estimates. Ignoring them does not.

**MNAR (missing not at random).** `P(R)` depends on `Y_mis` itself, after
accounting for `Y_obs`. Blood pressure missing precisely because it was high is
the standard example.

## Little's MCAR test

**Hypotheses.**

- H0: the data are MCAR.
- H1: the data are not MCAR.

**What it does.** Little (1988) partitions the data into groups by missingness
pattern, then compares the observed-variable means in each pattern against the
maximum-likelihood estimates computed under MCAR. The weighted sum of those
differences is a chi-square statistic with `Σp_j − p` degrees of freedom.

**Interpretation.**

- A small p-value rejects MCAR. The data are MAR or MNAR. The test does not say
  which.
- A large p-value fails to reject MCAR. This is not evidence that the data are
  MCAR. It means the test found no departure it is powered to detect.

**Limitations.** The test only responds to differences in means across
missingness patterns, so it is insensitive to departures that show up in the
covariance structure instead. It assumes multivariate normality. Power falls with
small samples and with many distinct patterns. It cannot distinguish MAR from
MNAR under any circumstances.

**Corrected in the code.** The internal flag is now named
`littles_fails_to_reject_mcar`, which is what `littles_p > alpha` actually
measures. The value is still persisted under the original `littles_suggests_mcar`
field so the API contract is unchanged.

The branch that previously reported "Likely MNAR (by elimination — no observed
driver found)" has been replaced. Concluding MNAR because no driver was found is
not defensible: it is equally consistent with MAR driven by a variable that was
never measured, or with a real driver the test was underpowered to detect. That
case is now labelled "Undetermined: MCAR rejected, no driver found among measured
variables" and carries the mechanism `Undetermined (MAR or MNAR)`. Routing is
unchanged — it still takes the cautious low-confidence path — so only the claim
being made has changed, not the imputation behaviour.

## Why MNAR cannot be confirmed from the data

MNAR means the probability of a value being missing depends on the value that is
missing. Because that value was never recorded, the observed data cannot
distinguish MNAR from MAR. This is a property of the data, not a shortcoming of
Little's test or of any other test. No procedure applied to the observed data can
resolve it.

The distinction has to come from domain knowledge about why the values went
missing, or from sensitivity analysis that reports how conclusions change across
a range of assumed MNAR mechanisms.

CONSORT 2025 item 21c ("How missing data were handled in the analysis") requires
that reports state the assumed mechanism with justification, describe the
imputation approach including the number of imputed datasets and how results were
combined, and present sensitivity analyses under different assumptions,
specifically including MNAR scenarios. It also asks for a comparison of
participants with observed against missing data. The tool's sensitivity output is
the component that addresses this requirement, so it should be framed that way in
the dissertation rather than as an optional extra.

## How placeholder values are identified

Supervisor question: how does the tool decide what is possible for a given
column, and what a sentinel means for a particular dataset?

Three layers, applied in order.

1. A fixed candidate list flags values worth examining: `0`, `-999`, `999`, `-99`,
   `-1` for numeric columns, and `"unknown"`, `"n/a"`, `"na"`, `"null"`, `"none"`,
   `"?"` and the empty string for text columns. This layer proposes candidates
   only. It never decides.
2. Each candidate is sent to a language model together with the column name and
   its summary statistics, and asked whether that value could be valid for that
   variable. This is what separates a zero in BMI from a zero in a pregnancy
   count.
3. If the model is unavailable, a keyword fallback applies. Zero is treated as
   missing in columns whose names contain bmi, glucose, blood pressure, insulin,
   skin thickness, age, weight, height or cholesterol, and as legitimate in
   columns containing pregnanc, child, visit, count, num or id.

**Limitation, stated plainly.** None of these layers uses a data dictionary. The
decision rests on the column name and a language model's prior about what that
name usually means, so it is not grounded in the dataset being analysed. Two
consequences follow. A column with an uninformative name gets a weaker judgement
than one called `bmi`. And the model can override the sentinel rule: in testing,
a `region` column containing 140 instances of `"Unknown"` was judged a legitimate
category and left unconverted, which removed that column from the analysis
entirely.

CPRD Aurum publishes a specification with permitted values and lookup tables. The
defensible version of this step reads valid ranges from that specification, or
from a user-supplied dictionary, and uses the model only where no entry exists.
Every decision should also record whether it came from the specification, the
model, or the fallback, so the cleaning step can be reported.

## The eight imputation methods

All methods except mode and flag-only operate on the full set of numeric columns,
so other numeric columns act as predictors or context.

| Method | What it does | Assumes | Limitations |
|---|---|---|---|
| Mean | Fills with the column mean | MCAR for unbiasedness | Shrinks variance, weakens correlations, and understates standard errors. Sensitive to skew and outliers. Distorts the distribution shape. |
| Median | Fills with the column median | MCAR for unbiasedness | Same variance shrinkage as mean. Robust to skew and outliers, which is its advantage over the mean. Biased under MAR because it ignores the observed drivers. |
| Mode | Fills with the most frequent category | MCAR for unbiasedness | Inflates the majority class and distorts category proportions. The only one of the simple methods defined for nominal data. |
| KNN (k=5) | Averages the k nearest complete records | Records close in predictor space have similar values. MAR-compatible if the predictors are observed | Results depend on the distance metric, on k, and on feature scaling. The current implementation does not standardise features first, so columns on larger numeric scales dominate the distance. Degrades as dimensionality rises. Costly on large datasets. |
| MICE (iterative, BayesianRidge, 50 iterations) | Models each variable conditional on the others and cycles until stable | MAR | See the note below on single versus multiple imputation. Assumes the conditional models are correctly specified. Convergence is not guaranteed. |
| Regression (single-pass linear) | Predicts missing values from the other numeric columns | MAR and linear relationships | Deterministic fitted values lie exactly on the regression surface, which inflates R², shrinks residual variance, and overstates precision. |
| Zero | Fills with 0 | Missing means the event did not occur | Not statistical imputation. Correct only for genuine structural zeros. Severely biased if the value is unknown rather than absent. |
| Flag-only | Leaves the value missing, adds a `<col>_missing` indicator | Nothing | Performs no imputation, so downstream analysis must handle missing values. Used for identifier columns, where a fabricated value would create a link to a record that does not exist. |

### Single versus multiple imputation

`IterativeImputer` previously ran with `sample_posterior=False`. Every gap
received the model's conditional-mean prediction, so the result was
deterministic: two runs with different seeds produced identical values. That is
regression imputation, not chained equations, and calling it MICE overstated what
it did.

It now runs with `sample_posterior=True`, so each filled value is a draw from the
posterior predictive distribution of the conditional model.

A single completed dataset still cannot express uncertainty about the values it
invented, however well drawn. Rubin's procedure requires several:

- `impute_mice_multiple(df, cols, m)` produces m completed datasets, each from a
  different seed.
- `pool_rubin(estimates, variances)` combines them. With `Qbar` the pooled
  estimate, `Ubar` the within-imputation variance, `B` the between-imputation
  variance and m the number of datasets, total variance is
  `T = Ubar + (1 + 1/m)B`, and the fraction of missing information is
  `(1 + 1/m)B / T`.

`B` is the term single imputation cannot produce, since with one dataset there is
nothing to vary. Reporting `T` rather than `Ubar` is what prevents standard errors
being too small, and the test suite asserts that the pooled standard error
exceeds the single-imputation one on the same data.

For reporting under CONSORT item 21c, quote m, the pooled estimate, the total
variance and the fraction of missing information. The downloadable CSV remains a
single completed dataset for onward use; it should be described as one draw, not
as the imputation result.

## Routing justification, and a problem with it

The tool applies semantic role before mechanism.

**Identifier to flag-only.** Imputing a patient or observation ID would assert a
link to a record that does not exist. No statistical argument supports inventing a
key, so the value is left missing and marked.

**Categorical to mode.** Mean and median are undefined on nominal codes: the
arithmetic mean of two lookup values is not a lookup value. Mode returns a valid
category. The cost is that it inflates the majority class, which should be
reported.

**Structural zero to zero fill.** When a count column has high missingness, the
missing entries may record that the event never happened. This is a domain
question that no statistical test can settle, which is why the tool flags it for
confirmation rather than deciding.

### The mechanism routing does not currently follow from the theory

The current table routes MCAR to MICE, and both MAR and MNAR to median. Setting
out the argument makes a problem visible.

Under MCAR, missingness carries no information. Simple methods are already
unbiased for the quantities they estimate, so the case for a conditional model is
the weakest here. It is not wrong to use MICE, since it preserves covariance
structure that mean or median would flatten, but it is the situation that needs it
least.

Under MAR, missingness depends on observed variables. Recovering unbiased
estimates requires conditioning on those variables. This is precisely what a
chained conditional model does and precisely what an unconditional median does
not: the median ignores the drivers the diagnosis step has just identified by
name. MAR is the case with the strongest argument for MICE, and it is currently
routed to median.

The routing is therefore close to inverted with respect to the mechanisms.

The rationale text in `method_router.py` defends the MAR choice on the grounds
that "empirical tests generally show it performs comparably to MICE for MAR
without the computational overhead". No source is given for this in the codebase,
and the claim runs against the standard treatment. It should either be supported
with a citation and reproduced benchmark, or the routing should change to send MAR
to the conditional model.

Under MNAR no method is valid without an untestable assumption about the missing
values. Median with a low-confidence flag is defensible as a placeholder provided
the output is accompanied by sensitivity analysis, which is what CONSORT item 21c
requires.

### Proposed change

Route MAR to iterative conditional imputation using the identified drivers, keep a
simple method for MCAR, and retain median with a low-confidence flag for MNAR
alongside sensitivity output. The synthetic benchmark can then be used to test the
current routing against the proposed routing, which turns the disagreement into a
measurable result rather than an assertion.

## Measuring the effect of imputation

The sensitivity output compares each column before and after imputation. It
reports two quantities rather than one, because they fail independently.

**Variance retention** is `SD_imputed / SD_observed`. Filling n gaps with a
single constant concentrates mass at that constant and narrows the spread, which
is the main documented cost of single imputation. Filling far from the centre
(zero-filling a count column, for instance) widens it instead. Both are
departures, so the score penalises deviation from 1.0 in either direction.

**Standardised mean shift** is `|mean_imputed − mean_observed| / SD_observed`,
expressed in standard deviations so it is comparable across columns on different
scales.

The reported score is the weaker of the two fidelities, so a column cannot appear
healthy by performing well on one axis alone. An earlier version scored on mean
shift alone; because median imputation barely moves a mean by construction, that
returned a near-constant value for every column and reported "Robust" for columns
whose spread had collapsed by more than 10%.

**MNAR bound.** Missing values are shifted by one standard deviation in each
direction and the larger resulting movement in the mean is reported. This is a
delta-adjustment, or tipping-point, analysis. It replaces an earlier bound drawn
from the observed 10th and 90th percentiles, which could not bound an MNAR
departure because it never left the observed support.

## Describing how the synthetic missingness was created

For the evaluation dataset, the dissertation should state for each column the
mechanism imposed, the variable that drives it where one exists, the functional
form of the missingness probability, the target and achieved missing rate, and the
random seed. The generator used for the 1,200-row evaluation set applies, for
example, a 0.55 probability of missing systolic blood pressure for current smokers
against 0.04 otherwise (MAR driven by smoking status), and removes HbA1c with
probability 0.7 where the true value exceeds 55 (MNAR driven by the value itself).
Recording these rules is what allows a diagnosis to be scored as correct or
incorrect.

## References

- Little, R. J. A. (1988). A test of missing completely at random for multivariate
  data with missing values. *Journal of the American Statistical Association*,
  83(404), 1198–1202.
- Rubin, D. B. (1987). *Multiple Imputation for Nonresponse in Surveys*. Wiley.
- van Buuren, S. (2018). *Flexible Imputation of Missing Data*, 2nd edition.
  Chapman and Hall/CRC.
- CONSORT 2025 item 21c, how missing data were handled in the analysis.
  https://www.consort-spirit.org/item21c-missingdata
