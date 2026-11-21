# Lagrangian module under MPI: code map for issue #217

Read-only research on `main` at 43ff9c30 (2026-11-21). Paths are relative to `/home/razinka/shyfem`.
"(inferred)" marks a conclusion drawn from reading code; it was not observed at runtime.
Abbreviations: LM = `src/shyfem/lagrange_main.f90`, LF = `lagrange_flux.f90`, LV = `lagrange_vertical.f90`,
LD = `lagrange_dif.f90`, LIO = `lagrange_inout.f90`, LI = `lagrange_init.f90`, LC = `lagrange_cont.f90`,
LMPI = `lagrange_mpi.f90`, LCN = `lagrange_connect.f90`, DF = `src/shyfem/discharge_flux.f90`,
MN = `src/utils/shympi/mpi_node.f90`, MNI = `src/utils/shympi/mpi_node_internal.f90`.

Per-step call order in `lagrange` (LM:128-393):
- First call only: `lgr_mpi_init` LM:193, `mod_lagrange_init(nel,nlv)` LM:221, `lagr_init_common` LM:226, `lgr_input_shell` LM:255, `shyfem_init_lgr_file` + `write(iu) ncust` LM:261-267.
- Every step:
  1. `lgr_init_shell`, when `dtime>=dtrnext .and. dtime<=dtrend` (LM:284-291).
  2. `lgr_init_traj` LM:297.
  3. `lagr_setup_timestep` LM:303.
  4. `lagr_continuous_release_shell`, when `brelease` (LM:312-316).
  5. `lagr_connect_continuous_points` LM:318.
  6. `lagr_count_init` LM:319.
  7. `lag_vdiff_ele` LM:325.
  8. `drogue` LM:331.
  9. `lgr_mpi_exchange` LM:337.
  10. `lgr_sediment` LM:343 and `lgr_larvae` LM:349.
  11. `lagrange_decay` LM:355.
  12. `lgr_mpi_reduce_connect` LM:361.
  13. Output (LM:367-373): `lgr_mpi_gather_output` or `lgr_output`.
  14. `lagr_count_out` LM:375-378 and `compress_particles` LM:385-387.
- Callers of `lagrange`: init at `src/shyfem/shyfem_subs.f90:485`, time loop at `shyfem_subs.f90:625`.
- Mesh setup order: `set_geom` (local mesh), then `set_geom_mpi`, at `shyfem_subs.f90:363-364`.

---------------------------------------------------------------------------------------------------

## 1. Flux pipeline

### Entry points
- `lagr_setup_timestep` LF:57-67 calls, in order:
  1. `rprs` (only on the first call, `icall` LF:83-87).
  2. `setup_fluxes_2d`.
  3. `setup_fluxes_3d`. Comment at LF:65: "this overwrites velocities in vel_ie".

### rprs (LF:71-108)
- Reads `nen3v` and `xgv/ygv` (module `basin`).
- Writes `dvert(k,ie)`, the length of side k, for ie=1..nel.
- Side k joins vertices i1=mod(k,3)+1 and i2=mod(i1,3)+1, so side k is opposite vertex k (LF:91-104).
- This matches the `ieltv(ii,ie)` convention: the neighbour across the side opposite vertex ii.

### setup_fluxes_3d (LF:114-180)
- Calls `getaz(azpar)`, stored in `azlgr` (LF:143-145).
- `getaz` (src/shyfem/iostr.f90:616-635) is a global scalar: `getpar('azpar')` passed through `changeimp`.
- Zeroes `flux3d(1:ilhv(ie),1:3,ie)` for ie=1..nel (LF:147-154).
- Loops over ALL local nodes k=1..nkn, ghost nodes included (LF:160-168):
  - `itype=flxtype(k)`
  - `get_elems_around(k,maxlnk,ne,elems)`
  - `flx3d_k`
  - `make_fluxes_3d`
  - `setup_flux3d`
- Then calls `setup_vl_3d` (LF:174).

### setup_fluxes_2d (LF:184-247)
- Same per-node loop over k=1..nkn with `flx2d_k`, `make_fluxes_2d`, `setup_flux2d` (LF:219-231).
- Ends with `setup_vl_2d` (LF:241).
- Uses the automatic array `flux2d_aux(3,nel)` (LF:205), which is never used after it is zeroed.

### flxtype(k) (DF:815-869)
- Returns 0 if k<=0 (DF:837-838).
- Returns 1 (inner) if `kantv(1,k)==0` (DF:840-841).
- Otherwise uses `is_external_boundary(k)`, which is `iopbnd(k)>0` (src/utils/shyutil/bnd_geom.f90:237-244):
  - 2: material boundary.
  - 3, 4, 5: open boundary, from neighbours `kantv(1:2,k)`.
  - 1: an open-boundary node whose neighbours are both non-open (a fake inner node, DF:857-858).
- Reads `kantv` (mod_geom), `iopbnd` (mod_bound_geom).

### get_elems_around (src/utils/shyutil/lnku.f90:526-566)
- Returns `elist(1:n,k)` (mod_geom), where `n=elist(0,k)`.
- `elist` is built on the LOCAL mesh by `set_geom` (src/utils/shyutil/topological.f90:110-146) through `connect_get_lists`.
- Ring order is set by `sort_ne_lists` (src/utils/generic/connections.f90:373-439):
  - Elements are chained by `enext(ie,k)` adjacency (connections.f90:748-759).
  - For a boundary node (`nlist(0,k)/=elist(0,k)`), the ring starts at the element reached by walking `ebhnd` until it returns 0 (`look_for_first_element`, connections.f90:407-409, 559-566).
  - For a non-contiguous element fan, a 0 entry is inserted into `elist` (connections.f90:416-421).
- `set_geom_mpi` (src/shyfem/lnkmpi.f90:44-188) changes only `kantv`, `ieltv` and `iboundv`, never `elist` or `nlist`.

### flx3d_k(k,istype,azr,lkmax,n,transp,ne,elems) (DF:262-372)
Model arrays read, from its `use` list DF:270-276:

| array | dims | module | ghost/border validity |
|---|---|---|---|
| `utlnv`, `vtlnv`, `utlov`, `vtlov` | level × elem | mod_hydro | computed for ie=1..nel (`hydrodynamic.f90:1654-1656`); exchanged only if `bextra_exchange` (`hydrodynamic.f90:423-426`); `bextra_exchange` defaults to `.false.` (MN:122). Equality with the owner's value not determined. |
| `ev(3+ii,ie)`, `ev(6+ii,ie)`, `ev(10,ie)` | elem | evgeom | static geometry |
| `mfluxv(l,k)` | level × node | mod_bound_dynamic | built for k=1..nkn (`bnd_routines.f90:1162-1166`); exchanged only if `bextra_exchange` (`bnd_routines.f90:1169-1171`) |
| `wlnv(l-1,k)`, `wlnv(l,k)` | 0:nlv × node | mod_hydro_vel | exchanged unconditionally (`hydrodynamic.f90:1928-1932`) |
| `areakv` via `areanode(l,k)` | level × node | mod_area | exchanged (`elems_dealing.f90:697`); `areanode` at `elems_dealing.f90:785-799` |
| `hdknv` / `hdkov` via `volnode(l,k,±1)` | level × node | mod_layer_thickness | `hdkn` exchanged (`elems_dealing.f90:1206-1209`); `volnode` at `elems_dealing.f90:766-781` |
| `ilhkv(k)`, `ilhv(ie)` | node / elem | levels | |
| `iopbnd` via `is_external_boundary(k)` | node | mod_bound_geom | set for every node returned by `kbnds`, ghost nodes included (`bndo_admin.f90:172-185`, inferred) |

