# Lagrangian particles under MPI — design

Date: 2026-11-21. Issue: #217. Status: for the owner's review; nothing is built yet.

Code map with `file:line` references for everything named here:
`docs/superpowers/specs/2026-11-21-lagrange-mpi-code-map.md` (read-only research on main `43ff9c30`).

## 1. What this is for

A particle run (`ilagr > 0`) on more than one MPI process must give the same particle tracks as
a serial run, and must write a `.lgr.shy` file the existing readers accept. Today it does neither.

The owner decided on 2026-11-21: no interim "not supported with MPI" stop for the whole feature;
a full fix; this design and a plan before any code; particles change rank at the mesh edge
(approach 1 in section 5).

## 2. Measured state (main `43ff9c30`, `mm_lgr.str`, 4 processes)

All numbers come from a throwaway probe build. The run used `rwhpar = 0` so that serial and MPI
are comparable.

| # | Finding | Evidence |
|---|---|---|
| M1 | The run crashes at the first particle output | `SIGFPE` in `xi2xy` ← `lgr_output` ← `lgr_mpi_gather_output`. On rank 0 all 145 gathered particles have element 0 and are counted as exited |
| M2 | With the gather skipped, it crashes one step after the first particle changes rank | `SIGFPE` in `xi2xy` ← `track_single` (`lagrange_main.f90:579`): the sender keeps the exported particle with `ie = 0`, and `track_single` looks up its coordinates before its `ie <= 0` return |
| M3 | With both crashes patched, tracks diverge from serial | 145 particles alive at all 96 outputs in both runs. Hours 1–11: equal to one single-precision step. Hour 12: 3 particles off by up to 4e-4°. End: 127 of 145 off, worst 0.04° |
| M4 | The side fluxes `flux3d` are wrong in every element that contains another rank's node | all-own-node elements: 0 of 7,320 values off. Mixed elements on the rank that owns them: 207 of 315 off, up to 14% of scale. Mixed elements on other ranks: 305 of 318 off, up to 53% |
| M5 | Particles go wrong when they enter a mixed element | at hour 12 exactly the 3 particles in mixed elements are the 3 that are off; through hour 16 every deviating particle had been in one |
| M6 | Every other array the tracker reads is valid on every rank | element arrays `utlnv, vtlnv, utlov, vtlov, ulnv, vlnv, hdenv, hev, zenv, iwegv` and node arrays `znv, areakv, hdknv`: worst difference 3e-6 of scale, in all element classes and at ghost nodes. `wlnv`, `mfluxv`, `difv` are zero in this 2D closed case and so are untested |
| M7 | Particle ids repeat across ranks | 49 ids occur twice: each rank counts `idbdy` from 1 |
| M8 | An element's vertex order is the same on every rank | 2,651 of 2,651 elements identical to serial |

Cause of M4, read from the source (code map, section 1): `setup_fluxes_3d` loops over all local
nodes and adds each node's contribution to the two sides of each element around it. A node owned
by another rank has only part of its ring of elements here, and `flxtype` classes it as an inner
node, so its contribution is wrong. A rank holds every element that contains one of its own nodes,
so contributions from own nodes are right. M4's numbers fit that: on the owning rank about a third
of the values are right, the sides between two own nodes.

Defects found by reading, not yet exercised by a run (code map, sections 4–6):

- The hand-over packs only the particle's current state. Its release record (`init`) is replaced
  by the current state, which empties the "inserted" block of the output and breaks particle age.
- A particle that reaches a side with no neighbour on this rank is treated as leaving through an
  open boundary. It is never handed over.
- The export buffer holds 1,024 particles per step, because it is sized before `nbdymax` is read.
- Connectivity bitmaps (64 bit) pass through a 32-bit integer.
- `lagbound_seed_particles` (release in polygons) has no owner filter. Whole-basin release has one,
  but takes its grid origin and spacing from the local mesh.
- Every rank writes the `ncust` record to its own unit, not only the master.

## 3. Goals, non-goals, anti-goals

**Goals**

1. With the random walk off, particle positions from 2 and from 4 processes equal the serial ones
   at every output, particle by particle, within round-off (tolerances in section 8).
