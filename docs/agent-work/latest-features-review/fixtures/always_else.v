// if/else inside an always block: the most common two lines in any netlist.
module seq2 (input clk, input rst, input d, output reg q);
  always @(posedge clk)
    if (rst) q <= 1'b0;
    else q <= d;
endmodule