What it computes:
- `n=ne`, or `ne+1` if `istype>1`; for a boundary node `transp(:,n)=0` (DF:323-332).
- For element i of the ring, with `ii=ithis(k,ie)`:
  - `transp(l,i) = 12*aj*(az*(utlnv*b+vtlnv*c) + (1-az)*(utlov*b+vtlov*c)) + (area/areal(l))*(q - dvol(l)/dt) + qw_bot - qw_top`
  - `q=0` at an external boundary node; `qw_bot=0` at `l==lmax` (DF:341-366).
  - Layers `lmax+1..lkmax` are zeroed (DF:367-369).
- Meaning: the flux into the finite-volume part of element i, divergence-corrected (DF:335-339).

### flx2d_k (DF:99-185)
- Same pattern with barotropic `unv, vnv, uov, vov` (mod_hydro_baro, elem) and `zenv(ii,ie)-zeov(ii,ie)` (mod_hydro, 3 × elem) (DF:162-183).
- `unv/vnv` are exchanged only if `bextra_exchange` (`hydrodynamic.f90:426-427`).
- `zenv` comes from `znv`, which is exchanged at `hydrodynamic.f90:409-412` (skipped when `solver_type=='PETSc'`), then copied by `setzev` (`hydrodynamic.f90:434`).
- `zeov=zenv` copy is at `transforms.f90:537`.

### make_fluxes_3d / make_fluxes_2d (DF:875-913, 917-979)
- 3D calls 2D layer by layer, l=1..lkmax.
- Cumulative sums, per itype:
  - Type 1 (inner) and type 5: `tflux(n)=(1/n)*sum_{i=1}^{n-1} i*rflux(i)`, then `tflux(i)=tflux(i+1)-rflux(i)` (DF:937-947, 965-975).
  - Type 2: `tflux(1)=0`, forward sum, `tflux(n)=0` (DF:948-954).
  - Type 3: `tflux(n)=0`, backward sum (DF:955-959).
  - Type 4: `tflux(1)=0`, forward sum (DF:960-964).

### setup_flux3d (LF:253-290) and setup_flux2d (LF:294-325)
For each `i=1..ne`, with `ie=elems(i)`:
- `n1=ibhnd(k,ie)`: position of the vertex before k (lnku.f90:223-246). Side n1 is the edge (k, vertex after k).
- `n2=inext(k,ie)`: position of the vertex after k (lnku.f90:196-219). Side n2 is the edge (k, vertex before k).
- `j=i+1`, wrapping to 1 only when `i==n`. For a boundary node `n=ne+1`, so j can reach n, which holds the zero/boundary tflux.
- The updates (LF:284-287; 2D at LF:321-322):
  - `flux3d(l,n2,ie) -= tflux(l,j)`
  - `flux3d(l,n1,ie) += tflux(l,i)`
  - layers l=1..`ilhv(ie)`, not lkmax (LF:257-258, 283).

Consequences:
- Each side of `ie` receives contributions from the finite volumes of its two end nodes. So `flux3d(:,ii,ie)` depends on `flx3d_k` for both nodes `nen3v(mod(ii,3)+1,ie)` and `nen3v(mod(ii+1,3)+1,ie)`.
- The sign convention is "flux over side into element" (comment at LV:924).

### setup_vl_3d (LF:329-392) and setup_vl_2d (LF:396-444)
- 3D: `vel3d_ie(l,ii,ie)=bfact*flux3d/(dp*dvert(ii,ie))`.
  - `dp=hdenv(1,ie)` for every l (hdenv is mod_layer_thickness, level × elem).
  - Only for `l==1` and not sigma: `dp=hdenv(1,ie)+(zenv(i1)+zenv(i2)-2*zenv(ii))/6`.
  - `vel_ie=vel3d_ie(1,:,:)` (LF:387-389).
- 2D: `vel_ie` from `flux2d` with `ar>=1e-5` (LF:427-442); this is overwritten by 3D.
- `bfact=-1` when `bback` (LF:361-362, 424-425).

### Use of flux2d, vel_ie, vel3d_ie
- The live xi tracker reads ONLY `flux3d`, in `track_xi_get_flux` LV:924.
- `flux2d` is read only by `get_bflux_ppv` LC:352: continuous release with negative `lgrpps`.
- `vel_ie` and `dvert` are read only by the old path, `src/shyfem/lagrange_track.f90` (145, 168, 201, 271, 324, 357, 446, 534, 756, 776, 917, 957, 1058). That path runs only through `track_body`, which is used by backtracking (section 7).
- `vel3d_ie` is never read outside LF.

### Order of `get_elems_around`
- Order matters. `make_fluxes_2d` treats `rflux(i)` as consecutive around the node.
- `setup_flux*` assigns `tflux(i)` and `tflux(i+1)` to the two sides of `elems(i)` that touch k (LF:281-286). This needs `elems(i)` and `elems(i+1)` to be neighbours across an edge through k, which is what `sort_ne_lists` guarantees on the local mesh.
- Types 2, 3, 4 anchor on the first and last element (the boundary element), so they depend on where the ring starts.
- Type 1 and type 5 (inferred, derived from the formula at DF:937-947):
  - tflux has zero mean.
  - The n-1 consecutive differences equal `rflux(1..n-1)`.
  - `rflux(n)` is never used.
  - So the result is rotation-invariant only if `sum_i rflux(i)==0` exactly. Otherwise it depends on which element is listed last.
- Mechanism of the measured MPI error (inferred):
  - A ghost node (not own) has only its local elements in `elist`, so its ring is truncated.
  - `set_geom_mpi` zeroes `kantv(:,k)` for nodes that are not boundary nodes of the global mesh (lnkmpi.f90:107-109). For ghost nodes on the global boundary, it also zeroes neighbours outside the domain (lnkmpi.f90:110-118).
  - So `flxtype` returns 1 (inner) for a truncated ring, and type-1 closure is applied to a partial fan.
  - If the local fan is non-contiguous, `elist` holds a 0 entry, and `flx3d_k` would call `ithis(k,0)` / `ev(:,0)` (out of bounds).
  - The two sides of an element that touch a ghost node are therefore wrong.
  - Own nodes have complete local rings, because a rank holds every element that contains an own node.

### Not determined (section 1)
- Whether `hdenv` (used by `setup_vl_*`) is valid in non-owned elements.
- Whether `utlnv`/`unv`/`mfluxv` in non-owned elements and ghost nodes equal the owner's values when `bextra_exchange=.false.`.
- Whether 0 entries in `elist` actually occur on Mar Menor partitions.

---------------------------------------------------------------------------------------------------

## 2. Other per-element / per-node reads in one time step

