.pragma library

function tokens(query) {
  var text = query.trim().toLowerCase()
  return text ? text.split(/\s+/) : []
}

function isSubsequence(token, title) {
  var matched = 0
  for (var i = 0; i < title.length; i++) {
    if (title[i] === token[matched] && ++matched === token.length) return true
  }
  return false
}

function tokenScore(token, title, category) {
  if (title.indexOf(token) === 0) return 6
  var index = title.indexOf(token)
  if (index !== -1) {
    for (var start = index; start !== -1; start = title.indexOf(token, start + 1)) {
      if (/[\s!-/:-@\[-`{-~\u2000-\u206f\u3000-\u303f]/.test(title[start - 1])) return 5
    }
    return 4
  }
  if (isSubsequence(token, title)) return 3
  if (category.indexOf(token) !== -1) return 2
  return -1
}

function scoreTokens(words, fields) {
  var title = String(fields.title || "").toLowerCase()
  var category = String(fields.categoryName || "").toLowerCase()
  var body
  var total = 0
  for (var i = 0; i < words.length; i++) {
    var rank = tokenScore(words[i], title, category)
    if (rank === -1) {
      if (body === undefined) body = String(fields.body || "").slice(0, 20000).toLowerCase()
      if (body.indexOf(words[i]) === -1) return -1
      rank = 1
    }
    total += rank
  }
  return total
}

function score(query, fields) {
  var words = tokens(query)
  return words.length ? scoreTokens(words, fields) : 0
}

function filter(query, rows) {
  var words = tokens(query)
  if (!words.length) return rows.slice()
  var ranked = []
  for (var i = 0; i < rows.length; i++) {
    var rank = scoreTokens(words, rows[i])
    if (rank !== -1) ranked.push({ row: rows[i], rank: rank, index: i })
  }
  ranked.sort(function(a, b) { return b.rank - a.rank || a.index - b.index })
  return ranked.map(function(entry) { return entry.row })
}
