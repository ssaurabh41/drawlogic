"""Behavioural Verilog, lowered to the gates and flip-flops a drawing can show.

    items = rtl.items(clean_text, start, end)   # a module body, item by item
    cells, warnings = rtl.lower(module)         # hdl._Module -> cell specs

hdl.py reads a netlist; this is what lets it read the RTL people actually
write. It is not a synthesiser. It covers the part of RTL that has an
obvious schematic:

- `assign` and `always @(*)` with ~ & | ^ ! && || ?: == != {..} {n{..}},
  bit and part selects, sized constants, if/else and case;
- `always @(posedge clk)`, optionally `or posedge rst` / `or negedge rst_n`
  with the reset tested first, which become one flip-flop per bit -- a
  `dffr` when there is an asynchronous reset, a `dff` otherwise.

Everything is bit-blasted, the way a synthesiser does it: a 4-bit register is
four flip-flops, which is also how a shift register is drawn by hand.
Arithmetic, comparisons other than == and !=, casez, loops and functions are
reported and left out -- run with Yosys installed for those (see yosys.py).
"""

import re


class LowerError(Exception):
  """This expression or statement has no drawing here; the text says why."""


# ---- tokens ----------------------------------------------------------------

TOKEN = re.compile(r"""
  (?P<ws>\s+)
 |(?P<num>(?:\d[\d_]*)?\s*'[sS]?[bBoOdDhH]\s*[0-9a-fA-FxXzZ_?]+|\d[\d_]*)
 |(?P<id>[A-Za-z_][A-Za-z0-9_$]*|\\\S+|\$[A-Za-z_][A-Za-z0-9_$]*)
 |(?P<str>"(?:\\.|[^"\\])*")
 |(?P<op>===|!==|<<<|>>>|<=|>=|==|!=|&&|\|\||<<|>>|~&|~\||~\^|\^~|\*\*|->|\+:|-:
        |[-+*/%<>!~&|^?:;,.\#@(){}\[\]=`'])
""", re.X)


class Token(object):
  __slots__ = ("kind", "text", "start", "end", "line")

  def __init__(self, kind, text, start, end, line):
    self.kind, self.text, self.start, self.end, self.line = (
      kind, text, start, end, line)

  def __repr__(self):
    return "Token(%r, line %d)" % (self.text, self.line)


def tokenize(text, start=0, end=None, first_line=1):
  end = len(text) if end is None else end
  tokens, line, position = [], first_line, start
  while position < end:
    match = TOKEN.match(text, position, end)
    if match is None:
      raise LowerError("line %d: unexpected character %r"
                       % (line, text[position]))
    kind = match.lastgroup
    if kind != "ws":
      tokens.append(Token(kind, match.group(), match.start(), match.end(), line))
    line += match.group().count("\n")
    position = match.end()
  return tokens


# ---- module items ----------------------------------------------------------

# Items with a keyword of their own that closes them. Everything in between
# is skipped: none of it is a netlist.
SKIPPED_BLOCKS = {"function": "endfunction", "task": "endtask",
                  "specify": "endspecify", "generate": "endgenerate",
                  "primitive": "endprimitive", "table": "endtable"}
PROCESSES = ("always", "always_ff", "always_comb", "always_latch", "initial",
             "final")


class Item(object):
  """One module item: `kind` is text, assign, process or skipped."""

  def __init__(self, kind, line, text=None, tree=None):
    self.kind, self.line, self.text, self.tree = kind, line, text, tree


class _Stream(object):
  def __init__(self, tokens):
    self.tokens = tokens
    self.index = 0

  def peek(self, offset=0):
    at = self.index + offset
    return self.tokens[at] if at < len(self.tokens) else None

  def text(self, offset=0):
    token = self.peek(offset)
    return token.text if token else None

  def take(self, expected=None):
    token = self.peek()
    if token is None:
      raise LowerError("unexpected end of module%s"
                       % (", expected %r" % expected if expected else ""))
    if expected is not None and token.text != expected:
      raise LowerError("line %d: expected %r, found %r"
                       % (token.line, expected, token.text))
    self.index += 1
    return token

  def done(self):
    return self.index >= len(self.tokens)

  def line(self):
    token = self.peek() or (self.tokens[-1] if self.tokens else None)
    return token.line if token else 0