| routine (file:line) | arrays read (module, location) | MPI validity evidence |
|---|---|---|
| `lag_vdiff_ele` LD:418-495 (loop ie=1..nel) | `difv(l,k)` (mod_diff_visc_fric, 0:nlv × node) through `nen3v`; layer thickness through `lagr_layer_thickness`; writes `wde(0:nlv,ie)`, `dtvd(ie)` | `difv` computed for k=1..nkn (`turbulence.f90:432,617`; GOTM `:767`); exchanged only if `bextra_exchange` (`turbulence.f90:622-625`) |
| `track_single` LM:543-637 | `lgr_ar(i)`; `xi2xy(abs(ie))` LM:578 (runs before the `ie<=0` return at LM:591); `iwegv(ie)` (mod_geom_dynamic, elem) LM:592; `lagr_layer_thickness` LM:594; `ip_int_elem(ie)` LM:626; `lgr_mpi_check_ghost` LM:627 → `id_elem(1,ie)` LMPI:458. Export is marked only when `ie>0` (LM:625-628) and only after the early returns at LM:591-595. A particle that leaves through a `-1000-ide` side (`ie=-ie` at LV:657-661) is never marked for export | `iwegv`: not determined |
| `track_body_xi` LM:641-745 | `dripar` LM:681; loop of up to 100 `track_xi` calls LM:687-702; `lagr_connect_count` / `lagr_count` if `bconnect` LM:693-697; `xi2xy(abs(iel))` LM:704; `iarv(iel)` vs `artype` LM:737 | `iarv`: static element type |
| `track_xi` LV:282-563 | `track_xi_get_vertical` LV:324; `track_xi_get_flux` LV:351; `xit_start_end` (`src/utils/generic/int_to_cart.f90:212`); `xi_dist(iel,…)` reads `ev(16+ii,ie)`, `ev(10+ii,ie)` (evgeom.f90:739-766); `track_xi_on_material_boundary` reads `ieltv(ii,ie)==0` LV:705-727; `track_xi_next_element` LV:567-701 reads `ieltv` and draws random numbers; `track_xi_has_layer` reads `ilhv` LV:731-742; `track_xi_adjust_layer` reads `ilhv` LV:746-779 | `ieltv` adjusted by `lnkmpi.f90:130-154`: a side with no local neighbour becomes `-1000-ide`, so `ieb<1` gives `ie=-ie` at LV:657-661, which looks the same as an open boundary. Exception: sides whose two end nodes are both global boundary nodes are skipped (`lnkmpi.f90:144-145`) and stay 0, which reads as a material wall at LV:722 and gets its flux zeroed at LV:927-931. Whether such internal sides occur is not determined |
| `track_xi_get_flux` LV:897-1015 | `flux3d(lb,:,iel)`, `ieltv`, `ulov, ulnv, vlov, vlnv` (mod_hydro_vel, level × elem) weighted by `azlgr` LV:935-937 | `ulnv=utlnv/hdenv` over whole arrays (`transforms.f90:117-122`); `ulov=ulnv` copy (`transforms.f90:545`); no element exchange (inherits from `utlnv`) |
| `track_xi_get_vertical` LV:1019-1059 | `lagr_layer_thickness`; `wlov(l,k)`, `wlnv(l,k)` over the 3 nodes | `wlnv` exchanged (`hydrodynamic.f90:1930`); `wlov=wlnv` copy (`transforms.f90:541`) |
| `lagr_layer_thickness` LV:158-201 | `get_sigma_info`; `get_zadapt_info(ie)` → `nadapt_com(:,ie)`, `hadapt_com(:,ie)` (module `zadapt`, `src/utils/shyutil/zadaptutil.f90:166-181`); `ilhv(ie)`, `hev(ie)` (mod_depth), `zenv(:,ie)`, `zeov(:,ie)`, `hlv` | `zenv` from exchanged `znv` (see section 1); `hev` and `zadapt`: not determined |
| `diff_body` LD:59-156 | vertical branch if `bvdiff` LD:104-112: `lgr_diff_vert` → `diff_get_vert` (`wde`, `dtvd`, layer thickness) LD:321-412; horizontal branch if `bhdiff`, ALWAYS true (`lagrange_data.f90:102`, never reassigned): `lag_diff_hor`, then `xy2xi(abs(iel),…)` LD:118-123; `iarv` LD:146-148 | — |
| `lag_diff_hor` LD:500-587 | `rwhpar`, or `-rwhpar*difhv(lb,iel)` if `rwhpar<0` LD:539-543; `lag_get_dxdy` LD:592-615; `ev_c2g` for spherical grids; `find_elem_from_old(ieold,…)` (`src/utils/shyutil/find.f90:172-255`); `particle_on_side` (`lagrange_util.f90:147-193`); `ilhv` | `difhv` (mod_diff_visc_fric, level × elem) computed over nel (`diffusion_admin.f90:587, 687, 714`); no exchange found |
| `lag_stk` lagrange_stk.f90:42-152 | active only when `stkpar>0` and `lb==1`; `wxv(k)`, `wyv(k)` (mod_meteo, node) over the 3 nodes :100-106; `find_elem_from_old` :127; `particle_on_side` :131; `xy2xi(iel,…)` without `abs` :146 (`xy2xi` stops if `ie<1`, evgeom.f90:567-570) | `wxv/wyv`: no exchange found except `nuopc_shyfem_cap.f90:1544-1547` |
| `lag_beach` LM:754-776 | `track_xi_on_material_boundary(iel,xi)`, called without an `iel>0` check (LM:769-771) | — |
| `lgr_compute_depths` LIO:872-906 (output only) | `hdenv(l,abs(ie))`, `ilhv` | — |
| `lagrange_decay` lagrange_decay.f90:78-113 | `lgr_ar(i)%init%time`; femtime `it` (:107) | — |
| `lagr_count_init` LM:925-939 | zeroes `i_count`, `t_count` (elem) every step | — |
| `lagr_count` LM:943-964 | writes `i_count(ie_to)`, `t_count(ie_from)` | — |
| `lagr_connect_count` LCN:491-613 | `i_connect_elems(ie_to/ie_from)`; `lagr_get_initial_vals` → `init%ie` (`lagrange_utils.f90:34-50`); per-particle bitmaps | — |

Geometry and search helpers (static, local):
- `xi2xy` / `xy2xi` / `xi_abc` (evgeom.f90:548-590, 685-737, 855-895): Cartesian grids use `ev(1:9,ie)`; spherical grids use `xgv/ygv` of `nen3v`.
- `find_elem_from_old` scans local element indices outward from `ieold`, alternating down and up (find.f90:217-241). For a point on a shared edge, which element is found depends on local numbering (inferred).
- `in_element` is boundary-inclusive, through `intri` (`regular.f90:1256-1289`: inside when `scal>=0`).

Pre-existing defects seen while reading:
- `particle_on_side` uses `xgv(i1)` / `ygv(i1)` with i1 in 1..3 instead of `xgv(nen3v(i1,ie))` (`lagrange_util.f90:166-171`).
- `diff_body`'s horizontal step converts xi → x,y (single-precision `real`) → xi every step, even when `rwhpar=0`:
  - track_single LM:578-580 converts xi to `real` x,y.
  - LD:120-122 calls `xy2xi`.
  - `lag_get_dxdy` gives `cf=sqrt(6*k*time)=0` (LD:605) but still draws twice (LD:607, 611).

### Not determined (section 2)
- Validity in ghost locations of `iwegv`, `hev`, `nadapt_com`/`hadapt_com`, `hdenv`, `wxv/wyv`, `difhv`.
- Whether `difv`/`utlnv` computed locally match the owner's values without `bextra_exchange`.