2. The `.lgr.shy` file from an MPI run has the serial layout and is read by `lgrelab`, `shyplot`
   and the UI's `lgrelab -lgmean` without change.
3. Particle ids are the same as in a serial run.
4. No crash and no hang, whatever the number of particles that change rank in a step.
5. A serial run is byte-identical before and after every stage of this work.
6. Every Lagrangian option either works under MPI and has a test, or stops at start-up with one
   clear message that names the option (section 6.9).

**Non-goals**

- Random numbers that do not depend on the number of processes. With the random walk on, an MPI
  run is statistically equivalent to serial, not identical.
- Speed. One extra exchange per time step and a short loop of hand-overs are acceptable.
- The semi-Lagrangian momentum advection (`itlin = 1`, `lagrange_back.f90`). It shares the flux
  setup but has its own tracker. It is left as it is and gets its own issue.
- Fixing serial defects that do not block this work (section 9).

**Anti-goals** (the work has failed if any of these happens)

- A serial result changes.
- A particle exists on two ranks at once, or on none, at the end of a time step.
- A run finishes with wrong tracks and no message.

## 4. Constraints

- Fortran conventions of CLAUDE.md: `implicit none`, `intent`, `allocate(..., stat=)`,
  `newunit=`, no bare `stop` in MPI paths (`shympi_abort_internal`), no GOTO.
- Build and run with OpenMPI only (`PATH=/usr/bin:$PATH`), verify `libmpi.so.40`.
- `lagrange_mpi.f90` already calls MPI directly (`include 'mpif.h'`). New MPI code stays in that
  file. `src/utils/shympi` is not changed unless the plan shows it is needed.
- The `.lgr.shy` format does not change.
- laguna runs the live binary from `~/shyfem`: all work happens in worktrees, and nothing is
  rebuilt there.

## 5. Approaches considered

All three need the same groundwork: correct fluxes across ranks, the crash fixes, unique ids and
output computed on the rank that holds the particle. They differ in when a particle changes rank.

1. **Hand over at the mesh edge (chosen).** Once the fluxes are right in every element a rank
   holds, a particle stays with its rank until it reaches a side with no neighbour there. It then
   moves to a rank that holds the neighbour, with the time left in the step, and carries on.
   One hand-over mechanism during advection; tracks match serial to round-off.
2. **Owner-only tracking.** Only the rank that owns an element tracks in it. Same flux work,
   about twice the hand-overs, and a second code path. It would only pay off if some per-element
   data were valid on the owner alone, and M6 shows that is not the case.
3. **Minimal.** Keep today's hand-over at the end of the step. A particle that crosses the whole
   overlap within one step stops at the mesh edge and loses the rest of the step, so tracks cannot
   match serial to round-off.

The owner picked approach 1 on 2026-11-21.

## 6. Design

### 6.1 Terms

- **Own node**: a node whose `id_node` is this rank. Local nodes `1..nkn_inner`.
- **Ghost node**: a local node owned by another rank.
- **Held element**: any local element. A rank holds every element with at least one own node.
- **Mixed element**: a held element with at least one ghost node.
- **Holders** of an element: the ranks that own one of its three nodes (`id_elem(1:3,ie)`).
- **Cut-off side**: a side of a held element whose neighbour exists in the basin but is not held
  here. Today `set_geom_mpi` marks it `ieltv = -1000 - ide`, where `ide` is a rank that holds the
  neighbour (code map, section 2; `lnkmpi.f90:130-154`).

### 6.2 Fluxes that are right in every held element

- `setup_fluxes_3d` and `setup_fluxes_2d` add contributions from **own nodes only**.
- After the loop, each rank holds a partial sum for its mixed elements. The full flux of a side is
  the sum of the partial sums of the element's holders. One exchange per time step adds them:
  every holder sends its partial values for each mixed element to the other holders and adds what
  it receives. Side indices need no translation (M8).
- `setup_vl_3d` and `setup_vl_2d` run after the exchange.
- In a serial run every node is own and there is no exchange, so the arithmetic and its order are
  unchanged (goal 5).
