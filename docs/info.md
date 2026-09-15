## How it works

This project wraps a 4x4 output-stationary integer systolic GEMM core
(bring-up milestone for an 8x8 BF16 accelerator) behind an 8-bit host byte
protocol.

Two synchronous handshake channels run over the bidirectional pins:
`RX_VALID`/`RX_READY` bring bytes in on `ui[7:0]`, and `TX_READY`/`TX_VALID`
send bytes back out on `uo[7:0]`. A command decoder interprets each incoming
byte as one of:

| Byte   | Op             | Then                                       | Reply              |
|--------|----------------|---------------------------------------------|---------------------|
| `0x10` | LOAD_A         | 16 data bytes, row-major (a00..a33)          | none                |
| `0x11` | LOAD_B         | 16 data bytes, row-major (b00..b33)          | none                |
| `0x21` | CLEAR_GEMM     | (only while !busy)                           | none, C = A x B     |
| `0x31` | READ_C_ELEMENT | 1 address byte (0-63)                        | 1 byte of C         |
| `0x40` | STATUS         | --                                             | `{7'b0, busy}`      |
| `0x41` | ID             | --                                             | `0xA2`              |

`C` is 16 accumulators x 4 bytes each (little-endian), address = `elem*4 +
byte_i`, `elem` in row-major order (c00..c33). There is no accumulate-only
mode yet -- `CLEAR_GEMM` always clears before multiplying.

## How to test

1. Send `0x41` (ID); expect `0xA2` back.
2. Send `0x10` then 16 bytes for A, then `0x11` then 16 bytes for B.
3. Send `0x21` to start the multiply.
4. Poll with `0x40` (STATUS) until bit 0 (busy) reads 0.
5. For each of the 64 result bytes, send `0x31` followed by the address
   byte (0-63); read back the corresponding byte of C.

A full example (LOAD_A / LOAD_B / CLEAR_GEMM / poll / READ_C_ELEMENT,
including an identity-matrix case and negative two's-complement operands)
is in `test/test_gemm4x4.py`, verified against a Python reference multiply.

## External hardware

None -- this project only needs the host byte-protocol connection over
`ui[7:0]`/`uo[7:0]`/`uio[3:0]`.
