# Food-limited population revision

The user identified excessive early cities and populations. The earlier river
world, seed 819801813 with 800 provinces, reached 52,165,428 people and 302
historical city sites by 8600 BCE. A discovery-disabled 64-province test grew
62-fold in 400 years and founded cities without agriculture. These are observed
model failures, not evidence of historical plausibility.

## Sources and scope

Sources checked on 2026-09-28:

- [US Census Bureau, historical world population estimates](https://www.census.gov/data/tables/time-series/demo/international-programs/historical-est-worldpop.html)
  compiles uncertain estimates: 1–10 million at 10000 BCE, approximately 5 million
  at 8000 BCE, and 5–20 million at 5000 BCE. These are broad screening ranges;
  the simulator's generated land area and ecological distribution differ.
- [Zahid, Robinson and Kelly (2016), PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC4743794/),
  DOI 10.1073/pnas.1517650112, estimates long-run prehistoric growth around
  0.04% per year from radiocarbon evidence. The result is uncertain and regional
  rates fluctuate. It motivates checking centuries of slow net growth rather
  than imposing a fixed annual growth cap or a universal fertility schedule.
- [The Metropolitan Museum of Art, Uruk: The First City](https://www.metmuseum.org/essays/uruk-the-first-city)
  describes Uruk as a major city around 3200 BCE, following millennia of farming.
  This is a comparison point, not a calendar unlock for fictional worlds.

No external dataset was imported. This revision is not independent calibration,
a fitted Earth reconstruction or expert validation.

## Revised mechanisms

Parameter version `earthlike-0.7` keeps annual integer births/deaths and conservative
cohort transfers. It changes the population and subsistence rules:

- Initial population scales with habitable foraging capacity and land area,
  without a per-province 3,000-person ceiling. The age pyramid matches the
  baseline cohort transition rather than injecting excess children. Sex and
  age cells use a largest-remainder allocation, preserving every initial person.
- Potential lifetime fertility is 3.6 births under this model's existing survival
  schedule, replacing 5.65. This is a model coefficient, not an observed human
  total fertility rate. Ideal isolated rural growth is about 0.12% per year;
  shortages, disease, urban mortality and conflict reduce realized growth.
- Food needs one annual ration per person. Only working-age residents, ages
  15–59, supply food-producing labor; 85% of that age group is available before
  urban occupations, military deployment and clearance. These are coarse labor
  equivalents, not individual employment records. Children alone cannot harvest.
- Agriculture starts with zero cultivated hectares. Existing plots yield food;
  newly expanded plots produce the following year. Cultivated land cannot exceed
  arable hectares or the plots the available workforce can tend. Plots decay
  by 0.1% annually only when the workforce cannot maintain them; abandoned capabilities return them
  to the uncultivated model. Ageing, adoption and migration therefore do not
  instantly turn all potential arable land into a harvest.
- Effective cultivated-area expansion is 0.0002 ha per available worker per year.
  This exploratory regional diffusion coefficient includes the small share of
  communities adopting/expanding cultivation; it is not a farmer's physical
  clearing speed. Clearance consumes labor and is separately recorded.
- Primitive farming uses two hectares per worker and 1.2 gross annual rations
  per hectare; irrigation and iron tools improve yields, while industry needs
  actual energy/material inputs. Foraging and herding continue alongside crops.
  Seed comes from crops; spoilage, consumption, shipments, waste and reserves
  remain in the conserved food ledger. Forager reserves are limited to half a
  year; agricultural grain reserves use the configured multi-year cap.
- Schooling alone does not impose modern fertility decline. That transition
  needs practical medicine or industry; modern medicine requires industry,
  education and sanitation. Local schools or councils cannot trigger the
  industrial demographic transition in early subsistence societies.
- Complex industrial capabilities require at least 5,000 food-supported urban
  residents as a coarse proxy for a specialist workforce, for local discovery
  and practical use. Industrial output is also scaled by urban labor, alongside
  its existing ore and energy limits. A received technique does not instantly
  turn a foraging province into an industrial food producer. This labor threshold
  is an explicit model approximation, not a historical universal.

## Cities and food hinterlands

The atlas uses 5,000 supported urban residents as its city reporting threshold.
This is an explicit reporting convention, not a universal archaeological definition.
Smaller communities remain settlements. A city requires agriculture, storage,
pottery, coordinated institutions and usable transport, plus 40 accumulated years
of reliable net surplus and enough crop food to support at least 5,000 residents.
Reserve drawdown is not recurring surplus. Severe
shortages reset that record; harvest fluctuations without shortages reduce it
gradually. Formation events include the observed duration and food support.

Local food reach begins at 10 km and expands with water transport, irrigation,
roads and rail. The catchment is bounded by provincial arable land. The crop
budget first accounts for food-producing families, seed and harvest losses;
only transferable surplus and actual crop-surplus imports can support urban residents.
Shipments earmark a conserved subset of crop food; ordinary forage/reserve imports
still feed the population but do not become an imaginary urban grain budget.
The regional rural demand also limits the amount available to a city. A province's
entire harvest or entire population is never automatically its city population.
Hinterlands include the local province and recorded shipment origins, rather than
every adjacent province regardless of supply.

Technology/transport also limits the urban share, which grows gradually. Declining
food support returns urban residents to rural production within the province;
their numbers remain in the common population ledger. Deaths still have explicit
causes. Arrivals and births cannot increase the city's count beyond its food budget.
City counts show currently supported cities; founded sites remain in the history.

This is a single focal settlement and a local catchment approximation per province.
It does not simulate every village, plot location, grain price or household. The
diffusion, labor, crop and transport coefficients remain exploratory. Province
aggregation can affect local settlement outcomes; exact historical dates are not
guaranteed. Publication checks and their limits are recorded in
[VERIFICATION.md](VERIFICATION.md).

## Saved histories

`earthlike-0.6` histories remain inspectable, exportable and replayable with their
original counts, events, hashes and city convention. Advancing or branching them
with the revised engine is rejected before any write. Generate a separate world
with the same seed and preset for the new rules. The atlas lists compatible
worlds first and labels the earlier histories; it disables their Run action.
No earlier population is silently replaced or migrated.