- Inputs: an own node's contribution reads node arrays at that node and element arrays in its
  ring. M6 shows the element arrays are valid in every held element. The plan repeats the M6 audit
  on a 3D case with open boundaries for `wlnv`, `mfluxv` and `difv` before relying on them.

How the exchange is built is the builder's choice. The contract: after it, `flux3d(l,ii,ie)` and
`flux2d(ii,ie)` equal the serial values for every held element, on every rank, within the flux
tolerance of section 8. A fitting form is a list per neighbour rank of the shared mixed elements,
sorted by global element number on both sides, built once at start-up.

### 6.3 One rank per particle

- At the end of every time step each particle is in the array of exactly one rank.
- A rank's array holds its live particles and the particles that left the basin while it had them.
- A particle that is handed over is removed from the sender's array at once. No entry with
  `ie = 0` is left behind.
- The model's meaning of `ie` stays: positive = in that local element, negative = left the basin
  through that element.

### 6.4 Hand-over at a cut-off side (during advection)

- `track_xi_next_element` tells a cut-off side from an open boundary. At a cut-off side the
  particle stops on the side and is marked for hand-over; it does not get a negative `ie`.
- **Destination**: a rank that holds the neighbour element. `ieltv` carries one today. The plan
  must cover one known gap: `set_geom_mpi` leaves a side unmarked when both of its end nodes are
  boundary nodes of the basin (`lnkmpi.f90:144-145`), so an interior side between two boundary
  nodes reads as a wall. The Lagrangian module therefore builds its own table of cut-off sides at
  start-up from the global mesh (`nen3v_global` and the node owners), and does not rely on the
  `ieltv` marks alone.
- **What travels**: the whole particle record (section 6.6), the global number of the element it
  left, the global numbers of the two end nodes of the side with the particle's weight at each,
  the particle's own time at the crossing, and a flag that its advection for this step is not
  finished.
- **On arrival**: the receiver finds its local element that contains both nodes and is not the
  element the particle left, sets the internal coordinates from the two weights (zero at the third
  vertex), and continues the advection for the time that is left. Lookups from global to local
  numbers use an index built once, not a scan of all elements per particle.
- **Loop**: track, exchange, track the arrivals, exchange again, until no rank has anything to
  send. A cap on the number of rounds (the plan sets it) ends the run with a clear message
  instead of looping forever.
- **Once per step**: the steps after advection (horizontal and vertical diffusion, Stokes drift,
  beaching) run exactly once per particle and time step, on the rank where its advection ends.
- A particle that ends the step inside a mixed element stays with the rank that has it. There is
  no hand-over at the end of a step.

### 6.5 Hand-over by position (random walk, Stokes drift)

The random walk and the Stokes drift move a particle by a displacement and then search for the
element that contains the new position (`find_elem_from_old`). On a rank's mesh the search can
fail for two different reasons: the point is outside the basin, or it is in an element this rank
does not hold.

- When the local search fails, the particle is offered to all ranks with its position. The rank
  that is the main owner of the element containing the point takes it. A point on a shared edge
  goes to the element with the lowest global number, so exactly one rank answers.
- If no rank takes it, the point is outside the basin and the particle is treated as in a serial
  run today.
- This is a second, rarer path. It also serves release by position (section 6.8).

### 6.6 The particle record on the wire

Everything in `lagr_entry` travels: `init` and `actual` (internal coordinates, time, `z`, layer,
global element number), `id`, `type`, `sinking`, both bitmaps as 64-bit values, and the custom
values with their own count. Local element numbers are never sent; the receiver derives them.
Buffers grow with the number of particles to send. No fixed limit can abort a run.

### 6.7 Ids

- Ids equal the serial ones. In a release, each rank creates the particles of the elements it is
  the main owner of. The particles of one release call are then numbered in the serial order:
  by global element number, then by the release grid's own order inside the element.
- The id counter is one global value kept in step on all ranks.
- `nbdymax` limits the global number of particles, as in a serial run.

### 6.8 Release paths

