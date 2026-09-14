# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

SIM ?= icarus
FST ?= -fst
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = \
    tt_um_apex_gemm2x2.sv \
    rx_byte_interface.sv \
    tx_byte_interface.sv \
    cmd_decoder_2x2.sv \
    gemm_top.sv \
    systolic_array.sv \
    pe.sv \
    mac_unit.sv

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD              = sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))

ifeq ($(SIM), icarus)
    COMPILE_ARGS += -g2012
endif

else

# Gate level simulation:
SIM_BUILD              = sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DUSE_POWER_PINS
COMPILE_ARGS    += -DSIM
COMPILE_ARGS    += -DUNIT_DELAY=\#1
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v

endif

TOPLEVEL = tt_um_apex_gemm2x2
COCOTB_TEST_MODULES = test_gemm2x2

include $(shell cocotb-config --makefiles)/Makefile.sim