def items(text, start, end, first_line):
  """The items of a module body, in order.

  Declarations and instances come back as their source text, for hdl.py's own
  reading; assigns and processes as trees. The body used to be split at every
  `;`, which cut an `if ... else` in two and made the `else` half a statement
  of its own -- that was the whole failure on a plain shift register.
  """
  stream = _Stream(tokenize(text, start, end, first_line))
  found = []
  while not stream.done():
    token = stream.peek()
    word = token.text
    if word in SKIPPED_BLOCKS:
      closing = SKIPPED_BLOCKS[word]
      while not stream.done() and stream.take().text != closing:
        pass
      found.append(Item("skipped", token.line, text=word))
      continue
    if word in PROCESSES:
      stream.take()
      try:
        found.append(Item("process", token.line,
                          tree=(word, _event(stream), _statement(stream))))
      except LowerError as exc:
        found.append(Item("skipped", token.line, text="%s (%s)" % (word, exc)))
        _resync(stream)
      continue
    if word == "assign":
      stream.take()
      try:
        tree = _assign_list(stream)
        found.append(Item("assign", token.line, tree=tree))
      except LowerError as exc:
        found.append(Item("skipped", token.line, text="assign (%s)" % exc))
        _resync(stream)
      continue
    if word == ";":
      stream.take()
      continue
    # Anything else runs to the next top-level `;`.
    depth, first = 0, stream.index
    while not stream.done():
      piece = stream.take().text
      if piece in "([{":
        depth += 1
      elif piece in ")]}":
        depth -= 1
      elif piece == ";" and depth <= 0:
        break
    last = stream.tokens[stream.index - 1]
    body_end = last.start if last.text == ";" else last.end
    found.append(Item("text", token.line, text=text[token.start:body_end]))
  return found


def _resync(stream):
  """After a statement that could not be read, skip to where the next item
  plausibly starts: past the next `;` or `end` at the outermost level."""
  depth = brackets = 0
  while not stream.done():
    word = stream.take().text
    if word in "([{":
      brackets += 1
    elif word in ")]}":
      brackets -= 1
    elif word in ("begin", "case", "casez", "casex", "fork"):
      depth += 1
    elif word in ("end", "endcase", "join"):
      depth -= 1
      if depth <= 0:
        return
    elif word == ";" and depth <= 0 and brackets <= 0:
      return


def _event(stream):
  """`@(posedge clk or negedge rst)` -> [("posedge", "clk"), ...];
  `@*` or `@(*)` -> "*"; nothing (always_comb) -> "*"."""
  if stream.text() != "@":
    return "*"
  stream.take("@")
  if stream.text() == "*":
    stream.take()
    return "*"
  stream.take("(")
  if stream.text() == "*":
    stream.take()
    stream.take(")")
    return "*"
  events = []
  while True:
    edge = None
    if stream.text() in ("posedge", "negedge"):
      edge = stream.take().text
    name = stream.take()
    if name.kind != "id":
      raise LowerError("line %d: cannot read the event %r"
                       % (name.line, name.text))
    events.append((edge, name.text))
    if stream.text() in ("or", ","):
      stream.take()
      continue
    stream.take(")")
    return events


# ---- statements ------------------------------------------------------------
#
#   ("block", [statement, ...])
#   ("if", expr, statement, statement or None)
#   ("case", expr, [([expr, ...] or None for default, statement), ...])
#   ("set", lvalue, expr, blocking, line)
#   ("unsupported", why, line)


def _statement(stream):
  token = stream.peek()
  if token is None:
    raise LowerError("unexpected end of module")
  word = token.text
  if word == "begin":
    stream.take()
    if stream.text() == ":":
      stream.take()
      stream.take()
    body = []
    while stream.text() != "end":
      body.append(_statement(stream))
    stream.take("end")
    if stream.text() == ":":
      stream.take()
      stream.take()
    return ("block", body)
  if word == "if":
    stream.take()
    stream.take("(")
    condition = _expression(stream)
    stream.take(")")
    then = _statement(stream)
    otherwise = None
    if stream.text() == "else":
      stream.take()
      otherwise = _statement(stream)
    return ("if", condition, then, otherwise)
  if word in ("unique", "priority"):
    stream.take()
    return _statement(stream)
  if word == "case":
    return _case(stream)
  if word == ";":
    stream.take()
    return ("block", [])
  if word == "for":
    return _for(stream)
  if word in ("while", "repeat", "forever"):
    # Skipped whole -- header and body -- so what follows is read as itself.
    stream.take()
    if stream.text() == "(":
      _skip_brackets(stream)
    _statement(stream)
    return ("unsupported", "`%s`" % word, token.line)
  if word in ("casez", "casex", "fork", "wait", "disable") \
      or word.startswith("$") or word == "#":
    _resync(stream)
    return ("unsupported", "`%s`" % word, token.line)
  lvalue = _primary(stream)
  operator = stream.take()
  if operator.text not in ("<=", "="):
    raise LowerError("line %d: expected <= or =, found %r"
                     % (operator.line, operator.text))
  if stream.text() == "#":
    stream.take()
    stream.take()
  value = _expression(stream)
  stream.take(";")
  return ("set", lvalue, value, operator.text == "=", token.line)