| Path | Selected by | Under MPI |
|---|---|---|
| Polygons | `lgrlin` | works: owner filter added |
| Whole basin | `lgrlin` blank | works: grid origin and spacing from the global basin |
| Restart from a particle file | `lgrini` | works: each rank takes the particles whose element it is the main owner of |
| Trajectory file | `lgrtrj` | stops with a message in this project (section 6.9) |
| Continuous release at boundaries | `lgrpps` on a boundary | stops with a message in this project |
| Connectivity stations | `icnn > 0` | stops with a message in this project |

### 6.9 Options: works with a test, or stops with a message

"Stops" means: on more than one process the run ends at start-up with one message that names the
option, printed by the master. Each stopped option gets a follow-up issue.

| Option | Switch | Under MPI in this project |
|---|---|---|
| Surface and layer tracking | `ilagr = 1, 2` | works |
| 3D tracking with vertical diffusion | `ilagr = 3` | works |
| Horizontal random walk | `rwhpar /= 0` | works (statistically, section 6.10) |
| Stokes and wind drift | `stkpar > 0` | works |
| Beaching | `lbeach > 0` | works |
| Transit area | `artype` | works |
| Decay | `ldecay > 0` | works. A decayed particle keeps its last element with a negative sign instead of element 0, so its last position can be written |
| Sediment | `ised > 0` | stops |
| Larvae | `ilarv > 0` | stops |
| Connectivity | `icnn > 0` | stops |
| Continuous boundary release | `lgrpps` | stops |
| Trajectory release | `lgrtrj` | stops |

This table is a proposal. The owner may move an option from "stops" to "works"; each one moved
adds a test case and a stage to the plan.

### 6.10 Random numbers

- Each rank draws from its own stream, so with the random walk on, an MPI run differs from the
  serial run particle by particle.
- With `rwhpar = 0` the draws in the diffusion step are multiplied by zero and change nothing.
- One draw remains with the random walk off: a particle that lands exactly on a vertex picks its
  next element at random (`track_xi_next_element`). Such a particle may take a different element
  in serial and MPI. This is accepted and documented. If it shows up in the acceptance tests, the
  plan replaces that draw by a rule that does not depend on the stream, for MPI and serial alike,
  and the owner is asked first because serial results would change.

### 6.11 Output

- Each rank prepares the output records of its own particles: coordinates, layer depth, and the
  block the particle belongs to (active, inserted, exited). Rank 0 gathers and writes them.
- Rank 0's own particle array is never overwritten by the gather.
- Order inside each block: by id. A serial run writes in array order, which is id order unless
  the run restarted from a file with other ids; the comparison tool matches by id.
- The element number written is the global one.
- If no rank has a particle, nothing is written for that time, as in a serial run.
- Only the master writes the `ncust` record.

### 6.12 OpenMP

`drogue`'s parallel loop stays. Lists of particles to hand over are filled under the existing
critical section. Their order may depend on the thread schedule; nothing downstream may depend on
that order. The per-thread counters that divide by `idbdy` are guarded for a rank without
particles.

### 6.13 A built-in check

With `levdbg >= 2` and more than one process, the module checks after every time step that the
global number of particles equals the sum over ranks and that no id occurs twice, and ends the
run with a message if not. This costs one small exchange per step and is off by default.

## 7. Cases the tests must cover

1. A particle that crosses two or more cut-off sides within one time step.
2. An element held by three ranks (triple point): fluxes summed over three holders, and a
   particle crossing there.
3. A cut-off side whose two end nodes are both basin boundary nodes (section 6.4).
4. A particle leaving through an open boundary from a mixed element held by a rank that is not
   its main owner.
5. A rank without particles, at release and at output.
6. More than 1,024 particles changing rank in one step.
7. A release point on an edge between elements of two ranks (the serial run inserts it in both
   elements; the MPI run must give the same particles and ids).
8. A dry element next to a cut-off side.
9. More than one OpenMP thread (`nomp = -1`) with hand-overs.

## 8. Tests and acceptance