---------------------------------------------------------------------------------------------------

## 3. Random numbers

### Generators
- **Intrinsic `random_number`**:
  - Model code never seeds it.
  - `random_seed` is called only in test routines: `queue_test` (`src/utils/generic/queue.f90:389`), `list_test` (`list.f90:440`), `stack_test` (`stack.f90:399`).
  - `init_random_seed` (`src/utils/generic/random.f90:52-100`) is called only by `test_mod_rand` (random.f90:157).
  - The default seed, and whether the state is per thread or per rank, depend on the compiler (not from the repo).
  - Other model users share the same intrinsic stream: `suboi.f90:386-387`, `waves_admin.f90:1756-1757`, `time_admin.f90:880`, and `src/utils/shympi/mpi_custom.f90:68` (custom partition only).
- **`ggrand(init)`** (`src/utils/generic/random_gen.f90:66-86`):
  - One saved global stream built on `shyran2` (random_gen.f90:174-200).
  - `init` reseeds only on the FIRST call of the program, or when `init<0` (random_gen.f90:79-82).
  - So the seeds 77, 2387, 0 and 99 used below all share one stream, seeded by whichever caller comes first.
- **`shygasdev` / `shyran1`** with a saved `idum=387` (LD:712-763; random_gen.f90:135-170): used only by `lag_rand` ← `lag_diff` ← `track_body`, the old path (LM:892-900). That code runs only when `.not.bback`, and `track_body` is reached only with `bback=.true.` (lagrange_back.f90:64, 123), so it is dead.

### Call sites
| # | routine | file:line | generator | active when |
|---|---|---|---|---|
| R1 | `track_xi_next_element` | LV:618-621 | intrinsic | always, when a particle lands on a vertex (`in==2`) during advection |
| R2 | `lag_get_dxdy` ← `lag_diff_hor` ← `diff_body` | LD:607, LD:611 | intrinsic, 2 draws | every live particle, every step (`bhdiff` always true), **even with `rwhpar=0`** |
| R3 | `diff_get_vert` | LD:398, plus `rgauss` LD:407 → LD:636-642 (loops ≥2 draws) | intrinsic | `bvdiff` (true only for `ilagr=3`, LM:434), each vertical sub-step (mode 3, LD:105) |
| R4 | `lgr_diff_vert` | LD:260 | intrinsic | `bvdiff`, when `lmax==1` and the particle leaves the layer |
| R5 | `lag_beach` | LM:772 | intrinsic | `lbeach>0` and the particle is on a material side |
| R6 | `insert_particle_3d` | LIO:344 | intrinsic | 3D release with `ipvert<-1` |
| R7 | `lgr_set_sedim` | lagrange_sedim.f90:146 | intrinsic | `ised>0`, once per insertion |
| R8 | `lgr_sediment` | lagrange_sedim.f90:236 | intrinsic | `ised>0`, per bottom particle |
| R9 | continuous release | LC:104, 165, 234, 256 (`rp`); 317-318 (`create_parts`); 418 (`find_elem_to_node`); 465, 468 (`release_on_point`) | `ggrand(77)` | `lgrpps≠0` on a boundary; also connectivity releases (LCN:218 → LC:465-468) |
| R10 | `lagrange_decay` | lagrange_decay.f90:109 | `ggrand(2387)` | `ldecay>0`; one draw per array entry i=1..nbdy, dead entries included |
| R11 | `lagr_decay` | lagrange_decay.f90:157 | `ggrand(2387)` | never: only via `lagr_func`, which has no caller |
| R12 | `treat_larva` | lagrange_larve.f90:103 | `ggrand(0)` | `ilarv>0`, per live particle (`perc=0`, so the draw has no effect but advances the stream) |
| R13 | `test_compress` | LIO:1024, 1027 | `ggrand(99)` | never called |

- With `rwhpar=0` and no decay, for `ilagr=1/2` with no `lgrpps`/connectivity/beaching/sediment/larvae: **R1 and R2 are active**.
- For `ilagr=3`, R3 and R4 are added.
- R2 happens inside the OMP loop, so the order of draws across particles follows the thread schedule.

---------------------------------------------------------------------------------------------------

## 4. Particle record

### Types (`lagrange_data.f90`)
- `lagr_body` (`:65-72`):
  - `xi(3)` double
  - `time` double
  - `z` real
  - `ie` int: local element; negative means exited
  - `ie_global` int: `ip_int_elem`
  - `l` int: layer; −1 means on the bottom (sediment)
- `lagr_entry` (`:74-82`):
  - `bitmap_in`, `bitmap_out`: `integer(kind(bm_kind))`, where `bm_kind` is `integer*8` (`:56`)
  - `sinking` double
  - `custom(:)` real allocatable
  - `id` int, `type` int
  - `init` and `actual`, both `lagr_body`
- Storage: `lgr_ar(:)` (`:84`). It grows and shrinks in `mod_lagrange_handle_alloc` (`:250-262`: min 1024, doubles, halves below 1/3) and `mod_lagrange_init_body` (`:266-299`, `move_alloc`).

### Counters and dimensions
- `nbdy`: count of used entries, dead ones included (`:106`).
- `idbdy`: last id issued, per process (`:107`). Set to 0 at LM:421 and incremented only in `insert_particle` (LIO:111). `lgr_input_shell` takes ids from the file and never updates `idbdy` (LIO:629-660).
- Naming: the STR key `nbdy` (particles per release, read at LI:66 and LI:198) is a different thing from the module counter `nbdy` below.
- `nbdymax` (`:58`, from STR LM:211-215): checked per rank in `insert_particle` (LIO:113-118) and `lgr_input_shell` (LIO:621-626).
- Initialisation order bug: `lgr_mpi_init` runs at LM:193, before `nbdymax` is read at LM:211.
  - So `max(nbdymax,1024)` at LMPI:61 sees the default 0, and the export buffers are always 1024 entries.
  - `lgr_mpi_mark_export` aborts once a rank exports more than 1024 particles in one step (LMPI:85-87).
  - `lgr_pack_size=13+ncust` (LMPI:56) is fixed at that moment too, before LIO:578 or LIO:170 can change `ncust`.
- `ncust` (`:59`, default 1): overwritten with `nc` on every insertion (LIO:170). `nc` is always 1 (LM:477, lagrange_sedim.f90:160). It is read from the file in `lgr_input_shell` (LIO:578).

### Writes to fields (exhaustive grep `lgr_ar(...)%... =` in src/shyfem, plus whole-record writes)
- `insert_particle` LIO:110-174:
  - `init%time`, `actual%time` LIO:121-122
  - `init%ie=-ie`, `init%l`, `init%z` LIO:133-135
  - `actual%ie`, `actual%l`, `actual%z` LIO:136-138
  - both `ie_global`, only if `ie>0` (LIO:139-142)
  - both `xi`, only if `ie>0` (LIO:144-149)
  - `id=idbdy` LIO:158; bitmaps through `lagr_connect_bitmap_init` LIO:160 (LCN:960-971)
  - allocate `custom(nc)` LIO:168; `type`, `sinking`, `custom(1)` LIO:172-174
