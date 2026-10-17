"""
Putting a value into one form field, whatever widget it is: a text box, a native <select>, a searchable
dropdown (react-select and other ARIA comboboxes, as on Greenhouse's job boards), a checkbox or radio group.

The fill agent used to drive searchable dropdowns itself: click, type, wait, click an option, check. That is
four or five model steps per dropdown, and a Greenhouse form can have twenty-five of them, so the agent ran
out of steps with the name and email still empty. Here one call fills a field and checks that it held.

Dropdowns are driven with the keyboard, not the mouse: focus the box, ArrowDown opens the menu, typing
filters it (and makes a type-ahead box such as a city search load its matches), ArrowDown moves to the
option and Enter picks it. Keys go to whatever has focus, so this works the same inside an iframe, where
mouse coordinates would be the iframe's, not the page's. Options are read from the dropdown's own
container: a page can keep hundreds of unrelated role=option elements around (a phone number's country list).
"""
import asyncio
import json
import re

# Field kinds DESCRIBE_JS reports.
TEXT, SELECT, COMBOBOX, CHECKBOX, RADIO, EDITABLE, FILE, OTHER = (
    "text", "select", "combobox", "checkbox", "radio", "editable", "file", "other")

_DESCRIBE_JS = r"""function () {
  const el = this, doc = el.ownerDocument;
  const text = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  const labelOf = e => {
    if (e.labels && e.labels.length) return text(e.labels[0]);
    const ids = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (ids.length) return ids.map(i => text(doc.getElementById(i))).join(' ');
    if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
    const set = e.closest('fieldset');
    if (set && set.querySelector('legend')) return text(set.querySelector('legend'));
    return e.getAttribute('placeholder') || '';
  };
  const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
  let kind = 'other', options = [], group = '';
  if (tag === 'select') { kind = 'select'; options = [...el.options].map(o => text(o)).filter(Boolean); }
  else if (type === 'checkbox' || type === 'radio') {
    kind = type;
    const members = el.name ? [...doc.querySelectorAll('input[type=' + type + ']')].filter(m => m.name === el.name) : [el];
    options = members.length > 1 ? members.map(m => labelOf(m)) : [];
    const set = el.closest('fieldset');
    group = set && set.querySelector('legend') ? text(set.querySelector('legend')) : '';
    if (!group && members.length > 1) {
      // Greenhouse-style: the group's question is the label of the box around the checkboxes.
      let box = el.parentElement;
      while (box && box.querySelectorAll('input[type=' + type + ']').length < members.length) box = box.parentElement;
      const head = box && box.querySelector('label:not(:has(input)), legend, [class*=label]');
      group = head ? text(head) : '';
    }
  }
  else if (type === 'file') kind = 'file';
  else if (el.getAttribute('role') === 'combobox' || ['list', 'both'].includes(el.getAttribute('aria-autocomplete'))
           || /\bselect__input\b/.test(el.className) || el.closest('[class*=select__control]')) kind = 'combobox';
  else if (el.isContentEditable) kind = 'editable';
  else if (tag === 'textarea' || tag === 'input') kind = 'text';
  return JSON.stringify({kind, label: labelOf(el), group, options, maxLength: el.maxLength > 0 ? el.maxLength : null,
    connected: el.isConnected,
    multi: !!(el.multiple ||
    (el.closest('[class*=select__container]') || el).querySelector?.('[class*=value-container--is-multi]'))});
}"""

# The options a combobox shows now: inside its own container (react-select), else in the listbox it names.
_OPTIONS_JS = r"""function () {
  const el = this, doc = el.ownerDocument;
  const text = n => (n.textContent || '').replace(/\s+/g, ' ').trim();
  const box = el.closest('[class*=select__container]');
  let opts = box ? [...box.querySelectorAll('[class*=select__option], [role=option]')] : [];
  if (!opts.length) {
    const ids = [el.getAttribute('aria-controls'), el.getAttribute('aria-owns')].filter(Boolean).join(' ').split(/\s+/);
    for (const id of ids) { const list = id && doc.getElementById(id); if (list) opts = [...list.querySelectorAll('[role=option]')]; }
  }
  const focused = opts.find(o => /option--is-focused/.test(o.className) || o.getAttribute('aria-selected') === 'true'
                                 || o.id && o.id === el.getAttribute('aria-activedescendant'));
  const shown = opts.map(text).filter(t => t && !/^no options$/i.test(t) && !/^loading/i.test(t));
  return JSON.stringify({options: shown, focused: focused ? text(focused) : null});
}"""