def _for(stream):
  """`for (i = a; cond; i = step) body` -> ("for", i, a, cond, step, body,
  line). `i++`, `i--`, `i += n` and `i -= n` are read as the step too."""
  line = stream.take("for").line
  stream.take("(")
  var = stream.take().text
  stream.take("=")
  start = _expression(stream)
  stream.take(";")
  condition = _expression(stream)
  stream.take(";")
  if stream.take().text != var:
    raise LowerError("line %d: a for loop stepping another variable" % line)
  operator = stream.take().text
  if operator == "=":
    step = _expression(stream)
  elif operator in ("+", "-") and stream.text() == operator:
    stream.take()
    step = ("bin", operator, ("id", var), ("num", None, "1"))
  elif operator in ("+", "-") and stream.text() == "=":
    stream.take()
    step = ("bin", operator, ("id", var), _expression(stream))
  else:
    raise LowerError("line %d: cannot read the step of a for loop" % line)
  stream.take(")")
  return ("for", var, start, condition, step, _statement(stream), line)


def _skip_brackets(stream):
  """Past one balanced ( ... ) group."""
  depth = 0
  while not stream.done():
    word = stream.take().text
    if word == "(":
      depth += 1
    elif word == ")":
      depth -= 1
      if depth == 0:
        return


def _case(stream):
  stream.take("case")
  stream.take("(")
  subject = _expression(stream)
  stream.take(")")
  arms = []
  while stream.text() != "endcase":
    if stream.text() == "default":
      stream.take()
      if stream.text() == ":":
        stream.take()
      arms.append((None, _statement(stream)))
      continue
    labels = [_expression(stream)]
    while stream.text() == ",":
      stream.take()
      labels.append(_expression(stream))
    stream.take(":")
    arms.append((labels, _statement(stream)))
  stream.take("endcase")
  return ("case", subject, arms)


def _assign_list(stream):
  """`assign a = x, b = y;` -> [(lvalue, expr, line), ...]"""
  found = []
  while True:
    if stream.text() == "#":
      stream.take()
      stream.take()
    line = stream.line()
    lvalue = _primary(stream)
    stream.take("=")
    found.append((lvalue, _expression(stream), line))
    if stream.text() == ",":
      stream.take()
      continue
    stream.take(";")
    return found


# ---- expressions -----------------------------------------------------------
#
#   ("id", name)    ("sel", name, msb, lsb)    ("num", width, "0101...")
#   ("cat", [e, ...])    ("rep", count, e)
#   ("un", op, e)    ("bin", op, a, b)    ("tern", c, a, b)

# Loosest first. Each level is a set of binary operators.
BINARY = [("||",), ("&&",), ("|",), ("^", "~^", "^~"), ("&",),
          ("==", "!=", "===", "!=="), ("<", "<=", ">", ">="),
          ("<<", ">>", "<<<", ">>>"), ("+", "-"), ("*", "/", "%"), ("**",)]


def _expression(stream):
  condition = _binary(stream, 0)
  if stream.text() == "?":
    stream.take()
    one = _expression(stream)
    stream.take(":")
    other = _expression(stream)
    return ("tern", condition, one, other)
  return condition


def _binary(stream, level):
  if level == len(BINARY):
    return _unary(stream)
  left = _binary(stream, level + 1)
  while stream.text() in BINARY[level]:
    operator = stream.take().text
    left = ("bin", operator, left, _binary(stream, level + 1))
  return left


def _unary(stream):
  if stream.text() in ("~", "!", "&", "|", "^", "~&", "~|", "~^", "^~", "-",
                       "+"):
    operator = stream.take().text
    return ("un", operator, _unary(stream))
  return _primary(stream)


def _primary(stream):
  token = stream.take()
  if token.text == "(":
    inner = _expression(stream)
    stream.take(")")
    return inner
  if token.text == "{":
    first = _expression(stream)
    if stream.text() == "{":
      # {n{x}}: replication.
      stream.take("{")
      inner = [_expression(stream)]
      while stream.text() == ",":
        stream.take()
        inner.append(_expression(stream))
      stream.take("}")
      stream.take("}")
      return ("rep", first, ("cat", inner))
    parts = [first]
    while stream.text() == ",":
      stream.take()
      parts.append(_expression(stream))
    stream.take("}")
    return ("cat", parts)
  if token.kind == "num":
    return _number(token)
  if token.kind == "id":
    if stream.text() == "(":
      raise LowerError("line %d: function call %s(...)" % (token.line, token.text))
    if stream.text() == "[":
      stream.take("[")
      msb = _expression(stream)
      lsb = None
      if stream.text() == ":":
        stream.take()
        lsb = _expression(stream)
      elif stream.text() in ("+:", "-:"):
        raise LowerError("line %d: indexed part select" % token.line)
      stream.take("]")
      if stream.text() == "[":
        raise LowerError("line %d: memory %s" % (token.line, token.text))
      return ("sel", token.text, msb, lsb)
    return ("id", token.text)
  raise LowerError("line %d: cannot read %r in an expression"
                   % (token.line, token.text))


