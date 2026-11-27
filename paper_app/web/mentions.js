"use strict";

(() => {
  const hub = document.getElementById("mention-inbox");
  if (hub && location.pathname === "/") {
    const message = document.getElementById("mention-inbox-status");
    const list = document.getElementById("mention-inbox-list");
    const button = document.getElementById("mention-refresh");
    async function refresh() {
      button.disabled = true;
      list.replaceChildren();
      message.textContent = "Loading mentions…";
      try {
        const {mentions} = await api("mentions");
        message.textContent = mentions.length ? "" : "No mentions yet.";
        for (const item of mentions) {
          const row = document.createElement("li");
          const link = document.createElement("a");
          link.href = item.url;
          link.textContent = item.title;
          const excerpt = document.createElement("p");
          excerpt.textContent = item.excerpt;
          const details = document.createElement("small");
          details.textContent = `${item.author || "Unknown author"} · ${item.updated} UTC`;
          row.append(link, details, excerpt);
          list.append(row);
        }
      } catch (error) {
        if (error.status === 401) {
          message.textContent = "";
          const link = document.createElement("a");
          link.href = "/account";
          link.textContent = "Sign in to see your mentions";
          message.append(link);
        } else message.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    }
    hub.hidden = false;
    button.addEventListener("click", refresh);
    refresh();
  }

  const picker = document.createElement("div");
  picker.className = "recipient-options mention-options";
  picker.id = "mention-options";
  picker.hidden = true;
  picker.setAttribute("role", "listbox");
  picker.setAttribute("aria-label", "Mention a user");
  let editor, cursor, query, entries = [], active = -1, timeout, sequence = 0;

  function close() {
    ++sequence;
    clearTimeout(timeout);
    picker.hidden = true;
    editor?.setAttribute("aria-expanded", "false");
    editor?.removeAttribute("aria-activedescendant");
    entries = [];
    active = -1;
  }

  function select(index) {
    const match = entries[index];
    if (!match || !editor) return;
    const field = editor;
    const start = cursor - query.length;
    const end = cursor + (field.value.slice(cursor).match(/^[A-Za-z0-9_.-]*/) || [""])[0].length;
    const separator = !field.value[end] || /[A-Za-z0-9_.-]/.test(field.value[end]) ? " " : "";
    field.setRangeText(match.username + separator, start, end, "end");
    close();
    field.focus();
  }

  document.addEventListener("input", event => {
    if (!event.target.matches?.("[data-mentions]")) return;
    close();
    const field = event.target;
    const end = field.selectionStart;
    const token = field.value.slice(0, end).match(/(?:^|[^A-Za-z0-9_.+@-])@([A-Za-z0-9][A-Za-z0-9_.-]{1,31})$/);
    if (!token || field.selectionEnd !== end) return;
    editor = field;
    editor.setAttribute("aria-autocomplete", "list");
    editor.setAttribute("aria-controls", picker.id);
    cursor = end;
    query = token[1];
    const request = sequence;
    const original = editor.value;
    timeout = setTimeout(async () => {
      try {
        const results = await api(`usernames?q=${encodeURIComponent(query)}`);
        if (request !== sequence || document.activeElement !== field ||
            field.value !== original || field.selectionStart !== end || !results.length) return;
        entries = results;
        picker.replaceChildren();
        for (const [index, match] of results.entries()) {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "secondary";
          option.tabIndex = -1;
          option.id = `mention-option-${index}`;
          option.setAttribute("role", "option");
          option.setAttribute("aria-selected", "false");
          option.textContent = match.display_name ? `@${match.username} · ${match.display_name}` : `@${match.username}`;
          option.addEventListener("mousedown", event => event.preventDefault());
          option.addEventListener("click", () => select(index));
          picker.append(option);
        }
        field.after(picker);
        picker.hidden = false;
        editor.setAttribute("aria-expanded", "true");
      } catch {
        if (request === sequence) close();
      }
    }, 150);
  });

  document.addEventListener("focusout", event => {
    if (event.target === editor && !picker.contains(event.relatedTarget)) close();
  });
  document.addEventListener("keydown", event => {
    if (event.target !== editor || picker.hidden) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      active = active < 0 ? (step === 1 ? 0 : entries.length - 1) : (active + step + entries.length) % entries.length;
      for (const [index, option] of Array.from(picker.children).entries()) {
        option.setAttribute("aria-selected", String(index === active));
      }
      editor.setAttribute("aria-activedescendant", picker.children[active].id);
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      select(active);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (["ArrowLeft", "ArrowRight", "Home", "End", "Tab"].includes(event.key)) {
      close();
    }
  });
})();
