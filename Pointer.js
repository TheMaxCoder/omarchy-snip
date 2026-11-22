.pragma library

// Keep the last accepted scene position so small steps can accumulate.
function advance(previous, x, y) {
  if (previous && Math.abs(x - previous.x) <= 1 && Math.abs(y - previous.y) <= 1)
    return previous
  return { x: x, y: y }
}
