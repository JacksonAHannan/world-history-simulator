# World History Simulator specification

Extracted locally from the supplied DOCX; the original is preserved.

World History Simulator Specification

A procedural engine for plausible civilizations from prehistory to modernity

Draft 0.1  |  28 September 2026  |  Audience: developer or development team

Purpose and decision

Build a desktop-first program that creates an Earth-like world and then simulates its history through interactions among terrain, climate, populations, food systems, languages, trade, states, conflict, institutions, and technology. A user should be able to watch centuries pass, inspect any place at any time, and trace major outcomes to specific prior conditions and events. The program produces coherent alternate histories, not a prediction of how Earth’s history had to unfold.

The recommended implementation is one deterministic, modular simulation engine with an append-only event ledger and periodic snapshots. Start with a small playable vertical slice; add full-world scale and modern systems only after population accounting, causal records, and calibration tests work. Keep narrative generation downstream of simulation state so attractive prose cannot invent events that never occurred.

1 Product definition

1.1 Core experience

The user selects a world seed and a preset, generates a planet, advances time from a chosen prehistoric starting point to a user-defined endpoint, and explores the resulting atlas. The reference preset begins around 9000 BCE and may run through a year corresponding to 2000 CE. Internally, time is an integer year offset from the start; display calendars have no year zero.

User action | Required result
Generate | A reproducible world with coherent drainage, climate, habitats, resources, initial communities, and a documented seed.
Run or pause | A timeline with maps for settlement, polities, languages, population, trade, conflict, and technology.
Inspect | A province, city, polity, or language dossier with changes over time and links to supporting events.
Compare | Two runs or a branch from a saved year, with differences in outcomes and their earlier causes.
Export | Portable maps, timelines, structured tables, and a readable history whose statements point to source events.

1.2 Intended audience and boundaries

Primary users are worldbuilders, strategy-game designers, and researchers interested in exploratory simulations. The first release is a worldbuilding tool rather than a game: it has no victory condition, player-controlled nation, or requirement that a particular empire arise. A historical-Earth benchmark mode may later use actual terrain and aggregate reference data, but the default output is a fictional planet and fictional peoples.

•  World assumptions: human-like populations, Earth-like biology and physical constraints, finite resources, and no supernatural intervention. These assumptions can later become scenario parameters without changing the core event contracts.

•  A modern endpoint is a date, not a promise of universal industrialization. The interface reports capabilities separately: mechanized energy, industrial production, public health, literacy, communication, transport, and administrative reach. A “modern-capable” preset supplies plausible preconditions but does not script a fixed sequence.

•  Identity and institutions are social and historical states. No ancestry, language, religion, or ethnicity has a built-in intellectual, moral, or technological advantage. Historical inequality arises only through modeled resources, institutions, contact, coercion, and contingent events.

1.3 Success criteria

A successful run has plausible aggregate patterns, internal consistency, meaningful variation between seeds, and inspectable chains of cause and effect. Visual beauty and entertaining narrative matter, but they cannot substitute for stable population accounting or a credible explanation of why a society gained territory, lost speakers, or adopted a technology.

2 Model architecture and time

2.1 Geographic and social resolution

Represent land as a connected graph of approximately 2,000 simulation provinces in the reference world. Provinces follow watershed and terrain boundaries where possible; coast, river, mountain pass, road, and sea connections carry different travel costs. Ocean routes join ports. A province contains several settlements and several population strata but is not an individual household or person. Polities, languages, religions, and trade networks are entities that overlap provinces rather than exclusive labels baked into map tiles.

Use annual macro ticks throughout the run to keep rates comparable across periods. Within an active war, optional seasonal substeps resolve campaigning and supply; they must sum to the same annual demographic and economic ledger. Long quiet intervals may be accelerated only if the optimization preserves annual transition semantics and seeded random streams.

2.2 Annual transition contract

Order | Process | Output or accounting rule
1 | Environment | Update weather anomalies, harvest conditions, disease exposure, resource stocks, and passability.
2 | Production and exchange | Allocate labor, produce food and goods, move inventories along affordable routes, and accrue taxes.
3 | Population | Compute births, ordinary and shock deaths, migration proposals, and settlement growth.
4 | Contact and knowledge | Update intergroup contact, language use, cultural transmission, discovery, and adoption proposals.
5 | Politics and conflict | Update institutions, diplomacy, mobilization, campaigns, treaties, and control proposals.
6 | Commit and record | Apply all effects through one ledger; verify invariants; emit events; write scheduled snapshots.