- `lgr_input_shell` LIO:631-658: the same fields, from the file.
- `copy_particle` LIO:431 (whole record).
- `delete_particle` LIO:468 (`actual%ie=0`).
- `lgr_insert_particle_to_be_deleted` LIO:501-513 (no caller).
- `lgr_output` LIO:825 (`init%ie=-ie`, which flips the "new" flag positive after writing).
- `track_single` LM:624-635: `actual%ie`, `ie_global`, `xi`, `z`, `l`, `type`; `actual%time` only if `ie>0`.
- `lagrange_decay`:
  - lagrange_decay.f90:110 sets `actual%ie=0`.
  - `lagr_decay` :159 and `lagr_conc` :185 have no callers.
  - `lagr_surv` :236 sets `ie=-ie` (no caller either: `lagr_func` is uncalled).
- `lgr_sediment` lagrange_sedim.f90:244, 253-254 (`actual%l`, `actual%z`).
- `lgr_larvae` lagrange_larve.f90:58, 79-80 (`custom(1)`, `actual%z`).
- `drogue_back` lagrange_back.f90:127-128 (`actual%z`, `actual%l` for i=1..nel).
- `lagr_connect_count` LCN:576, 580-581 (bitmaps); `bitmap_copy` LCN:983-984.
- MPI code:
  - `lgr_mpi_unpack_particle` writes the whole record through dummy `p` (LMPI:144-168).
  - `lgr_mpi_exchange` LMPI:299 (`actual%ie=ie_local`) and LMPI:308 (`actual%ie=0` for exported particles).
  - `lgr_mpi_gather_output` overwrites rank 0's `lgr_ar(1:nbdy_global)` (LMPI:426-436).

### What `lgr_mpi_pack_particle` (LMPI:96-129) omits or corrupts
- The whole `init` body is not packed (`xi`, `time`, `z`, `ie`, `ie_global`, `l`). On unpack, `p%init=p%actual` after `actual%ie=0` (LMPI:167-168). As a result:
  - `init%ie=0`: loses the "new" flag used by `lgr_output` LIO:748-752 and the source element used by `lagr_connect_count` LCN:543-544.
  - `init%time` becomes the current time instead of the insertion time, which breaks age in decay (lagrange_decay.f90:107).
- `actual%ie` is not packed; `ie_global` is sent instead.
- Bitmaps are packed as `dble(int8)` (exact only up to 2^53) and unpacked with `nint()` into the default integer kind (LMPI:154-155). Bits above 31 are lost or overflow, while the station limit is `bit_size(bm_kind)-1`=63 (LCN:257).
- The custom count `buf(13)` comes from the module `ncust`, not from `size(p%custom)` (LMPI:119-127).

---------------------------------------------------------------------------------------------------

## 5. Release paths

STR keys (section `$lagrg`, `src/shyfem/def_para.f90:1466-1597`):
- Core: `ilagr` (:1478), `nbdymax` (:1486), `nbdy` (:1492), `rwhpar` (:1499), `itlanf/itlend` (:1504-1505), `itmlgr/idtlgr` (:1511-1512), `idtl` (:1519), `itranf/itrend` (:1525-1526).
- Vertical release: `ipvert` (:1535), `linbot`/`lintop` (:1539-1542).
- Physics: `stkpar` (:1549), `dripar` (:1555), `lbeach` (:1560).
- Files: `lgrlin` (:1566), `lgrtrj` (:1572), `lgrini` + `itlgin` (:1577-1582).
- Other: `artype` (:1589), `lcust`, `ldecay`, `ioil`, `ilarv`, `ised` (:1593-1597).
- Boundary key `lgrpps` (`src/utils/shyutilmpi/bnd_admin.f90:538-547`).
- Connectivity section is named `'connec'` in `def_para.f90:2005-2016` (`icnn`, `radcnn`, `ppscnn`, `pldcnn`, `idtcnn`, `statcnn`), but read as `'connect'` in LCN:105-106.

| path | selected by | position choice | serial id order | owner filter |
|---|---|---|---|---|
| `lgr_init_shell` LI:56-85 | `nbdy>0`, at release times (LM:284) | dispatch: `lgrtrj` set → return; `lgrlin` blank → `lgr_init_total`, else `lgr_init_line`; both set → stop LI:72-75 | — | — |
| `lgr_init_total` → `lgr_init_all` LI:89-108, 524-585 | `lgrlin` blank | `dxy=sqrt(area/nbdy)` from `compute_total_area` = 12·Σ`ev(10,ie)` over LOCAL nel (`lagrange_util.f90:119-140`); origin `basin_center` = mean of LOCAL `xgv/ygv` (`lagrange_util.f90:103-115` → `line_util.f90:255`); regular grid points tested with `intri` per element (boundary-inclusive, so a point on a shared edge is inserted in both elements, inferred) | ie=1..nel, then i (x) outer, j (y) inner; per point `insert_particle_3d` (0, 1 or n per vertical rule) | **yes**: `id_elem(1,ie)/=my_id` → cycle (LI:554) |
| `lgr_init_line` → `lagbound_seed_particles` LI:112-155, 415-520 | `lgrlin` set | `dxy` from polygon area (`lagbound_get_area` LI:263-305, mesh-independent); origin `xy_center` of the polygon (LI:451); `check_elements` flags (`line_util.f90:40`); point accepted if `ifl==1 .or. inpoly` (LI:503); type = polygon index `iln` | polygon in file order, then ie=1..nel, then i, then j | **no** |
| `lgr_init_traj` LI:159-257 | `lgrtrj` set (each step) | read from file; `find_element(x,y,ie)` on the local mesh (LI:248); `nbdy` particles per record; type = record index | records 1..nt matching `dtime` | **no**; on a rank without the point, `ie=0` → `insert_particle_3d` reads `ilhv(0)` (LIO:286) |
| `lagr_continuous_release_pps_ppv` LC:192-279 (the only one used, LC:56-64) | per boundary `lgrpps≠0`, while `brelease` (LM:312-316) | `ibtyp` 1/2 (LC:229-251): accumulator `rp` (seeded by `ggrand`) over segments `kbnds(i-1..i)`, flux `get_bflux_ppv`→`flux2d` or length share; `create_parts` LC:283-325 puts points at random `rl` along the segment and random time `rt`. `ibtyp` 3 (LC:253-268): `release_on_node` → `find_elem_to_node` (random element among those containing k, alpha=0.99 toward the node, LC:385-445) → `release_on_point` LC:449-473 | ibc order, then segment order, then np per segment | **no**. Under MPI `irv(k)=0` for nodes outside the domain (`bnd_admin.f90:772-791`), ghost nodes kept (`:780-781`), whole boundary absent → `ibtyp=0` (`:803-805`), so `kbnds` can return 0 (inferred) |
| connectivity `lagr_connect_continuous_points` LCN:161-233 | `icnn>0` | stations from `statcnn`; `find_element` per station, which **stops** if the station is not local (LCN:860-882); `release_on_point` each step LCN:215-222 | station 1..np | **no** |
| `lgr_input_shell` LIO:519-666 | `lgrini` set (first call) | reads block `iwhat=0` at `itlgin`; `iea(i)` from the file used directly as the LOCAL element (LIO:635, 653) | file order, ids from the file | **no** |