**Test cases** (new files under `testcases/examples/mar_menor/`; names are the plan's choice):

| Case | Basin | What it covers |
|---|---|---|
| A | geographic `MM_geo`, 2D, polygon release, `rwhpar = 0` | the measured case |
| B | Cartesian `MM_coarse`, 2D, whole-basin release, `rwhpar = 0`, open boundary without tilting | Cartesian geometry, whole-basin release, exits through an open boundary |
| C | 3D with levels, `ilagr = 3` with vertical diffusion off if the code allows it, else `ilagr = 2` | layers, vertical velocity, `wlnv`/`mfluxv`/`difv` audit |
| D | case A with `rwhpar = 0.5` (today's `mm_lgr.str`) | random walk, hand-over by position |

**A comparison tool** reads two `.lgr.shy` files and reports, per output time and block, the
particle counts, any id present in only one file, and the largest position difference between
particles with the same id. It is used by the tests and by the CI gate.

**Acceptance** (each on 2 and on 4 processes unless noted):

| # | Criterion | Limit |
|---|---|---|
| AC1 | `flux3d` and `flux2d` in every held element equal serial | relative difference ≤ 1e-5 of the array's maximum (all-own elements measure 9e-7 today) |
| AC2 | Cases A, B, C: same ids in the same blocks at every output | exact |
| AC3 | Cases A, B, C: position of every particle against serial | ≤ 1e-5° (geographic) or ≤ 2 m (Cartesian, where single precision resolves 0.5 m), every output; layer and relative depth equal |
| AC4 | Case D: particle count per block equals serial at every output; every active particle lies inside the basin; no id twice | exact |
| AC5 | Case D: mean position and spread of each release group against serial | reported, not gated |
| AC6 | Serial `.lgr.shy`, `.hydro.shy` and `.inf` of `mm_lgr.str` and `mm_lgr_01.str` before and after each stage | byte-identical |
| AC7 | `mpirun -np 1` | byte-identical to serial |
| AC8 | `lgrelab -lgmean` on the MPI file of case A against the serial file | same particles; values within the AC3 limit |
| AC9 | The cases of section 7 | each has a test or a recorded run that shows it |
| AC10 | Each "stops" option of section 6.9 on 4 processes | one message naming the option, non-zero exit, no crash |

If AC3 cannot be met because the hydrodynamics themselves differ between serial and MPI
(measured today: up to 1.4e-4 m/s in one 2D case), the builder reports the measured numbers and
the owner decides on the limit. The limit is not relaxed silently.

**CI**: `testcases/examples/mar_menor/check_mpi.sh` gets a Lagrangian check (case A on 4
processes against serial with the comparison tool). That is a change to a test script, not to a
workflow file.

## 9. Not in this project

Each becomes its own issue when this design is approved:

- `particle_on_side` (`lagrange_util.f90:147-193`) intersects with the segments between mesh
  nodes 1, 2 and 3 instead of the element's own vertices. Serial code, in use for the random walk
  and Stokes drift.
- `lgr_output` calls `xi2xy` with element 0 for deleted particles (serial).
- `itlin = 1` (semi-Lagrangian momentum advection) under MPI.
- The options that stop under MPI in section 6.9.
- `lgr_mpi_reduce_connect` sums the connectivity matrices in place every step.

## 10. Decisions made here that the owner can change

1. The works/stops split of sections 6.8 and 6.9.
2. A decayed particle keeps its last element with a negative sign (changes serial output for
   runs with decay, which today write garbage coordinates for such particles or crash).
3. Ids equal to serial, at the cost of one small exchange per release.
4. Output order by id.
5. The limits of AC1 and AC3.
6. Staged delivery, each stage its own PR with serial byte-identical: (1) test cases, comparison
   tool and serial guards; (2) fluxes across ranks; (3) the particle record, one rank per
   particle, hand-over at cut-off sides; (4) release and ids; (5) output; (6) hand-over by
   position and the random-walk case; (7) the start-up stops and the CI check. MPI particle runs
   stay broken until stage 5 is merged, as they are today.

## 11. Left to the builder

- The data structures of the flux exchange and of the hand-over, within the contracts above.
- How the cut-off side table is built from the global mesh.
- The cap on hand-over rounds per step.
- The comparison tool's language and where it lives.
- The exact settings of cases B and C.