def _number(token):
  text = token.text.replace("_", "").replace(" ", "")
  if "'" not in text:
    return ("num", None, format(int(text), "b"))
  width, rest = text.split("'", 1)
  rest = rest.lstrip("sS")
  base, digits = rest[0].lower(), rest[1:].lower()
  bits_per = {"b": 1, "o": 3, "h": 4}.get(base)
  if base == "d":
    if any(c in "xz?" for c in digits):
      raise LowerError("line %d: x or z in %s" % (token.line, token.text))
    bits = format(int(digits), "b")
  else:
    bits = ""
    for digit in digits:
      if digit in "xz?":
        raise LowerError("line %d: x or z in %s" % (token.line, token.text))
      bits += format(int(digit, 16), "0%db" % bits_per)
  return ("num", int(width) if width else None, bits)


# ---- lowering --------------------------------------------------------------
#
# A bit is a hashable node:
#   ("c", 0 or 1)                  a constant
#   ("n", key)                     a net: a name, or (name, index)
#   ("not", a) ("and", a, b) ("or", a, b) ("xor", a, b) ("mux", s, a0, a1)
# built through the functions below, which fold constants as they go -- so a
# reset-to-0 mux arrives as an AND with an inverter, and needs no tie cell.

ZERO, ONE = ("c", 0), ("c", 1)


def NOT(a):
  if a[0] == "c":
    return ("c", 1 - a[1])
  if a[0] == "not":
    return a[1]
  return ("not", a)


def AND(a, b):
  if a == ZERO or b == ZERO:
    return ZERO
  if a == ONE:
    return b
  if b == ONE or a == b:
    return a
  return ("and",) + tuple(sorted((a, b), key=repr))


def OR(a, b):
  if a == ONE or b == ONE:
    return ONE
  if a == ZERO:
    return b
  if b == ZERO or a == b:
    return a
  return ("or",) + tuple(sorted((a, b), key=repr))


def XOR(a, b):
  if a[0] == "c" and b[0] == "c":
    return ("c", a[1] ^ b[1])
  if a == ZERO:
    return b
  if b == ZERO:
    return a
  if a == ONE:
    return NOT(b)
  if b == ONE:
    return NOT(a)
  if a == b:
    return ZERO
  return ("xor",) + tuple(sorted((a, b), key=repr))


def MUX(s, a0, a1):
  """s ? a1 : a0"""
  if s == ONE:
    return a1
  if s == ZERO or a0 == a1:
    return a0
  if a0 == ZERO and a1 == ONE:
    return s
  if a0 == ONE and a1 == ZERO:
    return NOT(s)
  if a0 == ZERO:
    return AND(s, a1)
  if a1 == ZERO:
    return AND(NOT(s), a0)
  if a0 == ONE:
    return OR(NOT(s), a1)
  if a1 == ONE:
    return OR(s, a0)
  return ("mux", s, a0, a1)


def _reduce(function, bits, empty):
  result = None
  for bit in bits:
    result = bit if result is None else function(result, bit)
  return empty if result is None else result


class _Scope(object):
  """What the names in one module mean, bit by bit."""

  def __init__(self, module):
    self.module = module

  def bits_of(self, name):
    """The nets of `name`, least significant first."""
    if name not in self.module.ranges:
      return [("n", name)]
    msb, lsb = self.module.ranges[name]
    step = 1 if msb >= lsb else -1
    return [("n", (name, index)) for index in range(lsb, msb + step, step)]

  def index(self, name, expr):
    value = fold(expr, self.module.params)
    if value is None:
      raise LowerError("a select on %s by something that is not a number"
                       % name)
    if name not in self.module.ranges:
      if value != 0:
        raise LowerError("%s[%d] of a one-bit net" % (name, value))
      return [("n", name)]
    msb, lsb = self.module.ranges[name]
    if not min(msb, lsb) <= value <= max(msb, lsb):
      raise LowerError("%s[%d] is outside [%d:%d]" % (name, value, msb, lsb))
    return value

  def select(self, name, msb_expr, lsb_expr):
    first = self.index(name, msb_expr)
    if isinstance(first, list):
      return first
    if lsb_expr is None:
      return [("n", (name, first))]
    second = self.index(name, lsb_expr)
    low, high = min(first, second), max(first, second)
    bits = [("n", (name, index)) for index in range(low, high + 1)]
    return bits if first >= second else bits[::-1]


