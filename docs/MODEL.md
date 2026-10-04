# Model contracts and limits

## Authority and truth

The supplied specification sets the product contract. Generated state is the truth
layer for one run, not a claim about real Earth. Events record applied effects or
explicit annual conditions. The history renderer copies only those records.
Belief profiles are in-world practices and claims; no supernatural act enters the
environment or demographic engine. Names are original generated forms.

The worldbuilding skills inform the cross-domain checks: river outlets and travel
costs; food/energy ceilings; identity separated from ancestry; institutional forms
without a universal ladder; logistics before victory; technology complements;
regular sound change and adapted loans; and narrative truth distinguished from
shared-entity context. The skills' local book material is not redistributed.

## Geographic units

The sphere has radius 6,371 km. The atlas uses longitude −180° to 180° and latitude
−68° to 68° in an equirectangular projection. Cell areas use spherical latitude
bands; display cell sizes are not equal-area. Polar caps are outside the simulated
domain, so the land-area report is not an entire-Earth land estimate.

Provinces are regular land cells, currently 24–4,000 per world, with stable IDs and
distinct settlement/polity/language namespaces. Smooth continent kernels and ridges
are tectonic-inspired heuristics, not geological simulation. Temperature uses
latitude and elevation; precipitation includes a dry subtropical band and an
upwind rain-shadow adjustment. Soils/arable share, vegetation and resource stocks
are coarse environmental proxies rather than measured datasets.

Priority flood establishes a strictly downhill **hydraulic** path to ocean.
Depressions represent lakes; their water surface can exceed the underlying ground.
Every downstream path is checked for cycles, monotonic water levels and coastal
outlets. The model does not currently generate endorheic basins or seasonal lake
boundaries. Sea-route searches cross ocean cells and join coastal provinces only.

Routes have km and scheduled travel days, with land, river, pass and sea modes.
Winter closure fractions, roads, navigation, rail, political access and interventions
modify costs. Most interaction is local graph diffusion and direct shipments;
global trade optimization and multi-destination household itineraries are not modeled.
Geography reports summarize direct edge travel times, basin sizes and capacities.

## Annual transition and numerical units

All proposal systems read frozen beginning-of-year arrays. Environment conditions
and production forecasts are explicit proposals passed between systems. No system
applies effects to the input state. The central commit applies:

1. Food/resource production, exchange and consumption forecasts.
2. Cohort ageing, births, baseline/famine/disease deaths.
3. Feasible military casualties, then conservative population transfers.
4. Knowledge/adoption, social and language changes, control and public-service effects.
5. Invariant checks, events, exact patches and scheduled checkpoints.

Later production uses the previous year's adopted capabilities. New discoveries
cannot chain through prerequisites during the same tick. Scarce complements may
invalidate dependent practical use during commit; knowledge remains retained.

| Quantity | Unit and interpretation |
|---|---|
| Cohorts, births, deaths, transfers | Integer people; exact accounting |
| Age bands | Five-year intervals 0–4 through 80–84; open 85+ |
| Sex model | Two fertility-relevant categories; not a social-gender model |
| Food | Person-years of annual consumption |
| Cultivated land | Hectares; bounded by arable land and available labor |
| City support duration | Years with a city-sized transferable crop surplus |
| Timber, ore, fossil stocks | Abstract resource units with versioned conversion rules |
| Energy | Abstract delivered-energy units; explicit input, use and spill |
| Treasury | Abstract fiscal output units, distinct from physical food stocks |
| Roads, schooling, sanitation, urban share | Bounded indices/shares, not real-world measurements |
| Pollution | Bounded-effect stock proxy with annual decay; not tonnes of CO₂ |
| Language similarity | Transparent heuristic score; not a dialect classification |

Float stocks are quantized to six decimal places at commit. Per-province ledger
rounding tolerance is 0.00002 abstract units. Population and migration have zero
rounding tolerance. Numerical/storage/service caps are listed in each annual
ledger's diagnostics; the model does not hide stability limits in map colors.

## Population, food and movement

Annual ageing stochastically moves approximately one fifth of a five-year band
upward; 85+ remains open. This is a coarse cohort-component approximation, not
individual birthdays. Mortality follows age-specific exploratory priors adjusted
for food shortages, density, sanitation, medicine and outbreaks. Baseline fertility
allows 3.6 potential lifetime births under the versioned survival schedule.
The initial age pyramid matches that schedule. The modern fertility transition
requires modern practical capabilities; early schools alone cannot trigger it.
Broad historical sources inform screening rather than a fitted reconstruction.
See [the population revision](POPULATION.md) for coefficients and evidence limits.

Food production is bounded by cultivated/foraging land and working-age labor,
then modified by weather and yields. Newly cleared fields bear food the next year.
Seed, spoilage, consumption, storage overflow and route shipments all enter the
food ledger. Trade consumes donor surplus and cannot create inventories. Campaign
rations transfer from a specific source to a frontier and remain in the same food
ledger; deployed consumption shifts location rather than counting soldiers twice.
Urban residents remain part of province totals. A city requires 5,000 supported
residents, a cultivated hinterland, storage, transport, coordination and 40 years
of reliable city-sized crop surplus. Staple shipments are a conserved subset of
food trade; forage or inventory drawdown is not a recurring urban crop surplus.
Crop support and the local catchment bound the settlement share. Industrial
yield improvements also require a fed specialist workforce, ore and energy.
City dossiers use that urban share for resident and composition estimates, label
them as estimates, and retain the whole province count separately. Camp dossiers
represent the province’s aggregated starting settlements.

