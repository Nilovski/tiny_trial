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


async def recv_byte(dut, timeout_cycles=50):
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
async def test_gemm_2x2(dut):
    """Full round trip: LOAD_A, LOAD_B, CLEAR_GEMM, poll STATUS, READ_C_ELEMENT."""
    await reset(dut)

    a = [1, 2, 3, 4]        # row-major 2x2: [[1, 2], [3, 4]]
    b = [5, 6, 7, 8]        # row-major 2x2: [[5, 6], [7, 8]]
    expected_c = [
        a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
    ]

    await send_byte(dut, OP_LOAD_A)
    for byte in a:
        await send_byte(dut, byte)

    await send_byte(dut, OP_LOAD_B)
    for byte in b:
        await send_byte(dut, byte)

    await send_byte(dut, OP_CLEAR_GEMM)

    for _ in range(20):
        await send_byte(dut, OP_STATUS)
        status = await recv_byte(dut)
        if (status & 0x1) == 0:
            break
    else:
        raise TimeoutError("GEMM never finished (busy stuck high)")

    for elem in range(4):
        value = 0
        for byte_i in range(4):
            addr = elem * 4 + byte_i
            await send_byte(dut, OP_READ_C_ELEMENT)
            await send_byte(dut, addr)
            byte = await recv_byte(dut)
            value |= byte << (8 * byte_i)
        assert value == expected_c[elem], (
            f"C[{elem}] = {value}, expected {expected_c[elem]}"
        )


@cocotb.test()
async def test_gemm_negative_values(dut):
    """Signed operands (two's-complement bytes) should accumulate correctly."""
    await reset(dut)

    def to_byte(v):
        return v & 0xFF

    a = [-1, 2, 3, -4]
    b = [5, -6, -7, 8]
    expected_c = [
        a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
    ]

    await send_byte(dut, OP_LOAD_A)
    for v in a:
        await send_byte(dut, to_byte(v))

    await send_byte(dut, OP_LOAD_B)
    for v in b:
        await send_byte(dut, to_byte(v))

    await send_byte(dut, OP_CLEAR_GEMM)

    for _ in range(20):
        await send_byte(dut, OP_STATUS)
        status = await recv_byte(dut)
        if (status & 0x1) == 0:
            break
    else:
        raise TimeoutError("GEMM never finished (busy stuck high)")

    for elem in range(4):
        value = 0
        for byte_i in range(4):
            addr = elem * 4 + byte_i
            await send_byte(dut, OP_READ_C_ELEMENT)
            await send_byte(dut, addr)
            byte = await recv_byte(dut)
            value |= byte << (8 * byte_i)
        # ACC_W=32, two's complement
        if value & (1 << 31):
            value -= 1 << 32
        assert value == expected_c[elem], (
            f"C[{elem}] = {value}, expected {expected_c[elem]}"
        )
