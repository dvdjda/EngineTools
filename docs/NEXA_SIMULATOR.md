# NEXA Simulator — How It Works

The single most-referenced document in the project. Open this when you want to know what a number means, where it came from, and what the framework is asserting about it.

---

## 1. The big picture in one paragraph

The **GPU is the primary load**. It demands electrical power and dumps every watt of that electrical input as heat into the coolant — a single-phase **dielectric immersion fluid**, not chilled water (first law). The **Gas Turbine (GT)** follows the GPU + plant aux load: in island mode it's pinned by what the bus can absorb, in grid-tied it can ramp higher and inject the surplus to the grid (export-only — imports are forbidden). The GT's exhaust feeds a **Heat Recovery Steam Generator (HRSG)**, which makes steam at a pressure you set. **All** of that steam goes to a single **LiBr absorption chiller** — there is no steam splitter and no MED steam feed; the chiller drives the cooling for the GPU dielectric loop. The chiller's **heat rejection** leaves as a hot cooling-water loop that in turn drives a **Multi-Effect Distillation (MED)** unit (rejection-driven, not steam-driven) to make fresh water, then passes to a dry **Radiator** with forced-air fans and a 3-way bypass valve that trims the loop return to the HRSG feedwater set-point and closes the loop. A second 3-way bypass around MED (default **Auto**) cascades with the radiator to hold the HRSG return at set-point — it opens just enough to keep MED from over-cooling the loop below the feedwater set-point.

Every solve runs three independent status layers:
- **Convergence** — did the solver loops settle? (the GPU↔LiBr dielectric loop is a real recycle, torn and solved by Wegstein)
- **Feasibility** — does supply ≥ demand for power and cooling? (with a 2.5 % screening tolerance on each for controller-vs-block precision noise)
- **Audit** — do all 42 first-principles checks pass? (mass closures, energy closures, second-law temperature feasibility, plausibility bounds)

The per-KPI "verified / unverified / screening" basis is **data-driven from audit coverage** — a KPI gets `verified` only if at least one audit check that names it actually passed. No hardcoded strings.

---

## 2. System flowsheet

```
                  ┌─────────────────────────────┐
                  │  Natural Gas  (LHV input)   │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │      GAS TURBINE         │──► GT GROSS power
                    │   (derated by site       │      − GT aux (internal derate)
                    │      ambient)            │      = GT NET power → bus
                    │                          │──► exhaust gas (hot)
                    └─────────────┬────────────┘    GT cooling water (small heat)
                                  │ exhaust
                                  ▼
                    ┌──────────────────────┐
                    │        HRSG          │──► stack flue gas (cooled exhaust)
                    │  exhaust → steam     │
                    └─────────────┬────────┘
                       feedwater  │ ALL steam (P_steam, t_sat+30°C)
                       (= loop     │
                        return)    ▼
                ┌──────────────────────────┐
                │      LiBr CHILLER        │──► CHW supply (dielectric, cold) ─┐
                │  Q_gen = ṁ_steam·Δh      │                                   │
                │  Q_cool = COP × Q_gen    │◄── coolant return (warm) ◄───────┐│
                │  Q_cond = Q_gen + Q_cool │                                  ││
                │  → reject_out (hot loop) │   ┌──────────────────────┐       ││
                └──────┬───────────────────┘   │   GPU CASSETTE       │       ││
                       │ reject_out            │  silicon + cassette  │       ││
                       │ (hot water, Q_cond)   │  overhead → heat     │       ││
                       ▼                        │  (dielectric coolant,│       ││
                ┌─────────────────┐             │   30°C→42°C, ΔT 12K) │       ││
                │       MED       │             └──────────────────────┘       ││
                │  rejection-     │──► fresh water         ▲                   ││
                │  DRIVEN         │──► brine reject        └── CHW supply ──────┘│
                │  GOR ≈ 0.8·n    │       (3-way med_bypass_frac skips MED)      │
                │  loop_out       │                  coolant return ────────────┘
                └──────┬──────────┘                  (GPU↔LiBr dielectric recycle loop)
                       │ loop_out (cooling water)
                       ▼
                ┌─────────────────────────────┐
                │          RADIATOR           │
                │  dry, forced-air fans       │
                │  T_rad = T_amb + approach   │
                │  3-way auto bypass valve →  │──► loop_out trimmed to fw_t_C
                │  trims return to fw_t_C     │      (= HRSG feedwater set-point;
                │  fan_frac × Q_rad           │       closes loop to HRSG feedwater)
                └─────────────────────────────┘

                   ─── Electrical bus ───
                   │  SUPPLY = GT NET power (gross − GT aux)
                   ▼
   GT net power supplied →  GPU silicon            (IT power)
                            GPU cassette overhead  (IT × (cassette_pue − 1))
                            Itemised plant aux (from plant_loads.py):
                              · pumps (dielectric, LiBr, cooling-loop, BFP,
                                seawater, MED feed, brine, distillate, condensate)
                              · dry-cooler fan (VSD, cube law on utilisation)
                              · container HVAC + lights
                            External load          (island only — manual scalar)
                            Grid export            (grid only — computed residual)
```

