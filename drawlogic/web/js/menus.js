// The toolbar's drop-down menus: a button, and a panel under it.
//
// Two kinds share this. A command menu (role="menu") is a list of buttons,
// walked with the arrow keys and closed by choosing one. The Sheet panel is a
// handful of form controls, so it stays open while they are changed and is
// walked with Tab like any other form. Both close on Esc, on a press outside
// them, and when another opens, and Esc hands focus back to the button so a
// keyboard user is left where they started.
//
// No popover attribute: Firefox before 125 does not have it.

export function bindMenus(root, { beforeOpen = () => {} } = {}) {
  let open = null;

  function items(menu) {
    return [...menu.panel.querySelectorAll('[role="menuitem"]')]
      .filter((item) => !item.disabled);
  }

  function close(menu, { focus = false } = {}) {
    if (!menu || open !== menu) return;
    menu.panel.hidden = true;
    menu.button.setAttribute("aria-expanded", "false");
    open = null;
    if (focus) menu.button.focus();
  }

  function show(menu, { focusFirst = false } = {}) {
    if (open && open !== menu) close(open);
    beforeOpen(menu.panel);
    menu.panel.hidden = false;
    menu.button.setAttribute("aria-expanded", "true");
    open = menu;
    if (focusFirst) {
      const first = menu.isList ? items(menu)[0]
        : menu.panel.querySelector("select, input, button");
      if (first) first.focus();
    }
  }

  const menus = [...root.querySelectorAll(".menu")].map((element) => {
    const button = element.querySelector(".menu-button");
    const panel = element.querySelector(".menu-panel");
    return { element, button, panel, isList: panel.getAttribute("role") === "menu" };
  });

  for (const menu of menus) {
    menu.button.addEventListener("click", () => {
      if (open === menu) close(menu);
      else show(menu);
    });
    // From the keyboard, opening also moves focus in, which a pointer click
    // should not: the keydown is cancelled so no click follows it.
    menu.button.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        show(menu, { focusFirst: true });
      }
    });

    menu.panel.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        // Stopped here so the canvas does not also take it as "deselect".
        event.preventDefault();
        event.stopPropagation();
        close(menu, { focus: true });
        return;
      }
      if (!menu.isList) return;
      const list = items(menu);
      const at = list.indexOf(document.activeElement);
      let next = null;
      if (event.key === "ArrowDown") next = list[(at + 1) % list.length];
      else if (event.key === "ArrowUp") next = list[(at - 1 + list.length) % list.length];
      else if (event.key === "Home") next = list[0];
      else if (event.key === "End") next = list[list.length - 1];
      else if (event.key === "Tab") close(menu);
      if (next) {
        event.preventDefault();
        next.focus();
      }
    });

    if (menu.isList) {
      // Choosing an item is the end of the menu. The item's own click
      // handler has already run by the time this one hears the click.
      menu.panel.addEventListener("click", (event) => {
        if (event.target.closest('[role="menuitem"]')) close(menu, { focus: true });
      });
    }
  }

  document.addEventListener("pointerdown", (event) => {
    if (open && !open.element.contains(event.target)) close(open);
  });
  // Focus leaving for somewhere else by Tab closes it too, so an open panel
  // is never left behind the thing now being typed into.
  document.addEventListener("focusin", (event) => {
    if (open && !open.element.contains(event.target)) close(open);
  });
}