def constant_value(expr):
  if expr[0] == "num":
    return int(expr[2], 2)
  if expr[0] == "int":
    return expr[1]
  return None


FOLD = {
  "+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
  "/": lambda a, b: a // b if b else None, "%": lambda a, b: a % b if b else None,
  "**": lambda a, b: a ** b if 0 <= b < 64 else None,
  "<<": lambda a, b: a << b if 0 <= b < 64 else None,
  ">>": lambda a, b: a >> b if b >= 0 else None,
  "<": lambda a, b: int(a < b), "<=": lambda a, b: int(a <= b),
  ">": lambda a, b: int(a > b), ">=": lambda a, b: int(a >= b),
  "==": lambda a, b: int(a == b), "!=": lambda a, b: int(a != b),
  "&&": lambda a, b: int(bool(a) and bool(b)),
  "||": lambda a, b: int(bool(a) or bool(b)),
}


def fold(expr, params):
  """The whole-number value of a constant expression -- numbers,
  parameters, arithmetic and comparisons, as in `WIDTH-1` or `i < N` -- or
  None for anything else."""
  kind = expr[0]
  if kind in ("num", "int"):
    return constant_value(expr)
  if kind == "id":
    value = params.get(expr[1])
    return fold(value, params) if value is not None else None
  if kind == "un" and expr[1] in ("-", "+", "!"):
    value = fold(expr[2], params)
    if value is None:
      return None
    return {"-": -value, "+": value, "!": int(not value)}[expr[1]]
  if kind == "bin" and expr[1] in FOLD:
    a, b = fold(expr[2], params), fold(expr[3], params)
    return None if a is None or b is None else FOLD[expr[1]](a, b)
  if kind == "tern":
    test = fold(expr[1], params)
    if test is None:
      return None
    return fold(expr[2] if test else expr[3], params)
  return None


def constant(text, params):
  """fold() for source text, e.g. the `WIDTH-1` of a range; None when it is
  not a constant expression."""
  try:
    stream = _Stream(tokenize(text))
    expr = _expression(stream)
  except LowerError:
    return None
  return fold(expr, params) if stream.done() else None


def evaluate(expr, scope, read):
  """The bits of `expr`, least significant first. `read(bit)` gives what a
  net currently holds -- itself, or an earlier blocking assignment's value."""
  kind = expr[0]
  if kind == "int":
    if expr[1] < 0:
      raise LowerError("a negative number used as bits")
    return [("c", int(b)) for b in reversed(format(expr[1], "b"))]
  if kind == "num":
    bits = [("c", int(b)) for b in reversed(expr[2])]
    if expr[1] is not None:
      bits = (bits + [ZERO] * expr[1])[:expr[1]]
    return bits
  if kind == "id":
    if expr[1] in scope.module.params:
      return evaluate(scope.module.params[expr[1]], scope, read)
    return [read(bit) for bit in scope.bits_of(expr[1])]
  if kind == "sel":
    return [read(bit) for bit in scope.select(expr[1], expr[2], expr[3])]
  if kind == "cat":
    bits = []
    for part in reversed(expr[1]):
      bits += evaluate(part, scope, read)
    return bits
  if kind == "rep":
    count = constant_value(expr[1])
    if count is None:
      raise LowerError("a replication count that is not a number")
    return evaluate(expr[2], scope, read) * count
  if kind == "un":
    operator, bits = expr[1], evaluate(expr[2], scope, read)
    if operator == "~":
      return [NOT(b) for b in bits]
    if operator == "!":
      return [NOT(_reduce(OR, bits, ZERO))]
    if operator == "&":
      return [_reduce(AND, bits, ONE)]
    if operator == "|":
      return [_reduce(OR, bits, ZERO)]
    if operator == "^":
      return [_reduce(XOR, bits, ZERO)]
    if operator == "~&":
      return [NOT(_reduce(AND, bits, ONE))]
    if operator == "~|":
      return [NOT(_reduce(OR, bits, ZERO))]
    if operator in ("~^", "^~"):
      return [NOT(_reduce(XOR, bits, ZERO))]
    if operator == "+":
      return bits
    raise LowerError("the operator %s" % operator)
  if kind == "bin":
    operator = expr[1]
    left = evaluate(expr[2], scope, read)
    right = evaluate(expr[3], scope, read)
    if operator in ("&&", "||"):
      one, other = _reduce(OR, left, ZERO), _reduce(OR, right, ZERO)
      return [AND(one, other) if operator == "&&" else OR(one, other)]
    if operator in ("==", "!=", "===", "!=="):
      width = max(len(left), len(right))
      left += [ZERO] * (width - len(left))
      right += [ZERO] * (width - len(right))
      same = _reduce(AND, [NOT(XOR(a, b)) for a, b in zip(left, right)], ONE)
      return [same if operator in ("==", "===") else NOT(same)]
    gate = {"&": AND, "|": OR, "^": XOR}.get(operator)
    if gate is None and operator in ("~^", "^~"):
      gate = lambda a, b: NOT(XOR(a, b))
    if gate is None:
      raise LowerError("the operator %s" % operator)
    width = max(len(left), len(right))
    left += [ZERO] * (width - len(left))
    right += [ZERO] * (width - len(right))
    return [gate(a, b) for a, b in zip(left, right)]
  if kind == "tern":
    condition = _reduce(OR, evaluate(expr[1], scope, read), ZERO)
    one = evaluate(expr[2], scope, read)
    other = evaluate(expr[3], scope, read)
    width = max(len(one), len(other))
    one += [ZERO] * (width - len(one))
    other += [ZERO] * (width - len(other))
    return [MUX(condition, b, a) for a, b in zip(one, other)]
  raise LowerError("the expression %r" % (kind,))