# What a field holds now, as the user would read it.
_HELD_JS = r"""function () {
  const el = this;
  const text = n => (n.textContent || '').replace(/\s+/g, ' ').trim();
  const box = el.closest('[class*=select__container]');
  if (box) {
    const picked = [...box.querySelectorAll('[class*=single-value], [class*=multi-value__label]')].map(text);
    return JSON.stringify(picked);
  }
  if (el.tagName === 'SELECT') return JSON.stringify([...el.selectedOptions].map(text));
  if (el.isContentEditable) return JSON.stringify([el.innerText]);
  return JSON.stringify([el.value || '']);
}"""

_FOCUS_JS = "function () { this.scrollIntoView({block: 'center'}); this.focus(); }"

_SET_SELECT_JS = r"""function (wanted) {
  const opt = [...this.options].find(o => o.textContent.replace(/\s+/g, ' ').trim() === wanted);
  if (!opt) return false;
  this.value = opt.value;
  this.dispatchEvent(new Event('input', {bubbles: true}));
  this.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
}"""

# Check exactly the group members named in `wanted` (a JSON list of labels), or set one box to `wanted`.
_SET_CHECKS_JS = r"""function (wanted, single) {
  const el = this, doc = el.ownerDocument;
  const text = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  const labelOf = e => (e.labels && e.labels.length) ? text(e.labels[0]) : (e.getAttribute('aria-label') || '');
  const type = el.type;
  const members = el.name ? [...doc.querySelectorAll('input[type=' + type + ']')].filter(m => m.name === el.name) : [el];
  const want = JSON.parse(wanted);
  for (const m of members) {
    const on = single ? want === true : want.includes(labelOf(m));
    if (m.checked !== on && (on || type === 'checkbox')) m.click();
  }
  return JSON.stringify(members.filter(m => m.checked).map(labelOf));
}"""

_STOP = {"the", "of", "and", "a", "an", "in", "at", "for", "to", "or", "on"}
_YES = re.compile(r"^(yes|y|true|checked|agree|i agree|accept|i accept|confirm|i confirm)\b", re.I)
_NO = re.compile(r"^(no|n|false|unchecked|disagree)\b", re.I)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9+]+", str(text or "").lower()))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower())) - _STOP


def best_option(value: str, options: list[str]) -> str | None:
    """The one option `value` names, or None when none or several could be it. Beyond answers.pick_option
    (exact, yes/no, prefix), an option holding every word of the value ('Black African' → 'Black (including
    African …)'), or a value holding every word of one option (a full university name → its listed name)."""
    if not options or not str(value or "").strip():
        return None
    from .answers import pick_option   # answers imports agent, which imports browser_agent: not at load time
    hit = pick_option(value, options)
    if hit:
        return hit
    v = _words(value)
    holding = sorted(((len(_words(o) - v), o) for o in options if v and v <= _words(o)))
    if holding and (len(holding) == 1 or holding[0][0] < holding[1][0]):
        return holding[0][1]     # "Bristol, United Kingdom": "Bristol, England, …", not "Little Bristol, England, …"
    if holding:
        return None
    # An option inside the value must cover most of it: "University of Bristol" is in "The University of the
    # West of England, Bristol" word for word, and is a different university. Initials count for the words
    # they stand for, so "Bristol, UWE" covers that name.
    initials = _initials(value)
    scored = []
    for o in options:
        words = _words(o)
        if len(words) < 2 or not words <= v | set(initials):
            continue
        covered = set().union(*(initials.get(w, {w}) for w in words)) & v
        scored.append((len(covered) / len(v), o))
    scored = sorted((c, o) for c, o in scored if c >= 0.75)
    if scored and (len(scored) == 1 or scored[-1][0] > scored[-2][0]):
        return scored[-1][1]
    return None