Each system reads a frozen beginning-of-year state and submits typed proposals. The commit phase resolves competition for the same land, people, or stocks in an explicit priority order. Casualties, famine, migration, and births appear once in the population ledger; a later module cannot silently apply them a second time. Every emitted event records its triggering rule, relevant conditions, random draw, affected entities, and state deltas. Modules cannot read future state.

2.3 Randomness and reproducibility

Separate pseudorandom streams by subsystem and stable entity ID, with a manifest containing seed, engine version, parameter-set version, data-source versions, and world-generation settings. Identical manifests must reproduce identical event IDs and snapshots on supported platforms. A branch copies a checkpoint and changes a named intervention; common random streams should be retained where feasible so observed differences are attributable to that intervention. Version migration must never silently alter saved results.

2.4 Initial transition rules

The following are candidate implementation rules, not historical laws. Keep rate parameters in a versioned configuration and test their sensitivity before calibration. Any cap used for numerical stability must be visible in diagnostics.

Process | Candidate rule and constraint
Rare events | Convert a context-dependent annual hazard λ into probability 1 − exp(−λ); log the hazard and draw.
Movement | Allocate prospective migrants from origins to feasible destinations by safety, expected livelihood, kin links, capacity, and shortest-path travel cost; cap departures by the origin cohort.
Diffusion | Spread skills and linguistic features through recorded contact volume and adoption costs; a distant polity cannot acquire knowledge without a valid route or independent invention.
Food | Available food = production + imports + withdrawals from storage − exports − seed and spoilage; unmet consumption becomes a shortage that affects mortality and decisions.
Conflict | Sample diplomatic or military actions only from feasible objectives and mobilizable budgets; resolve casualties and territorial control through the common commit ledger.

3 World generation and movement

3.1 Planet and environment

Generate landmasses, ocean basins, relief, major mountain chains, rain shadows, latitude-driven seasonality, drainage basins, river flow, lakes, soils, coastlines, and biomes in that order. A tectonic-inspired layout can make mountain placement believable without simulating geological time. Water must flow downhill to an ocean or a valid terminal basin; dry basins, deltas, and endorheic lakes are allowed. Climate is a lightweight long-run model with local variability, not a full atmospheric circulation simulation.

Assign arable land, pasture, timber, domesticable species, fibers, metal ores, fossil energy, and other relevant resources through environmental rules with localized randomness. Resource accessibility changes with technology and transport. Seed starting communities in viable ecological niches rather than evenly across the map. Generate enough bottlenecks, islands, river corridors, and land bridges to create different routes for diffusion and conquest.

3.2 Travel and contact

Use a weighted multimodal graph. Edge cost depends on slope, surface, river direction, vessel and navigation capabilities, infrastructure, season, and political access. Movement costs affect migration, trade, army supply, diplomatic contact, disease spread, and language contact. Geography changes probabilities and costs; it never categorically forbids a society from developing institutions or a technology. Trade routes can shift when ports, passes, canals, or roads appear.

3.3 Environment checks

•  Reject or repair worlds with impossible drainage, disconnected inland water edges, excessive uninhabitable land, or implausible allocation of essential starting resources.

•  Expose a geography report with land area, growing seasons, arable share, basin sizes, travel-time distribution, and initial carrying-capacity estimates. Show the seed and rejected-generation attempts.

4 Populations, subsistence, and settlements

4.1 Demographic engine

Track population by province and sparse local stratum. A stratum contains five-year age bands, sex categories required by the fertility model, primary language, optional second-language share, community identity, religion where relevant, and a social position or legal status. Keep descent and socially claimed identity as separate fields. Use a sparse representation and controlled merging of tiny strata to avoid a full cross-product of all identities; record aggregation when it affects reporting.

At each tick, age cohorts, compute births from age-specific rates, deaths from baseline mortality plus shortages, violence and epidemics, then transfer migrants between provinces. Migration conserves population globally, apart from recorded births and deaths. Demographic rates respond to food, disease, urban density, sanitation, and coercion. Early history may use broad calibrated priors; later periods can support richer age patterns and migration. The cohort-component structure follows established population-projection practice, while its historical parameters remain uncertain [R5].