def targets(lvalue, scope):
  """The nets an assignment writes, least significant first."""
  if lvalue[0] == "id":
    return [bit[1] for bit in scope.bits_of(lvalue[1])]
  if lvalue[0] == "sel":
    return [bit[1] for bit in scope.select(lvalue[1], lvalue[2], lvalue[3])]
  if lvalue[0] == "cat":
    keys = []
    for part in reversed(lvalue[1]):
      keys += targets(part, scope)
    return keys
  raise LowerError("assigning to something that is not a net")


def _fit(bits, width):
  return (bits + [ZERO] * width)[:width]


# More turns than this is a loop that is not meant to be drawn gate by gate.
MAX_UNROLL = 1024


def _unroll(statement, scope, state, blocking_reads):
  """A for loop with constant bounds, run once per turn with the loop
  variable standing in as a number -- the way a synthesiser unrolls it."""
  _, var, start, condition, step, body, line = statement
  params = scope.module.params
  saved = params.get(var)
  try:
    value = fold(start, params)
    for _ in range(MAX_UNROLL + 1):
      if value is None:
        raise LowerError("line %d: a for loop whose bounds are not numbers"
                         % line)
      params[var] = ("int", value)
      going = fold(condition, params)
      if going is None:
        raise LowerError("line %d: a for loop whose bounds are not numbers"
                         % line)
      if not going:
        return state
      state = execute(body, scope, state, blocking_reads)
      value = fold(step, params)
    raise LowerError("line %d: a for loop of more than %d turns"
                     % (line, MAX_UNROLL))
  finally:
    if saved is None:
      params.pop(var, None)
    else:
      params[var] = saved


def execute(statement, scope, state, blocking_reads):
  """Run `statement` symbolically. `state` maps a target key to the node it
  holds now; returns the state after. Branches become muxes."""
  kind = statement[0]
  if kind == "block":
    for inner in statement[1]:
      state = execute(inner, scope, state, blocking_reads)
    return state
  if kind == "unsupported":
    raise LowerError("line %d: %s is not drawn" % (statement[2], statement[1]))
  if kind == "for":
    return _unroll(statement, scope, state, blocking_reads)
  read = _reader(state, blocking_reads)
  if kind == "set":
    _, lvalue, value, _, line = statement
    try:
      keys = targets(lvalue, scope)
      bits = _fit(evaluate(value, scope, read), len(keys))
    except LowerError as exc:
      raise LowerError("line %d: %s" % (line, exc))
    state = dict(state)
    state.update(zip(keys, bits))
    return state
  if kind == "if":
    condition = _reduce(OR, evaluate(statement[1], scope, read), ZERO)
    then = execute(statement[2], scope, state, blocking_reads)
    otherwise = (execute(statement[3], scope, state, blocking_reads)
                 if statement[3] is not None else state)
    return _merge(condition, then, otherwise)
  if kind == "case":
    subject = statement[1]
    # A case is an if/else-if chain on equality, last arm innermost.
    chain = None
    for labels, body in reversed(statement[2]):
      if labels is None:
        chain = body
        continue
      condition = None
      for label in labels:
        equal = ("bin", "==", subject, label)
        condition = equal if condition is None else ("bin", "||", condition, equal)
      chain = ("if", condition, body, chain)
    return execute(chain, scope, state, blocking_reads) if chain else state
  raise LowerError("a statement of kind %s" % kind)


def _reader(state, blocking_reads):
  def read(bit):
    if blocking_reads and bit[0] == "n" and bit[1] in state:
      return state[bit[1]]
    return bit
  return read