- All paths end in `insert_particle` (LIO:69-178) through `insert_particle_3d` (LIO:255-356) or `insert_particle_surface` (LIO:360-377).
- Vertical rule in `insert_particle_3d`:
  - 2D, surface, or `ipvert==0`: lb=1, z=0.5 (LIO:309-314).
  - `ipvert==-1`: one per layer `lintop..linbot` (LIO:316-322).
  - Otherwise n regular or random depths (LIO:328-350).
- In `insert_particle`:
  - `ie==0` triggers `find_element` (LIO:124-129).
  - `xi` is set through `xy2xi` + `xi_move_inside` (eps 1e-5, LIO:182-251).
  - Insertion time is `t_act-dt_act*(1-rtime)` (LIO:121).

---------------------------------------------------------------------------------------------------

## 6. Output (.lgr) and readers

### File setup
- `shyfem_init_lgr_file('lgr',1,.false.,id)` (LM:263) runs `src/utils/shyutilmpi/shy_util.f90:569-598`:
  - name `<runnam>.lgr.shy`
  - `ftype=3`, `npr=1`, `nlg=nlv_global`
  - basin and levels of the GLOBAL mesh (`shy_open_output_file` :707-762 with `nkn_global/nel_global`; `shy_copy_basin_to_shy` writes `nen3v_global` :196)
- Only the master opens the file (`bopen=shympi_is_master()`, shy_util.f90:729-731).
- On other ranks, `shy_open_file` returns a unit number without opening it (src/utils/shyutil/io_shy.f90:454-463). LM:265-266 still runs `write(iu) ncust` on EVERY rank, which would implicitly create `fort.<iu>` on non-master ranks (inferred, gfortran behaviour).
- `lgr_write_header` (LIO:670-687; `mtype=367265`, `nvers=6`) and `lgr_get_header` (`io_lgr.f90:80-111`) have NO callers.

### Live record layout
1. shy header (ftype 3).
2. Record `ncust` (LM:266).
3. Per output time, `lgr_output` LIO:691-868 writes three blocks, each led by a record `dtime(dp), n, iwhat`:
   - `iwhat=0` active particles, `actual%ie>0` (LIO:768-793)
   - `iwhat=-1` inserted, `init%ie<0` (LIO:799-827)
   - `iwhat=1` exited, `actual%ie<=0`, which includes deleted and exported entries with `ie=0` (LIO:835-862)
4. Per particle, 3 records:
   - `id, type, tt(dp), s(real), ie`
   - `x, y, z(real), lb, hl(real)`
   - `c(1:ncust)`
   - The active block writes the local `ie` (LIO:790); the other blocks write `abs(ie)` (LIO:821, 857).
   - The active block writes `c=custom`; the other blocks write `c=custom(1)` broadcast (LIO:786, 817, 853).
- `lgr_output` returns before writing anything when `nbdy==0` (LIO:733).
- Exited particles are written again at every output, because `compress_particles` never runs (section 7).

### Values that need element data
- `xi2xy(abs(ie),…)` at LIO:777, 808, 844. With `ie=0` this calls `xi_abc(0)`, an out-of-bounds read of `ev(:,0)`. That case occurs in the exited block for decayed or deleted particles, even in serial (inferred).
- `lgr_compute_depths(ie,…)` reads `hdenv(l,abs(ie))`, `ilhv` (LIO:872-906).
- The `ie` written is the LOCAL index. Readers use it as an index into the file's (global) basin:
  - `lgrelab1.f90:670-674, 724-732` (`ilhv(ie)`, `ecount(l,ie)`)
  - so under MPI the written value must be the global internal number (`ip_int_elem`, matching `l2g` at MN:2642-2647; inferred).

### Current MPI path, `lgr_mpi_gather_output` (LMPI:351-441)
1. Allgathers counts.
2. Packs `actual` only.
3. `MPI_Gatherv` to rank 0.
4. Rank 0 unpacks into its OWN `lgr_ar(1:nbdy_global)`, with `ie=0`, then calls `lgr_output` and restores `nbdy` (LMPI:425-437).
- Effects (inferred):
  - rank 0's own particles are overwritten by copies with `ie=0`
  - every gathered particle falls into the exited block with `xi2xy(0)`
  - `n_new` is always 0, because `init%ie=0`

### Readers (the format must stay readable)
- `lgrelab` (`src/tools/shyelab/lgrelab1.f90`):
  - reads the shy header, then `read(iu) ncust` (:210-211), then the 3 blocks (:289-320)
  - age = active `tt` minus insertion `tt`, matched by `id` through `minloc(abs(idstore-ida))` over the inserted block (:343-371)
  - so it needs unique ids and a non-empty inserted block
- `shyplot` (`src/tools/shyplot/shyplot.f90:333-337, 401-472`): same id-matching age logic (:416-472).
- Model restart from file: `lgr_input_shell` (LIO:575-607).
- Shared helpers in `src/utils/shyutil/io_lgr.f90`:
  - `lgr_is_lgr_file` :41-74 (shy ntype 1617, ftype 3)
  - `lgr_peek_block_header` :117-139
  - `lgr_alloc` :145-204
  - `lgr_get_block` :210-275
  - `lgr_skip_block` :281-324
- The UI service runs `lgrelab -lgmean` (`shyfem-ui/shyfem_ui/services/lgr_service.py:1-76`; test data recipe in `testcases/examples/mar_menor/mm_lgr.str:1-20`).

### Other outputs
- Connectivity: list-directed `write(137,*)` and `write(128,*)` (files `fort.137`, `fort.128`) from every rank (LCN:664-668, 707-710).
- `lagr_count_out` writes `lagr_count_out.txt` on hard-coded unit 237 (LM:986-993); it is dead code (section 7).

---------------------------------------------------------------------------------------------------

## 7. Sub-modules and options

