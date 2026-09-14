`default_nettype none

// ---------------------------------------------------------------------------
// cmd_decoder_2x2 -- byte-protocol front end for the 2x2 integer GEMM
// bring-up core (gemm_top). Trimmed subset of the full instruction set
// frozen in README.md step 15:
//
//   0x00  NOP
//   0x10  LOAD_A            -- followed by N*K data bytes (row-major)
//   0x11  LOAD_B            -- followed by K*N data bytes (row-major)
//   0x21  CLEAR_GEMM        -- pulses start (only accepted while !busy);
//                              C = A x B. This bring-up core has no
//                              accumulate-only ("GEMM" 0x20) mode --
//                              gemm_top always clears at t==0.
//   0x31  READ_C_ELEMENT    -- followed by 1 address byte (0..NUM_C_BYTES-1),
//                              replies with that byte of c_flat
//   0x40  STATUS            -- replies {7'b0, busy}
//   0x41  ID                -- replies CHIP_ID
//
// Anything else is ignored. Not a full re-implementation of the eventual
// 8x8 protocol -- READ_C returning the whole matrix in one shot, and the
// GEMM-without-clear accumulate opcode, are deferred until gemm_top itself
// grows an accumulate mode.
// ---------------------------------------------------------------------------
module cmd_decoder_2x2 #(
    parameter int N      = 2,
    parameter int K      = 2,
    parameter int DATA_W = 8,
    parameter int ACC_W  = 32
) (
    input  logic clk,
    input  logic rst_n,

    // from rx_byte_interface
    input  logic [7:0] rx_byte,
    input  logic       rx_byte_valid,

    // to tx_byte_interface
    output logic [7:0] tx_byte,
    output logic        tx_byte_valid,
    input  logic         tx_ready,

    // gemm_top
    output logic                  gemm_start,
    output logic [N*K*DATA_W-1:0] a_flat,
    output logic [K*N*DATA_W-1:0] b_flat,
    input  logic                  gemm_busy,
    input  logic                  gemm_done,
    input  logic [N*N*ACC_W-1:0]  c_flat
);

    localparam int NUM_A_BYTES = N*K*DATA_W/8;
    localparam int NUM_B_BYTES = K*N*DATA_W/8;
    localparam int NUM_C_BYTES = N*N*ACC_W/8;
    localparam int AW = (NUM_A_BYTES > 1) ? $clog2(NUM_A_BYTES) : 1;
    localparam int BW = (NUM_B_BYTES > 1) ? $clog2(NUM_B_BYTES) : 1;
    localparam int CW = (NUM_C_BYTES > 1) ? $clog2(NUM_C_BYTES) : 1;

    localparam logic [7:0] OP_NOP            = 8'h00;
    localparam logic [7:0] OP_LOAD_A         = 8'h10;
    localparam logic [7:0] OP_LOAD_B         = 8'h11;
    localparam logic [7:0] OP_CLEAR_GEMM     = 8'h21;
    localparam logic [7:0] OP_READ_C_ELEMENT = 8'h31;
    localparam logic [7:0] OP_STATUS         = 8'h40;
    localparam logic [7:0] OP_ID             = 8'h41;
    localparam logic [7:0] CHIP_ID           = 8'hA2;

    typedef enum logic [2:0] {
        S_IDLE,
        S_LOAD_A,
        S_LOAD_B,
        S_READ_ADDR
    } state_t;

    state_t state;

    logic [7:0]     a_bytes [NUM_A_BYTES];
    logic [7:0]     b_bytes [NUM_B_BYTES];
    logic [7:0]     c_bytes [NUM_C_BYTES];
    logic [AW-1:0]  a_idx;
    logic [BW-1:0]  b_idx;

    // Note: tx_ready is sampled combinationally where used below; the
    // decoder only ever issues a byte when it knows the sender is free
    // (single in-flight reply per command), so back-pressure is not
    // modelled explicitly here.

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state         <= S_IDLE;
            a_idx         <= '0;
            b_idx         <= '0;
            gemm_start    <= 1'b0;
            tx_byte       <= '0;
            tx_byte_valid <= 1'b0;
            for (int i = 0; i < NUM_A_BYTES; i++) a_bytes[i] <= '0;
            for (int i = 0; i < NUM_B_BYTES; i++) b_bytes[i] <= '0;
        end else begin
            gemm_start    <= 1'b0;
            tx_byte_valid <= 1'b0;

            case (state)
                S_IDLE: begin
                    if (rx_byte_valid) begin
                        case (rx_byte)
                            OP_NOP: ; // no-op
                            OP_ID: begin
                                tx_byte       <= CHIP_ID;
                                tx_byte_valid <= 1'b1;
                            end
                            OP_STATUS: begin
                                tx_byte       <= {7'b0, gemm_busy};
                                tx_byte_valid <= 1'b1;
                            end
                            OP_LOAD_A: begin
                                state <= S_LOAD_A;
                                a_idx <= '0;
                            end
                            OP_LOAD_B: begin
                                state <= S_LOAD_B;
                                b_idx <= '0;
                            end
                            OP_CLEAR_GEMM: begin
                                if (!gemm_busy) gemm_start <= 1'b1;
                            end
                            OP_READ_C_ELEMENT: state <= S_READ_ADDR;
                            default: ; // unknown opcode: ignored
                        endcase
                    end
                end

                S_LOAD_A: begin
                    if (rx_byte_valid) begin
                        a_bytes[a_idx] <= rx_byte;
                        if (a_idx == AW'(NUM_A_BYTES - 1)) begin
                            state <= S_IDLE;
                        end else begin
                            a_idx <= a_idx + AW'(1);
                        end
                    end
                end

                S_LOAD_B: begin
                    if (rx_byte_valid) begin
                        b_bytes[b_idx] <= rx_byte;
                        if (b_idx == BW'(NUM_B_BYTES - 1)) begin
                            state <= S_IDLE;
                        end else begin
                            b_idx <= b_idx + BW'(1);
                        end
                    end
                end

                S_READ_ADDR: begin
                    if (rx_byte_valid) begin
                        tx_byte       <= c_bytes[rx_byte[CW-1:0]];
                        tx_byte_valid <= 1'b1;
                        state         <= S_IDLE;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // pack loaded operand bytes into gemm_top's flat buses
    always_comb begin
        a_flat = '0;
        for (int i = 0; i < NUM_A_BYTES; i++)
            a_flat[i*DATA_W +: DATA_W] = a_bytes[i];
        b_flat = '0;
        for (int i = 0; i < NUM_B_BYTES; i++)
            b_flat[i*DATA_W +: DATA_W] = b_bytes[i];
    end

    // latch the result bytes whenever a run completes; hold until the next
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int i = 0; i < NUM_C_BYTES; i++) c_bytes[i] <= '0;
        end else if (gemm_done) begin
            for (int i = 0; i < NUM_C_BYTES; i++)
                c_bytes[i] <= c_flat[i*8 +: 8];
        end
    end

    wire _unused = &{tx_ready, 1'b0};

endmodule

`default_nettype wire
