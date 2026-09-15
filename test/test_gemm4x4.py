import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

RX_VALID = 0
RX_READY = 1
TX_READY = 2
TX_VALID = 3

OP_NOP = 0x00
OP_LOAD_A = 0x10
OP_LOAD_B = 0x11
OP_CLEAR_GEMM = 0x21
OP_READ_C_ELEMENT = 0x31
OP_STATUS = 0x40
OP_ID = 0x41
CHIP_ID = 0xA2

N = 4  # matches localparam N/K in tt_um_sahpar_gemm4x4.sv


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def send_byte(dut, value):
    """Drive one byte into ui_in with a one-cycle RX_VALID pulse.

    host_ready is tied high in rx_byte_interface, so the byte is captured
    on the same edge the pulse is seen.
    """
    dut.ui_in.value = value
    dut.uio_in.value = int(dut.uio_in.value) | (1 << RX_VALID)
    await RisingEdge(dut.clk)
    dut.uio_in.value = int(dut.uio_in.value) & ~(1 << RX_VALID)
    await RisingEdge(dut.clk)


async def recv_byte(dut, timeout_cycles=200):
    """Wait for TX_VALID, capture uo_out, pulse TX_READY to accept it."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if int(dut.uio_out.value) & (1 << TX_VALID):
            byte = int(dut.uo_out.value)
            dut.uio_in.value = int(dut.uio_in.value) | (1 << TX_READY)
            await RisingEdge(dut.clk)
            dut.uio_in.value = int(dut.uio_in.value) & ~(1 << TX_READY)
            return byte
    raise TimeoutError("timed out waiting for TX_VALID")


def to_byte(v):
    """Signed int8 -> unsigned byte (two's complement)."""
    return v & 0xFF


def matmul(a, b, n):
    """Plain NxN row-major integer matmul, a and b as flat lists."""
    c = [0] * (n * n)
    for i in range(n):
        for j in range(n):
            c[i * n + j] = sum(a[i * n + k] * b[k * n + j] for k in range(n))
    return c


async def run_gemm(dut, a, b, n=N):
    """LOAD_A, LOAD_B, CLEAR_GEMM, poll STATUS, READ_C_ELEMENT for all n*n
    elements (4 bytes each, little-endian, two's complement)."""
    expected_c = matmul(a, b, n)

    await send_byte(dut, OP_LOAD_A)
    for v in a:
        await send_byte(dut, to_byte(v))

    await send_byte(dut, OP_LOAD_B)
    for v in b:
        await send_byte(dut, to_byte(v))

    await send_byte(dut, OP_CLEAR_GEMM)

    for _ in range(50):
        await send_byte(dut, OP_STATUS)
        status = await recv_byte(dut)
        if (status & 0x1) == 0:
            break
    else:
        raise TimeoutError("GEMM never finished (busy stuck high)")

    for elem in range(n * n):
        value = 0
        for byte_i in range(4):
            addr = elem * 4 + byte_i
            await send_byte(dut, OP_READ_C_ELEMENT)
            await send_byte(dut, addr)
            byte = await recv_byte(dut)
            value |= byte << (8 * byte_i)
        if value & (1 << 31):  # ACC_W=32, two's complement
            value -= 1 << 32
        assert value == expected_c[elem], (
            f"C[{elem}] = {value}, expected {expected_c[elem]}"
        )


@cocotb.test()
async def test_id(dut):
    """OP_ID should reply with the fixed chip ID byte."""
    await reset(dut)
    await send_byte(dut, OP_ID)
    byte = await recv_byte(dut)
    assert byte == CHIP_ID, f"expected ID {CHIP_ID:#x}, got {byte:#x}"


@cocotb.test()
async def test_status_idle(dut):
    """STATUS should read back busy=0 when nothing is running."""
    await reset(dut)
    await send_byte(dut, OP_STATUS)
    byte = await recv_byte(dut)
    assert (byte & 0x1) == 0, f"expected idle (busy=0), got status {byte:#x}"


@cocotb.test()
async def test_gemm_4x4_identity(dut):
    """A x I = A, with I as the 4x4 identity matrix."""
    await reset(dut)
    a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    identity = [1 if i == j else 0 for i in range(N) for j in range(N)]
    await run_gemm(dut, a, identity)


@cocotb.test()
async def test_gemm_4x4_general(dut):
    """Full round trip with arbitrary positive operands."""
    await reset(dut)
    a = [1, 2, 0, 1, 3, 1, 2, 0, 0, 1, 1, 2, 2, 0, 1, 3]
    b = [1, 0, 2, 1, 0, 1, 1, 0, 2, 1, 0, 1, 1, 2, 1, 0]
    await run_gemm(dut, a, b)


@cocotb.test()
async def test_gemm_4x4_negative_values(dut):
    """Signed operands (two's-complement bytes) should accumulate correctly."""
    await reset(dut)
    a = [-1, 2, 3, -4, 5, -6, -7, 8, -9, 10, 11, -12, 13, -14, -15, 16]
    b = [4, -3, 2, -1, -8, 7, -6, 5, 12, -11, 10, -9, -16, 15, -14, 13]
    await run_gemm(dut, a, b)
