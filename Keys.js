.pragma library

function modifierMask() {
  return Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier
}

function commandModifierMask() {
  return Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
}

function isPrintable(text) {
  return typeof text === "string" && Array.from(text).length === 1
    && !(text.length === 1 && /[\ud800-\udfff]/.test(text))
    && (text === " " || !/[\s\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f]/.test(text))
}

function parseSpec(spec) {
  if (typeof spec !== "string" || !spec) return null
  var parts = spec.split("+")
  var key = parts.pop()
  if (!key) {
    // The last plus may be the key itself ("+" or "Ctrl++").
    if (parts.pop() !== "") return null
    key = "+"
  }
  var names = { Ctrl: Qt.ControlModifier, Alt: Qt.AltModifier, Shift: Qt.ShiftModifier, Super: Qt.MetaModifier }
  var modifiers = 0
  for (var i = 0; i < parts.length; i++) {
    var flag = names[parts[i]]
    if (typeof flag !== "number" || (modifiers & flag)) return null
    modifiers |= flag
  }
  if (isPrintable(key)) return { text: key, modifiers: modifiers }
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(key) || key.indexOf("Key_") === 0) return null
  var code = Qt["Key_" + key]
  if (typeof code !== "number" || code === Qt.Key_unknown) return null
  if (code === Qt.Key_Backtab) {
    code = Qt.Key_Tab
    modifiers |= Qt.ShiftModifier
  }
  return { key: code, modifiers: modifiers }
}

function matches(event, spec) {
  var binding = parseSpec(spec)
  if (!binding) return false
  var modifiers = event.modifiers & modifierMask()
  var key = event.key
  if (key === Qt.Key_Backtab) {
    key = Qt.Key_Tab
    modifiers |= Qt.ShiftModifier
  }
  if (binding.text === undefined)
    return key === binding.key && modifiers === binding.modifiers

  if (!(binding.modifiers & commandModifierMask())) {
    // Let text express the effect of Shift, e.g. G and Shift+G both match
    // shifted "G", but only G also works without Shift (e.g. Caps Lock).
    if (!(binding.modifiers & Qt.ShiftModifier)) modifiers &= ~Qt.ShiftModifier
    return modifiers === binding.modifiers && event.text === binding.text
  }
  if (modifiers !== binding.modifiers) return false
  // Ctrl can emit a control code instead of text. Qt reports letter keys
  // in uppercase, so use that key code as a fallback for modified letters.
  if (/^[A-Za-z]$/.test(binding.text)) {
    var letter = binding.text.toUpperCase()
    return isPrintable(event.text) ? event.text.toUpperCase() === letter : key === letter.charCodeAt(0)
  }
  return event.text === binding.text
}

function actionFor(event, keymap) {
  var actions = Object.keys(keymap)
  for (var i = 0; i < actions.length; i++) {
    var specs = keymap[actions[i]]
    for (var j = 0; j < specs.length; j++) {
      if (matches(event, specs[j])) return actions[i]
    }
  }
  return ""
}

function keymapFor(keymap, allowedActions, textInput) {
  var result = {}
  Object.keys(keymap).forEach(function(action) {
    if (allowedActions.indexOf(action) === -1) return
    result[action] = !textInput ? keymap[action] : keymap[action].filter(function(spec) {
      var binding = parseSpec(spec)
      // Plain printable keys (including Shift-produced text) belong to input.
      return binding && ((binding.modifiers & commandModifierMask())
        || (binding.key !== undefined && binding.key >= Qt.Key_Escape))
    })
  })
  return result
}

function printableText(event) {
  return !(event.modifiers & commandModifierMask()) && isPrintable(event.text) ? event.text : ""
}

function tabDigit(event) {
  var text = printableText(event)
  return /^[0-9]$/.test(text) ? Number(text) : -1
}

function hint(spec) {
  var labels = { Up: "↑", Down: "↓", Left: "←", Right: "→", Return: "↵", Enter: "↵",
    Escape: "Esc", Backtab: "Shift+Tab", " ": "Space" }
  return spec.replace(/(^|\+)([^+]+)$/, function(_, prefix, key) {
    return prefix + (Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : key)
  })
}
