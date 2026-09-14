`default_nettype none

// ---------------------------------------------------------------------------
// tt_um_apex_gemm2x2 -- Tiny Tapeout top level for the 2x2 integer
// output-stationary systolic GEMM bring-up (README.md milestone: "Implement
// one systolic PE" / 2x2 stepping stone ahead of the 8x8 BF16 array).
//
// Pin map (frozen host byte protocol, README.md step 12):
//   ui_in[7:0]  = host_data in   (RX byte)
//   uo_out[7:0] = host_data out  (TX byte)
//   uio[0] = RX_VALID   in   (host asserts when ui_in holds a new byte)
//   uio[1] = RX_READY   out  (always 1 here -- see rx_byte_interface)
//   uio[2] = TX_READY   in   (host asserts to accept the byte on uo_out)
//   uio[3] = TX_VALID   out  (chip asserts while uo_out holds an unread byte)
//   uio[7:4] reserved, driven low
// ---------------------------------------------------------------------------
module tt_um_apex_gemm2x2 (
    input  logic [7:0] ui_in,
    output logic [7:0] uo_out,
    input  logic [7:0] uio_in,
    output logic [7:0] uio_out,
    output logic [7:0] uio_oe,
    input  logic       ena,
    input  logic       clk,
    input  logic       rst_n
);

    localparam int N      = 2;
    localparam int K      = 2;
    localparam int DATA_W = 8;
    localparam int ACC_W  = 32;

    // ---- RX ----------------------------------------------------------
    logic       rx_byte_valid;
    logic       rx_host_ready;
    logic [7:0] rx_byte;

    rx_byte_interface u_rx (
        .clk           (clk),
        .rst_n         (rst_n),
        .host_data     (ui_in),
        .host_valid    (uio_in[0]),
        .host_ready    (rx_host_ready),
        .rx_byte       (rx_byte),
        .rx_byte_valid (rx_byte_valid)
    );

    // ---- TX ------------------------------------------------------------
    logic [7:0] tx_byte;
    logic       tx_byte_valid;
    logic       tx_ready;
    logic       tx_host_valid;

    tx_byte_interface u_tx (
        .clk           (clk),
        .rst_n         (rst_n),
        .tx_byte       (tx_byte),
        .tx_byte_valid (tx_byte_valid),
        .tx_ready_o    (tx_ready),
        .host_ready    (uio_in[2]),
        .host_data     (uo_out),
        .host_valid    (tx_host_valid)
    );

    // ---- decoder + compute core ----------------------------------------
    logic                  gemm_start, gemm_busy, gemm_done;
    logic [N*K*DATA_W-1:0] a_flat;
    logic [K*N*DATA_W-1:0] b_flat;
    logic [N*N*ACC_W-1:0]  c_flat;

    cmd_decoder_2x2 #(
        .N(N), .K(K), .DATA_W(DATA_W), .ACC_W(ACC_W)
    ) u_decoder (
        .clk           (clk),
        .rst_n         (rst_n),
        .rx_byte       (rx_byte),
        .rx_byte_valid (rx_byte_valid & ena),
        .tx_byte       (tx_byte),
        .tx_byte_valid (tx_byte_valid),
        .tx_ready      (tx_ready),
        .gemm_start    (gemm_start),
        .a_flat        (a_flat),
        .b_flat        (b_flat),
        .gemm_busy     (gemm_busy),
        .gemm_done     (gemm_done),
        .c_flat        (c_flat)
    );

    gemm_top #(
        .N(N), .K(K), .DATA_W(DATA_W), .ACC_W(ACC_W), .MAC_LATENCY(0)
    ) u_gemm (
        .clk    (clk),
        .rst_n  (rst_n),
        .start  (gemm_start),
        .a_flat (a_flat),
        .b_flat (b_flat),
        .busy   (gemm_busy),
        .done   (gemm_done),
        .c_flat (c_flat)
    );

    assign uio_out = {4'b0, tx_host_valid, 1'b0, rx_host_ready, 1'b0};
    assign uio_oe  = 8'b0000_1010;   // [3]=TX_VALID out, [1]=RX_READY out

    wire _unused = &{uio_in[7:4], 1'b0};

endmodule

`default_nettype wire