---

## 3. The six blocks

Every block declares its **ports** (inlet / outlet streams), **params** (numeric inputs), the **physics** of its `compute()` method, and its **audit checks**.

The GT system wires six blocks: GasTurbine → HRSG → LiBrChiller → (GPUCassette dielectric recycle) ; LiBrChiller rejection → MED → Radiator → back to HRSG feedwater. (The `SteamSplitter` and `CoolingTower` block files still exist in `nexablock/blocks/` but the GT system no longer uses them.)

### 3.1 GasTurbine — `nexablock/blocks/gas_turbine.py`

Simple-cycle gas turbine — the power island. Its exhaust feeds the HRSG, its electrical output (net of GT auxiliaries) feeds the bus.

**Ports**:
- Outlet `exhaust` (generic fluid: hot exhaust to HRSG)
- Outlet `power` (electrical: GT gross power)
- Outlet `gt_cw` (energy: small GT cooling-water duty)

**Params**: `p_rated_kW` (ISO rating), `load_pct`, `gt_eff` (LHV basis), `t_ambient_C`, `t_exhaust_C`, `aux_frac` (default 1.0 % of derated capacity for GT auxiliaries).

**Physics**:
```
derate factor = max(0.50, 1 − 0.007 × max(0, T_amb − 15°C))     # 0.7%/°C above ISO 15°C
GT derated capacity = p_rated_kW × derate
GT gross (actual) power = GT derated capacity × load_pct / 100
Fuel energy input = GT gross / gt_eff
NG consumption = Fuel / LHV   (LHV = 50,050 kJ/kg)
Waste heat = Fuel − power
Exhaust heat = waste × 0.85   (CCGT GT, 15% lost to GT cooling water)
GT cooling water = waste × 0.15
Exhaust mdot = exhaust_heat / (cp_exh × (T_exh − T_amb))
GT aux electrical = aux_frac × GT derated capacity
GT NET power = GT gross − GT aux electrical    (the bus sees NET; GT aux is an internal derate)
```

**Audit checks**: E1 (NG·LHV·η=power), E2 (fuel = power + exhaust + GT_cw), M6 (NG closure), T8 (exhaust > ambient + 100°C), P1 (η in (0, 0.55)), P2 (derate in (0, 1]), P3 (load_pct in [10, 100]), P11 (actual ≤ derated).

### 3.2 HRSG — `nexablock/blocks/hrsg.py`

**Ports**: Inlet `exhaust_in` + `feedwater`; Outlet `stack` + `steam`. The `feedwater` inlet is the loop return set-point: the cooling loop closes back here (the radiator trims the loop to `fw_t_C`, and the feedwater seed is at `fw_t_C`).

**Params**: `hrsg_eff_pct` (effectiveness), `steam_p_bar` (drum pressure), `fw_t_C` (feedwater / loop-return set-point).

**Physics**:
```
Q_exhaust = ṁ_exh × cp_exh × (T_exh − 298.15)        # 298.15 K = HRSG fixed reference
HRSG duty = Q_exhaust × η_hrsg
Stack loss = Q_exhaust × (1 − η_hrsg)
T_sat = IAPWS-IF97 saturation at P_steam
T_steam = T_sat + 30°C    (fixed superheat for CCGT screening)
h_steam = h(P_steam, T_steam)        # superheated enthalpy
h_fw = h(P_steam, T_fw)              # compressed liquid enthalpy
ṁ_steam = HRSG duty / (h_steam − h_fw)
ṁ_steam capped at 0.999 × ṁ_feedwater_supply   (can't exceed FW available)
```

**Audit checks**: E3 (exhaust·η=duty), E4 (duty = ṁ·Δh), **M1 (feedwater supply ≥ steam consumed — sufficiency form)**, T1 (hot pinch > 0), T2 (cold pinch > 0), T3 (T_steam ≥ T_sat), P8 (HRSG eff in [50, 95]%), P9 (subcritical P_steam).

### 3.3 LiBrChiller — `nexablock/blocks/libr_chiller.py`

Single-effect LiBr-H₂O absorption chiller. There is no steam splitter: **all** HRSG steam feeds this one block.

