# tapeout-2x2 -- Tiny Tapeout scaffold for the 2x2 GEMM bring-up

This wraps the existing `bringup-2x2` compute core (`gemm_top` / `systolic_array`
/ `pe` / `mac_unit`, unchanged) in an actual `tt_um_*` Tiny Tapeout top module,
using the host byte protocol frozen in the root `README.md` (steps 12-15).
That's the piece the original `bringup-2x2` explicitly didn't have yet
("no Cocotb, no Tiny Tapeout wrapper, no synthesis or timing").

## What's here

```
tapeout-2x2/
├── info.yaml                      Tiny Tapeout project config (confirmed schema, see below)
├── .github/workflows/             gds.yaml, test.yaml, docs.yaml -- copied from the shift-register repo
├── .devcontainer/                 optional local Docker/LibreLane dev environment
├── src/
│   ├── tt_um_apex_gemm2x2.sv      top-level TT wrapper
│   ├── rx_byte_interface.sv       host -> chip byte receiver
│   ├── tx_byte_interface.sv       chip -> host byte sender
│   ├── cmd_decoder_2x2.sv         opcode decoder, wires protocol to gemm_top
│   ├── gemm_top.sv                (copied unchanged from bringup-2x2/rtl)
│   ├── systolic_array.sv          (unchanged)
│   ├── pe.sv                      (unchanged)
│   ├── mac_unit.sv                (unchanged)
│   └── config.json                LibreLane hardening config (from the shift-register project)
└── test/
    ├── test_gemm2x2.py            cocotb testbench
    ├── requirements.txt           pinned cocotb/pytest versions
    └── Makefile                   cocotb + Icarus Verilog runner, RTL and GATES=yes modes
```

## Protocol (subset of the full spec, see root README.md step 15)

| Byte   | Op               | Then                                   | Reply             |
|--------|------------------|-----------------------------------------|-------------------|
| `0x00` | NOP              | --                                       | none              |
| `0x10` | LOAD_A           | 4 data bytes, row-major (a00,a01,a10,a11)| none              |
| `0x11` | LOAD_B           | 4 data bytes, row-major (b00,b01,b10,b11)| none              |
| `0x21` | CLEAR_GEMM       | (only while !busy)                       | none, C = A x B   |
| `0x31` | READ_C_ELEMENT   | 1 address byte (0-15)                    | 1 byte of `c_flat`|
| `0x40` | STATUS           | --                                       | `{7'b0, busy}`    |
| `0x41` | ID               | --                                       | `0xA2`            |

`c_flat` is 4 accumulators x 4 bytes (little-endian each), address = `elem*4 + byte_i`,
`elem` in row-major C order (c00, c01, c10, c11).

This bring-up core has **no accumulate-only mode** -- `gemm_top` always clears
at t=0, so there's no `0x20 GEMM` (C += A x B) opcode yet. The full 8x8
protocol (root README) distinguishes `GEMM` vs `CLEAR_GEMM`; that needs an
extra control input on `gemm_top` first.

## Simulate

```bash
cd test
make          # Icarus Verilog + cocotb; needs: apt install iverilog, pip install cocotb
```

Verified in this session: `test_id`, `test_status_idle`, `test_gemm_2x2`, and
`test_gemm_negative_values` (signed two's-complement operands) all pass
against the RTL as written.

## Size estimate (real yosys synthesis, sky130_fd_sc_hd)

Ran `yosys` locally against the actual `sky130_fd_sc_hd__tt_025C_1v80.lib`
(no Docker/OpenLane needed for this part -- just `apt install yosys` and the
public liberty file). `hierarchy -top tt_um_apex_gemm2x2; proc; opt; techmap;
dfflibmap; abc -liberty ...; stat -liberty ...` on the full wrapper+decoder+
gemm_top stack gives:

| Metric                        | Value                    |
|--------------------------------|--------------------------|
| Cell count                    | 3,986 (487 are `dfxtp` flops) |
| **Raw standard-cell area**    | **37,153 µm² (0.0372 mm²)** |
| 1 Tiny Tapeout tile            | 160 x 100 µm = 16,000 µm² |

That raw cell-footprint number alone is already **>2x a single tile**,
before routing (which TT's own FAQ says typically takes more area than the
logic itself), tap cells, decap, or antenna diodes. At a realistic placed
utilization of 45-62%, expect somewhere around **4-6 tiles**, not the "1x1"
this bring-up stage was loosely aimed at. `info.yaml` above is set to `2x2`
(4 tiles) as a placeholder -- treat it as a lower bound, not a submission-
ready number, until an actual placement run confirms it.

This is a pre-placement estimate (cell footprints summed, no floorplanning/
routing/tap-cell overhead), so it's a floor, not the final die size -- but
it's real numbers from the real sky130hd library, not a guess.

## How to actually get a GDS -- confirmed from the shift-register project

This repo is now wired up the same way as the 4-bit shift register project
that actually made it through to GDS on TTSKY26c. The mechanism is a
**GitHub Actions workflow**, not a local Docker/OpenLane install:

- `.github/workflows/gds.yaml` runs `TinyTapeout/tt-gds-action@ttsky26c` on
  every push. That single action does the full LibreLane/OpenLane hardening
  (synthesis -> floorplan -> place -> route -> GDS), a Tiny Tapeout precheck,
  a gate-level simulation against the hardened netlist, and publishes a
  layout viewer to GitHub Pages.
- `.github/workflows/test.yaml` runs the cocotb RTL tests on push.
- `.github/workflows/docs.yaml` builds the project datasheet.
- `.devcontainer/` gives you a local dev environment (Docker-in-Docker +
  `tt-support-tools` + LibreLane 2.4.2 preinstalled) if you want to iterate
  with `tt/tt_tool.py --harden` before pushing -- useful in GitHub Codespaces
  specifically, since Codespaces provisions the Docker this sandbox doesn't
  have. Not required though; CI alone produces the GDS.
- `src/config.json` is the shift-register project's LibreLane config
  (density target, margins, etc.) copied as-is -- it's meant to be generic
  and is marked "do not edit unless you know what you're doing" in the file.

**To reproduce what happened for the shift register:**
1. Create a new GitHub repo from `https://github.com/TinyTapeout/ttsky-verilog-template`
   (or push this folder's contents into a fresh repo -- same effect).
2. Drop in everything under `src/`, `test/`, `info.yaml`, `.github/`,
   `.devcontainer/` from this folder.
3. `git push`.
4. Watch the Actions tab: `test` runs first, then `gds` (build -> precheck ->
   gl_test -> viewer). The GDS, hardening logs, and gate-level netlist come
   back as workflow artifacts; the viewer job publishes an interactive layout
   to GitHub Pages.

Given the area estimate above, expect the `gds` job's floorplan/placement
step to be where `tiles: "2x2"` gets tested for real -- if it's still too
small, PL_TARGET_DENSITY_PCT in `src/config.json` or the `tiles` value in
`info.yaml` are the first things to bump.

## What this scaffold does NOT include yet