| option | switch | loop / MPI-relevant behaviour |
|---|---|---|
| Sediment | `ised>0` (LM:209) | `lgr_sedim_init` LM:224; `lgr_set_sedim` at insertion (lagrange_sedim.f90:107-162); `lgr_sediment` loops particles i=1..nbdy (:221-259), reads `taubot(nen3v)` weighted by xi (:234-235); calls `bottom_stress` if `isedi==0` (:215; `taubot` exchanged at `substress.f90:186`); forces `bcompress=.false.` (:207); no global sums |
| Larvae | `ilarv>0` (LM:208) | `lgr_larvae` loops particles (lagrange_larve.f90:64-81); calls `xi2xy(abs(ie))` even for `ie=0` (:71); `ggrand(0)` per live particle; no sums |
| Decay | `ldecay>0` (LM:203) | loops all `nbdy` entries with one `ggrand` each (lagrange_decay.f90:106-111); age from `init%time`; per-rank stream |
| Connectivity | `$connec icnn>0` (LCN:108-110) | sets `bconnect` (LCN:186, 201); per-element `i_connect_elems/total`, `t_connect_total(nel)` (LCN:268-277); station matrices `i_connect`, `t_connect`, etc. `(50,50)` (LCN:78-84) updated inside the OMP loop; `lgr_mpi_reduce_connect` (LMPI:467-494) allreduces `i_connect` and `t_connect` IN PLACE every step (LM:361); the matrices are reset only at init (LCN:200; reset commented at LCN:230), so counts compound across steps (inferred); `if_connect`, `tf_connect`, `agef_connect`, `i_connect_released` and the element totals are not reduced; `ip_orig` from `init%ie`, which is negative before the first output (LIO:133, 825; LCN:543-552) |
| Beaching | `lbeach>0` (LM:204-205) | per-particle random draw on a material side (LM:769-774); a beached particle has `type<0` and stops (LM:673; LD:90) |
| Backtracking | `itlin=1` (`explicit.f90:193-196`; STR section not checked) → `set_semi_lagrange` → `back_trace` (lagrange_back.f90:52-75) | sets `bback=.true.`; recomputes fluxes; `bar_ie` puts one tracer per element at its barycentre; `drogue_back` loops `i=1..nel` using `lgr_ar(i)` and the old `track_body` (lagrange_back.f90:101-133); `lagr_vel` loops elements, reads `uprv/vprv` (node) and `zeov` (lagrange_back.f90:137-262); independent of `lagrange()` (which sets `bback=.false.` LM:278) |
| `bcompress` | never set `.true.`; only set `.false.` at lagrange_sedim.f90:207 | so `compress_particles` (LIO:934-997) never runs and `lgr_ar` keeps dead entries |
| `lagr_count` | `bcount` is never set `.true.` | `lagr_count_out` (LM:375-378) never runs; `lagr_count_init` still zeroes over nel every step (LM:319); `lagr_count` is called only when `bconnect` (LM:696) |
| Oil | `ioil>0` sets `boilsim` (LM:207) | passed to `lgr_set_properties`, which ignores it (LM:481 commented); no effect |
| Stokes / wind drift | `stkpar>0` | `lag_stk` per surface particle (lagrange_stk.f90:83-146); node `wxv/wyv`; element search |
| Vertical diffusion | `bvdiff`, true unless `ilagr` is 1 or 2 (LM:434) | per particle; per-element `wde/dtvd` from `lag_vdiff_ele` |
| Horizontal diffusion | `bhdiff` always `.true.` | runs even when `rwhpar=0` (section 2) |
| Transit area | `artype` (LM:409) | per-particle `iarv(iel)==artype` sets `iel=-iel` (LM:737; LD:147) |
| `lcust` / `lagr_func` | `lcust` | dead: `lagr_func` has no caller (lagrange_decay.f90:49-74) |

---------------------------------------------------------------------------------------------------

## 8. MPI helpers available

### (a) Element exchange
Copies from the main owner to the other holders. The owner sends its `ghost_elems_in` (`id_elem(1,ie)==my_id`); the others receive into `ghost_elems_out` (mpi_ghost.f90:300-322; MNI:681-803).
- `shympi_exchange_2d_elem(val)`: integer, real or double `val(nel)`. Generic at MN:295-299; bodies MN:1396-1443.
- `shympi_exchange_3d_elem(val)`: REAL only, `val(nlvdi,nel)`. MN:289-293, 1328-1341.
- `shympi_exchange_fix_elem(nfix,val)`: INTEGER only, `val(nfix,nel)`. MN:267-269, 1229-1254.
- No real/double fixed-first-dimension or 3-index variant exists, so nothing fits `flux3d(nlv,3,nel)` directly.

### (b) Exchange-and-sum
Phase 1 adds ghost values into the owner; phase 2 runs the forward exchange (MNI:925-1050).
- `shympi_exchange_and_sum_3d_nodes(a)`: real or double `a(:,:)`. MN:503-506, 3967-4005.
- `shympi_exchange_and_sum_2d_nodes(a)`: real or double. MN:508-511, 4009-4047.
- **No element variant**: `belem=.false.` is hard-coded. Node min/max variants exist at MN:513-521, 4049-4129.

### (c) Reductions
- `shympi_sum`, `shympi_min`, `shympi_max` (generics MN:415-440):
  - a scalar argument (the `_0_` variants) gives the global value
  - an array argument gives a global scalar of the local SUM/MIN/MAX
  - bodies MN:3633-3905
- `shympi_array_reduce(what,vals)`: element-wise allreduce. MN:442-446, 3909-3931.
- `shympi_reduce(what,vals,val)`: real only. MN:3937-3957.
- `shympi_gather_and_sum(val(:))`: allgather + SUM. MN:384-388, 2269-2319.
- `shympi_collect_node_value(k,vals,val)`. MN:404-409, 2372-2419.

### (d) Gathering variable-length arrays to rank 0
- **No true gatherv in shympi.**
  - The internal layer needs equal lengths: `ni/=no` aborts (MNI:1665-1669, 1801-1804).
  - The public `shympi_gather` wrappers accept `size(val) <= size(vals,1)` and zero-pad to the common size (MN:1896-1909). Unequal local lengths therefore work only by padding every rank to one maximum size.
- What does exist:
  - `shympi_gather(val,vals)`, padded fixed size; allgather when `bmpi_alloper` (MN:363-374, 1855-2235)
  - `shympi_gather_root` (double, MN:376-378, 2238-2263)
  - `shympi_bcast` (MN:394-398, 2325-2366)
- `src/utils/shympi` has no `gatherv` or `alltoall`. LMPI calls `MPI_Alltoall` (LMPI:236), `MPI_Alltoallv` (:279), `MPI_Allgather` (:381), `MPI_Gatherv` (:418) and `MPI_Allreduce` (:486, 490) directly.

### (e) Ownership tests
- `shympi_is_inner_node(k)`: `k<=nkn_inner`, i.e. own. MN:1045-1052.
- `shympi_is_inner_elem(ie)`: `ie<=nel_inner`, i.e. all 3 nodes own. MN:1056-1063.
- `shympi_is_unique_node`: MN:1067-1074.
- `shympi_is_unique_elem(ie)`: `ie<=nel_unique`, i.e. `id_elem(1,ie)==my_id`. MN:1078-1085.
- Arrays `id_node`, `id_elem(0:3,:)` (MN:189-199).
- `shympi_is_master` / `shympi_output` (`my_id==0`, MN:4135-4151); `shympi_is_parallel` (MN:4193).
- `shympi_partition_on_nodes` is always `.true.` (MN:1033-1039).
- Local ordering:
  - nodes `1..nkn_inner` are own (mpi_basin.f90:507-524)
  - elements: `1..nel_inner` inner, `..nel_unique` border with main owner me, the rest main owner another rank (mpi_basin.f90:631-646)
- Main-owner rule: the owner of 2 of the 3 nodes. At a triple point, the owner of the node with the smallest global number (mpi_basin.f90:569-605; doc :440-461).

### (f) Global ↔ local lookup
- `ip_int_node(:)`, `ip_int_elem(:)`: local to global internal (MN:217-218).
- `ip_int_nodes`, `ip_int_elems(:,ia)`: per-domain tables (MN:222-223).
- `ipint(k)` / `ieint(ie)`: external to LOCAL internal, linear search, 0 if absent. `ipext`/`ieext` go the other way (`src/utils/shyutil/fem_util.f90:149-245`).
- `shympi_find_node(ke,ki,id)` / `shympi_find_elem(ieext,ieint,id)`: collective allgather, returns the internal number plus owning domain, searches unique items only (MN:2441-2538).
- `shympi_internal_node`/`shympi_internal_elem(external)`: global internal index by scanning `ip_ext_node`/`ip_ext_elem`, O(n_global) (MN:889-919).
- `lgr_mpi_global_to_local_elem`: linear scan of `ip_int_elem` (LMPI:322-347).
- No hashed global-to-local map was found.