def _merge(condition, then, otherwise):
  merged = {}
  for key in set(then) | set(otherwise):
    hold = ("n", key)
    merged[key] = MUX(condition, otherwise.get(key, hold), then.get(key, hold))
  return merged


# ---- cells -----------------------------------------------------------------

GATE_SYMBOL = {"and": ("and2", ("a", "b")), "or": ("or2", ("a", "b")),
               "xor": ("xor2", ("a", "b")), "not": ("inv", ("a",))}


class Emitter(object):
  """Turns nodes into cell specs: (symbol, name, {pin: net text}, line)."""

  def __init__(self, taken, line):
    self.cells = []
    self.done = {}       # node -> net text
    self.taken = taken   # every name already used in the module
    self.line = line
    self.count = 0

  def fresh(self, prefix):
    while True:
      self.count += 1
      name = "%s%d" % (prefix, self.count)
      if name not in self.taken:
        self.taken.add(name)
        return name

  def fresh_named(self, name):
    candidate, number = name, 2
    while candidate in self.taken:
      candidate = "%s_%d" % (name, number)
      number += 1
    self.taken.add(candidate)
    return candidate

  def add(self, symbol, pins, name=None):
    self.cells.append((symbol, name or self.fresh("g"), pins, self.line))

  def net(self, node, into=None):
    """The net carrying `node`, making the cells for it; `into` names the net
    the result must be on, when it has one already."""
    if node[0] == "n":
      text = key_text(node[1])
      if into is not None and into != text:
        self.add("buf", {"a": text, "y": into})
        return into
      return text
    if node[0] == "c":
      out = into or self.fresh("k")
      self.add("tie1" if node[1] else "tie0", {"y": out})
      return out
    if node in self.done:
      if into is not None and into != self.done[node]:
        self.add("buf", {"a": self.done[node], "y": into})
        return into
      return self.done[node]
    # not(and) and not(or) read better as one nand or nor.
    if node[0] == "not" and node[1][0] in ("and", "or") and node[1] not in self.done:
      inner = node[1]
      out = into or self.fresh("n")
      self.done[node] = out
      self.add("nand2" if inner[0] == "and" else "nor2",
               {"a": self.net(inner[1]), "b": self.net(inner[2]), "y": out})
      return out
    if into is None and node[0] == "not" and node[1][0] == "n":
      # An inverted signal gets the name people give it by hand: reset_n.
      out = self.fresh_named(key_text(node[1][1]).replace("[", "_")
                             .replace("]", "") + "_n")
    else:
      out = into or self.fresh("n")
    self.done[node] = out
    if node[0] == "mux":
      self.add("mux2", {"s": self.net(node[1]), "d0": self.net(node[2]),
                        "d1": self.net(node[3]), "y": out})
      return out
    symbol, inputs = GATE_SYMBOL[node[0]]
    pins = {pin: self.net(arg) for pin, arg in zip(inputs, node[1:])}
    pins["y"] = out
    self.add(symbol, pins)
    return out


def key_text(key):
  return key if isinstance(key, str) else "%s[%d]" % key


def lower(module):
  """Cell specs for a module's assigns and processes, and what was left out.

  Returns ([(symbol, name, {pin: net text}, line)], [warning]).
  """
  scope = _Scope(module)
  taken = set(module.ranges) | set(p.name for p in module.ports)
  for item in module.behaviour:
    for key in _written(item, scope):
      taken.add(key if isinstance(key, str) else key[0])
  cells, warnings = [], []
  where = lambda line: "%s line %d" % (module.name, line)

  for item in module.behaviour:
    emitter = Emitter(taken, item.line)
    try:
      if item.kind == "assign":
        for lvalue, value, line in item.tree:
          keys = targets(lvalue, scope)
          bits = _fit(evaluate(value, scope, lambda bit: bit), len(keys))
          for key, bit in zip(keys, bits):
            emitter.net(bit, into=key_text(key))
      else:
        _process(item, scope, emitter, warnings, where(item.line))
    except LowerError as exc:
      # The message names its own line when it knows a closer one.
      said = str(exc)
      warnings.append("%s: %s; left out" % (
        module.name if said.startswith("line ") else where(item.line), said))
      continue
    cells.extend(emitter.cells)
  return cells, warnings


def _written(item, scope):
  try:
    if item.kind == "assign":
      return [k for lvalue, _, _ in item.tree for k in targets(lvalue, scope)]
    return list(execute(item.tree[2], scope, {}, False))
  except LowerError:
    return []