def _initials(value: str) -> dict[str, set[str]]:
    """{initials: the words they stand for} for each comma-separated part of `value` of two or more words:
    'University of the West of England' → {'uwe': {'university', 'west', 'england'}}."""
    out = {}
    for part in str(value).split(","):
        words = [w for w in re.findall(r"[a-z0-9]+", part.lower()) if w not in _STOP]
        if len(words) >= 2:
            out["".join(w[0] for w in words)] = set(words)
    return out


def _queries(value: str) -> list[str]:
    """What to type into a searchable dropdown to find `value`: the value, then shorter forms of it."""
    value = " ".join(str(value).split())
    out = [value]
    plain = re.sub(r"^the\s+", "", value.split(",")[0], flags=re.I).strip()
    words = [w for w in plain.split() if w.lower() not in _STOP]
    for q in (plain, " ".join(words[:3]), words[0] if words else ""):
        if q and q not in out:
            out.append(q)
    return out


_KEYS = {"ArrowDown": ("ArrowDown", 40), "Enter": ("Enter", 13), "Escape": ("Escape", 27), "Backspace": ("Backspace", 8)}


class Field:
    """One element of the page, reached through the CDP session of the frame it lives in."""

    def __init__(self, browser_session, node):
        self.browser_session, self.node = browser_session, node
        self.send = self.session_id = self.object_id = None

    async def open(self) -> "Field":
        cdp = await self.browser_session.cdp_client_for_node(self.node)
        self.send, self.session_id = cdp.cdp_client.send, cdp.session_id
        resolved = await self.send.DOM.resolveNode(params={"backendNodeId": self.node.backend_node_id},
                                                   session_id=self.session_id)
        self.object_id = resolved["object"]["objectId"]
        return self

    async def call(self, js: str, *args):
        result = await self.send.Runtime.callFunctionOn(
            params={"objectId": self.object_id, "functionDeclaration": js, "returnByValue": True,
                    "arguments": [{"value": a} for a in args]},
            session_id=self.session_id)
        return (result.get("result") or {}).get("value")

    async def key(self, name: str) -> None:
        key, code = _KEYS[name]
        for kind in ("keyDown", "keyUp"):
            await self.send.Input.dispatchKeyEvent(
                params={"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code}, session_id=self.session_id)
        await asyncio.sleep(0.05)

    async def type(self, text: str) -> None:
        await self.send.Input.insertText(params={"text": text}, session_id=self.session_id)

    async def describe(self) -> dict:
        return json.loads(await self.call(_DESCRIBE_JS))

    async def held(self) -> list[str]:
        return json.loads(await self.call(_HELD_JS))

    async def shown(self) -> dict:
        return json.loads(await self.call(_OPTIONS_JS))

    async def clear_typed(self) -> None:
        """Remove text typed into a combobox's search box (react-select keeps it until blur)."""
        for _ in range(60):
            if not await self.call("function () { return this.value || ''; }"):
                return
            await self.key("Backspace")


async def read_options(field: Field) -> list[str]:
    """A dropdown's options: a <select>'s, a checkbox/radio group's labels, or what a combobox lists when opened
    ([] for a type-ahead box, which lists nothing until something is typed)."""
    info = await field.describe()
    if info["kind"] != COMBOBOX:
        return info["options"]
    await field.call(_FOCUS_JS)
    options: list[str] = []
    for _ in range(2):
        await asyncio.sleep(0.3)
        await field.key("ArrowDown")
        options = await _wait_options(field, 1.5)
        if options:
            break
    await field.key("Escape")
    return options


async def _wait_options(field: Field, seconds: float = 2.5) -> list[str]:
    options: list[str] = []
    for _ in range(int(seconds / 0.25)):
        await asyncio.sleep(0.25)
        latest = (await field.shown())["options"]
        if latest and latest == options:
            return latest          # settled
        options = latest
    return options


async def _choose_in_combobox(field: Field, value: str) -> tuple[bool, str]:
    await field.call(_FOCUS_JS)
    await field.clear_typed()
    await field.key("ArrowDown")
    options = await _wait_options(field, 1.0)
    target = best_option(value, options)
    seen = list(options)
    if not target:
        for query in _queries(value):
            await field.clear_typed()
            await field.type(query)
            options = await _wait_options(field)
            seen = seen if not options else options
            target = best_option(value, options)
            if target:
                break
    if not target:
        await field.clear_typed()
        await field.key("Escape")
        listed = "; ".join(f"“{o}”" for o in seen[:15]) + (" …" if len(seen) > 15 else "")
        return False, (f"none of its options matches “{value}”" + (f". It lists: {listed}" if seen else
                                                                    ", and it listed nothing for it"))
    for _ in range(len(options) + 2):
        state = await field.shown()
        if state["focused"] == target:
            await field.key("Enter")
            break
        await field.key("ArrowDown")
    else:
        await field.key("Escape")
        return False, f"couldn't move to “{target}” in its list"
    await asyncio.sleep(0.3)
    held = await field.held()
    if (await field.describe())["multi"]:
        await field.key("Escape")
    # A dropdown can show less than the option it picked: a dial-code box shows "+44" for "United Kingdom +44".
    if any(h and (h == target or f" {_norm(h)} " in f" {_norm(target)} ") for h in held):
        return True, target
    return False, f"picked “{target}” but it shows {held or 'nothing'}"


async def fill(browser_session, node, value: str) -> tuple[bool, str]:
    """Put `value` into the field `node`, checked. Returns (True, what it now holds) or (False, why not)."""
    try:
        field = await Field(browser_session, node).open()
        info = await field.describe()
        kind = info["kind"]
        if not info.get("connected", True):
            return False, "that element is no longer on the page (the form re-rendered): use the current indexes"
        if info.get("maxLength") and len(value) > info["maxLength"] and kind in (TEXT, EDITABLE):
            return False, f"the box takes at most {info['maxLength']} characters and the value has {len(value)}"
        if kind == FILE:
            return False, "it's a file upload: use upload_file"
        if kind == COMBOBOX:
            return await _choose_in_combobox(field, value)
        if kind == SELECT:
            target = best_option(value, info["options"])
            if not target:
                return False, f"none of its options matches “{value}”. It lists: " + "; ".join(info["options"][:15])
            await field.call(_SET_SELECT_JS, target)
            held = await field.held()
            return (True, target) if target in held else (False, f"it shows {held} after choosing “{target}”")
        if kind in (CHECKBOX, RADIO):
            if info["options"]:   # a group: check the members the value names
                parts = [p.strip() for p in re.split(r"[;\n]|,(?![^(]*\))", value) if p.strip()]
                wanted = [best_option(p, info["options"]) for p in parts]
                if not parts or None in wanted:
                    return False, f"“{value}” isn't one of its choices: " + "; ".join(info["options"][:20])
                checked = json.loads(await field.call(_SET_CHECKS_JS, json.dumps(wanted), False))
                ok = set(wanted) <= set(checked)
                return (True, ", ".join(checked)) if ok else (False, f"it shows {checked} checked")
            on = bool(_YES.search(value.strip()))
            if not on and not _NO.search(value.strip()):
                return False, f"a single checkbox takes yes or no, not “{value}”"
            checked = json.loads(await field.call(_SET_CHECKS_JS, json.dumps(on), True))
            return (True, "checked" if checked else "unchecked") if bool(checked) == on else (False, "it didn't change")
        if kind in (TEXT, EDITABLE):
            await field.call(_FOCUS_JS)
            await field.call("function () { if (typeof this.select === 'function') this.select(); else "
                             "document.getSelection().selectAllChildren(this); }")
            await field.type(value)
            held = (await field.held() or [""])[0]
            if " ".join(held.split()) == " ".join(value.split()):
                return True, value
            return False, f"it holds “{held[:80]}” instead"
        return False, "it isn't a field that takes a value"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]


def same_question(label: str, question: str) -> bool:
    """Whether a field's label is the question the model says it is: guards against an answer going into
    the field next to the one it belongs to."""
    from .answers import question_key
    a, b = question_key(label), question_key(question)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.7
