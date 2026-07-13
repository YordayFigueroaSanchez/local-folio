// Utilidades genericas de UI reutilizables entre vistas: toasts, tablas,
// debounce y los modales genericos (formulario y advertencia de
// coherencia). Depende de la funcion global t() (definida por i18n.js,
// cargado como script clasico antes de este modulo).

export function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast ${isError ? "error" : "ok"}`;
  setTimeout(() => {
    el.className = "toast hidden";
  }, 3400);
}

export function renderTable(tableId, headers, rows, numericCols = []) {
  const table = document.getElementById(tableId);
  const head = `<thead><tr>${headers.map((h, i) => `<th${numericCols.includes(i) ? ' class="col-num"' : ''}>${h}</th>`).join("")}</tr></thead>`;
  const bodyRows = rows.length
    ? rows
        .map((row) => `<tr>${row.map((cell, i) => `<td${numericCols.includes(i) ? ' class="col-num"' : ''}>${cell}</td>`).join("")}</tr>`)
        .join("")
    : `<tr><td colspan="${headers.length}">${t("common.no_data")}</td></tr>`;
  const body = `<tbody>${bodyRows}</tbody>`;
  table.innerHTML = `${head}${body}`;
}

export function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

export function showCoherenceWarningModal(errorMessage) {
  return new Promise((resolve) => {
    const existingModal = document.getElementById('coherence-warning-modal');
    if (existingModal) {
      existingModal.remove();
    }

    const modal = document.createElement('div');
    modal.id = 'coherence-warning-modal';
    modal.className = 'modal-overlay';

    const content = document.createElement('div');
    content.className = 'modal-card modal-card-warning';

    const title = document.createElement('h3');
    title.className = 'modal-title modal-title-warning';
    title.textContent = t("coherence.title");

    const errorParagraph = document.createElement("p");
    errorParagraph.className = "modal-message";
    errorParagraph.textContent = errorMessage;

    const hintParagraph = document.createElement("p");
    hintParagraph.className = "modal-hint";
    hintParagraph.textContent = t("coherence.hint");

    const actions = document.createElement('div');
    actions.className = 'modal-actions';

    const noButton = document.createElement('button');
    noButton.id = 'modal-no';
    noButton.type = 'button';
    noButton.className = 'modal-btn modal-btn-secondary';
    noButton.textContent = 'NO';

    const yesButton = document.createElement('button');
    yesButton.id = 'modal-yes';
    yesButton.type = 'button';
    yesButton.className = 'modal-btn modal-btn-primary';
    yesButton.textContent = 'SI';

    actions.appendChild(noButton);
    actions.appendChild(yesButton);
    content.appendChild(title);
    content.appendChild(errorParagraph);
    content.appendChild(hintParagraph);
    content.appendChild(actions);

    modal.appendChild(content);
    document.body.appendChild(modal);

    document.getElementById('modal-yes').onclick = () => {
      modal.remove();
      resolve(true);
    };

    document.getElementById('modal-no').onclick = () => {
      modal.remove();
      resolve(false);
    };
  });
}

export function showFormModal({ title, message = "", fields, confirmText = "Confirmar", cancelText = "Cancelar", danger = false, onFieldChange = null, defaultLock = null }) {
  return new Promise((resolve) => {
    const existingModal = document.getElementById("generic-form-modal");
    if (existingModal) {
      existingModal.remove();
    }

    const modal = document.createElement("div");
    modal.id = "generic-form-modal";
    modal.className = "modal-overlay";

    const content = document.createElement("div");
    content.className = "modal-card";

    const escapeHtml = (value) => String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    const escapeAttr = (value) => String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    const lockableFieldNames = fields.filter((f) => f.lockable).map((f) => f.name);
    let lockedField = defaultLock || lockableFieldNames[0] || null;

    const controlsHtml = fields
      .map((field) => {
        if (field.type === "select") {
          const optionsHtml = (field.options || [])
            .map((opt) => `<option value="${escapeAttr(opt.value)}"${String(opt.value) === String(field.value) ? " selected" : ""}>${escapeHtml(opt.label)}</option>`)
            .join("");
          return `
            <label class="modal-field">
              <span>${escapeHtml(field.label)}</span>
              <select class="modal-input" id="modal-field-${field.name}">
                ${optionsHtml}
              </select>
            </label>
          `;
        }

        if (field.lockable) {
          const isLocked = lockedField === field.name;
          return `
            <label class="modal-field">
              <span>${escapeHtml(field.label)}</span>
              <div class="modal-input-lockwrap">
                <input
                  class="modal-input"
                  id="modal-field-${field.name}"
                  type="${field.type || "text"}"
                  value="${escapeAttr(field.value)}"
                  placeholder="${escapeAttr(field.placeholder)}"
                  step="${field.step || ""}"
                  min="${field.min ?? ""}"
                />
                <button type="button" class="modal-lock-btn${isLocked ? " is-locked" : ""}" data-lock-field="${escapeAttr(field.name)}" title="${isLocked ? "Campo fijo" : "Fijar este campo"}">${isLocked ? "&#128274;" : "&#128275;"}</button>
              </div>
            </label>
          `;
        }

        return `
          <label class="modal-field">
            <span>${escapeHtml(field.label)}</span>
            <input
              class="modal-input"
              id="modal-field-${field.name}"
              type="${field.type || "text"}"
              value="${escapeAttr(field.value)}"
              placeholder="${escapeAttr(field.placeholder)}"
              step="${field.step || ""}"
              min="${field.min ?? ""}"
            />
          </label>
        `;
      })
      .join("");

    content.innerHTML = `
      <h3 class="modal-title">${escapeHtml(title)}</h3>
      ${message ? `<p class="modal-message">${escapeHtml(message)}</p>` : ""}
      <div class="modal-fields">${controlsHtml}</div>
      <div class="modal-actions">
        <button id="modal-cancel" class="modal-btn modal-btn-secondary" type="button">
          ${cancelText}
        </button>
        <button id="modal-confirm" class="modal-btn ${danger ? "modal-btn-danger" : "modal-btn-primary"}" type="button">
          ${confirmText}
        </button>
      </div>
    `;

    modal.appendChild(content);
    document.body.appendChild(modal);

    // Reactive field change support
    if (onFieldChange) {
      const setValue = (name, val) => {
        const el = document.getElementById(`modal-field-${name}`);
        if (el) el.value = val;
      };
      const getValues = () => {
        const vals = {};
        fields.forEach((f) => {
          const el = document.getElementById(`modal-field-${f.name}`);
          vals[f.name] = el ? el.value : "";
        });
        return vals;
      };
      fields.forEach((field) => {
        const el = document.getElementById(`modal-field-${field.name}`);
        if (el) {
          el.addEventListener("input", () => {
            onFieldChange(field.name, getValues(), setValue, lockedField);
          });
        }
      });
    }

    // Lock button click handlers
    content.querySelectorAll(".modal-lock-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        lockedField = btn.dataset.lockField;
        content.querySelectorAll(".modal-lock-btn").forEach((b) => {
          const isNowLocked = b.dataset.lockField === lockedField;
          b.classList.toggle("is-locked", isNowLocked);
          b.innerHTML = isNowLocked ? "&#128274;" : "&#128275;";
          b.title = isNowLocked ? "Campo fijo" : "Fijar este campo";
        });
      });
    });

    const cleanup = () => modal.remove();

    document.getElementById("modal-cancel").onclick = () => {
      cleanup();
      resolve({ confirmed: false, values: {} });
    };

    document.getElementById("modal-confirm").onclick = () => {
      const values = {};
      fields.forEach((field) => {
        const input = document.getElementById(`modal-field-${field.name}`);
        values[field.name] = input ? input.value : "";
      });
      cleanup();
      resolve({ confirmed: true, values });
    };
  });
}