Expected migration departures accumulate as a proposal credit until a 24-person
cohort is viable; serious shortages may bypass batching. Credits are not residents.
Departures are capped by surviving origin cohorts; largest-remainder allocations
conserve counts across all age/sex cells. Migration transports primary language,
community, belief, legal status, descent shares and known techniques. War displacement
uses reachable safe neighboring routes and the same transfer machinery. Conquest
changes control separately from language or identity.

Strata merge when identical local reporting keys receive new residents. Empty
strata retire and IDs never recycle. Distinct social identities are not silently
collapsed for speed. Descent shares are separate from community identity and never
modify intellectual, moral, production or technological capacity. Individual
marriage, patrilineal inheritance and detailed identity reclassification are not modeled.

## Language, culture and institutions

Founding varieties have inventories with articulatory feature descriptions, CV
roots with optional final n, penultimate stress, 32 meanings and compact grammar
traits. Compound names preserve dated source forms and their modifier/head sense;
a root-final n may remain at a compound boundary. Older names can preserve older
phonology. These are naming languages and grammar sketches, not complete conlangs.

Sound changes apply consistently to all matching recorded forms and retain
historical stages. Loans need a contact route and nativization into the receiver's
inventory. Sustained isolation permits a distinct variety after accumulated
separation; its parent must have an earlier founding date. Lineage uses a list of
parents so the schema can represent contact varieties, but this version generates
ordinary divergence only. Minority primary-language strata persist; bilingual use
and schooling can mediate slower shifts. Writing is a separate capability/reference.

Community profiles distinguish shared, contested and minority practices. Belief
traditions and communities overlap languages and polities. Their detailed rites,
conversion and doctrinal histories are not a full agent model. Institutional forms
are independent of biological descent and are not stages every population must pass.

Polities can form through funded coordination and integrate neighbors by agreement.
Effective control, claims, fiscal capacity, representation, accountability, coercion,
legitimacy and public goods are separate fields. Campaigns use actual border routes,
supplies, mobilization limits and treasury costs. Casualties and refugees enter the
common ledger. Exhaustion and loss of control end campaigns; food/fiscal stress can
produce secession. Tactical battles, elite genealogies, layered tribute and detailed
succession bargaining remain coarse or outside this release.

## Technology and later history

Twenty-three capabilities record prerequisites, resource access, reserve thresholds
and administrative requirements. Discovery, contact knowledge and practical adoption
are distinct. Independent invention can occur; loss of operational inputs can end
use while preserving know-how. Industrial output is limited by actual energy and
ore availability. Food, public goods, disease, pollution and depletion respond to
capabilities rather than the calendar. The current industrial pathway starts with
fossil-powered steam; renewable energy contributes after electricity is available.
Technology diffusion and production pathways need broader calibration and alternatives.

Higher yield is not guaranteed to produce a larger long-run population in this
implementation. Increased surplus raises urbanization, which changes fertility
and mortality. Sensitivity reports retain both food-security benefits and compound
demographic outcomes; neither is treated as an identified real historical effect.

## Randomness, provenance and persistence

SplitMix64 draws are keyed by world seed, subsystem name, stable entity ID, year
and slot. No mutable random stream is consumed by display or export. Branches use
the same keys, so unchanged contexts retain common random numbers. Settings and
data/runtime versions are recorded in a hashed, immutable manifest. Save versions
are rejected on mismatch; future changes must explicitly revise engine/parameters.

Events contain rule/version, conditions, draws, participants, exact changes and
uncertainty. **Parents** point to recorded annual inputs and specific triggers.
**Related events** link earlier records sharing entities and assert no causation.
Neither is interpreted as a unique causal explanation. Both must point backward
in sequence/time. Event IDs and a content hash chain are deterministic.

SQLite stores indexed events, annual ledgers, compressed exact binary XOR patches
and periodic compressed checkpoints. XOR applies to numeric bytes, so float replay
does not accumulate subtraction/rounding drift. Entity metadata uses structured
patches. No pickle or executable save format is used. Annual writes are atomic;
past maps replay from the nearest checkpoint. Exported prose never changes state.
Validation also checks each ledger against its immutable annual event receipt;
an audit reads one committed database view even if another process advances the run.
Readable history exports select at most 50 recorded events per century using
documented type priorities and chronological ties. Every selected statement cites
its event ID; all events and cohort flows remain in separate structured files.

## Evidence boundary

Release checks can establish internal accounting, replay, temporal integrity,
conditional rules and mechanistic sensitivity. They do not establish empirical
historical realism. Dataset licenses/versions, independent calibration regions and
periods, larger ensembles, ablations and external expert review must be settled
before making stronger claims. The source document's research links are a proposed
validation basis, not datasets bundled into this implementation.