Accounting identity: P(t+1) = P(t) + births − deaths + in-migration − out-migration. Across the world, net migration must equal zero. The model must retain both cause-of-death totals and destination/source flows so famine or conquest can be audited.

4.2 Economy and land use

Each province has productive land, labor, seasonality, water, inputs, and accessible technology. Hunting, gathering, herding, agriculture, fishing, mining, craft production, and later industry coexist where conditions permit. Food production determines surplus after seed, storage loss, consumption, and spoilage. Trade can buffer local failures but is limited by route costs and partner stocks. Population pressure feeds migration and political stress; settlement and cultivation change ecology and disease exposure over time.

Represent wealth and political extractability separately. A fertile region can be wealthy but difficult to tax; an organized state can redirect surplus to roads, armies, public works, temples, schools, or sanitation. Use coarse sectors and inventories in the first release, not person-level markets or a full monetary economy. Include cities as nodes that arise from durable surplus, exchange, security, institutions, and transport access; track their food hinterlands and disease costs.

4.3 Migration and mixture

Households or demographic cohorts move in aggregate in response to expected food security, safety, opportunity, kin ties, destination capacity, border policy, and travel cost. Migration, enslavement, expulsion, and resettlement have distinct event types. Each move transports population, languages, techniques, beliefs, and ancestry shares, with acquisition or loss of identity handled by subsequent social processes. This prevents a conquest from instantly replacing every resident’s language or identity.

5 Language and culture

5.1 Language representation

Each language variety has a stable ID, phoneme inventory, phonotactics, a compact lexicon of meanings, a small set of grammatical traits, writing-system references, usage domains, and speaker distributions. Ancestry is a lineage graph rather than a rigid single-parent tree: ordinary divergence retains one parent; a contact variety may record more than one source. Store historical forms and regular sound rules so a place name or borrowed term has an etymology. Generate people and place names from the relevant variety’s phonotactics; preserve renaming and exonyms as dated records. Writing can spread independently of spoken language.

5.2 Change mechanisms

Within communities, probabilistic sound changes apply consistently to qualifying forms; morphology and syntax change at slower calibrated rates. Geographic isolation, population size, prestige, schools, administration, trade, forced displacement, and media alter contact and adoption. Borrowing transfers particular words and features; bilingual speakers mediate diffusion. Splits require sustained separation and accumulated divergence. A language can persist as a minority, regain official use, become a lingua franca, or die without forcing the speakers themselves to vanish.

The engine calculates intelligibility as a transparent heuristic from regular sound correspondences, shared basic vocabulary, and grammatical divergence; it does not pretend there is a universal objective language-versus-dialect threshold. Distinct community labels may exist even with close linguistic similarity. Phoneme and family diversity should be checked against external linguistic data such as PHOIBLE and Glottolog [R6, R7], while generated languages remain original.

5.3 Other cultural systems

Represent belief, ritual, law, household organization, prestige practices, and collective identity as separately transmissible traits or institutions. These traits can spread through conversion, imitation, migration, conquest, and schooling at different rates. A polity may contain many cultures; a culture may cross several polities. Do not make a single scalar “civilization level” or assign inherent capacities to groups.

6 State formation, institutions, and war

6.1 Political organization

Support autonomous villages, city-states, confederations, tributary systems, kingdoms, empires, republics, and other governing arrangements as combinations of institutions rather than mandatory evolutionary stages. A polity has de jure claims, effective local control, tax capacity, administrative reach, legitimacy sources, succession rules, coalition structure, public goods, and coercive capacity. A province may have disputed control, layered tribute, or weak central reach without losing its population or cultural composition.

Political integration becomes attractive when a coalition can fund defense, coordination, infrastructure, adjudication, or extraction. It becomes harder with travel time, local autonomy, elite bargaining, cultural conflict, and maintenance cost. Fragmentation follows real fiscal, succession, or military failures; it is neither random renaming nor an automatic collapse date. Institutions can persist after dynastic change. Warfare can promote scale in some conditions but is not the sole permitted route to complexity [R4].

6.2 Diplomacy, conflict, and settlement

