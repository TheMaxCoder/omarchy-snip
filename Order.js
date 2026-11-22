.pragma library

function neighbor(rows, index, direction) {
  var row = rows[index]
  if (!row) return null
  var target = index + direction
  if (!rows[target]) return { reason: direction < 0 ? "Already at the top" : "Already at the bottom" }
  if (rows[target].pinned !== row.pinned)
    return { reason: direction < 0 ? "Top of unpinned items" : "Bottom of pinned items" }
  return { index: target }
}
