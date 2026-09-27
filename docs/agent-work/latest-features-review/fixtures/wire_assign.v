// `wire x = a & b;` is a declaration carrying an expression. hdl.py says
// expressions it cannot draw are reported as a warning.
module cont (input a, input b, output y);
  wire x = a & b;
  buf g (y, x);
endmodule