Polities assess border disputes, trade access, security, legitimacy, coalition interests, expected gain, risk, and fiscal capacity. Responses include negotiation, marriage or alliance, tribute, trade concessions, raids, limited war, and large campaigns. Armies draw people and supplies from specific provinces. Seasonal movement, terrain, fortifications, disease, morale, technology, sea access, and lines of supply constrain campaigns. War ends through negotiated settlement, exhaustion, loss of governing capacity, or decisive defeat.

Each conflict records objectives, participants, belligerent coalitions, battles or campaign phases, deaths, displacement, costs, territorial changes, and treaty obligations. Civilians and soldiers are counted separately where evidence supports a distinction. Annexation changes control first; taxation, administration, religious practice, and language can respond over years or centuries. Uprisings, secession, and decolonization use the same institutional and territorial contracts instead of special event scripts.

6.3 Political economy feedback

A state chooses among army support, elite transfers, roads, irrigation, policing, schools, and health under a budget and institutional constraints. Capacity can raise both public-good provision and extraction; representation, accountability, and coercion are independent axes. Stability depends on distributive conflict, food security, political incorporation, and succession. Modern state building adds bureaucracy, mass education, census capacity, public finance, and broader political participation without equating these with one political system.

7 Technology, disease, and modern transitions

7.1 Knowledge and adoption

Represent technologies as capabilities with required inputs, know-how, complementary techniques, institutions, and local costs. Discovery is a conditional experiment, not a dated global unlock. Adoption requires resources and incentives; diffusion travels through people, trade, copying, espionage, and conquest. Keep discovery, knowledge transfer, practical adoption, and scale of use separate. Independent invention and abandonment must both be possible.

Example: effective rail transport requires more than knowledge of steam. It also needs usable energy, metallurgy, machine production, capital and labor, maintainable routes, and demand dense enough to pay the cost. Another region can know the design and decline to build it. Technologies can increase crop yields or military reach while raising environmental damage, contagion, or resource demand.

7.2 Disease and ecological shocks

The first version uses endemic mortality and occasional disease shocks driven by population density, contact, animal interfaces, and trade connectivity. A later version can add explicit pathogen lineages and immunity. Droughts, floods, volcanic cooling, and harvest failures arise from bounded stochastic processes with spatial correlation; localized shocks propagate through prices or food scarcity, migration, war, and institutions. Do not use a random catastrophe as an unexplained shortcut to a desired plot point.

7.3 Industrial and contemporary systems

When complementary capabilities align, model mechanized production, fossil energy and alternative energy, urban employment, sanitation, mass literacy, medicine, long-distance transport, fast communication, and increasingly destructive weapons. Later fertility decline responds to survival, household incentives, urban costs, education, and policy rather than a global calendar switch. Add emissions, depletion, land change, and other environmental feedback once the core stocks balance. Polities may reach these capabilities at different times or not at all by the end date.

8 Data contracts and causal history

8.1 Core entity schema

Entity | Minimum persistent fields | Integrity condition
Run / year | Seed, versions, settings, year, parent branch, checkpoint hash | One authoritative manifest per branch.
Province | Geometry, neighbors, terrain, climate, basin, resources, stocks | No invalid hydrology or negative stocks.
Population stratum | Province, cohort counts, language, identities, status | Cohort counts nonnegative; totals reconcile.
Settlement / city | Location, population, services, hinterland links, founding | Settlement population is part of province totals.
Language variety | Parents, inventory, sound rules, lexicon, speaker shares | All lineage links point to earlier varieties.
Polity / institution | Control, claims, budget, reach, laws, succession, links | Control conflicts resolved; treasuries reconcile.
Technology | Prerequisites, knowledge, adoption and scope by place | Use requires satisfied operational inputs.
Event / conflict | Year, type, participants, causes, deltas, parameters, draw | Replaying from checkpoint yields same state.

Entity IDs never recycle. A world map tile is a geographic place, a province is an accounting unit, and a polity is a time-varying organization; their identifiers must not be conflated. Store territorial changes as dated relationships so old maps can be reconstructed without overwriting borders. Keep reported classifications separate from raw simulation state.

8.2 Event provenance and history output

Use typed events such as CropFailure, Migration, LanguageSplit, Discovery, Adoption, StateFormation, Treaty, Battle, Secession, Epidemic, and CityGrowth. Each event contains a rule ID and version, trigger data, parent event IDs where applicable, a confidence or uncertainty tag for interpretation, and exact affected state deltas. A causal graph follows recorded dependencies; “why did this happen?” can show contributing conditions and countervailing factors without claiming a unique cause.

