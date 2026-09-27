// A clocked block with a case statement -- what an ordinary netlist of
// sequential logic looks like. hdl.py's module docstring promises that
// behavioural code is "reported as a warning rather than refused".
module seq (input clk, input [1:0] sel, output reg q);
  always @(posedge clk) begin
    case (sel)
      2'd0: q <= 1'b0;
      default: q <= 1'b1;
    endcase
  end
endmodule
