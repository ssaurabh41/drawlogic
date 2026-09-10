"""Bus name parsing.

A net named `d[7:0]` carries eight bits; `d[3]` carries one. Width lives in
the name rather than only in a field so that what you read on the drawing and
what the checker enforces cannot drift apart.
"""

import re

_RANGE = re.compile(r"^(?P<base>[A-Za-z_][A-Za-z0-9_.$]*)\[(?P<msb>\d+):(?P<lsb>\d+)\]$")
_INDEX = re.compile(r"^(?P<base>[A-Za-z_][A-Za-z0-9_.$]*)\[(?P<bit>\d+)\]$")
_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.$]*$")


def parse(name):
  """Split a net name into (base, msb, lsb).

  Returns None if the name is not a legal net name at all. A plain name and a
  single-bit index both come back with msb == lsb.
  """
  if not name:
    return None

  match = _RANGE.match(name)
  if match:
    return (match.group("base"), int(match.group("msb")), int(match.group("lsb")))

  match = _INDEX.match(name)
  if match:
    bit = int(match.group("bit"))
    return (match.group("base"), bit, bit)

  if _PLAIN.match(name):
    return (name, 0, 0)

  return None


def width_of(name):
  """Bit width implied by a net name; 1 for plain or unparseable names."""
  parsed = parse(name)
  if parsed is None:
    return 1
  _, msb, lsb = parsed
  return abs(msb - lsb) + 1


def is_bus(name):
  return width_of(name) > 1


def bits(name):
  """Expand `d[7:0]` into ['d[7]', 'd[6]', ... 'd[0]'], msb first."""
  parsed = parse(name)
  if parsed is None:
    return []
  base, msb, lsb = parsed
  if msb == lsb and "[" not in (name or ""):
    return [base]
  step = -1 if msb >= lsb else 1
  return ["%s[%d]" % (base, i) for i in range(msb, lsb + step, step)]