A deterministic renderer composes timeline summaries from event records and current state. Optional language-model prose may improve style, names, or local descriptions but cannot create state changes; it must cite underlying event IDs. Keep a machine-readable truth layer even when narrative text is regenerated. Allow users to mark a passage as speculative flavor rather than simulated fact.

8.3 Storage and interfaces

Use a single local application for the first release. A Python package is sufficient for orchestration and experimentation; store dense province arrays in compact numeric structures, sparse entities in typed records, indexed events and metadata in SQLite, and periodic compressed snapshots. Export maps as standard image or GeoJSON-like geometry and tabular outputs as CSV or Parquet. Profile before moving any hot loop to compiled code. Avoid microservices and an open-ended extension system until real workloads justify them.

Expose a documented command interface with operations equivalent to generate, simulate, resume, branch, inspect, validate, and export. Every command takes a manifest path and writes to a run directory. The interface returns structured error codes for invalid parameters, a failed invariant, unavailable checkpoints, and incompatible data versions. A later local web interface calls the same application layer instead of reproducing logic.

9 Atlas and analysis interface

The atlas has a map, timeline scrubber, layer switcher, search, and linked entity dossier. Layers include topography, watersheds, food productivity, settlements, population density, language use, community identities, faiths, political control, contested zones, trade, technology adoption, war, and displacement. A cursor over a date displays values for that date; map color keys include units and whether values are estimates or direct engine counts.

The dossier for a polity includes territory, population, age structure, language shares, economic base, institutions, military capacity, wars, and predecessor and successor entities. A language dossier shows phonology samples, lexicon, writing, family graph, contact sources, and speakers over time. A region dossier shows environmental change, settlement history, identities, and governing layers. Each chart can jump to the event or accounting change responsible for a break.

Comparison mode aligns two seeds or a branch and parent at the same date. It shows absolute and relative population changes, border difference, language divergence, tech adoption, and the earliest recorded causal divergence. Users can set a bounded intervention such as “lower this mountain pass travel cost after year X” or “reduce drought severity here,” with an explicit warning that complex downstream differences are scenario results rather than identified causal effects.

10 Realism, evidence, and validation

10.1 What realism means

The product targets plausible distributions, constraints, and causal behavior, not one supposedly correct alternate history. Validate against many seeds and broad properties: settlement near usable water, variation in agricultural onset, city-size distributions, population and land-use trajectories, variable state size and persistence, language-family diversity, contact effects, and the uneven spread of technology. Calibration sources include HYDE for population and land-use patterns [R3], Seshat for coded social organization and military technology [R1, R2], UN demographic methods for later-period cohort accounting [R5], and Glottolog and PHOIBLE for linguistic reference distributions [R6, R7]. These sources have coverage and reconstruction uncertainty, so no dataset is a universal ground truth.

Separate calibration targets from held-out checks by time and region, compare ensembles rather than cherry-picked worlds, report both central tendency and variation, and test ablations. Preserve broad mechanisms when tuning; reject a parameter set that merely forces every world to reach the same empire or industrial date. Include expert review from historical demography, historical linguistics, archaeology, and economic history before describing the tool as historically realistic.

10.2 Required checks

Check | Release gate
Accounting | Every year balances population, food, energy, stock, and treasury ledgers within documented rounding tolerance.
Geography | Every river reaches valid water; sea and land graph edges are valid and reachable as designed.
Reproducibility | Same manifest yields identical checkpoint and event hashes; a resumed run matches an uninterrupted run.
Causality | No narrative claim lacks a state field or event reference; event links never point forward in time.
Sensitivity | Changing travel costs, food yield, or mortality changes relevant distributions across ensembles in interpretable directions.
Historical plausibility | Selected aggregate patterns lie within predeclared broad ranges or deviations are documented with a model explanation.

10.3 Scenario tests

•  Fertile river corridor: food surplus can support settlement and political integration, but no dynasty or political form is predetermined.

•  Barrier and contact: a higher mountain crossing cost reduces travel and lexical borrowing on average across paired seeds; a reachable port can offset some of that isolation.

