import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Keys.js" as KeyBindings
import "Search.js" as Search

Item {
  id: root

  property string homePath: Quickshell.env("HOME")
  property var shell: null
  property var manifest: null
  readonly property string backendPath: manifest && manifest.__sourceDir ? manifest.__sourceDir + "/bin/snip" : ""
  property string clipboardFile: ""
  property var config: ({})
  readonly property var keymap: config.keys || ({})
  readonly property var searchKeys: KeyBindings.keymapFor(keymap, ["up", "down", "paste", "copy", "back"], true)
  readonly property var savePickerKeys: KeyBindings.keymapFor(keymap, ["up", "down", "paste", "back"], false)
  readonly property var categoryInputKeys: KeyBindings.keymapFor(keymap, ["paste", "back"], true)
  property bool startModePending: false

  property bool opened: false
  property bool searchMode: false
  property string searchText: ""
  property int currentTab: 0
  property int selectedIndex: 0
  property bool cursorActive: true
  property var categories: []
  property var savedItems: []
  property var inboxItems: []
  property bool savePickerOpen: false
  property int saveCategoryIndex: 0
  property bool categoryInputOpen: false
  property bool categoryInputForSave: false
  property string categoryInput: ""
  property string statusText: ""
  property string statusTone: "accent"
  property int deleteArmedId: -1
  property int deleteArmedCategoryId: -1
  property string pendingAction: ""
  property string processOutput: ""
  property string processError: ""

  property color background: Commons.Color.menu.background
  property color foreground: Commons.Color.menu.text
  property color border: Commons.Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Commons.Color.menu.scrim
  property color selectedBackground: Commons.Color.menu.selectedBackground
  property color selectedText: Commons.Color.menu.selectedText
  property color accent: Commons.Color.accent
  property color urgent: Commons.Color.urgent
  property color muted: Commons.Color.muted
  property color success: Commons.Color.accent
  property color warning: Commons.Color.accent
  property color danger: Commons.Color.urgent
  property color info: Commons.Color.accent
  property color navigation: Commons.Color.accent
  property color navigationBackground: Qt.rgba(Commons.Color.accent.r, Commons.Color.accent.g, Commons.Color.accent.b, 0.16)
  property color navigationTabBackground: navigationRowBackground
  property color navigationRowBackground: Qt.rgba(Commons.Color.accent.r, Commons.Color.accent.g, Commons.Color.accent.b, 0.05)
  property color navigationBorder: Qt.rgba(Commons.Color.accent.r, Commons.Color.accent.g, Commons.Color.accent.b, 0.12)
  readonly property color statusColor: statusTone === "success" ? success
    : (statusTone === "warning" ? warning : (statusTone === "danger" ? danger : accent))
  readonly property color translucentBackground: background
  readonly property int cornerRadius: Style.cornerRadius
  property string fontFamily: Style.font.menuFamily
  property int contentMargin: Style.spacing.panelPadding
  property int contentSpacing: Style.spacing.md
  property int cardWidth: Math.min(Style.space(1040), panel.width - Style.gapsOut * 2)
  property int cardHeight: Math.min(Style.space(650), panel.height - Style.gapsOut * 2)
  property int headerHeight: Math.max(Style.space(40), Style.font.title + Style.spacing.controlPaddingY * 2)
  property int footerHeight: Math.max(Style.space(30), Style.font.caption + Style.spacing.controlPaddingY * 2)
  property int rowHeight: Math.max(Style.space(58), Style.font.body + Style.font.caption + Style.spacing.rowPaddingX * 2)
  property int tabCount: 2 + categories.length

  property var displayRows: []
  property var selectedItem: null
  property bool resetSelectionOnSnapshot: false
  readonly property string previewText: {
    var body = root.selectedItem ? String(root.selectedItem.body || "") : ""
    return body.length > 12000 ? body.slice(0, 12000) + "\n\n[Preview truncated · copy or edit for full text]" : body
  }

  function open(payload) {
    root.close(null)
    root.searchMode = Boolean(root.config.startInSearch)
    root.rebuildDisplay()
    root.startModePending = true
    root.resetSelectionOnSnapshot = true
    root.opened = true
    themeColors.reload()
    Qt.callLater(function() { if (root.opened) keyCatcher.forceActiveFocus() })
    if (!root.checkBackendPath()) return
    configTimer.restart()
    if (!root.runBackend(["snapshot"], "snapshot")) refreshTimer.restart()
  }

  function close(payload) {
    root.opened = false
    root.startModePending = false
    root.searchMode = false
    root.searchText = ""
    root.currentTab = 0
    root.resetSelectionOnSnapshot = false
    root.selectedIndex = 0
    root.selectedItem = null
    root.cursorActive = false
    root.savePickerOpen = false
    root.saveCategoryIndex = 0
    root.categoryInputOpen = false
    root.categoryInputForSave = false
    root.categoryInput = ""
    root.statusText = ""
    root.statusTone = "accent"
    root.deleteArmedId = -1
    root.deleteArmedCategoryId = -1
    configTimer.stop()
    refreshTimer.stop()
    statusTimer.stop()
    deleteTimer.stop()
  }

  function dismiss() {
    root.close(null)
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "themaxcoder.snip")
  }

  function checkBackendPath() {
    if (root.backendPath) return true
    statusTimer.stop()
    root.statusText = "Cannot locate Snip: the plugin manifest has no install directory (__sourceDir)"
    root.statusTone = "danger"
    return false
  }

  function applyConfig(raw) {
    try {
      var config = JSON.parse(raw)
      config.keys = KeyBindings.validatedKeymap(config.keys, config.warnings)
      root.config = config
    } catch (error) {
      if (root.opened) root.status("Could not read Snip configuration", "danger")
      return
    }
    if (root.startModePending) {
      root.startModePending = false
      if (root.searchMode !== root.config.startInSearch) {
        root.searchMode = root.config.startInSearch
        root.selectedIndex = 0
        root.rebuildDisplay()
      }
    }
    if (root.opened && root.config.warnings.length)
      root.status(root.config.warnings.join(" · "), "warning")
  }

  function runBackend(args, action) {
    if (!root.checkBackendPath()) return false
    if (backend.running) {
      root.status("Still working…", "warning")
      return false
    }
    root.pendingAction = action
    root.processOutput = ""
    root.processError = ""
    backend.command = [root.backendPath].concat(args)
    backend.running = true
    return true
  }

  function applySnapshot(raw) {
    try {
      var data = JSON.parse(raw)
      root.clipboardFile = data.clipboardFile || ""
      root.categories = data.categories || []
      root.savedItems = data.items || []
      root.inboxItems = data.inbox || []
      if (root.currentTab >= root.tabCount) root.currentTab = Math.max(0, root.tabCount - 1)
    } catch (error) {
      root.status("Could not read Snip data", "danger")
      return
    }
    if (root.resetSelectionOnSnapshot) root.selectedIndex = 0
    root.rebuildDisplay(!root.resetSelectionOnSnapshot)
  }

  function status(message, tone) {
    root.statusText = message
    root.statusTone = tone || "accent"
    statusTimer.restart()
  }

  function keyHint(keymap, actions) {
    var specs = actions.map(function(action) { return (keymap[action] || [])[0] })
      .filter(Boolean).map(KeyBindings.hint)
    return specs.length ? "[" + specs.join("/") + "]" : ""
  }

  function hints(keymap, labels) {
    return labels.map(function(pair) {
      var key = root.keyHint(keymap, pair.slice(1))
      return key ? key + " " + pair[0] : ""
    }).filter(Boolean).join("   ")
  }

  function footerHint() {
    if (root.searchMode)
      return root.hints(root.searchKeys, [["move", "up", "down"], ["paste", "paste"],
        ["copy", "copy"], [root.searchText ? "clear search" : "navigation", "back"]])
    var row = root.selectedItem
    var itemAction = !row ? [] : row.source === "inbox" ? ["save", "save"]
      : row.kind === "text" ? ["edit", "edit"] : []
    return root.hints(root.keymap, [["tabs", "prevTab", "nextTab"], ["move", "up", "down"],
      ["ends", "first", "last"], ["pin", "pin"], itemAction,
      ["delete", "delete"], ["tab +/−", "newTab", "deleteTab"], ["search", "search"],
      ["paste", "paste"], ["copy", "copy"], ["close", "back", "close"]])
  }

  function loadThemePalette(raw) {
    function namedColor(name, fallback) {
      var expression = new RegExp("^\\s*" + name + "\\s*=\\s*[\\\"']?(#[0-9A-Fa-f]{6})", "m")
      var match = String(raw || "").match(expression)
      return match ? match[1] : fallback
    }
    function hexToRgba(hex, alpha) {
      if (!hex || typeof hex !== "string" || hex.charAt(0) !== "#") return Qt.rgba(0.5, 0.5, 0.5, alpha)
      var r = parseInt(hex.slice(1, 3), 16) / 255
      var g = parseInt(hex.slice(3, 5), 16) / 255
      var b = parseInt(hex.slice(5, 7), 16) / 255
      return Qt.rgba(r, g, b, alpha)
    }
    var fgHex = namedColor("foreground", "#dcd7ba")
    var rawAccent = namedColor("accent", "#7daea3")
    var accentHex = (rawAccent.toLowerCase() === fgHex.toLowerCase())
      ? namedColor("cyan", namedColor("blue", rawAccent))
      : rawAccent
    root.accent = accentHex
    root.success = namedColor("green", accentHex)
    root.warning = namedColor("orange", namedColor("yellow", accentHex))
    root.danger = namedColor("red", root.urgent)
    var infoHex = namedColor("cyan", namedColor("blue", accentHex))
    root.info = infoHex
    root.navigation = accentHex
    root.navigationBackground = hexToRgba(accentHex, 0.16)
    root.navigationTabBackground = hexToRgba(accentHex, 0.05)
    root.navigationRowBackground = hexToRgba(accentHex, 0.05)
    root.navigationBorder = hexToRgba(accentHex, 0.12)
  }

  function inboxRow(entry) {
    return {
      source: "inbox",
      itemId: -1,
      ref: entry.ref,
      categoryId: -1,
      categoryName: "Inbox",
      kind: entry.kind || "text",
      title: entry.title || "Untitled",
      subtitle: entry.subtitle || "",
      body: entry.body || "",
      path: entry.path || "",
      imageMissing: Boolean(entry.imageMissing),
      pinned: false
    }
  }

  function savedRow(entry) {
    return {
      source: "saved",
      itemId: Number(entry.id),
      categoryId: entry.categoryId === null ? -1 : Number(entry.categoryId),
      categoryName: entry.categoryName || "Pinned only",
      kind: entry.kind || "text",
      title: entry.title || "Untitled",
      subtitle: entry.subtitle || entry.categoryName || "",
      body: entry.body || "",
      path: entry.path || "",
      imageMissing: Boolean(entry.imageMissing),
      pinned: Boolean(entry.pinned)
    }
  }

  function rebuildDisplay(preserveSelection) {
    var previous = preserveSelection ? root.selectedItem : null
    var rows = []
    if (root.searchMode) {
      rows = Search.filter(root.searchText, root.savedItems.map(root.savedRow).concat(root.inboxItems.map(root.inboxRow)))
    } else if (root.currentTab === 0) {
      for (var i = 0; i < root.inboxItems.length; i++) rows.push(root.inboxRow(root.inboxItems[i]))
    } else if (root.currentTab === 1) {
      for (var p = 0; p < root.savedItems.length; p++) {
        if (root.savedItems[p].pinned) rows.push(root.savedRow(root.savedItems[p]))
      }
    } else {
      var category = root.categories[root.currentTab - 2]
      if (category) {
        for (var c = 0; c < root.savedItems.length; c++) {
          if (Number(root.savedItems[c].categoryId) === Number(category.id)) rows.push(root.savedRow(root.savedItems[c]))
        }
      }
    }

    var nextIndex = Math.max(0, Math.min(root.selectedIndex, rows.length - 1))
    if (previous) {
      for (var r = 0; r < rows.length; r++) {
        var row = rows[r]
        if (row.source === previous.source && (row.source === "saved"
            ? row.itemId === previous.itemId
            : row.ref === previous.ref)) {
          nextIndex = r
          break
        }
      }
    }
    root.displayRows = rows
    root.updateSelection(nextIndex)
    root.cursorActive = rows.length > 0
    Qt.callLater(function() {
      if (root.displayRows.length > 0) resultList.positionViewAtIndex(root.selectedIndex, ListView.Contain)
      preview.contentY = 0
    })
  }

  function back() {
    root.startModePending = false
    if (!root.searchMode) {
      root.dismiss()
      return
    }
    if (root.searchText) root.searchText = ""
    else root.searchMode = false
    root.selectedIndex = 0
    root.rebuildDisplay()
  }

  function tabName(index) {
    if (index === 0) return "Inbox"
    if (index === 1) return "Pinned"
    var category = root.categories[index - 2]
    return category ? category.name : ""
  }

  function switchTab(delta) {
    root.currentTab = (root.currentTab + delta + root.tabCount) % root.tabCount
    root.selectedIndex = 0
    root.deleteArmedId = -1
    root.deleteArmedCategoryId = -1
    root.rebuildDisplay()
  }

  function updateSelection(index) {
    root.resetSelectionOnSnapshot = false
    root.selectedIndex = index
    root.selectedItem = root.displayRows[index] || null
  }

  function select(delta) {
    if (root.displayRows.length === 0) return
    root.updateSelection((root.selectedIndex + delta + root.displayRows.length) % root.displayRows.length)
    root.cursorActive = true
    resultList.positionViewAtIndex(root.selectedIndex, ListView.Contain)
    preview.contentY = 0
  }

  function selectAbsolute(index) {
    if (root.displayRows.length === 0) return
    root.updateSelection(Math.max(0, Math.min(index, root.displayRows.length - 1)))
    root.cursorActive = true
    resultList.positionViewAtIndex(root.selectedIndex, ListView.Contain)
    preview.contentY = 0
  }

  function pasteSelected(copyOnly) {
    var row = root.selectedItem
    if (!row || !root.checkBackendPath()) return
    var args = row.source === "inbox" ? ["paste", "--ref", row.ref] : ["paste", "--id", String(row.itemId)]
    if (copyOnly) {
      root.runBackend(args.concat(["--copy-only"]), "copy")
    } else {
      root.dismiss()
      Quickshell.execDetached([root.backendPath].concat(args))
    }
  }

  function quickPin() {
    var row = root.selectedItem
    if (!row) return
    if (row.source === "inbox") {
      if (root.runBackend(["pin-inbox", "--ref", row.ref], "mutate")) {
        var save = root.keyHint(root.keymap, ["save"])
        root.status("Pinned" + (save ? " · " + save + " choose or create a tab" : ""), "success")
      }
    } else {
      if (root.runBackend(["toggle-pin", String(row.itemId)], "mutate"))
        root.status(row.pinned ? "Unpinned" : "Pinned", row.pinned ? "warning" : "success")
    }
  }

  function openSavePicker() {
    var row = root.selectedItem
    if (!row || row.source !== "inbox") return
    root.saveCategoryIndex = 0
    root.savePickerOpen = true
  }

  function saveToCategory() {
    var row = root.selectedItem
    if (root.saveCategoryIndex === root.categories.length) {
      root.savePickerOpen = false
      root.categoryInput = ""
      root.categoryInputForSave = true
      root.categoryInputOpen = true
      return
    }
    var category = root.categories[root.saveCategoryIndex]
    if (!row || !category) return
    root.savePickerOpen = false
    if (root.runBackend(["save-inbox", "--ref", row.ref, String(category.id)], "mutate"))
      root.status("Saved to " + category.name, "success")
  }

  function deleteSelected() {
    var row = root.selectedItem
    if (!row || row.source !== "saved") return
    if (root.deleteArmedId !== row.itemId) {
      root.deleteArmedId = row.itemId
      root.status("Press " + root.keyHint(root.keymap, ["delete"]) + " again to delete", "danger")
      deleteTimer.restart()
      return
    }
    root.deleteArmedId = -1
    root.runBackend(["delete", String(row.itemId)], "mutate")
    root.status("Deleted", "danger")
  }

  function deleteCurrentTab() {
    if (root.currentTab < 2) {
      root.status("Inbox and Pinned are permanent tabs", "warning")
      return
    }
    var category = root.categories[root.currentTab - 2]
    if (!category) return
    if (root.deleteArmedCategoryId !== Number(category.id)) {
      root.deleteArmedCategoryId = Number(category.id)
      root.status("Delete “" + category.name + "”? Press " + root.keyHint(root.keymap, ["deleteTab"])
        + " again · snippets move to Pinned", "danger")
      deleteTimer.restart()
      return
    }
    root.deleteArmedCategoryId = -1
    root.currentTab = 1
    root.selectedIndex = 0
    if (root.runBackend(["delete-category", String(category.id)], "mutate"))
      root.status("Deleted “" + category.name + "” · snippets moved to Pinned", "danger")
  }

  function editSelected() {
    var row = root.selectedItem
    if (!row || row.source !== "saved") {
      var saveKey = root.keyHint(root.keymap, ["save"])
      root.status("Only saved snippets can be edited" + (saveKey ? " · press " + saveKey + " to save this one to a tab" : ""), "warning")
      return
    }
    if (row.kind !== "text") {
      root.status("Images cannot be edited as text", "warning")
      return
    }
    if (!root.checkBackendPath()) return
    var terminal = root.config.terminal
    if (!terminal || !terminal.length) {
      if (!root.config.hasDefaultTerminal) {
        root.status("xdg-terminal-exec not found; set terminal in Snip's config", "danger")
        return
      }
      terminal = ["xdg-terminal-exec", "--app-id=TUI.float", "--title=Edit Snip", "--"]
    }
    root.dismiss()
    Quickshell.execDetached(terminal.concat([root.backendPath, "edit", String(row.itemId)]))
  }

  function createCategory() {
    var name = root.categoryInput.trim()
    if (!name) return
    var saveAfterCreate = root.categoryInputForSave
    var row = root.selectedItem
    root.categoryInputOpen = false
    root.categoryInputForSave = false
    root.categoryInput = ""
    if (saveAfterCreate && row && row.source === "inbox") {
      if (root.runBackend(["save-inbox-new", "--ref", row.ref, "--", name], "mutate"))
        root.status("Created and saved to " + name, "success")
    } else if (root.runBackend(["create-category", name], "mutate")) {
      root.status("Created " + name, "success")
    }
  }

  Process {
    id: backend
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.processOutput = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.processError = text
    }
    onExited: function(exitCode) {
      var action = root.pendingAction
      root.pendingAction = ""
      if (!root.opened) return
      if (exitCode !== 0) {
        root.status(root.processError.trim() || "Snip operation failed", "danger")
        return
      }
      if (action === "snapshot") root.applySnapshot(root.processOutput)
      else {
        if (action === "copy") root.status("Copied", "success")
        refreshTimer.restart()
      }
    }
  }

  Process {
    id: configReader
    command: [root.backendPath, "config"]
    stdout: StdioCollector { id: configOutput }
    stderr: StdioCollector { id: configError }
    onExited: function(exitCode) {
      if (exitCode === 0) root.applyConfig(configOutput.text)
      else if (root.opened) root.status(configError.text.trim() || "Could not load Snip configuration", "danger")
    }
  }

  FileView {
    path: root.config.configFile || ""
    watchChanges: true
    printErrors: false
    onFileChanged: {
      reload()
      configTimer.restart()
    }
  }

  FileView {
    path: root.clipboardFile
    watchChanges: true
    printErrors: false
    onFileChanged: {
      reload()
      if (root.opened) refreshTimer.restart()
    }
  }

  FileView {
    id: themeColors
    path: root.homePath + "/.local/state/omarchy/current/theme/colors.toml"
    watchChanges: true
    printErrors: false
    onLoaded: root.loadThemePalette(text())
    onFileChanged: reload()
  }

  Timer {
    id: configTimer
    interval: 80
    onTriggered: {
      if (configReader.running) restart()
      else if (root.backendPath) configReader.running = true
    }
  }

  Timer {
    id: refreshTimer
    interval: 80
    onTriggered: {
      if (!root.opened) return
      if (backend.running) restart()
      else root.runBackend(["snapshot"], "snapshot")
    }
  }

  Timer {
    id: statusTimer
    interval: 2200
    onTriggered: {
      root.statusText = ""
      root.statusTone = "accent"
    }
  }

  Timer {
    id: deleteTimer
    interval: 3500
    onTriggered: {
      root.deleteArmedId = -1
      root.deleteArmedCategoryId = -1
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "snip"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      anchors.centerIn: parent
      color: root.translucentBackground
      borderSpec: root.borderSpec
      padding: root.contentMargin

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          event.accepted = true
          if (root.savePickerOpen) {
            var saveAction = KeyBindings.actionFor(event, root.savePickerKeys)
            var choices = root.categories.length + 1
            if (saveAction === "back") root.savePickerOpen = false
            else if (saveAction === "up") root.saveCategoryIndex = (root.saveCategoryIndex - 1 + choices) % choices
            else if (saveAction === "down") root.saveCategoryIndex = (root.saveCategoryIndex + 1) % choices
            else if (saveAction === "paste") root.saveToCategory()
            return
          }

          if (root.categoryInputOpen) {
            var inputAction = KeyBindings.textInputAction(event, root.categoryInputKeys)
            if (inputAction === "back") {
              root.categoryInputOpen = false
              root.categoryInputForSave = false
              root.categoryInput = ""
            } else if (inputAction === "paste") {
              root.createCategory()
            } else if (Util.editsFilter(event, root.categoryInput)) {
              root.categoryInput = Util.editedFilter(event, root.categoryInput)
            } else {
              root.categoryInput += KeyBindings.printableText(event)
            }
            return
          }

          var tab = KeyBindings.tabDigit(event)
          if (tab >= 0) {
            if (tab < root.tabCount) {
              root.startModePending = false
              root.searchMode = false
              root.searchText = ""
              root.currentTab = tab
              root.selectedIndex = 0
              root.deleteArmedId = -1
              root.deleteArmedCategoryId = -1
              root.rebuildDisplay()
            }
            return
          }

          var action = root.searchMode ? KeyBindings.textInputAction(event, root.searchKeys)
            : KeyBindings.actionFor(event, root.keymap)
          if (action === "back") root.back()
          else if (action === "up") root.select(-1)
          else if (action === "down") root.select(1)
          else if (action === "paste") root.pasteSelected(false)
          else if (action === "copy") root.pasteSelected(true)
          else if (root.searchMode) {
            var query = Util.editsFilter(event, root.searchText)
              ? Util.editedFilter(event, root.searchText)
              : root.searchText + KeyBindings.printableText(event)
            if (query !== root.searchText) {
              root.searchText = query
              root.selectedIndex = 0
              root.rebuildDisplay()
            }
          } else if (action === "close") root.dismiss()
          else if (action === "nextTab") root.switchTab(1)
          else if (action === "prevTab") root.switchTab(-1)
          else if (action === "first") root.selectAbsolute(0)
          else if (action === "last") root.selectAbsolute(root.displayRows.length - 1)
          else if (action === "pin") root.quickPin()
          else if (action === "save") root.openSavePicker()
          else if (action === "delete") root.deleteSelected()
          else if (action === "deleteTab") root.deleteCurrentTab()
          else if (action === "edit") root.editSelected()
          else if (action === "newTab") {
            root.categoryInput = ""
            root.categoryInputForSave = false
            root.categoryInputOpen = true
          } else if (action === "search") {
            root.startModePending = false
            root.searchMode = true
            root.searchText = ""
            root.selectedIndex = 0
            root.rebuildDisplay()
          }
        }
      }

      Column {
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: root.contentSpacing

        Item {
          width: parent.width
          height: root.headerHeight

          Row {
            visible: !root.searchMode
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.sm

            Repeater {
              model: root.tabCount
              delegate: Rectangle {
                id: resultRow
                required property int index
                height: root.headerHeight - Style.spacing.sm
                width: tabLabel.implicitWidth + Style.spacing.controlPaddingX * 2
                radius: root.cornerRadius
                color: index === root.currentTab ? root.navigationTabBackground : "transparent"
                border.width: index === root.currentTab ? 1 : 0
                border.color: index === root.currentTab ? root.navigationBorder : "transparent"

                Text {
                  id: tabLabel
                  anchors.centerIn: parent
                  text: index + "  " + root.tabName(index)
                  color: index === root.currentTab
                    ? root.navigation
                    : (index === 1 ? root.success : root.muted)
                  opacity: index === 1 && index !== root.currentTab ? 0.8 : 1
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.weight: index === root.currentTab ? Font.DemiBold : Font.Normal
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    root.currentTab = index
                    root.selectedIndex = 0
                    root.rebuildDisplay()
                  }
                }
              }
            }
          }

          Text {
            visible: root.searchMode
            anchors.left: parent.left
            anchors.right: searchCount.left
            anchors.verticalCenter: parent.verticalCenter
            text: "󰍉  " + (root.searchText || "Search saved snippets and clipboard…") + (root.searchText ? "▍" : "")
            color: root.searchText ? root.foreground : root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            elide: Text.ElideRight
          }

          Text {
            id: searchCount
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.displayRows.length + (root.displayRows.length === 1 ? " item" : " items")
            color: root.info
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Rectangle {
          width: parent.width
          height: 1
          color: root.muted
          opacity: 0.45
        }

        Item {
          width: parent.width
          height: parent.height - root.headerHeight - root.footerHeight - root.contentSpacing * 4 - 1

          Item {
            id: listPane
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width * 0.38

            ListView {
              id: resultList
              anchors.fill: parent
              anchors.rightMargin: root.contentSpacing
              model: root.displayRows
              clip: true
              spacing: Style.spacing.xs
              boundsBehavior: Flickable.StopAtBounds

              delegate: Rectangle {
                id: snippetRow
                required property int index
                required property var modelData

                readonly property bool hasCursor: root.cursorActive && index === root.selectedIndex
                width: resultList.width
                height: root.rowHeight
                radius: root.cornerRadius
                color: hasCursor ? root.navigationRowBackground : "transparent"
                border.width: hasCursor ? 1 : 0
                border.color: hasCursor ? root.navigationBorder : "transparent"

                Rectangle {
                  visible: snippetRow.hasCursor
                  anchors.left: parent.left
                  anchors.verticalCenter: parent.verticalCenter
                  width: Math.max(2, Style.space(3))
                  height: parent.height - Style.spacing.sm * 2
                  radius: width / 2
                  color: root.navigation
                }

                Column {
                  anchors.left: parent.left
                  anchors.right: pinIcon.left
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.spacing.rowPaddingX
                  anchors.rightMargin: Style.spacing.sm
                  spacing: Style.spacing.xxs

                  Text {
                    width: parent.width
                    text: snippetRow.modelData.title
                    color: parent.parent.hasCursor ? root.navigation : root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.weight: parent.parent.hasCursor ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    text: root.searchMode ? snippetRow.modelData.categoryName : snippetRow.modelData.subtitle
                    color: root.muted
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }

                Text {
                  id: pinIcon
                  anchors.right: parent.right
                  anchors.rightMargin: Style.spacing.md
                  anchors.verticalCenter: parent.verticalCenter
                  text: snippetRow.modelData.kind === "image" ? "󰋩" : (snippetRow.modelData.pinned ? "󰐃" : "")
                  color: snippetRow.modelData.kind === "image" ? root.info : (snippetRow.modelData.pinned ? root.success : root.muted)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.icon
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onContainsMouseChanged: if (containsMouse) {
                    root.cursorActive = true
                    root.updateSelection(index)
                  }
                  onClicked: {
                    root.updateSelection(index)
                    root.pasteSelected(false)
                  }
                }
              }
            }

            Column {
              anchors.centerIn: parent
              visible: root.displayRows.length === 0
              spacing: Style.spacing.sm

              Text {
                width: parent.width
                text: root.searchMode ? "󰈉" : (root.currentTab === 1 ? "󰐃" : "󰅍")
                color: root.currentTab === 1 ? root.success : root.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.displayLarge
                horizontalAlignment: Text.AlignHCenter
              }

              Text {
                width: parent.width
                text: root.searchMode ? "No matches" : (root.currentTab === 1 ? "Nothing pinned yet" : "No items")
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                horizontalAlignment: Text.AlignHCenter
              }
            }
          }

          Rectangle {
            anchors.left: listPane.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: root.muted
            opacity: 0.4
          }

          Item {
            id: previewPane
            anchors.left: listPane.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: root.contentSpacing * 2

            Flickable {
              id: preview
              anchors.fill: parent
              clip: true
              contentWidth: width
              contentHeight: previewContent.height
              boundsBehavior: Flickable.StopAtBounds

              Column {
                id: previewContent
                width: preview.width
                spacing: Style.spacing.lg

                Image {
                  id: previewImage
                  width: parent.width
                  height: visible ? Math.min(Style.space(430), implicitHeight * width / Math.max(1, implicitWidth)) : 0
                  visible: source.toString() !== "" && status !== Image.Error
                  source: root.selectedItem && root.selectedItem.kind === "image" && !root.selectedItem.imageMissing
                    ? Util.fileUrl(root.selectedItem.path) : ""
                  fillMode: Image.PreserveAspectFit
                  asynchronous: true
                  cache: false
                }

                Text {
                  width: parent.width
                  visible: root.selectedItem !== null
                    && (root.selectedItem.kind !== "image" || root.selectedItem.imageMissing || previewImage.status === Image.Error)
                  text: !root.selectedItem || root.selectedItem.kind !== "image" ? root.previewText
                    : (root.selectedItem.imageMissing ? "Image file missing" : "Could not load image")
                  textFormat: Text.PlainText
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  lineHeight: 1.3
                  font.hintingPreference: Font.PreferFullHinting
                  wrapMode: Text.Wrap
                }
              }
            }
          }
        }

        Rectangle {
          width: parent.width
          height: 1
          color: root.muted
          opacity: 0.35
        }

        Item {
          width: parent.width
          height: root.footerHeight

          Text {
            anchors.left: parent.left
            anchors.right: pinnedHint.left
            anchors.rightMargin: Style.spacing.sm
            anchors.verticalCenter: parent.verticalCenter
            text: root.statusText || root.footerHint()
            textFormat: Text.PlainText
            color: root.statusText ? root.statusColor : root.foreground
            opacity: root.statusText ? 1.0 : 0.65
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Text {
            id: pinnedHint
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.selectedItem && root.selectedItem.source === "saved" && root.selectedItem.pinned ? "󰐃 pinned" : ""
            color: root.success
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      Rectangle {
        id: dialogScrim
        anchors.fill: parent
        z: 20
        visible: root.savePickerOpen || root.categoryInputOpen
        radius: root.cornerRadius
        color: Qt.rgba(root.background.r, root.background.g, root.background.b, 0.94)

        BorderSurface {
          anchors.centerIn: parent
          width: dialogColumn.width + contentLeftInset + contentRightInset
          height: dialogColumn.implicitHeight + contentTopInset + contentBottomInset
          radius: root.cornerRadius
          color: root.background
          borderSpec: root.borderSpec
          padding: root.contentMargin

          Column {
            id: dialogColumn
            anchors.centerIn: parent
            width: Math.min(dialogScrim.width * 0.5, Style.space(420))
            spacing: Style.spacing.md

            Text {
              width: parent.width
              text: root.categoryInputOpen
                ? (root.categoryInputForSave ? "Create new tab and save" : "New tab")
                : "Save to tab"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.weight: Font.DemiBold
            }

            Rectangle {
              visible: root.categoryInputOpen
              width: parent.width
              height: root.headerHeight
              radius: root.cornerRadius
              color: root.selectedBackground

              Text {
                anchors.fill: parent
                anchors.margins: Style.spacing.controlPaddingX
                verticalAlignment: Text.AlignVCenter
                text: root.categoryInput ? root.categoryInput + "▍" : "Category name…"
                color: root.categoryInput ? root.foreground : root.selectedText
                opacity: root.categoryInput ? 1 : 0.6
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
            }

            Repeater {
              visible: root.savePickerOpen
              model: root.categories.length + 1
              delegate: Rectangle {
                required property int index
                visible: root.savePickerOpen
                width: parent.width
                height: visible ? root.headerHeight : 0
                radius: root.cornerRadius
                color: index === root.saveCategoryIndex ? root.selectedBackground : "transparent"

                Text {
                  anchors.left: parent.left
                  anchors.leftMargin: Style.spacing.controlPaddingX
                  anchors.verticalCenter: parent.verticalCenter
                  text: index === root.categories.length ? "＋  Create new tab…" : root.categories[index].name
                  color: index === root.saveCategoryIndex ? root.selectedText
                    : (index === root.categories.length ? root.accent : root.foreground)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }
              }
            }

            Text {
              width: parent.width
              text: root.categoryInputOpen
                ? root.hints(root.categoryInputKeys, [["confirm", "paste"], ["cancel", "back"]])
                : root.hints(root.savePickerKeys, [["move", "up", "down"], ["confirm", "paste"], ["cancel", "back"]])
              color: root.foreground
              opacity: 0.5
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }
    }
  }
}