### Abort and direct MPI elsewhere
- `shympi_abort_internal(message)`: MNI:303.
- Direct MPI in src/shyfem outside LMPI:
  - only `ww3.f90` (`use mpi` :40, `mpi_reduce` :247, `MPI_SEND` :259)
  - `include 'mpif.h'` appears only in LMPI (:190, 359, 476)
  - the case-insensitive `call mpi_` hits in `custom_admin.f90:220-223` and `shyfem_subs.f90:649` are SHYFEM routines (`mpi_test_basin`, `mpi_debug`), not MPI library calls.

---------------------------------------------------------------------------------------------------

## 9. OpenMP in drogue

- Directive at LM:520-528: `!$OMP PARALLEL DO DEFAULT(SHARED) PRIVATE(i,it)` over `i=1,nbdy` calling `track_single(i,dt,dtime)`.
- There is no SCHEDULE clause, so the default schedule is implementation-defined.
- Thread count: STR `nomp` defaults to 0, which forces 1 thread (`iostr.f90:763-771`; `def_para.f90:1833`). Neither Lagrangian test sets `nomp`, so (inferred) both run the loop on one thread.

Shared state written inside the loop:
- `ic(it)`, indexed by thread number (LM:523-524).
- `lgr_ar(i)` fields (LM:624-635): a distinct `i` per iteration.
- `blgrdebug` (module variable): set at LV:311 and LD:191 in every particle.
- Saved counters `nk`, `nl`, `nu` in `track_body_xi` (LM:669-671, 721-731) and in `diff_body` (LD:86-88, 131-141). Unsynchronised. They also divide by `idbdy`, which can be 0 on a rank.
- First-call saved `icall`/`bsphe` in `lag_diff_hor` (LD:519-529) and `lag_stk` (lagrange_stk.f90:61-81).
- When `bconnect`:
  - `lagr_connect_count` writes `i_connect_total`, `t_connect_total`, `i_connect`, `if_connect`, `t_connect`, `tf_connect`, `agef_connect` (LCN:533-534, 586-611). Unsynchronised.
  - `lagr_count` writes `i_count`, `t_count` (LM:961-962).
- `lgr_mpi_mark_export` updates `n_export`, `export_idx`, `export_dest` under `!$OMP CRITICAL (lgr_export)` (LMPI:83-90). The order of the export list follows the thread schedule.
- Intrinsic `random_number` calls (R1–R5, section 3): whether the generator state is shared or per thread is compiler-dependent.
- `write(6,…)` diagnostics (LM:710-733; LV:354-356 and others).

---------------------------------------------------------------------------------------------------

## 10. Tests

### `testcases/examples/mar_menor_lagrange/mm_lgr_01.str`
- Basin: `GRID/MM_coarse_smooth`, Cartesian UTM. `GRID` is a symlink created by the Makefile `links` target.
- Run: 2009-01-01 to 01-03, `idt=30s`. No `$levels`, so 2D (inferred).
- `$lagrg`: `ilagr=1` (surface), `nbdymax=100000`, `idtlgr=3600`, `idtl=86400`, `nbdy=1000`.
- `rwhpar` defaults to 0, so whole-domain daily release through `lgr_init_all`.
- Boundaries:
  - `$bound1` is an open level boundary (`ibtyp=1`) with **`ztilt=0.008`, `ktilt=130`**. These now stop an MPI run (`bnd_admin.f90:714-730`).
  - `$bound2` is a river node (`ibtyp=3`) with no `lgrpps`, so no continuous release.
- Driver `mm_lgr_01.sh` checks only that `$sim.hydro.shy` exists, then makes plots. It never checks particle output.

### `testcases/examples/mar_menor/mm_lgr.str`
- Basin: `GRID/MM_geo`, GEOGRAPHIC (tracked).
- Run: 2009-01-01 to 01-05, `idt=300s`, `ilin=1`. No `$bound` sections, so a closed basin.
- `$lagrg`: `ilagr=1`, `nbdymax=5000`, `nbdy=150`, `idtl=0` (single release at start), `idtlgr='1h'`, **`rwhpar=0.5`**, `lgrlin='release_areas.txt'`.
- `release_areas.txt` (tracked) holds 3 polygons, so `lagbound_seed_particles` creates types 1–3. There is no owner filter on this path.
- Spherical branches are active in `lag_diff_hor` (`ev_c2g`, LD:561-569).
- Its header (`mm_lgr.str:1-20`) says it is the source of UI test data (`lgrelab -lgmean`).
- `mm_lgr.lgr.shy`, `mm_lgr.hydro.shy` and `mm_lgr.inf` exist locally but are untracked.

### Particle-output checks
- No script compares `.lgr` output. There is no Fortran regression for particles.
- `shyfem-ui/tests/test_lgr_service.py` tests only the parsing of `lgrelab` text output, with fixtures and mocks.
- CI never runs a Lagrangian case:
  - The serial feature battery runs `mm_hyd_beach`, `mm_hyd_assim`, `mm_rst_cycle_write`, `mm_rst_cycle_read` (`.github/workflows/fortran-ci.yml:64-72`), plus `mm_hyd_41_6h` and the venlag smoke tests (:80-102).
  - The MPI job runs `mpirun -np 2 shyfem mm_hyd_00.str` (:157).
  - Lagrangian code appears only in a comment (:27-30): no serial build is maintained, because `lagrange_mpi.f90` calls MPI collectives directly.
- Partition files exist for Mar Menor: `testcases/examples/mar_menor/GRID/partition.{2,4}.txt` and `MM_coarse.{2,4}.{node,elem}.grd`.

---------------------------------------------------------------------------------------------------

## Not determined (overall)
- Validity in ghost or non-owned locations of `hdenv`, `iwegv`, `hev`, `nadapt_com/hadapt_com`, `wxv/wyv`, `difhv`.
- Whether locally computed `utlnv/unv/mfluxv/difv` equal the owner's values when `bextra_exchange=.false.`.
- `znv`/`zenv` ghost validity when the solver is PETSc (exchange skipped at `hydrodynamic.f90:409`).
- Whether 0 entries actually appear in `elist` for ghost nodes on real partitions.
- Default gfortran seed, and whether `random_number` state is per thread or per rank.
- Default OMP schedule.
- Whether the `'connec'`/`'connect'` section-name mismatch matters (section-name truncation not checked).
- Contents of `lagr_connect_write_entry` outputs (LCN:716-855, not read in full).
- Code not read: `lagr_connect_mark_elems` (LCN:337-476), `src/shyfem/lagrange_track.f90` (old tracker), `src/shyfem/lagrange_util_tr.f90`.
- Module attributions checked against declarations: `utlnv`/`zenv`/`zeov` in `src/utils/modules/mod_hydro.f90:48-50`, `unv` in `mod_hydro_baro.f90:42`, `ulnv`/`wlov`/`wlnv` in `mod_hydro_vel.f90:47-51`, `mfluxv` in `src/utils/shyutil/bnd_dynamic.f90:51`, `hev` in `src/utils/shyutil/depth.f90:46`. The other module attributions come from `use` lists only.
- Whether `bndo.f90` or `bndo_admin.f90` is the live `iopbnd` setter.