**Ports**: Inlet `steam_in` + optional `chw_return` (the warm dielectric return from the GPU); Outlet `condensate` + `chw_supply` (cold dielectric coolant to the GPU) + **`reject_out`** (the chiller's heat rejection, leaving as a hot WATER stream into the cooling loop — drives MED, then the radiator, then back to the HRSG feedwater).

**Params**: `cop` (typical 0.65–0.75 single-effect), `chw_sup_C` (= dielectric supply temp `gpu_t_in_C`), `chw_dt_K` (= dielectric loop ΔT), `chw_cp` (= dielectric `coolant_cp`), `pump_frac` (legacy, screening), `reject_t_C` (`libr_reject_t_C`, the hot cooling-loop temperature), `reject_return_C` (= `fw_t_C`, the loop cold side / HRSG return set-point).

**Physics**:
```
h_cond_100 = h_sat_liq at 1 atm                  # saturated liquid condensate at 100°C
Q_gen  = ṁ_steam × (h_steam − h_cond_100)
Q_cool = Q_gen × COP
Q_cond = Q_gen + Q_cool                          # 1st law on chiller envelope
ṁ_chw  = Q_cool / (cp_chw × ΔT_chw)              # dielectric-coolant supply flow sizing
reject loop: ṁ_cw = Q_cond / (cp_w × (reject_t − reject_return))   # hot cooling-water flow
LiBr pump electrical = pump_frac × Q_cool        # legacy screening line
```
The chilled-water stream here is the **dielectric coolant** (cp ≈ 2100 J/kg·K, rho ≈ 780 kg/m³), supplied at `gpu_t_in_C` (default 30°C) — not 7°C chilled water. The heat rejection `reject_out` carries Q_cond at `reject_t_C` (default 95°C) down to `fw_t_C` (default 80°C) across the cooling loop.

**Audit checks**: E5 (Q_gen·COP=Q_cool), E6 (Q_cond = Q_gen + Q_cool), M3 (steam_in = condensate_out), T6 (T_chw_supply ≥ 5°C), T7 (T_chw_return > T_chw_supply), T9 (T_steam > T_condensate), P4 (COP in (0.5, 1.3)).

### 3.4 GPUCassette — `nexablock/blocks/gpu_cassette.py`

Single-phase **dielectric** immersion-cooled compute unit. The GT system instantiates one virtual cassette (`n_gpu = 1`, `p_gpu_kW = gpu_it_kW`) representing the whole data centre.

**Ports**: Inlet `coolant_in` (dielectric supply from the chiller); Outlet `coolant_out` (dielectric return — wired back to the chiller's `chw_return`, the recycle tear) + `heat` (energy).

**Params**: `n_gpu`, `p_gpu_kW`, `aux_frac` (= `cassette_pue − 1`, the cassette overhead inside the enclosure), `coolant_cp` (default 2100 J/kg·K, dielectric fluid — NOT water), `coolant_rho` (default 780 kg/m³), `dt_K` (= `gpu_t_out_C − gpu_t_in_C`, default 12 K: 30°C supply → 42°C return).

**Physics**:
```
IT power = n_gpu × p_gpu_kW
Cassette overhead electrical = IT × aux_frac     # itemised on both the power
                                                   demand AND the cooling demand
Heat load = IT + cassette overhead               # all electrical → heat by 1st law
PUE       = 1 + aux_frac
ṁ_coolant = Heat / (cp × ΔT)
```

**Audit checks**: **E7 (Heat = IT + Cassette_overhead)** — the cassette energy-closure check, explicit form. **M7 (coolant inlet supply ≥ cassette flow demand)** — sufficiency check with 2.5 % screening tolerance. P7 (PUE ≥ 1.0).

### 3.5 MED — `nexablock/blocks/med.py`

Multi-Effect Distillation thermal desalination, now **driven by the LiBr chiller's heat rejection** (the hot cooling-water loop), not by steam.

**Ports**: Inlet **`loop_in`** (the hot LiBr-rejection water) + optional `seawater`; Outlet **`loop_out`** (cooling water continuing to the radiator) + `fresh` + `brine`.

**Params**: `n_effects` (2–20 allowed), `sw_t_C`, `recovery` (default 35 %), **`bypass_frac`** (the 3-way valve fraction routed AROUND MED — set manually via `med_bypass_frac` or auto-resolved by the controller, see §4.3), `loop_cold_C` (the temperature MED cools the captured branch to: `fw_t_C` in manual mode, `sw_t_C + med_cold_pinch_K` in auto).

**Physics (screening)**:
```
GOR = 0.8 × n_effects                            # thin-film falling-film rule
Q_window = ṁ_cw × cp_w × (T_loop_in − T_cold)    # full loop heat ( = Q_cond )
Q_med    = (1 − bypass_frac) × Q_window          # heat MED captures
ṁ_dist   = GOR × Q_med / h_fg                    # h_fg = 2257 kJ/kg
ṁ_sw     = ṁ_dist / recovery
ṁ_brine  = ṁ_sw − ṁ_dist
m³/day   = ṁ_dist × 86400 / 1000
MED electrical = 1.5 kWh/m³ × (m³/h)             # pumps + controls (SEC)
loop_out T = (1 − bypass)·T_cold + bypass·T_loop_in   # recombined loop temperature
```

If there is no usable rejection heat (`ṁ_cw = 0` or `T_loop_in ≤ T_cold`), MED produces zero water and populates zero-valued result rows so downstream audit doesn't crash — there is no steam fallback.

**Audit checks**: E8 (captured heat ≈ ṁ_dist · h_fg / GOR, 5 % screening tolerance), M4 (sw = dist + brine), M5 (GOR in (4, 10) band), T4 (ΔT/effect ≥ 3°C — rejection source vs seawater), T10 (T_brine > T_seawater), P5 (GOR plausibility), P6 (recovery in (0, 0.5)).

### 3.6 Radiator — `nexablock/blocks/radiator.py`

Dry, forced-air (fan) radiator with a 3-way auto bypass valve. Replaces the old evaporative cooling tower for the closed cooling-water loop. The loop water arrives hot (post-MED); a 3-way valve auto-splits it between the radiator core (cooled toward ambient dry-bulb) and a bypass (stays hot), then remixes to a controlled outlet temperature — the HRSG feedwater return set-point. So the radiator only rejects the *surplus* heat and never overcools the feedwater.

**Ports**: Inlet `loop_in` (hot loop water); Outlet `loop_out` (blended return at the set-point, WATER_STEAM so it can feed the HRSG feedwater).

**Params**: `t_ambient_C`, `approach_K` (`radiator_approach_K`, default 15 K — radiator cold-branch approach to ambient), `t_return_C` (= `fw_t_C`, the 3-way blend target), `fan_frac` (legacy `ct_fan_frac`, fan electrical as fraction of rejected heat).

**Physics (screening)**:
```
T_rad = T_ambient + approach                     # radiator cold-branch outlet
f     = (T_in − T_set) / (T_in − T_rad), clamped [0, 1]   # 3-way split through radiator
Q_rad = f × ṁ × cp × (T_in − T_rad)              # heat rejected to ambient air
T_out = T_set  (= f·T_rad + (1−f)·T_in)          # blended return; idles (f=0) if T_in ≤ T_set
Fan electrical = fan_frac × Q_rad
```
Note: with the default **Auto** MED bypass (§4.3) the bypass valve already blends the loop back to the set-point `fw_t_C`, so the radiator idles (`f = 0`, duty 0) at the balance point. In **Manual** mode, `med_bypass_frac = 0` likewise sends the loop to the radiator at the set-point (idle); raising the manual bypass sends hotter water to the radiator, which then trims it back to the set-point.

**Audit checks**: T5 (radiator branch > ambient, i.e. approach > 0), T5b (return ≥ radiator branch — can't blend below the cold side), P14 (3-way split in [0, 100] %).

---

## 4. Control modes — three switches, one external-load knob

The v2 GT engine has three mode switches (`operating_mode`, `gt_power_mode`, `med_bypass_mode`) and the `external_load_kW` scalar. Defaults are island / auto / auto / 0 kW — the "real-plant" semantics. There is no longer a steam-split mode: with no splitter, `libr_frac` is constant 1.0.

### 4.1 Operating mode — Island / Grid-tied

| | Island | Grid-tied |
|---|---|---|
| External load input | manual scalar (user-entered) | hidden (grid absorbs) |
| Grid import allowed | n/a | NO (forbidden per spec) |
| GT cap on excess electrical | yes — can't go past elec demand | no — surplus exports |
| Cooling deficit at high GPU | possible (real engineering finding) | only if GT ≥ 100 % derated and still short |

### 4.2 GT power control — Auto / Manual

- **Auto**: controller picks `load_pct` from demand. Island: `min(elec_required, 100)`. Grid: `min(max(elec_required, steam_required), 100)`.
- **Manual**: user's `load_pct` input is used directly. The controller-derived line in the results table disappears.

The UI also offers a **GT load (kW)** field twinned to `load_pct` (kW = derated capacity × load% ÷ 100, the actual-power basis). It's a convenience mirror, not a separate input: in Manual it equals `GT actual power`; in Auto it's inert like `load_pct`. See [`MANUAL.md`](MANUAL.md) §3.1.

### 4.3 MED bypass — Manual / Auto

The MED 3-way bypass valve has two modes (`med_bypass_mode`, default **Auto** on both GT engines):

- **Manual**: uses the fixed `med_bypass_frac` (0–1). MED cools the captured branch to `loop_cold = fw_t_C` (exactly the set-point), so it never over-cools.
- **Auto**: a cascade with the radiator that **holds the cooling-loop return at the HRSG feedwater set-point** `fw_t_C`. MED is allowed to cool toward its real cold-end `t_med_cold = sw_t_C + med_cold_pinch_K` (default seawater + 15 K, *below* the set-point); the bypass auto-opens to the fraction that blends the MED-cooled branch (at `t_med_cold`) and the hot bypassed branch (at the LiBr rejection temperature) back to `fw_t_C`:

  ```
  med_bypass = (fw_t_C − t_med_cold) / (libr_reject_t_C − t_med_cold)   clamped [0, 1]
  ```

  So the feedwater inlet holds set-point and the radiator idles at the balance point. It prioritises MED capture (water), opening only as far as needed; it trades some desalination water to protect the feedwater temperature, and self-adjusts as load / ambient / seawater change. Resolved by `med_bypass_fraction(p)` / `med_loop_cold_C(p)` in `control.py`, shared by the single- and double-effect engines. At the design point Auto captures ≈ the same heat (≈ same MED water) as Manual `bypass=0`.

### 4.4 The controller — `simulators/gt_system/control.py`

`control_setpoints(p)` runs a fixed-point (up to 8 iterations, converges in 2–4 at screening fidelity) before block instantiation:

1. Compute `GPU_heat = gpu_it_kW × cassette_pue` (invariant — doesn't depend on solve state).
2. Compute `steam_to_libr_required = GPU_heat / (libr_cop × Δh_steam_to_cond)` (used as the steam-driven load requirement in grid mode).
3. Pre-compute steam at 100 % load (closed-form).
4. Iterate: guess `load_pct` → derive itemised aux loads (the analytical mirror of `plant_loads`) + GT aux → derive `elec_demand` → recompute `required_load_for_elec` → resolve `load_pct` per mode → repeat to convergence.
5. Return `ControlSetpoints` with `load_pct`, `libr_frac` (= 1.0 always, `derived_libr_frac = False`), `external_load_kW` (= user input in island, 0 in grid), `grid_export_kW` (= max(0, GT − NEXA) in grid, 0 in island), and `derived_*` booleans for the renderer.

In auto GT-power mode: **island** picks `min(required_load_for_elec, 100)`; **grid** picks `min(max(required_load_for_elec, required_load_for_steam), 100)` so it ramps high enough for full cooling and exports the surplus.

**No hidden safety margin** — the controller targets exactly what's needed. Small mismatches between the analytical model and the block compute (Δh approximations, fixed-reference t_amb in HRSG, prop-table rounding) are absorbed by the **screening tolerance** on the cooling balance and M7 check, not by oversizing the controller.

---

## 5. The solver

`nexablock/core/solver.py` — sequential-modular with Wegstein recycle.

- **Tarjan SCC** finds recycle loops in the connection graph.
- **Kahn's algorithm** gives a topological order for acyclic portions.
- **Wegstein iteration** with bounded q ∈ [−5, 0] for any tear streams (the recycle convergence acceleration).
- **Block `compute()` runs idempotently** — `block.results.clear()` is called before each compute so multiple Wegstein passes don't trip the framework's duplicate-label guard.
- **No raise on max-iter exhaustion**. Solver completes a final forward pass with the last tear estimates and returns `SolvedSystem.convergence.converged = False`. The renderer turns this into a red "⚠ NOT CONVERGED" card with the loop name, residual, and reason; KPIs go red.

The GT system **has one real recycle loop**: the GPU↔LiBr dielectric coolant loop (chiller `chw_supply` → GPU `coolant_in`, GPU `coolant_out` → chiller `chw_return`). Tarjan finds it, the solver tears `LiBrChiller.chw_supply → GPUCassette.coolant_in`, and Wegstein converges it (2 iterations, residual ≈ 0 at the defaults). The cooling-water rejection loop (LiBr → MED → radiator → HRSG feedwater) is **not** a graph cycle: the radiator's controlled return fixes the feedwater temperature at `fw_t_C`, so there is no feedback to iterate. The convergence card reads "converged in N iterations".

---

## 6. Convergence → Feasibility → Audit

Three independent status objects, threaded through `SolvedSystem` (for convergence) and the engine `r["..."]` dict (for feasibility + audit).

### 6.1 Convergence

Per-loop `LoopStatus` aggregated into a system-wide `ConvergenceStatus`. Surfaces the loop name (`Heater→Cooler→Recycle`), iterations used, final residual, tolerance, and a reason on failure. See [`DICTIONARY.md`](DICTIONARY.md) under "Convergence".

### 6.2 Feasibility — resource balances

`FeasibilityStatus` wraps a list of `ResourceBalance` objects, each with supply / demand / balance / shortfall / breakdown / assumption / tolerance.

For the v2 GT system:

| Balance | Supply | Demand | Tolerance |
|---|---|---|---|
| **Power** | **GT net power** (gross − GT aux) | GPU silicon + cassette overhead + itemised plant aux + (island) external_load OR (grid) grid export | **2.5 % closure** (bus must close, both excess and deficit flag) |
| **Cooling capacity** | LiBr Q_cool | GPU silicon heat + cassette overhead heat | **2.5 % screening** |

The power supply is **GT net power** (gross − GT auxiliaries), not the gross output and not the derated capacity. GT aux is the package's own parasitic — an internal derate — so it never appears on the bus; the bus sees the net only. The power balance uses `closure=True`: the bus must close, so *both* a positive imbalance (surplus with nowhere to go, island) and a deficit flag.

Power balance breakdown lines, verified at island/auto defaults (GPU 5 MW, 25°C). Supply = GT net; demand lines are itemised from `plant_loads`:
```
GT net power (supply)                  +5,492 kW    supply
GT gross power (info)                   5,585 kW
GT auxiliaries (internal derate, info)     93 kW
Derated capacity (max available, info)  9,300 kW
GPU silicon (IT power)                  −5,000 kW
Cassette overhead (pumps/ctl)             −250 kW
Dielectric coolant pump                    −57 kW
LiBr chiller pump                           −5 kW
Cooling-loop pump                          −84 kW
HRSG feed-water pump                        −4 kW
Seawater intake pump                       −29 kW
MED feed pump                              −29 kW
Brine pump                                 −19 kW
Distillate pump                            −10 kW
Condensate pump                             −1 kW
Dry-cooler fan (VSD)                         0 kW    (= 0 when MED captures all rejection)
HVAC (containers)                            0 kW    (= 0 when ambient < inside set-point)
Lights                                       0 kW
External load (island, manual)              0 kW    (user input; 0 by default)
```
(Itemised plant aux totals ≈ 236 kW; demand = 5 000 + 250 + 236 = 5 486 kW vs net supply 5 492 kW — within the 2.5 % closure tolerance.) The dry-cooler fan rides a VSD (cube law on dry-cooler utilisation); at the defaults MED captures all the rejection so the radiator idles and the fan draws 0. HVAC is the container-envelope cooling load (`n_containers · area · U · (T_ambient − T_inside)`), which is 0 when ambient is below the inside set-point. Lights = `lights_frac × HVAC`.

In grid-tied mode the External-load line is replaced by:
```
Grid export (sent to grid)              +N kW      (= GT net − NEXA demand)
```

### 6.3 Audit — 42 checks (island/auto and grid/auto), 41 (fully manual)

Verified by live solve: 42 checks at island/auto and grid/auto; 41 in fully-manual GT-power mode (the F3 derived-`load_pct` check only exists in auto). By category at the defaults: **Energy closure 10, Mass closure 5, Second law 11, Plausibility 16**. Four categories of "real-issue" assertions on every solve:

| Category | Checks | What they verify |
|---|---|---|
| **Energy closure** | E1–E8 (+ M6 NG closure via the energy-balance helper) + E9 | First-law equations close per block (NG·LHV·η, fuel = power + exhaust + GT_cw, exhaust·η = duty, Q_gen·COP = Q_cool, Q_cond = Q_gen + Q_cool, MED captured heat = ṁ_dist·h_fg/GOR, Heat = IT + overhead) and the system bus closes (E9). |
| **Mass closure** | M1, M3, M4, M5, M7 (M7 with 2.5 % tolerance) | Per-stream / per-block: HRSG FW ≥ steam (M1), LiBr steam_in = condensate (M3), MED sw = dist + brine (M4), GOR band (M5), GPU coolant inlet ≥ cassette demand (M7). |
| **Second law** | T1–T10, T5b | Positive pinch in HRSG (T1, T2, T3), ΔT-per-effect ≥ 3°C in MED (T4), radiator approach > 0 (T5) and return ≥ radiator branch (T5b), LiBr CHW feasibility (T6, T7), T_steam > T_condensate (T9), T_brine > T_seawater (T10), exhaust > ambient + 100°C (T8). |
| **Plausibility** | P1–P9, P11, P14 (system-level) + P12, P13 (generic) + F1–F5 | η < 0.55, derate in (0, 1], load_pct in [10, 100], COP in (0.5, 1.3), GOR in (4, 10), recovery < 0.5, HRSG eff / P_steam bounds, GT actual ≤ derated (P11), 3-way split in [0, 100] % (P14), no negative flows (P12), every kW value finite (P13), and the composition checks F1–F5. (M5 is registered under Mass closure.) |

Composition checks added by `simulators/gt_system/audit.py` (note: there is no longer an F4 libr-frac check — `libr_frac` is constant 1.0 and `derived_libr_frac` is always False):

| id | name | category | shown in |
|---|---|---|---|
| **E9** | Bus closure: GT net = NEXA + external (island) OR NEXA + grid_export (grid) | Energy closure | both |
| **F1** | Island power balance closed without grid import | Plausibility | island only |
| **F2** | External load finite and ≥ 0 | Plausibility | both |
| **F3** | Derived `load_pct` ≤ 100 % | Plausibility | when `gt_power_mode=auto` |
| **F5** | Grid export ≥ 0 (imports forbidden) | Plausibility | grid only |

**Coverage table — every v2 KPI is named by multiple checks** (via each check's `affects` list):

| KPI | Vouched by |
|---|---|
| GT actual power | E1, E2, M6, T8, P1, P2, P3, P11, E9, F1, F3 (auto), F5 (grid) |
| NG consumption | E1, M6 |
| Steam generation | E3, E4, M1, T1, T2, T3, P8, P9 |
| Steam temperature | T1, T2, T3 |
| LiBr cooling capacity | E5, E6, M3, T5, T5b, T6, T7, T9, P4, P14 |
| GPU IT load | E7, M7, P7 |
| MED water production | E8, M4, M5, T4, T10, P5, P6 |

### 6.4 Per-KPI basis is now data-driven from audit coverage

```python
cov = audit.coverage_for(kpi_label)
if   cov == "failed":   basis = "unverified"   # a covering check failed
elif cov == "passed":   basis = engine_basis   # respected — typically "verified"
else:                   basis = "screening"    # no check named this KPI
```

Plus global override: convergence / any-feasibility / generic-audit-failure (P12/P13) → every row becomes `unverified`.

---

## 7. Studies

After Run, the Studies card (between chart and results table) drives three exploratory tools:

- **Sensitivity** — multi-select inputs × multi-select KPIs → multi-panel tornado, one tornado per KPI, ranked by |elasticity|, zero-elasticity bars suppressed.
- **Sweep** — 1D / 2D toggle.
  - 1D: pick X input, multi-select KPIs → subplots, one per KPI (independent y-scales so the small-magnitude KPIs don't crush against the big ones).
  - 2D: pick X input + Y input + single KPI → 5×5 grid, real `contourf` with colorbar.
- **Scenarios** — predefined named bundles ("summer peak", "winter low load") solved as a batch → grouped-bar comparison normalised to base.

All study results are stashed per-engine (in-memory dict + disk pickle under `~/.enginetools/studies/`) for the Download Study CSV / Excel buttons. Reports can attach the latest study chart via the "Include latest study" checkbox.

---

## 8. Reports

Every PDF and Excel report carries these sections, in order:

1. Title + engine name
2. **Design point** (input table)
3. **Convergence** (green ✓ / red ⚠)
4. **Power balance** (one band) + (island) external load OR (grid) grid export in breakdown
5. **Cooling capacity balance** (one band)
6. **Audit** — `N/N passed`, or a table listing every failed check (name, category, detail)
7. **Results table** with the per-KPI basis colour — headline KPIs plus the single **Plant PUE (electrical, export excluded)** screening KPI. The granular overhead lines (Cassette PUE, the itemised pumps, the dry-cooler fan, HVAC, lights, GT aux) are *not* results; the per-load fractions live in the Design point block as inputs and Plant PUE rolls the consumption into one figure. **Plant PUE numerator** = IT + cassette overhead + itemised plant aux (pumps + dry-cooler fan + HVAC + lights, from `plant_loads`) + GT aux; denominator = IT. It excludes MED electrical, external load, and grid export. At island/auto defaults it reads ≈ 1.116.
8. **Chart** — flowsheet (SVG, rasterised to PNG via cairosvg for PDF/PPTX), or sweep line chart for the load-sweep adapter
9. (Optional) **AI Analysis** narrative
10. Method note from the engine
11. (Optional, ticked at download) **Study** section/sheet with chart + table
12. (PDF, GT-system engines only) **PFD page** — a final **landscape** page redrawing the process flow diagram with every value live from the run: block boxes, flow streams, a Key-results table, an energy-balance/audit panel, the island/grid badge + named operating-mode strip (Operating mode / GT power control), a mode-aware **External load** (island) / **Grid export** (grid) cell, and a stream/basis legend. Native reportlab redraw — no PowerPoint/LibreOffice at render time (`nexa_toolkit/reporting/pfd_page.py`).

The exact same layout is on the Excel "Study" sheet whether it came from `study_to_xlsx` standalone or from `build_excel(..., study=...)` — `write_study_sheet` is the one source of truth.

---

## 9. Where to look in the code

| Concept | File | Key function/class |
|---|---|---|
| Block contract | `nexablock/core/block.py` | `Block.compute`, `Block.audit_checks` |
| Stream + Port | `nexablock/core/stream.py`, `port.py` | `Stream`, `StreamKind`, `Port` |
| System + Solver | `nexablock/core/system.py`, `solver.py` | `System.solve(tol, max_iter)`, `Solver._solve_with_recycle` |
| Convergence | `nexablock/core/convergence.py` | `ConvergenceStatus`, `convergence_summary` |
| Audit framework | `nexablock/audit/*.py` | `audit()`, `AuditStatus`, helper constructors |
| §7.5 SVG renderer | `nexablock/viz/svg.py` | `render(system_or_solved)` |
| Studies primitives | `nexablock/studies/*.py` | `ParameterSweep`, `OneAtATimeSensitivity`, `ScenarioRunner` |
| Chart helpers | `nexablock/studies/charts.py` | `tornado_chart`, `sweep_chart`, `sweep_contour` |
| Gas Turbine | `nexablock/blocks/gas_turbine.py` | `GasTurbine` |
| Radiator (replaces CoolingTower) | `nexablock/blocks/radiator.py` | `Radiator` |
| GT system composition | `simulators/gt_system/system.py` | `build_gt_system(p)`, `summary(solved)` |
| GT controller | `simulators/gt_system/control.py` | `control_setpoints(p)` |
| GT plant-electrical (itemised aux) | `simulators/gt_system/plant_loads.py` | `plant_loads(solved, p)` |
| GT feasibility | `simulators/gt_system/feasibility.py` | `power_balance`, `cooling_balance`, `feasibility` |
| GT composition audit | `simulators/gt_system/audit.py` | `gt_system_audit_checks(solved)` |
| v2 engine adapter | `nexa_toolkit/engines/gt_system_v2.py` | `GTSystemV2`, `_params_from(v)` |
| Reporting pipeline | `nexa_toolkit/reporting/generic_report.py` | `build_pdf`, `build_excel`, `write_study_sheet`, `_result_rows` |
| Live PFD landscape page | `nexa_toolkit/reporting/pfd_page.py` | `make_pfd_flowable`, `pfd_context`, `PFDFlowable` |
| Dash UI | `nexa_toolkit/app/app.py` | `input_fields`, `results_table`, `convergence_card`, `feasibility_card`, `audit_card`, `datasets_panel`, `_sync_gt_load` |
| Input datasets (Save/Load/Update/Delete) | `nexa_toolkit/framework/datasets.py` | `save_dataset`, `get_dataset`, `delete_dataset`, `list_datasets` |

---

## 10. A complete worked example — what happens when you click Run

Setup: pick **GT System v2 — nexablock** in the dropdown. Defaults: Gas Turbine / island / auto, `gpu_it_kW = 5000`, `external_load_kW = 0`, `t_ambient_C = 25`.

1. **Click Run.** `_run` callback fires.
2. **`engine.solve(values)`** in `gt_system_v2.py`:
   - `_params_from(v)` translates UI ints/floats → `GTSystemParams` with mode strings.
   - `build_gt_system(params)` is called.
3. **`build_gt_system`** in `system.py`:
   - `control_setpoints(p)` runs the fixed-point. At GPU 5 MW island/auto: `load_pct ≈ 60.1 %`, `libr_frac = 1.0`, external_load = 0, grid_export = 0, `derived_load_pct = True`, `derived_libr_frac = False`.
   - 6 blocks instantiated (GasTurbine, HRSG, LiBrChiller, GPUCassette, MED, Radiator).
   - Feedwater seed (20 kg/s, at `fw_t_C`) attached to the HRSG feedwater inlet; seawater seed (100 kg/s) attached to the MED seawater inlet.
   - **6 connections** wired: GT.exhaust→HRSG.exhaust_in, HRSG.steam→LiBr.steam_in (all steam), LiBr.chw_supply→GPU.coolant_in, GPU.coolant_out→LiBr.chw_return (the **dielectric recycle loop**), LiBr.reject_out→MED.loop_in, MED.loop_out→Radiator.loop_in.
   - `sys.solve()` runs the framework solver — Tarjan finds the GPU↔LiBr recycle, tears `LiBr.chw_supply→GPU.coolant_in`, and Wegstein converges it in 2 iterations.
   - Each block's `compute()` populates its outlet streams + result rows.
   - Returns `SolvedSystem` with `.convergence` (converged) and stashed `.control`, `.operating_mode`, `.params`.
4. **`summary(solved)`** extracts the top-level KPIs into a dict including the derived setpoints, mode-specific KPIs, the itemised `Plant aux electrical kW`, and `Plant PUE`.
5. **`feasibility(solved, bop_frac=...)`** returns a `FeasibilityStatus` with two `ResourceBalance` objects — Power (supply = GT net) and Cooling capacity, each with `tol_rel=0.025`.
6. **`audit(solved, extra_checks=gt_system_audit_checks(solved))`** runs all 42 checks. M7 honors the 2.5 % screening tolerance. P12/P13 sweep all streams + all kW results.
7. **The engine returns** `r = {"solved", "kpis", "feasibility", "audit", "inputs"}`.
8. **The UI callback** assembles the highlight cards, the convergence card, the feasibility cards (one per balance), the audit card, the chart (PFD/SVG flowsheet), the results table (with basis colours read from `audit.coverage_for(label)`), and the smart section.

At the defaults the user sees (verified by live solve): GT net power supply ≈ 5 492 kW (gross 5 585, GT aux 93), GPU IT 5 000 kW, steam 10.72 t/h, LiBr cooling 5 072 kW, MED water ≈ 3 018 m³/day, `load_pct ≈ 60.1 %`, Plant PUE ≈ 1.116. **At island/auto defaults there is a small cooling deficit**: the electrically-pinned GT raises only enough steam for ≈ 5 072 kW of LiBr cooling against a 5 250 kW demand (a ≈ 3.4 % gap, beyond the 2.5 % screening tolerance), so the Cooling-capacity card goes red and audit **M7** (coolant inlet supply ≥ cassette demand) fails — 41/42 pass. Everything else passes. Switching to **grid-tied** is clean: the GT ramps to `load_pct ≈ 62.2 %`, delivers the full 5 250 kW of cooling, exports ≈ 195 kW, and all 42 checks pass.

---

## 11. Where to go from here

- **Adjust the mode switches** (Operating mode, GT power, MED bypass) to explore the design space.
- **Run Sensitivity** with multi-select inputs/KPIs to see what matters.
- **Run a 2D sweep** of, say, `gpu_it_kW × t_ambient_C` with `Grid export` as the contoured KPI to learn the export envelope.
- **Tick "Include latest study"** before downloading PDF/Excel to embed the chart in the report.
- For terminology, see [`DICTIONARY.md`](DICTIONARY.md).
- For framework / extension developer notes, see [`ARCHITECTURE.md`](ARCHITECTURE.md).
- For day-to-day UI walkthrough, see [`MANUAL.md`](MANUAL.md).