•  Drought and migration: a spatially correlated harvest loss reduces local stocks, causes recorded mortality or movement where buffers fail, and does not create or delete people during transit.

•  Conquest and identity: control changes immediately after settlement; taxation and language distribution change only through subsequent modeled mechanisms.

•  Technology complementarity: knowing a device without required energy, inputs, institutions, or transport does not produce industrial-scale output.

11 Delivery sequence and performance

Stage | Scope | Exit evidence
A  Vertical slice | One region; 200–400 provinces; food, cohorts, migration, simple language change, small polities, event log. | A 3,000-year run can be inspected and replayed; ledgers and lineage checks pass.
B  Ancient world | Continents; 2,000 provinces; trade, cities, institutions, wars, richer language contact. | Ensembles show varied settlement and political patterns; failures are traceable.
C  Long transition | Disease, energy, industry, modern demography, environmental feedback. | Long runs have no mandatory modern transition and meet calibrated broad checks.
D  Atlas and branching | Timeline interface, entity dossiers, intervention branches, export, documentation. | A new user can reproduce and explain a saved world from its manifest.

Provisional performance target: on a six-core desktop with 16 GB of RAM, complete a headless reference run of about 2,000 provinces and 11,000 annual ticks within 30 minutes, with under 12 GB peak memory. This is a product target to measure after Stage A, not a claim that the proposed implementation already meets it. The atlas should retrieve a stored century checkpoint and display a map layer within one second in the reference world. If profiling misses these targets, optimize arrays and snapshot frequency before increasing architecture complexity.

Large maps, fully explicit epidemics, detailed household economies, tactical battles, and global person-level records are future extensions. Stage A must still exercise the same entity and event contracts as later stages; it should not be discarded and rebuilt as a parallel engine.

12 Risks and unresolved design decisions

Historical underdetermination is the central risk: many mechanisms can fit the same aggregate pattern. Counter it with ensembles, competing model variants, explicit uncertainty, and expert review. Combinatorial growth in cultural strata and entities threatens memory; merge small strata transparently and keep map resolution coarser than rendering resolution. An event ledger can become large; snapshot periodically and index by year, place, entity, and event type. Modern systems may dominate development time; implement them only after long ancient runs behave credibly.

Before Stage B, decide the exact province construction algorithm and which time-series statistics form the held-out calibration set. Before Stage C, decide whether epidemics need named pathogen lineages and whether prices or monetary stocks materially improve outputs. These decisions should be made from measured failure cases rather than adding subsystems for their own sake.

13 Worked example of a generated causal chain

Illustrative only: in one seeded run, two groups settle opposite banks of the Tavar basin. Seasonal floods favor irrigation; increased food storage supports a market town and a taxing council. A nearby pass connects the town to copper ore, but a highland dialect remains distinct because winter closes the route. A drought reduces grain stores. The council borrows food, loses legitimacy after imposing emergency levies, and a rival coalition controls the upstream canal. A brief war changes political control, while most residents keep speaking their prior language for generations. Centuries later the successor state adopts an imported writing system; the spoken languages continue to diverge. The history viewer links each sentence to flood yields, road costs, harvest records, decisions, conflict events, and measured language shares. No later chapter exists unless the simulation actually produces it.

14 Research and reference basis

These are reference sources for design and validation, not a claim that any one model explains all of world history. Check each dataset’s specific license and version before distributing imported data.

[R1] Seshat Global History Databank, How We Work and coding process. https://seshatdatabank.info/how-we-work

[R2] Seshat Global History Databank, Data and published snapshots. https://seshatdatabank.info/data

[R3] PBL Netherlands Environmental Assessment Agency, New anthropogenic land use estimates for the Holocene: HYDE 3.2. https://www.pbl.nl/en/publications/new-anthropogenic-land-use-estimates-for-the-holocene-hyde-32

[R4] Turchin et al., “War, space, and the evolution of Old World complex societies,” PNAS 110 (2013). https://doi.org/10.1073/pnas.1308825110

[R5] United Nations Population Division, World Population Prospects 2024: Methodology report. https://www.un.org/development/desa/pd/content/world-population-prospects-2024-methodology-report-0

[R6] Glottolog, Downloads and language-family data. https://glottolog.org/meta/downloads

[R7] PHOIBLE 2.0, Phonological inventory data. https://phoible.org/
