#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT

mkdir -p -- "$test_root/legacy" "$test_root/data"
mkdir -m 700 -- "$test_root/runtime"
printf '# First\nalpha body\n\n# Second\nbeta body\n' > "$test_root/legacy/1_prompts.md"
printf '%s\n' '[{"type":"text","text":"clipboard value"}]' > "$test_root/history.json"

export SNIP_DATA_DIR="$test_root/data"
export SNIP_LEGACY_DIR="$test_root/legacy"
export SNIP_CLIPBOARD_FILE="$test_root/history.json"
export XDG_RUNTIME_DIR="$test_root/runtime"
snip="$repo_root/home/.local/bin/snip"

snapshot=$($snip snapshot)
jq -e '.categories[0].name == "Prompts" and (.items | length) == 2 and (.inbox | length) == 1' <<<"$snapshot" >/dev/null

$snip pin-inbox 0 >/dev/null
snapshot=$($snip snapshot)
jq -e '(.items | length) == 3 and ([.items[] | select(.pinned)] | length) == 1' <<<"$snapshot" >/dev/null

pinned_id=$(jq -r '.items[] | select(.pinned) | .id' <<<"$snapshot")
$snip toggle-pin "$pinned_id" >/dev/null
snapshot=$($snip snapshot)
jq -e '(.items | length) == 2 and ([.items[] | select(.pinned)] | length) == 0' <<<"$snapshot" >/dev/null

category_id=$(jq -r '.categories[0].id' <<<"$snapshot")
$snip save-inbox 0 "$category_id" >/dev/null
snapshot=$($snip snapshot)
jq -e '([.items[] | select(.body == "clipboard value" and .categoryName == "Prompts")] | length) == 1' <<<"$snapshot" >/dev/null

editable_id=$(jq -r '.items[] | select(.body == "clipboard value") | .id' <<<"$snapshot")
fake_editor="$test_root/fake-editor"
printf '%s\n' '#!/usr/bin/env bash' 'printf '\''# Edited title\n\nedited body\n'\'' > "$1"' > "$fake_editor"
chmod +x "$fake_editor"
EDITOR="$fake_editor" $snip edit "$editable_id" >/dev/null
snapshot=$($snip snapshot)
jq -e 'any(.items[]; .id == $id and .title == "Edited title" and .body == "edited body")' --argjson id "$editable_id" <<<"$snapshot" >/dev/null

$snip create-category Later >/dev/null
snapshot=$($snip snapshot)
jq -e 'any(.categories[]; .name == "Later")' <<<"$snapshot" >/dev/null

$snip save-inbox-new 0 Scratch >/dev/null
snapshot=$($snip snapshot)
jq -e 'any(.categories[]; .name == "Scratch") and any(.items[]; .body == "clipboard value" and .categoryName == "Scratch")' <<<"$snapshot" >/dev/null

scratch_id=$(jq -r '.categories[] | select(.name == "Scratch") | .id' <<<"$snapshot")
$snip delete-category "$scratch_id" >/dev/null
snapshot=$($snip snapshot)
jq -e 'all(.categories[]; .name != "Scratch") and any(.items[]; .body == "clipboard value" and .pinned and .categoryId == null)' <<<"$snapshot" >/dev/null

$snip delete "$pinned_id" >/dev/null
snapshot=$($snip snapshot)
jq -e 'all(.items[]; .id != $id)' --argjson id "$pinned_id" <<<"$snapshot" >/dev/null

printf 'snip tests passed\n'
