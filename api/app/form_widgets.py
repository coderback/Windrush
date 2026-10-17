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
    """The one option `value` names, or None when none or several could be it (answers.pick_option)."""
    if not options or not str(value or "").strip():
        return None
    from .answers import pick_option   # answers imports agent, which imports browser_agent: not at load time
    return pick_option(value, options)


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
    """One element of the page, reached through the CDP session of the frame it lives in: from a browser-use
    node (`open()`), or from a JS object id already resolved in a session (find_by_label)."""

    def __init__(self, browser_session=None, node=None, *, send=None, session_id=None, object_id=None):
        self.browser_session, self.node = browser_session, node
        self.send, self.session_id, self.object_id = send, session_id, object_id

    async def open(self) -> "Field":
        if self.object_id:
            return self
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
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]
    return await fill_field(field, value)


async def fill_field(field: Field, value: str) -> tuple[bool, str]:
    """fill() for a Field already opened."""
    try:
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


# ── Finding a field by its label, and reading back what the form holds ──────────────────────────
# The fill agent names a field by an index from its last view of the page, which can be out of date (the page
# scrolled, or re-rendered) or made up. A question's label is what it reliably knows, so a field is also found
# by that: in the page and in any same-origin frame (a cross-origin frame's document can't be read from here).

_CONTROLS_JS = r"""
  const text = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {} }
  const labelOf = (e, doc) => {
    if (e.labels && e.labels.length) return text(e.labels[0]);
    const ids = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (ids.length) return ids.map(i => text(doc.getElementById(i))).join(' ');
    return e.getAttribute('aria-label') || '';
  };
  const groupOf = (e, doc) => {
    const type = e.type;
    const members = e.name ? [...doc.querySelectorAll('input[type=' + type + ']')].filter(m => m.name === e.name) : [e];
    if (members.length < 2) return null;
    const set = e.closest('fieldset');
    if (set && set.querySelector('legend')) return {label: text(set.querySelector('legend')), members};
    let box = e.parentElement;
    while (box && box.querySelectorAll('input[type=' + type + ']').length < members.length) box = box.parentElement;
    const head = box && box.querySelector('label:not(:has(input)), legend, [class*=label]');
    return {label: head ? text(head) : '', members};
  };
  const shown = el => { const s = el.ownerDocument.defaultView.getComputedStyle(el); const b = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && (b.width > 0 || b.height > 0); };
  // Never a password box: what's typed there must not leave the browser.
  const controls = 'input:not([type=hidden]):not([type=file]):not([type=submit]):not([type=button]):not([type=password]), select, textarea, [contenteditable=true]';
"""

_FIND_JS = "(wanted) => {" + _CONTROLS_JS + r"""
  const key = s => s.toLowerCase().replace(/\((required|optional)\)|\*/g, ' ').replace(/[^a-z0-9]+/g, ' ').trim();
  const w = key(wanted);
  if (!w) return null;
  const exact = [], close = [];
  for (const doc of docs) for (const el of doc.querySelectorAll(controls)) {
    if (el.closest('[aria-hidden=true]')) continue;
    const isBox = el.type === 'checkbox' || el.type === 'radio';
    const group = isBox ? groupOf(el, doc) : null;
    if (group && group.members[0] !== el) continue;
    const k = key(group ? group.label : labelOf(el, doc));
    if (!k) continue;
    if (k === w) exact.push(el);
    else if (Math.min(k.length, w.length) >= 12 && (k.includes(w) || w.includes(k))) close.push(el);
  }
  return exact.length === 1 ? exact[0] : (!exact.length && close.length === 1 ? close[0] : null);
}"""

# Every field that holds something, as {label, value}: what the user would read on the form.
_FILLED_JS = "() => {" + _CONTROLS_JS + r"""
  const out = [], seen = new Set();
  for (const doc of docs) for (const el of doc.querySelectorAll(controls)) {
    if (el.closest('[aria-hidden=true]') || el.disabled) continue;
    const box = el.closest('[class*=select__container]');
    if (box) {
      const picked = [...box.querySelectorAll('[class*=single-value], [class*=multi-value__label]')].map(text).filter(Boolean);
      if (picked.length) out.push({label: labelOf(el, doc), value: picked.join(', ')});
      continue;
    }
    if (!shown(el)) continue;
    if (el.type === 'checkbox' || el.type === 'radio') {
      const group = groupOf(el, doc);
      if (group) {
        if (seen.has(group.members[0])) continue;
        seen.add(group.members[0]);
        const on = group.members.filter(m => m.checked).map(m => labelOf(m, doc));
        if (on.length) out.push({label: group.label, value: on.join(', ')});
      } else if (el.checked) out.push({label: labelOf(el, doc), value: 'checked'});
      continue;
    }
    const value = el.tagName === 'SELECT' ? [...el.selectedOptions].map(text).join(', ')
                : el.isContentEditable ? el.innerText.trim() : String(el.value || '').trim();
    if (value && !(el.tagName === 'SELECT' && el.selectedIndex === 0 && !el.value)) out.push({label: labelOf(el, doc), value});
  }
  return JSON.stringify(out);
}"""


async def _tab(browser_session):
    cdp = await browser_session.get_or_create_cdp_session(focus=False)
    return cdp.cdp_client.send, cdp.session_id


async def find_by_label(browser_session, label: str) -> Field | None:
    """The one field on the page whose label is `label` (a checkbox group's first box), or None."""
    send, session_id = await _tab(browser_session)
    result = await send.Runtime.evaluate(
        params={"expression": f"({_FIND_JS})({json.dumps(str(label))})", "returnByValue": False},
        session_id=session_id)
    found = result.get("result") or {}
    if found.get("subtype") != "node" or not found.get("objectId"):
        return None
    return Field(send=send, session_id=session_id, object_id=found["objectId"])


async def filled_fields(browser_session) -> list[dict]:
    """[{label, value}] for every field on the page that holds something; [] if the page can't be read."""
    try:
        send, session_id = await _tab(browser_session)
        result = await send.Runtime.evaluate(params={"expression": f"({_FILLED_JS})()", "returnByValue": True},
                                             session_id=session_id)
        found = json.loads((result.get("result") or {}).get("value") or "[]")
    except Exception:
        return []
    return [{"label": str(f.get("label") or "")[:200], "value": str(f.get("value") or "")[:300]}
            for f in found if isinstance(f, dict)]