def _process(item, scope, emitter, warnings, where):
  kind, events, body = item.tree
  if kind in ("initial", "final"):
    raise LowerError("an %s block only sets up a simulation" % kind)
  if events == "*" or kind in ("always_comb", "always_latch"):
    state = execute(body, scope, {}, True)
    for key, node in sorted(state.items(), key=lambda kv: repr(kv[0])):
      if _holds(node, key):
        warnings.append("%s: %s keeps its value on some path, which is a "
                        "latch; left out" % (where, key_text(key)))
        continue
      emitter.net(node, into=key_text(key))
    return

  edges = [event for event in events if event[0]]
  if not edges or len(edges) != len(events):
    raise LowerError("a sensitivity list that is neither @(*) nor all edges")
  clock, reset, reset_low, body = _clock_and_reset(edges, body)
  state = execute(body["run"], scope, {}, False)
  reset_values = (execute(body["reset"], scope, {}, False)
                  if reset is not None else {})
  clock_net = emitter.net(("n", clock[1]))
  if clock[0] == "negedge":
    clock_net = emitter.net(NOT(("n", clock[1])))
  reset_net = None
  if reset is not None:
    # dffr's reset is active low: an active-high reset goes through one
    # inverter, shared by every flip-flop it resets.
    reset_net = emitter.net(("n", reset) if reset_low else NOT(("n", reset)))

  keys = sorted(set(state) | set(reset_values), key=repr)
  for key in keys:
    d_net = emitter.net(state.get(key, ("n", key)))
    q_net = key_text(key)
    name = (q_net.replace("[", "_").replace("]", "") + "_reg")
    value = reset_values.get(key)
    if reset_net is not None and value is not None and value != ZERO:
      if value == ONE:
        warnings.append("%s: %s is set to 1 on reset, and the library has "
                        "no flip-flop with a set; drawn without its reset"
                        % (where, q_net))
      else:
        warnings.append("%s: %s resets to something that is not a constant; "
                        "drawn without its reset" % (where, q_net))
      value = None
    if reset_net is not None and value is not None:
      emitter.add("dffr", {"d": d_net, "ck": clock_net, "rn": reset_net,
                           "q": q_net}, name=emitter.fresh_named(name))
    else:
      emitter.add("dff", {"d": d_net, "ck": clock_net, "q": q_net},
                  name=emitter.fresh_named(name))


def _holds(node, key):
  """Does `node` still depend on the target itself -- a latch?"""
  if node == ("n", key):
    return True
  if node[0] in ("n", "c"):
    return False
  return any(_holds(part, key) for part in node[1:])


def _clock_and_reset(edges, body):
  """Which edge is the clock and which the reset, from the body's shape.

  `always @(posedge clk or posedge rst) if (rst) ... else ...` -- the
  signal the outermost `if` tests is the reset, the other edge the clock.
  """
  if len(edges) == 1:
    return edges[0], None, False, {"run": body}
  if len(edges) > 2:
    raise LowerError("more than one reset")
  inner = body
  while inner[0] == "block" and len(inner[1]) == 1:
    inner = inner[1][0]
  if inner[0] != "if" or inner[3] is None:
    raise LowerError("two edges, but no `if (reset) ... else ...` first")
  condition, low = inner[1], False
  if condition[0] == "un" and condition[1] in ("!", "~"):
    condition, low = condition[2], True
  if condition[0] != "id":
    raise LowerError("a reset test that is not a plain signal")
  names = [name for _, name in edges]
  if condition[1] not in names:
    raise LowerError("the first `if` tests %s, which is not in the "
                     "sensitivity list" % condition[1])
  reset_edge = edges[names.index(condition[1])]
  clock = edges[1 - names.index(condition[1])]
  if (reset_edge[0] == "negedge") != low:
    raise LowerError("%s is tested the opposite way to its edge"
                     % condition[1])
  return clock, condition[1], low, {"run": inner[3], "reset": inner[2]}


def parameters(text, known=None):
  """`localparam IDLE = 2'b00, RUN = 2'b01` -> {name: constant tree}.

  Values are kept when they come to a number: a plain one, or arithmetic on
  numbers and the parameters before it (`known`, then this statement's own),
  as in `MSB = WIDTH - 1`. Anything else is left for whoever reads it to
  report.
  """
  stream = _Stream(tokenize(text))
  found = {}
  while not stream.done():
    token = stream.peek()
    if token.kind == "id" and stream.text(1) == "=":
      stream.take()
      stream.take("=")
      try:
        value = _expression(stream)
      except LowerError:
        value = None
        while not stream.done() and stream.text() != ",":
          stream.take()
      if value is not None and value[0] != "num":
        number = fold(value, dict(known or {}, **found))
        value = ("int", number) if number is not None and number >= 0 \
            else None
      if value is not None:
        found[token.text] = value
      continue
    stream.take()
  return found
