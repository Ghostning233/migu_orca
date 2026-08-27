(function () {
  const form = document.getElementById("request-generate-form");
  const titleInput = document.getElementById("request-title");
  const formError = document.getElementById("request-form-error");
  const submitButton = document.getElementById("request-generate-submit");
  const refreshButton = document.getElementById("request-list-refresh");
  const listSearchInput = document.getElementById("request-list-search");
  const listStatusFilter = document.getElementById("request-list-status-filter");
  const listSortSelect = document.getElementById("request-list-sort");
  const listCount = document.getElementById("request-list-count");
  const listContainer = document.getElementById("request-list-container");
  const detailContainer = document.getElementById("request-detail-container");
  const notification = document.getElementById("page-notification");
  const storageSummaryText = document.getElementById("storage-preference-summary-text");
  const storagePreferencesForm = document.getElementById("storage-preferences-form");
  const settingsStorageInput = document.getElementById("settings-storage-dir");
  const settingsSaveInput = document.getElementById("settings-save-request");
  const storagePreferencesStatus = document.getElementById("storage-preferences-status");
  const clearPreferencesButton = document.getElementById("storage-preferences-clear");
  const qbittorrentForm = document.getElementById("settings-qbittorrent-test-form");
  const qbittorrentEndpointInput = document.getElementById("settings-qbittorrent-endpoint");
  const qbittorrentUsernameInput = document.getElementById("settings-qbittorrent-username");
  const qbittorrentPasswordInput = document.getElementById("settings-qbittorrent-password");
  const qbittorrentTimeoutInput = document.getElementById("settings-qbittorrent-timeout-seconds");
  const qbittorrentVerifyTlsInput = document.getElementById("settings-qbittorrent-verify-tls");
  const qbittorrentFormError = document.getElementById("settings-qbittorrent-error");
  const qbittorrentResult = document.getElementById("settings-qbittorrent-result");
  const qbittorrentSubmitButton = document.getElementById("settings-qbittorrent-test-submit");
  const settingsAbContext = document.getElementById("settings-ab-context");
  const settingsAbForm = document.getElementById("settings-ab-submit-form");
  const settingsAbRequestId = document.getElementById("settings-ab-request-id");
  const settingsAbAuthModeInput = document.getElementById("settings-ab-auth-mode");
  const settingsAbBaseUrlInput = document.getElementById("settings-ab-endpoint");
  const settingsAbUsernameInput = document.getElementById("settings-ab-username");
  const settingsAbPasswordInput = document.getElementById("settings-ab-password");
  const settingsAbTokenInput = document.getElementById("settings-ab-token");
  const settingsAbFallbackInput = document.getElementById("settings-ab-fallback-enabled");
  const settingsAbTestButton = document.getElementById("settings-ab-test-submit");
  const settingsAbFormError = document.getElementById("settings-ab-error");
  const settingsAbResult = document.getElementById("settings-ab-result");
  const settingsAbSubmitButton = document.getElementById("settings-ab-submit");
  const settingsAbReturnLink = document.getElementById("settings-ab-return-link");
  const preferenceSettingsForm = document.getElementById("preference-settings-form");
  const preferencePreferredInput = document.getElementById("preference-preferred-groups");
  const preferenceExcludedInput = document.getElementById("preference-excluded-groups");
  const preferenceFallbackSelect = document.getElementById("preference-fallback");
  const preferenceFilterContainInput = document.getElementById("preference-filter-must-contain");
  const preferenceFilterNotContainInput = document.getElementById("preference-filter-must-not-contain");
  const preferenceFilterUseRegexInput = document.getElementById("preference-filter-use-regex");
  const preferenceFilterCaseSensitiveInput = document.getElementById("preference-filter-case-sensitive");
  const preferenceNamingStrategySelect = document.getElementById("preference-naming-strategy");
  const preferenceNamingTemplateInput = document.getElementById("preference-naming-template");
  const preferenceSearchReuseInput = document.getElementById("preference-search-reuse-corrections");
  const preferenceSettingsError = document.getElementById("preference-settings-error");
  const preferenceSettingsStatus = document.getElementById("preference-settings-status");
  const preferenceSettingsSaveButton = document.getElementById("preference-settings-save");
  const preferenceSettingsResetButton = document.getElementById("preference-settings-reset");
  const candidateSearchForm = document.getElementById("mikan-candidate-search-form");
  const candidateQueryInput = document.getElementById("mikan-candidate-query");
  const candidateSearchError = document.getElementById("mikan-candidate-search-error");
  const candidateSearchResult = document.getElementById("mikan-candidate-search-result");
  const candidateSearchSubmit = document.getElementById("mikan-candidate-search-submit");
  const candidateFallbackForm = document.getElementById("mikan-fallback-form");
  const candidateFallbackEnabled = document.getElementById("mikan-fallback-enabled");
  const candidateFallbackInput = document.getElementById("mikan-fallback-bangumi");
  const candidateFallbackError = document.getElementById("mikan-fallback-error");
  const candidateFallbackGenerate = document.getElementById("mikan-fallback-generate");
  const searchModeTabs = document.getElementById("search-mode-tabs");
  const singleSearchEntry = document.getElementById("single-search-entry");
  const batchSearchEntry = document.getElementById("batch-workbench-entry");
  const batchSearchResults = document.getElementById("batch-search-results");
  const batchParseForm = document.getElementById("batch-parse-form");
  const batchRawInput = document.getElementById("batch-raw-input");
  const batchParseError = document.getElementById("batch-parse-error");
  const batchParseResult = document.getElementById("batch-parse-result");
  const batchParseSubmit = document.getElementById("batch-parse-submit");
  const batchAcceptToolbar = document.getElementById("batch-accept-toolbar");
  const batchSelectAllCheckbox = document.getElementById("batch-select-all-checkbox");
  const batchAcceptSelectedCount = document.getElementById("batch-accept-selected-count");
  const batchAcceptSubmit = document.getElementById("batch-accept-submit");
  const batchAcceptAll = document.getElementById("batch-accept-all");
  const batchQueueRefresh = document.getElementById("batch-queue-refresh");
  const batchQueueCount = document.getElementById("batch-queue-count");
  const batchQueueList = document.getElementById("batch-queue-list");
  const batchQueueSubmitForm = document.getElementById("batch-queue-submit-form");
  const batchQueueAbAuthModeInput = document.getElementById("batch-queue-ab-auth-mode");
  const batchQueueAbBaseUrlInput = document.getElementById("batch-queue-ab-endpoint");
  const batchQueueAbUsernameInput = document.getElementById("batch-queue-ab-username");
  const batchQueueAbPasswordInput = document.getElementById("batch-queue-ab-password");
  const batchQueueAbTokenInput = document.getElementById("batch-queue-ab-token");
  const batchQueueAbFallbackInput = document.getElementById("batch-queue-ab-fallback-enabled");
  const batchQueueAbConfirmInput = document.getElementById("batch-queue-ab-confirm");
  const batchQueueAbError = document.getElementById("batch-queue-ab-error");
  const batchQueueSubmitResult = document.getElementById("batch-queue-submit-result");
  const batchQueueSubmitButton = document.getElementById("batch-queue-submit-button");
  const preferenceKeys = {
    storageDir: "miguOrca.web.storageDir",
    saveRequest: "miguOrca.web.saveRequest",
  };

  let selectedRequestId = null;
  let loadedRequests = [];
  let currentDetailPayload = null;
  let currentBatchEditItemId = null;
  // A batch card may borrow the shared detail panel, but it never owns a
  // second detail panel inside the card itself.
  let currentBatchDetailItemId = null;
  let batchDraftCards = [];
  let currentBatchId = null;
  // Candidate choices are a single anchored dialog, rather than card content.
  // Keeping the active item separately prevents cards from growing with every
  // candidate and makes switching between rows deterministic.
  let activeBatchCandidateItemId = null;
  let selectedBatchItemIds = new Set();
  let batchAcceptInFlight = false;
  let batchQueueItems = [];
  let storageDirPreference = "";
  let saveRequestPreference = true;
  let currentPreferenceValues = null;
  let activeSearchMode = "single";
  let searchWorkspaceDisabledStates = new Map();

  function searchModeButtons() {
    return searchModeTabs
      ? Array.from(searchModeTabs.querySelectorAll("[data-search-mode]"))
      : [];
  }

  function setSearchMode(mode, focusTab) {
    const nextMode = mode === "batch" ? "batch" : "single";
    if (nextMode !== "batch") {
      closeBatchCandidatePopover({focusTrigger: false});
      clearBatchDetailContext();
    }
    activeSearchMode = nextMode;
    const isBatch = nextMode === "batch";
    if (singleSearchEntry) {
      singleSearchEntry.hidden = isBatch;
    }
    if (batchSearchEntry) {
      batchSearchEntry.hidden = !isBatch;
    }
    if (candidateSearchResult) {
      candidateSearchResult.hidden = isBatch;
    }
    if (batchSearchResults) {
      batchSearchResults.hidden = !isBatch;
    }
    for (const button of searchModeButtons()) {
      const selected = button.dataset.searchMode === nextMode;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (selected && focusTab) {
        button.focus();
      }
    }
  }

  function wireSearchModeTabs() {
    const buttons = searchModeButtons();
    for (const button of buttons) {
      button.addEventListener("click", function () {
        setSearchMode(button.dataset.searchMode, false);
      });
      button.addEventListener("keydown", function (event) {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          return;
        }
        event.preventDefault();
        const currentIndex = buttons.indexOf(button);
        const nextIndex = event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? buttons.length - 1
            : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
        const nextButton = buttons[nextIndex];
        setSearchMode(nextButton.dataset.searchMode, true);
      });
    }
    setSearchMode(activeSearchMode, false);
  }

  function setSearchWorkspaceInFlight(isInFlight) {
    const controls = [];
    for (const container of [
      document.getElementById("generate-panel"),
      document.getElementById("search-results-panel"),
    ]) {
      if (!container) {
        continue;
      }
      for (const control of container.querySelectorAll("button, input, textarea, select")) {
        controls.push(control);
      }
    }
    for (const control of controls) {
      if (isInFlight) {
        searchWorkspaceDisabledStates.set(control, control.disabled);
        control.disabled = true;
      } else if (searchWorkspaceDisabledStates.has(control)) {
        control.disabled = searchWorkspaceDisabledStates.get(control);
      }
    }
    if (!isInFlight) {
      searchWorkspaceDisabledStates = new Map();
    }
  }

  function readPreference(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function writePreference(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      return;
    }
  }

  function removePreference(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      return;
    }
  }

  function restoreWebPreferences() {
    const savedStorageDir = readPreference(preferenceKeys.storageDir);
    const savedSaveRequest = readPreference(preferenceKeys.saveRequest);
    storageDirPreference = savedStorageDir || "";
    saveRequestPreference =
      savedSaveRequest === null ? true : savedSaveRequest === "true";
    if (settingsStorageInput) {
      settingsStorageInput.value = storageDirPreference;
    }
    if (settingsSaveInput) {
      settingsSaveInput.checked = saveRequestPreference;
    }
    updateStoragePreferenceSummary();
    updateStoragePreferencesStatus("已读取浏览器偏好。", "empty-state compact-state");
  }

  function updateStoragePreferenceSummary() {
    if (!storageSummaryText) {
      return;
    }
    const storageText = storageDirPreference
      ? "自定义 storage_dir：" + storageDirPreference
      : "默认 `.migu_orca/storage`";
    const saveText = saveRequestPreference
      ? "默认保存订阅方案 JSON"
      : "默认只生成预览";
    storageSummaryText.textContent =
      "当前使用" + storageText + "；" + saveText + "。可在 Settings 修改。";
  }

  function updateStoragePreferencesStatus(message, className) {
    if (!storagePreferencesStatus) {
      return;
    }
    storagePreferencesStatus.className = className || "empty-state compact-state";
    storagePreferencesStatus.textContent = message;
  }

  function currentStorageDir() {
    return storageDirPreference.trim();
  }

  function currentSaveRequest() {
    return saveRequestPreference;
  }

  function readSettingsFormPreferences() {
    return {
      storageDir: settingsStorageInput ? settingsStorageInput.value.trim() : "",
      saveRequest: settingsSaveInput ? settingsSaveInput.checked : false,
    };
  }

  function applyPreferenceValues(storageDir, saveRequest) {
    storageDirPreference = storageDir || "";
    saveRequestPreference = Boolean(saveRequest);
    if (settingsStorageInput) {
      settingsStorageInput.value = storageDirPreference;
    }
    if (settingsSaveInput) {
      settingsSaveInput.checked = saveRequestPreference;
    }
    updateStoragePreferenceSummary();
  }

  function persistWebPreferences(event) {
    if (event && event.preventDefault) {
      event.preventDefault();
    }
    const preferences = readSettingsFormPreferences();
    applyPreferenceValues(preferences.storageDir, preferences.saveRequest);
    if (storageDirPreference) {
      writePreference(preferenceKeys.storageDir, storageDirPreference);
    } else {
      removePreference(preferenceKeys.storageDir);
    }
    writePreference(preferenceKeys.saveRequest, String(saveRequestPreference));
    updateStoragePreferencesStatus("偏好已保存。", "success-state compact-state");
  }

  function clearWebPreferences() {
    removePreference(preferenceKeys.storageDir);
    removePreference(preferenceKeys.saveRequest);
    applyPreferenceValues("", true);
    updateStoragePreferencesStatus(
      "偏好已清除；订阅方案工作台将使用默认 `.migu_orca/storage` 并保存订阅方案 JSON。",
      "empty-state compact-state",
    );
  }

  function storageQuery() {
    const storageDir = currentStorageDir();
    if (!storageDir) {
      return "";
    }
    return "?storage_dir=" + encodeURIComponent(storageDir);
  }

  function apiPath(path) {
    return path + storageQuery();
  }

  function requestIdFromLocation() {
    const params = new URLSearchParams(window.location.search);
    return (params.get("request_id") || "").trim();
  }

  function syncRequestIdToUrl(requestId, options) {
    if (!window.history || !window.history.pushState) {
      return;
    }
    const url = new URL(window.location.href);
    if (requestId) {
      url.searchParams.set("request_id", requestId);
    } else {
      url.searchParams.delete("request_id");
    }
    if (url.href === window.location.href) {
      return;
    }
    const method = options && options.replace ? "replaceState" : "pushState";
    window.history[method]({request_id: requestId || null}, "", url);
  }

  if (form || storagePreferencesForm) {
    restoreWebPreferences();
  }

  if (storagePreferencesForm) {
    storagePreferencesForm.addEventListener("submit", persistWebPreferences);
  }
  if (clearPreferencesButton) {
    clearPreferencesButton.addEventListener("click", clearWebPreferences);
  }

  function safeText(value) {
    return displayValue(value);
  }

  function summarizeValidationErrors(errorData) {
    const errors = errorData && Array.isArray(errorData.errors) ? errorData.errors : [];
    if (!errors.length) {
      return "";
    }
    return errors
      .map((error) => {
        const field = safeText(error.field || "_schema");
        const message = safeText(error.message || "校验失败");
        return field + ": " + message;
      })
      .join("；");
  }

  function hideNotification() {
    if (!notification) {
      return;
    }
    notification.hidden = true;
    notification.replaceChildren();
    notification.className = "page-notification";
    notification.setAttribute("role", "status");
  }

  function showNotification(kind, title, message, options) {
    if (!notification) {
      return;
    }
    notification.replaceChildren();
    notification.hidden = false;
    notification.className = "page-notification notification-" + kind;
    notification.setAttribute("role", kind === "error" ? "alert" : "status");

    const copy = document.createElement("div");
    copy.className = "notification-copy";
    const heading = document.createElement("strong");
    heading.textContent = title;
    const body = document.createElement("p");
    body.textContent = safeText(message);
    copy.append(heading, body);

    if (options && options.detail) {
      const detail = document.createElement("p");
      detail.className = "notification-detail";
      detail.textContent = safeText(options.detail);
      copy.appendChild(detail);
    }

    const actions = document.createElement("div");
    actions.className = "notification-actions";
    if (options && Array.isArray(options.actions)) {
      for (const action of options.actions) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = action.className || "secondary-button";
        button.textContent = action.label;
        button.addEventListener("click", action.handler);
        actions.appendChild(button);
      }
    }

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "secondary-button notification-close";
    closeButton.textContent = "关闭";
    closeButton.addEventListener("click", hideNotification);
    actions.appendChild(closeButton);

    notification.append(copy, actions);
  }

  function notifyApiError(title, error) {
    const validationSummary = summarizeValidationErrors(error.errorData);
    showNotification("error", title, error.message || "请求失败", {
      detail: validationSummary,
    });
  }

  function setState(container, message, className) {
    container.className = className || "empty-state";
    container.textContent = message;
  }

  function setFormError(message, field) {
    formError.textContent = message;
    formError.hidden = false;
    const invalidField = field || titleInput;
    invalidField.setAttribute("aria-invalid", "true");
  }

  function clearFormError() {
    formError.textContent = "";
    formError.hidden = true;
    titleInput.removeAttribute("aria-invalid");
  }

  function setSubmitInFlight(isInFlight) {
    submitButton.disabled = isInFlight;
    submitButton.textContent = isInFlight
      ? "正在生成..."
      : submitButton.dataset.defaultLabel || "生成";
  }

  function fieldValue(value) {
    if (value === null || value === undefined || value === "") {
      return "未设置";
    }
    if (Array.isArray(value)) {
      return value.length ? value.join("，") : "无";
    }
    return String(value);
  }

  function displayValue(value) {
    const text = fieldValue(value);
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) {
      return "[redacted_url]";
    }
    return text;
  }

  // User-facing Chinese label for a Request status code. Internal/API values
  // keep their stable English codes; only what is rendered to users is mapped.
  function statusLabel(status) {
    const labels = {
      PENDING_CONFIRM: "待确认",
      ACCEPTED: "已确认",
      CANCELLED: "已取消",
    };
    const value = fieldValue(status);
    return Object.prototype.hasOwnProperty.call(labels, value)
      ? labels[value]
      : value;
  }

  function actionLabel(action) {
    const labels = {
      ACCEPT: "确认",
      CANCEL: "取消",
      MODIFY: "修改",
    };
    const value = fieldValue(action);
    return Object.prototype.hasOwnProperty.call(labels, value)
      ? labels[value]
      : value;
  }

  function scrubConfig(value) {
    if (Array.isArray(value)) {
      return value.map(scrubConfig);
    }
    if (value && typeof value === "object") {
      const clean = {};
      const blockedKey = new RegExp(
        "to" + "ken|secret|password|authorization|cookie|sid|session|api[_-]?key|url|endpoint",
        "i",
      );
      for (const [key, child] of Object.entries(value)) {
        clean[key] = blockedKey.test(key) ? "[redacted]" : scrubConfig(child);
      }
      return clean;
    }
    if (typeof value === "string" && /^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
      return "[redacted_url]";
    }
    return value;
  }

  async function fetchJson(path, options) {
    const response = await fetch(path, options);
    const payload = await response.json();
    if (!payload.ok) {
      const error = new Error(payload.error_message || "请求失败");
      error.errorType = payload.error_type || "request_error";
      error.errorData = payload.error_data || null;
      throw error;
    }
    return payload.result;
  }

  function setQbittorrentFormError(message, field) {
    if (!qbittorrentFormError) {
      return;
    }
    qbittorrentFormError.textContent = message;
    qbittorrentFormError.hidden = false;
    for (const input of [
      qbittorrentEndpointInput,
      qbittorrentUsernameInput,
      qbittorrentPasswordInput,
      qbittorrentTimeoutInput,
    ]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
    if (field) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  function clearQbittorrentFormError() {
    if (!qbittorrentFormError) {
      return;
    }
    qbittorrentFormError.textContent = "";
    qbittorrentFormError.hidden = true;
    for (const input of [
      qbittorrentEndpointInput,
      qbittorrentUsernameInput,
      qbittorrentPasswordInput,
      qbittorrentTimeoutInput,
    ]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
  }

  function setQbittorrentResult(message, className) {
    if (!qbittorrentResult) {
      return;
    }
    qbittorrentResult.className = className || "empty-state compact-state";
    qbittorrentResult.textContent = message;
  }

  function setQbittorrentInFlight(isInFlight) {
    if (!qbittorrentForm) {
      return;
    }
    const controls = qbittorrentForm.querySelectorAll("button, input");
    for (const control of controls) {
      control.disabled = isInFlight;
    }
    if (qbittorrentSubmitButton) {
      qbittorrentSubmitButton.textContent = isInFlight ? "正在测试..." : "测试 qBittorrent 连接";
    }
  }

  function clearQbittorrentSensitiveFields() {
    if (qbittorrentEndpointInput) {
      qbittorrentEndpointInput.value = "";
    }
    if (qbittorrentUsernameInput) {
      qbittorrentUsernameInput.value = "";
    }
    if (qbittorrentPasswordInput) {
      qbittorrentPasswordInput.value = "";
    }
  }

  function buildQbittorrentConnectionPayload() {
    const endpoint = qbittorrentEndpointInput ? qbittorrentEndpointInput.value.trim() : "";
    const username = qbittorrentUsernameInput ? qbittorrentUsernameInput.value.trim() : "";
    const password = qbittorrentPasswordInput ? qbittorrentPasswordInput.value.trim() : "";
    const timeoutText = qbittorrentTimeoutInput ? qbittorrentTimeoutInput.value.trim() : "";
    const timeoutSeconds = Number(timeoutText);
    if (!endpoint) {
      const error = new Error("测试 qBittorrent 前必须填写 endpoint。");
      error.field = qbittorrentEndpointInput;
      throw error;
    }
    if (!username) {
      const error = new Error("测试 qBittorrent 前必须填写 username。");
      error.field = qbittorrentUsernameInput;
      throw error;
    }
    if (!password) {
      const error = new Error("测试 qBittorrent 前必须填写 password。");
      error.field = qbittorrentPasswordInput;
      throw error;
    }
    if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) {
      const error = new Error("测试 qBittorrent 前 timeout_seconds 必须为正数。");
      error.field = qbittorrentTimeoutInput;
      throw error;
    }
    return {
      qbittorrent_config: {
        endpoint: endpoint,
        username: username,
        password: password,
        timeout_seconds: timeoutSeconds,
        verify_tls: qbittorrentVerifyTlsInput ? qbittorrentVerifyTlsInput.checked : true,
      },
    };
  }

  function renderQbittorrentResult(summary) {
    const status = safeText(summary && summary.status);
    const reachable = safeText(summary && summary.reachable);
    const version = safeText(summary && summary.version);
    setQbittorrentResult(
      "status: " + status + "；reachable: " + reachable + "；version: " + version,
      "qbittorrent-result qbittorrent-result-success success-state compact-state",
    );
  }

  async function testQbittorrentConnection(event) {
    event.preventDefault();
    clearQbittorrentFormError();
    let payload;
    try {
      payload = buildQbittorrentConnectionPayload();
    } catch (validationError) {
      setQbittorrentFormError(validationError.message, validationError.field);
      setQbittorrentResult("请修正 qBittorrent 表单后再测试。", "error-state compact-state");
      return;
    }
    if (!window.confirm("确认使用当前 qBittorrent 配置测试连接？")) {
      return;
    }

    setQbittorrentInFlight(true);
    setQbittorrentResult("正在测试 qBittorrent 连接...", "loading-state compact-state");
    try {
      const result = await fetchJson("/api/v1/qbittorrent/test-connection", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      renderQbittorrentResult(result);
      clearQbittorrentSensitiveFields();
    } catch (error) {
      setQbittorrentResult(
        "qBittorrent 连接测试失败。请检查配置后重试。",
        "error-state compact-state",
      );
    } finally {
      setQbittorrentInFlight(false);
    }
  }

  if (qbittorrentForm) {
    qbittorrentForm.addEventListener("submit", testQbittorrentConnection);
  }

  function settingsAbRequestIdFromLocation() {
    return requestIdFromLocation();
  }

  function abInputs(prefix) {
    return {
      mode: document.getElementById(prefix + "-auth-mode"),
      baseUrl: document.getElementById(prefix + "-base-url") || document.getElementById(prefix + "-endpoint"),
      username: document.getElementById(prefix + "-username"),
      password: document.getElementById(prefix + "-password"),
      token: document.getElementById(prefix + "-token"),
      passwordFields: document.getElementById(prefix + "-password-fields"),
      tokenFields: document.getElementById(prefix + "-token-fields"),
    };
  }

  function syncAbAuthMode(prefix) {
    const inputs = abInputs(prefix);
    const tokenMode = inputs.mode && inputs.mode.value === "api_token";
    if (inputs.passwordFields) inputs.passwordFields.hidden = tokenMode;
    if (inputs.tokenFields) inputs.tokenFields.hidden = !tokenMode;
  }

  function buildAbConfig(prefix) {
    const inputs = abInputs(prefix);
    const authMode = inputs.mode ? inputs.mode.value : "password";
    const baseUrl = inputs.baseUrl ? inputs.baseUrl.value.trim() : "";
    const fallbackInput = document.getElementById(prefix + "-fallback-enabled");
    const fallbackEnabled = fallbackInput ? fallbackInput.checked : false;
    if (!baseUrl) throw {message: "请填写服务地址。", field: inputs.baseUrl};
    if (authMode === "password") {
      const username = inputs.username ? inputs.username.value.trim() : "";
      const password = inputs.password ? inputs.password.value : "";
      if (!username) throw {message: "请填写用户名。", field: inputs.username};
      if (!password) throw {message: "请填写密码。", field: inputs.password};
      return {auth_mode: "password", base_url: baseUrl, username: username, password: password, fallback_enabled: fallbackEnabled};
    }
    const token = inputs.token ? inputs.token.value.trim() : "";
    if (!token) throw {message: "请填写 API Token。", field: inputs.token};
    return {auth_mode: "api_token", base_url: baseUrl, token: token, fallback_enabled: fallbackEnabled};
  }

  function clearAbSensitiveFields(prefix, clearConfirm) {
    const inputs = abInputs(prefix);
    for (const input of [inputs.baseUrl, inputs.username, inputs.password, inputs.token]) {
      if (input) input.value = "";
    }
    if (clearConfirm) clearConfirm.checked = false;
  }

  function setSettingsAbError(message, field) {
    if (!settingsAbFormError) {
      return;
    }
    settingsAbFormError.textContent = message;
    settingsAbFormError.hidden = false;
    for (const input of [settingsAbBaseUrlInput, settingsAbUsernameInput, settingsAbPasswordInput, settingsAbTokenInput]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
    if (field) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  function clearSettingsAbError() {
    if (!settingsAbFormError) {
      return;
    }
    settingsAbFormError.textContent = "";
    settingsAbFormError.hidden = true;
    for (const input of [settingsAbBaseUrlInput, settingsAbUsernameInput, settingsAbPasswordInput, settingsAbTokenInput]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
  }

  function setSettingsAbResult(message, className) {
    if (!settingsAbResult) {
      return;
    }
    settingsAbResult.className = className || "empty-state compact-state";
    settingsAbResult.textContent = message;
  }

  function setSettingsAbInFlight(isInFlight) {
    if (!settingsAbForm) {
      return;
    }
    const controls = settingsAbForm.querySelectorAll("button, input");
    for (const control of controls) {
      control.disabled = isInFlight;
    }
    if (settingsAbSubmitButton) {
      settingsAbSubmitButton.textContent = isInFlight
        ? "正在提交..."
        : "提交 Auto Bangumi";
    }
  }

  function clearSettingsAbSensitiveFields() {
    clearAbSensitiveFields("settings-ab");
  }

  function initializeSettingsAbForm() {
    if (!settingsAbForm) {
      return;
    }
    const requestId = settingsAbRequestIdFromLocation();
    if (!requestId) {
      const submitButton = settingsAbSubmitButton;
      if (submitButton) submitButton.hidden = true;
      const requestContext = document.getElementById("settings-ab-request-context");
      if (requestContext) requestContext.hidden = true;
      if (settingsAbContext) {
        settingsAbContext.textContent =
          "可使用当前服务地址和认证信息测试连接；从已确认订阅方案详情进入后可提交。";
      }
      return;
    }
    if (settingsAbSubmitButton) settingsAbSubmitButton.hidden = false;
    const requestContext = document.getElementById("settings-ab-request-context");
    if (requestContext) requestContext.hidden = false;
    if (settingsAbRequestId) {
      settingsAbRequestId.textContent = requestId;
    }
    if (settingsAbContext) {
      settingsAbContext.textContent =
        "已选择订阅方案 " + requestId + "；请确认该订阅方案已确认后再提交。";
    }
    if (settingsAbReturnLink) {
      settingsAbReturnLink.href = "/index?request_id=" + encodeURIComponent(requestId);
    }
  }

  async function submitSettingsAb(event) {
    event.preventDefault();
    clearSettingsAbError();
    const requestId = settingsAbRequestIdFromLocation();
    if (!requestId) {
      setSettingsAbError("缺少 request_id，无法提交 Auto Bangumi。");
      return;
    }
    let abConfig;
    try {
      abConfig = buildAbConfig("settings-ab");
    } catch (validationError) {
      setSettingsAbError(validationError.message, validationError.field);
      return;
    }
    if (!window.confirm("确认提交此订阅方案到 Auto Bangumi？")) {
      return;
    }

    setSettingsAbInFlight(true);
    setSettingsAbResult("正在提交 Auto Bangumi...", "loading-state compact-state");
    try {
      const result = await fetchJson(
        apiPath("/api/v1/requests/" + encodeURIComponent(requestId) + "/submit-ab"),
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            storage_dir: currentStorageDir() || null,
            ab_config: abConfig,
          }),
        },
      );
      const summary = result && result.ab_submit_result;
      const subscriptionId = summary && summary.ab_subscription_id
        ? "；ab_subscription_id: " + safeText(summary.ab_subscription_id)
        : "";
      clearSettingsAbSensitiveFields();
      setSettingsAbResult(
        "Auto Bangumi 提交成功；request_id: " + safeText(requestId) + subscriptionId,
        "success-state compact-state",
      );
      showNotification("success", "Auto Bangumi 提交成功", "订阅方案 " + requestId, {
        actions: settingsAbReturnLink
          ? [
              {
                label: "返回详情",
                handler: () => {
                  window.location.href = settingsAbReturnLink.href;
                },
              },
            ]
          : [],
      });
    } catch (error) {
      setSettingsAbResult(
        "Auto Bangumi 提交失败。请检查配置与订阅方案状态后重试。",
        "error-state compact-state",
      );
      showNotification("error", "Auto Bangumi 提交失败", "请检查配置与订阅方案状态后重试。");
    } finally {
      setSettingsAbInFlight(false);
    }
  }

  initializeSettingsAbForm();

  syncAbAuthMode("settings-ab");
  if (settingsAbAuthModeInput) settingsAbAuthModeInput.addEventListener("change", () => syncAbAuthMode("settings-ab"));
  if (settingsAbTokenInput) settingsAbTokenInput.addEventListener("input", () => {
    if (settingsAbTokenInput.value && settingsAbAuthModeInput && settingsAbAuthModeInput.value === "password") {
      settingsAbAuthModeInput.value = "api_token";
      syncAbAuthMode("settings-ab");
    }
  });

  async function testSettingsAbConnection() {
    clearSettingsAbError();
    let abConfig;
    try {
      abConfig = buildAbConfig("settings-ab");
    } catch (validationError) {
      setSettingsAbError(validationError.message, validationError.field);
      return;
    }
    setSettingsAbInFlight(true);
    setSettingsAbResult("正在测试 Auto Bangumi 连接...", "loading-state compact-state");
    try {
      const result = await fetchJson("/api/v1/autobangumi/test-connection", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ab_config: abConfig})});
      clearSettingsAbSensitiveFields();
      setSettingsAbResult("连接成功；版本：" + safeText(result.version) + "；认证方式：" + safeText(result.auth_mode), "success-state compact-state");
    } catch (error) {
      setSettingsAbResult("Auto Bangumi 连接测试失败。请检查配置后重试。", "error-state compact-state");
    } finally { setSettingsAbInFlight(false); }
  }

  if (settingsAbTestButton) settingsAbTestButton.addEventListener("click", testSettingsAbConnection);

  if (settingsAbForm) {
    settingsAbForm.addEventListener("submit", submitSettingsAb);
  }

  function setPreferenceSettingsError(message, field) {
    if (!preferenceSettingsError) {
      return;
    }
    preferenceSettingsError.textContent = message;
    preferenceSettingsError.hidden = false;
    for (const input of [
      preferencePreferredInput,
      preferenceExcludedInput,
      preferenceFallbackSelect,
      preferenceFilterContainInput,
      preferenceFilterNotContainInput,
      preferenceFilterUseRegexInput,
      preferenceFilterCaseSensitiveInput,
      preferenceNamingStrategySelect,
      preferenceNamingTemplateInput,
      preferenceSearchReuseInput,
    ]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
    if (field) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  function clearPreferenceSettingsError() {
    if (!preferenceSettingsError) {
      return;
    }
    preferenceSettingsError.textContent = "";
    preferenceSettingsError.hidden = true;
    for (const input of [
      preferencePreferredInput,
      preferenceExcludedInput,
      preferenceFallbackSelect,
      preferenceFilterContainInput,
      preferenceFilterNotContainInput,
      preferenceFilterUseRegexInput,
      preferenceFilterCaseSensitiveInput,
      preferenceNamingStrategySelect,
      preferenceNamingTemplateInput,
      preferenceSearchReuseInput,
    ]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
  }

  function setPreferenceSettingsStatus(message, className) {
    if (!preferenceSettingsStatus) {
      return;
    }
    preferenceSettingsStatus.className = className || "empty-state compact-state";
    preferenceSettingsStatus.textContent = message;
  }

  function setPreferenceSettingsInFlight(isInFlight) {
    if (!preferenceSettingsForm) {
      return;
    }
    const controls = preferenceSettingsForm.querySelectorAll("button, input, select, textarea");
    for (const control of controls) {
      control.disabled = isInFlight;
    }
    if (preferenceSettingsSaveButton) {
      preferenceSettingsSaveButton.textContent = isInFlight
        ? "正在保存..."
        : "保存偏好默认值";
    }
  }

  function preferenceListToText(value) {
    if (!Array.isArray(value)) {
      return "";
    }
    return value.join("\n");
  }

  function preferenceTextToArray(value) {
    const text = value || "";
    return text
      .split("\n")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
  }

  function renderPreferenceSettings(preferences) {
    if (!preferenceSettingsForm) {
      return;
    }
    currentPreferenceValues = preferences;
    const subtitleGroups = preferences && preferences.subtitle_groups
      ? preferences.subtitle_groups
      : {};
    const filterDefaults = preferences && preferences.filter_defaults
      ? preferences.filter_defaults
      : {};
    const naming = preferences && preferences.naming ? preferences.naming : {};
    const search = preferences && preferences.search ? preferences.search : {};

    if (preferencePreferredInput) {
      preferencePreferredInput.value = preferenceListToText(subtitleGroups.preferred);
    }
    if (preferenceExcludedInput) {
      preferenceExcludedInput.value = preferenceListToText(subtitleGroups.excluded);
    }
    if (preferenceFallbackSelect) {
      preferenceFallbackSelect.value = subtitleGroups.fallback || "next_preferred";
    }
    if (preferenceFilterContainInput) {
      preferenceFilterContainInput.value = filterDefaults.must_contain || "";
    }
    if (preferenceFilterNotContainInput) {
      preferenceFilterNotContainInput.value = filterDefaults.must_not_contain || "";
    }
    if (preferenceFilterUseRegexInput) {
      preferenceFilterUseRegexInput.checked = filterDefaults.use_regex === true;
    }
    if (preferenceFilterCaseSensitiveInput) {
      preferenceFilterCaseSensitiveInput.checked = filterDefaults.case_sensitive === true;
    }
    if (preferenceNamingStrategySelect) {
      preferenceNamingStrategySelect.value = naming.strategy || "official_title_season";
    }
    if (preferenceNamingTemplateInput) {
      preferenceNamingTemplateInput.value = naming.template || "{title}";
    }
    if (preferenceSearchReuseInput) {
      preferenceSearchReuseInput.checked = search.reuse_explicit_corrections !== false;
    }
  }

  function buildPreferenceSettingsPayload() {
    const payload = {
      preferences: {
        subtitle_groups: {
          preferred: preferenceTextToArray(preferencePreferredInput.value),
          excluded: preferenceTextToArray(preferenceExcludedInput.value),
          fallback: preferenceFallbackSelect ? preferenceFallbackSelect.value : "next_preferred",
        },
        filter_defaults: {
          must_contain: preferenceFilterContainInput ? preferenceFilterContainInput.value.trim() : "",
          must_not_contain: preferenceFilterNotContainInput ? preferenceFilterNotContainInput.value.trim() : "",
          use_regex: preferenceFilterUseRegexInput ? preferenceFilterUseRegexInput.checked : false,
          case_sensitive: preferenceFilterCaseSensitiveInput ? preferenceFilterCaseSensitiveInput.checked : false,
        },
        naming: {
          strategy: preferenceNamingStrategySelect ? preferenceNamingStrategySelect.value : "official_title_season",
          template: preferenceNamingTemplateInput ? preferenceNamingTemplateInput.value.trim() : "{title}",
        },
        search: {
          reuse_explicit_corrections: preferenceSearchReuseInput ? preferenceSearchReuseInput.checked : true,
        },
      },
    };
    const storageDir = currentStorageDir();
    if (storageDir) {
      payload.storage_dir = storageDir;
    }
    return payload;
  }

  async function loadPreferenceSettings() {
    if (!preferenceSettingsForm) {
      return;
    }
    clearPreferenceSettingsError();
    setPreferenceSettingsStatus("正在读取偏好默认值...", "loading-state compact-state");
    try {
      const preferences = await fetchJson(apiPath("/api/v1/preferences"));
      renderPreferenceSettings(preferences);
      setPreferenceSettingsStatus("已读取偏好默认值。", "empty-state compact-state");
    } catch (error) {
      renderPreferenceSettings(currentPreferenceValues || {});
      setPreferenceSettingsStatus(
        "读取偏好默认值失败。请检查存储目录后重试。",
        "error-state compact-state",
      );
    }
  }

  async function savePreferenceSettings(event) {
    if (event && event.preventDefault) {
      event.preventDefault();
    }
    clearPreferenceSettingsError();
    setPreferenceSettingsInFlight(true);
    setPreferenceSettingsStatus("正在保存偏好默认值...", "loading-state compact-state");
    try {
      const payload = buildPreferenceSettingsPayload();
      const preferences = await fetchJson("/api/v1/preferences", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      renderPreferenceSettings(preferences);
      setPreferenceSettingsStatus("偏好默认值已保存。", "success-state compact-state");
      showNotification("success", "偏好默认值已保存", "后续批量订阅草案将使用这些默认值。");
    } catch (error) {
      // 回退到上次已成功加载/保存的偏好，保证被拒绝的敏感输入不会残留在表单中。
      renderPreferenceSettings(currentPreferenceValues || {});
      setPreferenceSettingsStatus("保存偏好默认值失败。请修正后重试。", "error-state compact-state");
      setPreferenceSettingsError(error.message || "保存失败", null);
      notifyApiError("保存偏好默认值失败", error);
    } finally {
      setPreferenceSettingsInFlight(false);
    }
  }

  async function resetPreferenceSettings() {
    if (!window.confirm(
      "确认恢复所有偏好为默认值？此操作不会清除订阅方案、批量提交队列或 Auto Bangumi 结果存储。"
    )) {
      return;
    }
    clearPreferenceSettingsError();
    setPreferenceSettingsInFlight(true);
    setPreferenceSettingsStatus("正在恢复默认偏好...", "loading-state compact-state");
    try {
      const payload = {preferences: {}};
      const storageDir = currentStorageDir();
      if (storageDir) {
        payload.storage_dir = storageDir;
      }
      const preferences = await fetchJson("/api/v1/preferences", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      renderPreferenceSettings(preferences);
      setPreferenceSettingsStatus("已恢复默认偏好。", "success-state compact-state");
      showNotification("success", "已恢复默认偏好", "偏好默认值已清空，订阅方案与队列不受影响。");
    } catch (error) {
      renderPreferenceSettings(currentPreferenceValues || {});
      setPreferenceSettingsStatus("恢复默认偏好失败。请重试。", "error-state compact-state");
      notifyApiError("恢复默认偏好失败", error);
    } finally {
      setPreferenceSettingsInFlight(false);
    }
  }

  if (preferenceSettingsForm) {
    preferenceSettingsForm.addEventListener("submit", savePreferenceSettings);
  }
  if (preferenceSettingsResetButton) {
    preferenceSettingsResetButton.addEventListener("click", resetPreferenceSettings);
  }
  if (preferenceSettingsForm) {
    loadPreferenceSettings();
  }

  if (!form) {
    return;
  }

  function batchStatusLabel(status) {
    const labels = {
      RAW: "待解析",
      PARSED: "已解析",
      FOUND: "找到候选",
      EMPTY: "未找到候选",
      FAILED: "搜索失败",
      NEEDS_REVIEW: "待确认",
      DRAFT: "草案",
      READY: "待接受",
      ACCEPTED: "已接受",
    };
    const value = fieldValue(status);
    return Object.prototype.hasOwnProperty.call(labels, value)
      ? labels[value]
      : value;
  }

  function setBatchParseError(message, field) {
    if (!batchParseError) {
      return;
    }
    batchParseError.textContent = message;
    batchParseError.hidden = false;
    if (batchRawInput) {
      batchRawInput.removeAttribute("aria-invalid");
    }
    if (field) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  function clearBatchParseError() {
    if (!batchParseError) {
      return;
    }
    batchParseError.textContent = "";
    batchParseError.hidden = true;
    if (batchRawInput) {
      batchRawInput.removeAttribute("aria-invalid");
    }
  }

  function setBatchParseResult(message, className) {
    if (!batchParseResult) {
      return;
    }
    batchParseResult.className = className || "empty-state compact-state";
    batchParseResult.replaceChildren();
    batchParseResult.textContent = message;
  }

  function setBatchParseInFlight(isInFlight) {
    setSearchWorkspaceInFlight(isInFlight);
    if (batchParseSubmit) {
      batchParseSubmit.disabled = isInFlight;
      batchParseSubmit.textContent = isInFlight
        ? "正在获取..."
        : "获取批量草案";
    }
  }

  function buildBatchParsePayload() {
    const rawInput = batchRawInput ? batchRawInput.value : "";
    if (!rawInput.trim()) {
      const error = new Error("批量获取前必须输入至少一个番剧名称。");
      error.field = batchRawInput;
      throw error;
    }
    return {raw_input: rawInput, storage_dir: currentStorageDir() || null};
  }

  function batchCardTitle(row) {
    const canonicalTitles = Array.isArray(row.canonical_title_candidates)
      ? row.canonical_title_candidates
      : [];
    if (canonicalTitles.length) {
      return safeText(canonicalTitles[0]) || "未命名条目";
    }
    return safeText(row.raw_title) || "未命名条目";
  }

  function batchCardSourceName(row) {
    const selectedCandidate = row.selected_candidate || null;
    if (selectedCandidate) {
      return "已选 MiKan 合集";
    }
    return "MiKan 候选搜索";
  }

  const titleParseSourceLabels = {
    correction: "用户修正",
    rule: "规则识别",
    alias: "别名匹配",
    fallback: "原始标题回退",
    fake: "测试解析",
  };

  function titleParseSourceLabel(source) {
    const value = String(source || "");
    return Object.prototype.hasOwnProperty.call(titleParseSourceLabels, value)
      ? titleParseSourceLabels[value]
      : "原始标题回退";
  }

  function titleParseData(result) {
    const parse = result && result.parse_result;
    if (parse && typeof parse === "object") {
      return parse;
    }
    return null;
  }

  function titleParseReviewHints(result, parse) {
    const hints = [];
    for (const source of [parse && parse.review_hints, result && result.review_hints]) {
      if (!Array.isArray(source)) {
        continue;
      }
      for (const hint of source) {
        const text = safeText(hint).trim();
        if (text && !hints.includes(text)) {
          hints.push(text);
        }
      }
    }
    return hints;
  }

  // This block consumes only the API's public parse summary and actual query
  // list.  It is intentionally shared by single and batch results so their
  // explanations cannot drift apart or reflect provider-owned fields.
  function renderTitleParseSummary(result) {
    const parse = titleParseData(result);
    if (!parse) {
      return null;
    }
    const block = document.createElement("section");
    block.className = "title-parse-summary";
    block.setAttribute("aria-label", "标题解析摘要");

    const heading = document.createElement("h3");
    heading.textContent = "标题解析摘要";
    block.appendChild(heading);

    const season = Number(parse.season && parse.season.number);
    const recognizedTitle = safeText(parse.normalized_title || parse.base_title || result.raw_title);
    const rows = [
      ["识别标题", recognizedTitle || "未识别"],
      ["识别季度", Number.isInteger(season) && season >= 1 && season <= 99 ? "第" + season + "季" : "未识别"],
      ["解析来源", titleParseSourceLabel(parse.source)],
    ];
    block.appendChild(detailList(rows));

    const attempted = Array.isArray(result && result.attempted_queries)
      ? result.attempted_queries
      : [];
    const queryPlan = attempted.length ? attempted : (Array.isArray(parse.query_plan) ? parse.query_plan : []);
    const queryHeading = document.createElement("h4");
    queryHeading.textContent = attempted.length ? "实际搜索词" : "计划搜索词";
    block.appendChild(queryHeading);
    if (queryPlan.length) {
      const queries = document.createElement("ul");
      queries.className = "title-parse-query-list";
      for (const entry of queryPlan) {
        const query = entry && typeof entry === "object" ? entry.query : entry;
        const text = safeText(query).trim();
        if (!text) {
          continue;
        }
        const item = document.createElement("li");
        item.textContent = text;
        queries.appendChild(item);
      }
      if (queries.childElementCount) {
        block.appendChild(queries);
      }
    }

    const hints = titleParseReviewHints(result, parse);
    if (parse.needs_user_review === true && !hints.length) {
      hints.push("该解析结果需要人工核对。");
    }
    if (hints.length) {
      const hintHeading = document.createElement("h4");
      hintHeading.textContent = "需人工核对";
      block.appendChild(hintHeading);
      const list = document.createElement("ul");
      list.className = "title-parse-review-hints";
      for (const hint of hints) {
        const item = document.createElement("li");
        item.textContent = hint;
        list.appendChild(item);
      }
      block.appendChild(list);
    }
    return block;
  }

  function batchCardSeedSummary(row) {
    const review = batchCardReviewData(row);
    const value = review.effectiveSeeds.length || row.valid_seed_count;
    if (Number.isInteger(value) && value >= 0) {
      return String(value);
    }
    return "待展开";
  }

  function batchCardReviewData(row) {
    const request = row.request || row.preview_request || row.draft_request || row;
    const config = request.confirmable_config || row.confirmable_config || {};
    const sourceInfo = request.source_info || row.source_info || {};
    const filterRule = config.filter_rule || row.filter_rule || {};
    const source = selectedRssSource(sourceInfo, config);
    const validSeeds = source.valid_seed_names || row.valid_seed_names || [];
    const excludedSeeds = source.excluded_seed_names || row.excluded_seed_names || [];
    const effectiveSeeds =
      config.effective_seed_names ||
      row.effective_seed_names ||
      validSeeds;
    const selectedGroupName =
      config.selected_subtitle_group ||
      row.selected_subtitle_group ||
      source.subtitle_group ||
      "未选择字幕组";
    return {
      config: config,
      filterRule: filterRule,
      effectiveSeeds: Array.isArray(effectiveSeeds) ? effectiveSeeds : [],
      excludedSeeds: Array.isArray(excludedSeeds) ? excludedSeeds : [],
      selectedGroupName: selectedGroupName,
    };
  }

  // Stage 21 (US-156): the batch card exposes the parse-time preference/review
  // metadata (preference hits, preference warnings, review hints, search-query
  // source) plus the preference default config. These helpers only read the
  // public non-sensitive fields the batch parse API already returns, so no
  // endpoint/token/cookie/raw response ever reaches the rendered card.

  function batchCardPreferenceHits(row) {
    return Array.isArray(row.preference_hits) ? row.preference_hits : [];
  }

  function batchCardPreferenceWarnings(row) {
    return Array.isArray(row.preference_warnings) ? row.preference_warnings : [];
  }

  function batchCardReviewHints(row) {
    return Array.isArray(row.review_hints) ? row.review_hints : [];
  }

  function batchCardEnhancedQueries(row) {
    return Array.isArray(row.enhanced_search_queries) ? row.enhanced_search_queries : [];
  }

  function batchCardAppliedPreferences(row) {
    const applied = row.applied_preferences;
    return applied && typeof applied === "object" ? applied : null;
  }

  function batchCardPreferenceFallback(row) {
    const warnings = batchCardPreferenceWarnings(row);
    for (const warning of warnings) {
      const text = String(warning || "");
      if (text.indexOf("偏好读取失败") !== -1 || text.indexOf("偏好应用失败") !== -1) {
        return text;
      }
    }
    return null;
  }

  function batchCardPreferenceHitLabel(field) {
    const labels = {
      subtitle_groups: "字幕组",
      filter_rule: "筛选",
      naming: "命名",
    };
    return Object.prototype.hasOwnProperty.call(labels, field)
      ? labels[field]
      : safeText(field);
  }

  function batchCardPreferenceSummary(row) {
    if (batchCardPreferenceFallback(row)) {
      return "偏好不可用，已回退默认流程";
    }
    const hits = batchCardPreferenceHits(row);
    const appliedFields = hits
      .filter((hit) => hit && hit.applied === true)
      .map((hit) => batchCardPreferenceHitLabel(hit.field));
    if (appliedFields.length) {
      return "偏好命中：" + appliedFields.join("、");
    }
    return "未配置偏好，使用默认流程";
  }

  function batchCardNeedsReview(row) {
    return row.needs_user_review === true && fieldValue(row.status) !== "ACCEPTED";
  }

  function batchCardFallbackLabel(fallback) {
    const labels = {
      next_preferred: "偏好字幕组优先",
      none: "不自动选择",
    };
    return Object.prototype.hasOwnProperty.call(labels, fallback)
      ? labels[fallback]
      : safeText(fallback);
  }

  function batchCardNamingStrategyLabel(strategy) {
    const labels = {
      official_title_season: "官方标题+季",
      official_title: "官方标题",
      raw_title: "原始标题",
    };
    return Object.prototype.hasOwnProperty.call(labels, strategy)
      ? labels[strategy]
      : safeText(strategy);
  }

  function buildBatchCardPreferenceBlock(row) {
    const block = document.createElement("div");
    block.className = "batch-card-review-block batch-card-preference-block";
    const heading = document.createElement("h4");
    heading.textContent = "偏好与审核";
    block.appendChild(heading);

    const fallback = batchCardPreferenceFallback(row);
    if (fallback) {
      const fallbackNote = document.createElement("p");
      fallbackNote.className = "batch-card-preference-note";
      fallbackNote.textContent = safeText(fallback);
      block.appendChild(fallbackNote);
    }

    const hits = batchCardPreferenceHits(row);
    if (hits.length) {
      const hitsHeading = document.createElement("h5");
      hitsHeading.textContent = "偏好命中摘要";
      block.appendChild(hitsHeading);
      const hitsList = document.createElement("ul");
      hitsList.className = "batch-card-preference-list";
      for (const hit of hits) {
        if (!hit) {
          continue;
        }
        const item = document.createElement("li");
        item.textContent =
          batchCardPreferenceHitLabel(hit.field) +
          "：" +
          safeText(hit.summary);
        hitsList.appendChild(item);
      }
      block.appendChild(hitsList);
    } else if (!fallback) {
      const note = document.createElement("p");
      note.className = "muted-text";
      note.textContent = "未配置偏好默认值。";
      block.appendChild(note);
    }

    const warnings = batchCardPreferenceWarnings(row).filter(
      (warning) => String(warning || "").trim() !== "",
    );
    if (warnings.length) {
      const warningsHeading = document.createElement("h5");
      warningsHeading.textContent = "偏好警告";
      block.appendChild(warningsHeading);
      const warningsList = document.createElement("ul");
      warningsList.className = "batch-card-preference-list";
      for (const warning of warnings) {
        const item = document.createElement("li");
        item.textContent = safeText(warning);
        warningsList.appendChild(item);
      }
      block.appendChild(warningsList);
    }

    const reviewHeading = document.createElement("h5");
    reviewHeading.textContent = "审核提示";
    block.appendChild(reviewHeading);
    const reviewHints = batchCardReviewHints(row);
    if (reviewHints.length) {
      const hintsList = document.createElement("ul");
      hintsList.className = "batch-card-preference-list";
      for (const hint of reviewHints) {
        const item = document.createElement("li");
        item.textContent = safeText(hint);
        hintsList.appendChild(item);
      }
      block.appendChild(hintsList);
    } else {
      const note = document.createElement("p");
      note.className = "muted-text";
      note.textContent = "无需人工核对。";
      block.appendChild(note);
    }

    const applied = batchCardAppliedPreferences(row);
    if (applied) {
      const configHeading = document.createElement("h5");
      configHeading.textContent = "当前默认配置";
      block.appendChild(configHeading);
      const subtitleGroups =
        applied.subtitle_groups && typeof applied.subtitle_groups === "object"
          ? applied.subtitle_groups
          : {};
      const filterRule =
        applied.filter_rule && typeof applied.filter_rule === "object"
          ? applied.filter_rule
          : {};
      const naming =
        applied.naming && typeof applied.naming === "object"
          ? applied.naming
          : {};
      const preferred = Array.isArray(subtitleGroups.preferred)
        ? subtitleGroups.preferred
        : [];
      const excluded = Array.isArray(subtitleGroups.excluded)
        ? subtitleGroups.excluded
        : [];
      const filterParts = [filterRule.must_contain, filterRule.must_not_contain]
        .map((part) => String(part || "").trim())
        .filter((part) => part !== "");
      const configRows = [
        ["偏好字幕组", safeText(preferred.join("、") || "未配置")],
        ["排除字幕组", safeText(excluded.join("、") || "未配置")],
        ["Fallback", batchCardFallbackLabel(subtitleGroups.fallback)],
        ["默认筛选", filterParts.length ? safeText(filterParts.join(" / ")) : "无"],
        ["匹配模式", filterRule.use_regex === true ? "正则" : "普通字符"],
        ["大小写", filterRule.case_sensitive === true ? "区分大小写" : "不区分大小写"],
        ["命名策略", batchCardNamingStrategyLabel(naming.strategy)],
        ["命名模板", safeText(naming.template || "{title}")],
      ];
      if (applied.expected_folder_name) {
        configRows.push(["默认目录名", safeText(applied.expected_folder_name)]);
      }
      block.appendChild(detailList(configRows));
    }

    return block;
  }

  function buildBatchCardSearchSourceBlock(row) {
    const block = document.createElement("div");
    block.className = "batch-card-review-block batch-card-search-source-block";
    const heading = document.createElement("h4");
    heading.textContent = "搜索词来源";
    block.appendChild(heading);

    const enhanced = batchCardEnhancedQueries(row);
    if (enhanced.length) {
      const sourceLabel = document.createElement("h5");
      sourceLabel.textContent = "修正增强搜索词";
      block.appendChild(sourceLabel);
      const list = document.createElement("ul");
      list.className = "batch-card-preference-list";
      for (const entry of enhanced) {
        if (!entry) {
          continue;
        }
        const item = document.createElement("li");
        item.textContent = safeText(entry.query) + "（来源：" + safeText(entry.source) + "）";
        list.appendChild(item);
      }
      block.appendChild(list);
      const originalHeading = document.createElement("h5");
      originalHeading.textContent = "原始搜索词";
      block.appendChild(originalHeading);
      const originalList = document.createElement("ul");
      originalList.className = "batch-card-preference-list";
      const originalQueries = Array.isArray(row.search_queries)
        ? row.search_queries
        : [];
      for (const query of originalQueries) {
        const item = document.createElement("li");
        item.textContent = safeText(query);
        originalList.appendChild(item);
      }
      block.appendChild(originalList);
      return block;
    }

    const queries = Array.isArray(row.search_queries) ? row.search_queries : [];
    if (queries.length) {
      const defaultLabel = document.createElement("h5");
      defaultLabel.textContent = "默认解析搜索词";
      block.appendChild(defaultLabel);
      const list = document.createElement("ul");
      list.className = "batch-card-preference-list";
      for (const query of queries) {
        const item = document.createElement("li");
        item.textContent = safeText(query);
        list.appendChild(item);
      }
      block.appendChild(list);
    } else {
      const note = document.createElement("p");
      note.className = "muted-text";
      note.textContent = "无搜索词，已回退默认流程。";
      block.appendChild(note);
    }
    return block;
  }

  function canExpandBatchCard(row) {
    return ["DRAFT", "READY"].indexOf(fieldValue(row.status)) !== -1;
  }

  function batchCardRequest(row) {
    return row.request || row.preview_request || row.draft_request || null;
  }

  function canModifyBatchCard(row) {
    return canExpandBatchCard(row) && Boolean(batchCardRequest(row));
  }

  function canAcceptBatchCard(row) {
    return canExpandBatchCard(row) && Boolean(batchCardRequest(row));
  }

  function updateBatchCardRequest(itemId, modified) {
    if (!itemId || !modified) {
      return;
    }
    batchDraftCards = batchDraftCards.map((row) => {
      if (row.item_id !== itemId) {
        return row;
      }
      const next = Object.assign({}, row);
      if (row.request) {
        next.request = modified;
      } else if (row.draft_request) {
        next.draft_request = modified;
      } else {
        next.preview_request = modified;
      }
      next.confirmable_config = modified.confirmable_config || row.confirmable_config;
      next.source_info = modified.source_info || row.source_info;
      return next;
    });
    renderBatchParseItems(batchDraftCards);
  }

  function markBatchCardAccepted(itemId, acceptedRequest, options) {
    const opts = options || {};
    if (!itemId || !acceptedRequest) {
      return;
    }
    batchDraftCards = batchDraftCards.map((row) => {
      if (row.item_id !== itemId) {
        return row;
      }
      const next = Object.assign({}, row);
      next.status = "ACCEPTED";
      next.request = acceptedRequest;
      delete next.preview_request;
      delete next.draft_request;
      next.confirmable_config =
        acceptedRequest.confirmable_config || row.confirmable_config;
      next.source_info = acceptedRequest.source_info || row.source_info;
      if (opts.queued) {
        next.queue_status = "READY_TO_SUBMIT";
      }
      return next;
    });
    if (opts.render !== false) {
      renderBatchParseItems(batchDraftCards);
    }
  }

  async function savePreviewDraftRequest(request) {
    const result = await fetchJson("/api/v1/requests/preview-save", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        request: request,
        storage_dir: currentStorageDir() || null,
      }),
    });
    return result && result.request;
  }

  function batchCardSavedRequest(row) {
    return (row && row.request) || null;
  }

  function batchCardPreviewRequest(row) {
    return (row && (row.preview_request || row.draft_request)) || null;
  }

  function batchCardIsSelectable(row) {
    return canAcceptBatchCard(row);
  }

  function updateBatchAcceptToolbar() {
    if (!batchAcceptToolbar) {
      return;
    }
    const selectable = batchDraftCards.filter(batchCardIsSelectable);
    const selectedCount = batchDraftCards.filter(
      (row) =>
        selectedBatchItemIds.has(row.item_id) && batchCardIsSelectable(row),
    ).length;
    if (batchAcceptSelectedCount) {
      batchAcceptSelectedCount.textContent = "已选择 " + selectedCount + " 项";
    }
    if (batchSelectAllCheckbox) {
      batchSelectAllCheckbox.checked =
        selectable.length > 0 &&
        selectable.every((row) => selectedBatchItemIds.has(row.item_id));
      batchSelectAllCheckbox.indeterminate =
        selectedCount > 0 && selectedCount < selectable.length;
    }
    if (batchAcceptSubmit) {
      batchAcceptSubmit.disabled =
        selectedCount === 0 || batchAcceptInFlight;
    }
    if (batchAcceptAll) {
      batchAcceptAll.disabled =
        batchAcceptInFlight || selectable.length === 0;
    }
  }

  function toggleBatchItemSelection(itemId, selected) {
    if (selected) {
      selectedBatchItemIds.add(itemId);
    } else {
      selectedBatchItemIds.delete(itemId);
    }
    updateBatchAcceptToolbar();
  }

  function setAllBatchItemsSelected(selected) {
    selectedBatchItemIds = new Set();
    if (selected) {
      for (const row of batchDraftCards) {
        if (batchCardIsSelectable(row)) {
          selectedBatchItemIds.add(row.item_id);
        }
      }
    }
    renderBatchParseItems(batchDraftCards);
  }

  function setBatchAcceptInFlight(isInFlight) {
    batchAcceptInFlight = isInFlight;
    if (batchAcceptSubmit) {
      batchAcceptSubmit.textContent = isInFlight ? "正在接受..." : "批量接受";
    }
    if (batchAcceptAll) {
      batchAcceptAll.textContent = isInFlight ? "正在接受..." : "全接受";
    }
    if (batchDraftCards.length) {
      renderBatchParseItems(batchDraftCards);
    } else {
      updateBatchAcceptToolbar();
    }
  }

  function setBatchCardAcceptFeedback(itemId, status, reason) {
    batchDraftCards = batchDraftCards.map((row) => {
      if (row.item_id !== itemId) {
        return row;
      }
      const next = Object.assign({}, row);
      next.accept_feedback = {
        status: status,
        reason: reason || "接受失败",
      };
      return next;
    });
  }

  function applyBatchAcceptResult(result, pendingSavedRequests) {
    const saved = pendingSavedRequests || new Map();
    const outcomeCounts = {};
    const items = Array.isArray(result && result.items) ? result.items : [];
    for (const item of items) {
      outcomeCounts[item.status] = (outcomeCounts[item.status] || 0) + 1;
      batchDraftCards = batchDraftCards.map((row) => {
        if (row.item_id !== item.item_id) {
          return row;
        }
        const next = Object.assign({}, row);
        delete next.accept_feedback;
        if (item.status === "accepted" || item.status === "already_accepted") {
          const savedRequest =
            saved.get(item.item_id) ||
            row.request ||
            row.preview_request ||
            row.draft_request ||
            {};
          next.status = "ACCEPTED";
          next.request = Object.assign({}, savedRequest, {status: "ACCEPTED"});
          delete next.preview_request;
          delete next.draft_request;
          next.confirmable_config =
            next.request.confirmable_config || row.confirmable_config;
          next.source_info = next.request.source_info || row.source_info;
          if (item.status === "accepted") {
            next.queue_status = "READY_TO_SUBMIT";
          }
          selectedBatchItemIds.delete(item.item_id);
        } else {
          next.accept_feedback = {
            status: item.status,
            reason: item.reason || "接受失败",
          };
        }
        return next;
      });
    }
    // Sync the authoritative queue statuses onto matching accepted cards so a
    // re-accept (already_accepted) still reflects the persisted queue.
    const queue = result && result.queue;
    const queueItems = queue && Array.isArray(queue.items) ? queue.items : [];
    for (const qItem of queueItems) {
      batchDraftCards = batchDraftCards.map((row) => {
        if (row.item_id !== qItem.item_id || row.status !== "ACCEPTED") {
          return row;
        }
        const next = Object.assign({}, row);
        next.queue_status = qItem.status;
        return next;
      });
    }
    return outcomeCounts;
  }

  function showBatchAcceptNotification(outcomeCounts, isSingle) {
    const accepted = outcomeCounts.accepted || 0;
    const already = outcomeCounts.already_accepted || 0;
    const bad = (outcomeCounts.unacceptable || 0) + (outcomeCounts.failed || 0);
    let message = "已接受 " + accepted + " 项";
    if (already) {
      message += "；已确认跳过 " + already + " 项";
    }
    if (bad) {
      message += "；" + bad + " 项无法接受";
    }
    if (isSingle) {
      if (bad > 0 && accepted === 0) {
        showNotification("error", "接受失败", message);
      } else if (accepted > 0) {
        showNotification(
          "success",
          "接受成功",
          "当前批量卡片已标记为已接受并待提交，其他卡片保持不变。",
        );
      } else if (already > 0) {
        showNotification(
          "success",
          "接受成功",
          "当前批量卡片已确认，跳过重复接受。",
        );
      } else {
        showNotification("success", "接受成功", message);
      }
      return;
    }
    if (bad > 0 && accepted === 0) {
      showNotification("error", "批量接受失败", message);
    } else if (bad > 0) {
      showNotification("success", "批量接受完成", message);
    } else {
      showNotification("success", "批量接受成功", message);
    }
  }

  async function resolveBatchAcceptDescriptors(rows) {
    const descriptors = [];
    const pendingSavedRequests = new Map();
    const localFailures = [];
    for (const row of rows) {
      const saved = batchCardSavedRequest(row);
      if (saved && saved.request_id) {
        descriptors.push({
          item_id: row.item_id,
          request_id: saved.request_id,
          title: batchCardTitle(row),
        });
        pendingSavedRequests.set(row.item_id, saved);
        continue;
      }
      const preview = batchCardPreviewRequest(row);
      if (preview && preview.request_id) {
        try {
          const savedRequest = await savePreviewDraftRequest(preview);
          if (!savedRequest || !savedRequest.request_id) {
            throw new Error("preview-save returned no request_id");
          }
          descriptors.push({
            item_id: row.item_id,
            request_id: savedRequest.request_id,
            title: batchCardTitle(row),
          });
          pendingSavedRequests.set(row.item_id, savedRequest);
        } catch (error) {
          localFailures.push({
            item_id: row.item_id,
            title: batchCardTitle(row),
            reason: "订阅草案保存失败，无法接受",
          });
        }
        continue;
      }
      descriptors.push({
        item_id: row.item_id,
        request_id: null,
        title: batchCardTitle(row),
      });
    }
    return {descriptors: descriptors, pendingSavedRequests: pendingSavedRequests, localFailures: localFailures};
  }

  function postBatchAccept(descriptors, itemIds) {
    const payload = {
      items: descriptors,
      storage_dir: currentStorageDir() || null,
    };
    if (itemIds) {
      payload.item_ids = itemIds;
    }
    return fetchJson(
      apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/accept"),
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      },
    );
  }

  async function submitBatchAccept(rows, options) {
    const opts = options || {};
    if (!currentBatchId) {
      showNotification(
        "error",
        "接受失败",
        "缺少批次标识，请重新获取批量草案。",
      );
      return;
    }
    hideNotification();
    setBatchAcceptInFlight(true);
    try {
      const resolved = await resolveBatchAcceptDescriptors(rows);
      if (!resolved.descriptors.length) {
        for (const failure of resolved.localFailures) {
          setBatchCardAcceptFeedback(failure.item_id, "failed", failure.reason);
        }
        renderBatchParseItems(batchDraftCards);
        showNotification(
          "error",
          "接受失败",
          resolved.localFailures.length
            ? resolved.localFailures[0].reason
            : "没有可接受的批量卡片。",
        );
        return;
      }
      const result = await postBatchAccept(
        resolved.descriptors,
        opts.itemIds || null,
      );
      const outcomeCounts = applyBatchAcceptResult(
        result,
        resolved.pendingSavedRequests,
      );
      for (const failure of resolved.localFailures) {
        setBatchCardAcceptFeedback(failure.item_id, "failed", failure.reason);
        outcomeCounts.failed = (outcomeCounts.failed || 0) + 1;
      }
      renderBatchParseItems(batchDraftCards);
      applyQueueResult(result && result.queue);
      // 用户确认了这些卡片的 raw_title → canonical title 映射：记录为搜索词
      // 修正，供后续批量输入复用（非关键路径，失败不阻断接受流程）。
      // 从更新后的 batchDraftCards 匹配（applyBatchAcceptResult 已把被接受的
      // 行状态更新为 ACCEPTED），而不是用传入的旧行引用。
      for (const acceptedRow of rows) {
        const updatedRow = batchDraftCards.find(
          (card) => card.item_id === acceptedRow.item_id,
        );
        if (updatedRow && fieldValue(updatedRow.status) === "ACCEPTED") {
          recordUserCorrection(updatedRow);
        }
      }
      await loadList({loadSelectedDetail: false});
      showBatchAcceptNotification(outcomeCounts, opts.single);
    } catch (error) {
      notifyApiError("接受失败", error);
    } finally {
      setBatchAcceptInFlight(false);
    }
  }

  async function recordUserCorrection(row) {
    // 把用户确认的 raw_title → canonical title 保存为非敏感 TitleCorrection，
    // 供 search_enhancer 在后续批量输入中生成可审核的增强搜索词。只有公开
    // 非敏感字段被提交；保存失败静默（不影响接受流程）。
    const canonicalTitles = Array.isArray(row.canonical_title_candidates)
      ? row.canonical_title_candidates
      : [];
    const canonical = canonicalTitles.length ? String(canonicalTitles[0]) : "";
    const raw = row.raw_title ? String(row.raw_title) : "";
    if (!raw || !canonical) {
      return;
    }
    const candidates = Array.isArray(row.candidates) ? row.candidates : [];
    const first = candidates.length ? candidates[0] : null;
    const correction = {
      raw_title: raw,
      canonical_title: canonical,
      season_hint: row.season_hint || null,
      query_correction: canonical,
    };
    if (first && first.bangumi_id) {
      correction.bangumi_metadata = {
        bangumi_id: String(first.bangumi_id),
        title: String(first.title || canonical),
      };
    }
    try {
      await fetchJson("/api/v1/corrections", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          correction: correction,
          storage_dir: currentStorageDir() || null,
        }),
      });
    } catch (error) {
      // 非关键路径：修正保存失败不阻断接受流程。
    }
  }

  async function acceptBatchCard(row) {
    await submitBatchAccept([row], {single: true});
  }

  function setPreviewEditError(message) {
    const formError = document.getElementById("preview-edit-error");
    if (!formError) {
      return;
    }
    formError.textContent = message || "订阅草案修改失败。请重试。";
    formError.hidden = false;
  }

  function openBatchCardModify(row) {
    openBatchCardDetail(row);
  }

  function openBatchCardDetail(row) {
    const request = batchCardRequest(row);
    if (!request) {
      showNotification(
        "error",
        "查看草案失败",
        "当前卡片缺少订阅草案，无法在详情中查看。",
      );
      return;
    }
    currentBatchDetailItemId = row.item_id || null;
    currentBatchEditItemId = row.item_id || null;
    renderDetailPayload({request: request}, {preview: true, batchItemId: row.item_id});
    const detailHeading = document.getElementById("request-detail-heading");
    if (detailHeading && detailHeading.scrollIntoView) {
      detailHeading.scrollIntoView({behavior: "smooth", block: "start"});
      detailHeading.tabIndex = -1;
      detailHeading.focus({preventScroll: true});
    }
  }

  function clearBatchDetailContext() {
    if (!currentBatchDetailItemId) {
      return;
    }
    currentBatchDetailItemId = null;
    currentBatchEditItemId = null;
    currentDetailPayload = null;
    setState(detailContainer, "选择一个订阅方案后查看详情。", "empty-state");
  }

  function deleteBatchCard(itemId) {
    selectedBatchItemIds.delete(itemId);
    if (activeBatchCandidateItemId === itemId) {
      activeBatchCandidateItemId = null;
    }
    if (currentBatchDetailItemId === itemId) {
      clearBatchDetailContext();
    }
    batchDraftCards = batchDraftCards.filter((row) => row.item_id !== itemId);
    renderBatchParseItems(batchDraftCards);
  }

  function batchCandidateTrigger(itemId) {
    if (!batchParseResult || !itemId) {
      return null;
    }
    return Array.from(batchParseResult.querySelectorAll(".batch-card-expand[data-item-id]")).find(
      (trigger) => trigger.dataset.itemId === String(itemId),
    ) || null;
  }

  function positionBatchCandidatePopover() {
    const popover = document.getElementById("batch-candidate-choices");
    const trigger = batchCandidateTrigger(activeBatchCandidateItemId);
    if (!popover || !trigger) {
      return;
    }
    const margin = 12;
    const gap = 10;
    const triggerRect = trigger.getBoundingClientRect();
    const maxWidth = Math.min(760, window.innerWidth - margin * 2);
    popover.style.maxWidth = maxWidth + "px";
    popover.style.maxHeight = Math.max(180, window.innerHeight - margin * 2) + "px";
    let left = Math.max(margin, Math.min(triggerRect.left, window.innerWidth - maxWidth - margin));
    let top = triggerRect.bottom + gap;
    const opensAbove = top + popover.offsetHeight > window.innerHeight - margin;
    if (opensAbove) {
      top = Math.max(margin, triggerRect.top - popover.offsetHeight - gap);
    }
    popover.classList.toggle("is-above", opensAbove);
    popover.style.left = left + "px";
    popover.style.top = top + "px";
    popover.style.setProperty(
      "--batch-popover-arrow-left",
      Math.max(18, Math.min(triggerRect.left + triggerRect.width / 2 - left, maxWidth - 18)) + "px",
    );
  }

  function closeBatchCandidatePopover(options) {
    if (!activeBatchCandidateItemId) {
      return;
    }
    const opts = options || {};
    const itemId = activeBatchCandidateItemId;
    activeBatchCandidateItemId = null;
    renderBatchParseItems(batchDraftCards);
    if (opts.focusTrigger !== false) {
      requestAnimationFrame(function () {
        const trigger = batchCandidateTrigger(itemId);
        if (trigger) {
          trigger.focus();
        }
      });
    }
  }

  function renderBatchCardPoster(row) {
    const selectedCandidate = row.selected_candidate || null;
    const posterUrl = selectedCandidate ? safeText(selectedCandidate.poster_url) : "";
    const posterWrap = document.createElement("div");
    posterWrap.className = "batch-card-poster";

    function showPlaceholder(message, kind) {
      posterWrap.replaceChildren();
      const placeholder = document.createElement("span");
      placeholder.className = "batch-card-poster-placeholder";
      if (kind) {
        placeholder.dataset.posterState = kind;
      }
      placeholder.textContent = message;
      posterWrap.appendChild(placeholder);
    }

    if (posterUrl) {
      const poster = document.createElement("img");
      poster.alt = "";
      poster.src = posterUrl;
      poster.loading = "lazy";
      poster.decoding = "async";
      poster.addEventListener("error", function () {
        showPlaceholder("暂无封面", "unavailable");
      }, {once: true});
      posterWrap.appendChild(poster);
    } else if (fieldValue(row.status) === "FOUND") {
      showPlaceholder("待选择合集", "unselected");
    } else {
      showPlaceholder("暂无封面", "unavailable");
    }
    return posterWrap;
  }

  function renderBatchCard(row) {
    const item = document.createElement("article");
    item.className = "batch-draft-card";
    item.dataset.itemId = safeText(row.item_id);

    const selectCheckbox = document.createElement("input");
    selectCheckbox.type = "checkbox";
    selectCheckbox.className = "batch-card-checkbox";
    selectCheckbox.dataset.itemId = safeText(row.item_id);
    selectCheckbox.setAttribute(
      "aria-label",
      "选择 " + (safeText(row.raw_title) || "批量条目"),
    );
    selectCheckbox.checked = selectedBatchItemIds.has(row.item_id);
    selectCheckbox.disabled = !batchCardIsSelectable(row) || batchAcceptInFlight;
    selectCheckbox.addEventListener("change", function () {
      toggleBatchItemSelection(row.item_id, selectCheckbox.checked);
    });

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "icon-button batch-card-delete";
    removeButton.setAttribute("aria-label", "删除 " + (safeText(row.raw_title) || "批量条目"));
    removeButton.title = "删除";
    removeButton.textContent = "×";
    if (fieldValue(row.status) === "ACCEPTED") {
      removeButton.hidden = true;
    }
    removeButton.disabled = batchAcceptInFlight;
    removeButton.addEventListener("click", () => {
      deleteBatchCard(row.item_id);
    });

    const posterWrap = renderBatchCardPoster(row);

    const statusRow = document.createElement("div");
    statusRow.className = "batch-card-status-row";
    const status = document.createElement("span");
    status.className = "batch-status batch-card-status";
    status.textContent = batchStatusLabel(row.status);
    statusRow.appendChild(status);
    if (row.queue_status) {
      const queueStatus = document.createElement("span");
      queueStatus.className =
        "batch-status batch-card-queue-status batch-card-queue-status-" +
        batchQueueStatusClass(row.queue_status);
      queueStatus.textContent = batchQueueStatusLabel(row.queue_status);
      statusRow.appendChild(queueStatus);
    }
    if (batchCardNeedsReview(row)) {
      const reviewStatus = document.createElement("span");
      reviewStatus.className = "batch-status batch-card-review-status";
      reviewStatus.textContent = "需人工核对";
      statusRow.appendChild(reviewStatus);
    }

    const title = document.createElement("strong");
    title.className = "batch-card-title";
    title.textContent = batchCardTitle(row);

    const rawTitle = document.createElement("div");
    rawTitle.className = "batch-card-raw-title";
    rawTitle.textContent = "输入：" + (safeText(row.raw_title) || "未命名条目");

    const source = document.createElement("div");
    source.className = "batch-card-source";
    source.textContent = "候选来源：" + batchCardSourceName(row);

    const preference = document.createElement("div");
    preference.className = "batch-card-preference";
    preference.textContent = batchCardPreferenceSummary(row);

    const seeds = document.createElement("div");
    seeds.className = "batch-card-seeds";
    seeds.textContent = "有效种子数：" + batchCardSeedSummary(row);

    const progress = document.createElement("div");
    progress.className = "batch-card-progress";
    const selectedCandidate = row.selected_candidate || null;
    const totalEpisodes = selectedCandidate && selectedCandidate.total_episodes;
    progress.textContent =
      "播出进度：待开发 / " +
      (Number.isInteger(totalEpisodes) && totalEpisodes > 0 ? totalEpisodes + " 集" : "未知");

    const candidateFeedback = renderBatchCandidateSearchFeedback(row);

    const expandButton = document.createElement("button");
    expandButton.type = "button";
    expandButton.className = "secondary-button batch-card-expand";
    const canChooseCandidate =
      fieldValue(row.status) === "FOUND" &&
      Array.isArray(row.candidates) &&
      row.candidates.length > 0;
    const isCandidateActive = activeBatchCandidateItemId === row.item_id;
    if (canChooseCandidate) {
      expandButton.textContent = isCandidateActive ? "收起候选" : "查看候选";
      expandButton.setAttribute(
        "aria-label",
        (isCandidateActive ? "收起候选" : "查看候选") + "：" +
          (safeText(row.raw_title) || "批量条目"),
      );
      expandButton.setAttribute("aria-controls", "batch-candidate-choices");
      expandButton.setAttribute("aria-expanded", isCandidateActive ? "true" : "false");
      expandButton.dataset.itemId = safeText(row.item_id);
      expandButton.addEventListener("click", function () {
        if (isCandidateActive) {
          closeBatchCandidatePopover();
          return;
        }
        activeBatchCandidateItemId = row.item_id;
        renderBatchParseItems(batchDraftCards);
        requestAnimationFrame(function () {
          const closeButton = document.querySelector("#batch-candidate-choices .batch-candidate-close");
          positionBatchCandidatePopover();
          if (closeButton) {
            closeButton.focus();
          }
        });
      });
    } else if (canExpandBatchCard(row)) {
      expandButton.textContent = "查看草案";
      expandButton.setAttribute("aria-label", "查看草案：" + (safeText(row.raw_title) || "批量条目"));
      expandButton.setAttribute("aria-controls", "request-detail-panel");
      expandButton.setAttribute("aria-expanded", currentBatchDetailItemId === row.item_id ? "true" : "false");
      expandButton.addEventListener("click", function () {
        openBatchCardDetail(row);
      });
    } else {
      expandButton.textContent = "查看候选";
      expandButton.disabled = true;
      expandButton.title = "当前条目没有可选择的候选合集";
      expandButton.setAttribute("aria-expanded", "false");
    }

    const children = [
      selectCheckbox,
      removeButton,
      posterWrap,
      statusRow,
      title,
      rawTitle,
      source,
      preference,
      seeds,
      progress,
    ];
    if (candidateFeedback) {
      children.push(candidateFeedback);
    }
    const parseSummary = renderTitleParseSummary(row);
    if (parseSummary) {
      children.push(parseSummary);
    }
    if (row.accept_feedback && row.accept_feedback.reason) {
      const reason = document.createElement("div");
      reason.className = "batch-card-reason";
      const prefix =
        row.accept_feedback.status === "failed" ? "接受失败：" : "无法接受：";
      reason.textContent =
        prefix + safeText(row.accept_feedback.reason);
      children.push(reason);
    }
    children.push(expandButton);
    item.append.apply(item, children);
    return item;
  }

  function renderBatchCandidateChoices(row) {
    if (fieldValue(row.status) !== "FOUND") {
      return null;
    }
    const candidates = Array.isArray(row.candidates) ? row.candidates : [];
    if (!candidates.length) {
      return null;
    }
    const container = document.createElement("div");
    container.id = "batch-candidate-choices";
    container.className = "batch-candidate-choices";
    container.setAttribute("role", "dialog");
    container.setAttribute("aria-modal", "false");
    container.setAttribute("aria-labelledby", "batch-candidate-choices-title");
    const heading = document.createElement("h3");
    heading.id = "batch-candidate-choices-title";
    heading.textContent = "候选合集：" + batchCardTitle(row);
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "icon-button batch-candidate-close";
    closeButton.setAttribute("aria-label", "关闭候选合集");
    closeButton.textContent = "×";
    closeButton.addEventListener("click", function () {
      closeBatchCandidatePopover();
    });
    container.append(heading, closeButton);
    const hint = document.createElement("p");
    hint.className = "field-help";
    hint.textContent = "请选择一个真实 MiKan 合集后生成订阅草案。";
    container.appendChild(hint);
    const list = document.createElement("ul");
    list.className = "candidate-list batch-candidate-list";
    for (const candidate of candidates) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button batch-candidate-select";
      button.textContent = "选择此合集";
      button.disabled = batchAcceptInFlight;
      button.addEventListener("click", function () {
        activeBatchCandidateItemId = null;
        generateBatchRequestFromCandidate(row, candidate);
      });
      list.appendChild(
        renderCandidateCard(candidate, {
          query: batchCardTitle(row),
          chooseButton: button,
        }),
      );
    }
    container.appendChild(list);
    return container;
  }

  function renderBatchCandidateSearchFeedback(row) {
    const status = fieldValue(row.status);
    if (status !== "EMPTY" && status !== "FAILED") {
      return null;
    }
    const feedback = document.createElement("p");
    feedback.className = "batch-candidate-feedback";
    if (status === "EMPTY") {
      feedback.textContent = "未找到匹配的 MiKan 合集。";
      return feedback;
    }
    const error = row.error && typeof row.error === "object" ? row.error : {};
    const message = safeText(error.error_message);
    feedback.textContent = message
      ? "搜索失败：" + message + "。可重新获取批量草案后重试。"
      : "搜索失败。可重新获取批量草案后重试。";
    return feedback;
  }

  function renderBatchParseItems(items) {
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) {
      setBatchParseResult(
        "没有可展示的批量解析结果。",
        "empty-state compact-state",
      );
      if (batchAcceptToolbar) {
        batchAcceptToolbar.hidden = true;
      }
      return;
    }

    batchParseResult.className = "batch-card-grid-wrapper";
    batchParseResult.replaceChildren();

    const list = document.createElement("div");
    list.className = "batch-card-grid";
    for (const row of rows) {
      list.appendChild(renderBatchCard(row));
    }
    batchParseResult.appendChild(list);

    const activeRow = rows.find((row) => row.item_id === activeBatchCandidateItemId);
    if (activeRow && fieldValue(activeRow.status) === "FOUND") {
      const choices = renderBatchCandidateChoices(activeRow);
      if (choices) {
        batchParseResult.appendChild(choices);
        requestAnimationFrame(positionBatchCandidatePopover);
      }
    } else if (activeBatchCandidateItemId) {
      activeBatchCandidateItemId = null;
    }

    if (batchAcceptToolbar) {
      batchAcceptToolbar.hidden = false;
    }
    updateBatchAcceptToolbar();
  }

  async function parseBatchDraft(event) {
    event.preventDefault();
    clearBatchParseError();
    let payload;
    try {
      payload = buildBatchParsePayload();
    } catch (validationError) {
      setBatchParseError(
        validationError.message || "批量草案表单校验失败。",
        validationError.field,
      );
      setBatchParseResult(
        "请修正批量输入后再获取草案。",
        "error-state compact-state",
      );
      return;
    }

    setBatchParseInFlight(true);
    const itemCount = payload.raw_input
      .split(/\r?\n/)
      .filter((line) => line.trim()).length;
    setBatchParseResult(
      "正在搜索 " + itemCount + " 个批量条目的 MiKan 候选...",
      "loading-state compact-state",
    );
    try {
      const result = await fetchJson("/api/v1/batches/parse", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const items = (result && result.items) || [];
      currentBatchId = (result && result.batch_id) || null;
      syncBatchIdToUrl(currentBatchId);
      selectedBatchItemIds = new Set();
      batchAcceptInFlight = false;
      activeBatchCandidateItemId = null;
      clearBatchDetailContext();
      batchDraftCards = Array.isArray(items) ? items.slice() : [];
      renderBatchParseItems(batchDraftCards);
      await loadBatchQueue();
      showNotification(
        "success",
        "批量搜索完成",
        "已返回 " + items.length + " 个条目的候选搜索状态。",
      );
    } catch (error) {
      setBatchParseResult(
        "批量草案获取失败。请稍后重试。",
        "error-state compact-state",
      );
      notifyApiError("批量草案获取失败", error);
    } finally {
      setBatchParseInFlight(false);
    }
  }

  if (batchParseForm) {
    batchParseForm.addEventListener("submit", parseBatchDraft);
  }

  document.addEventListener("click", function (event) {
    if (!activeBatchCandidateItemId || !(event.target instanceof Element)) {
      return;
    }
    if (event.target.closest("#batch-candidate-choices, .batch-card-expand")) {
      return;
    }
    closeBatchCandidatePopover();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && activeBatchCandidateItemId) {
      event.preventDefault();
      closeBatchCandidatePopover();
    }
  });

  window.addEventListener("resize", positionBatchCandidatePopover);
  window.addEventListener("scroll", positionBatchCandidatePopover, true);

  if (batchSelectAllCheckbox) {
    batchSelectAllCheckbox.addEventListener("change", function () {
      setAllBatchItemsSelected(batchSelectAllCheckbox.checked);
    });
  }

  if (batchAcceptSubmit) {
    batchAcceptSubmit.addEventListener("click", function () {
      const selectedRows = batchDraftCards.filter((row) =>
        selectedBatchItemIds.has(row.item_id),
      );
      if (!selectedRows.length || batchAcceptInFlight) {
        return;
      }
      if (
        window.confirm(
          "确认接受选中的 " + selectedRows.length + " 个批量卡片？",
        )
      ) {
        submitBatchAccept(selectedRows, {itemIds: Array.from(selectedBatchItemIds)});
      }
    });
  }

  if (batchAcceptAll) {
    batchAcceptAll.addEventListener("click", function () {
      const selectable = batchDraftCards.filter(batchCardIsSelectable);
      if (!selectable.length || batchAcceptInFlight) {
        return;
      }
      if (window.confirm("确认接受全部批量卡片？")) {
        submitBatchAccept(batchDraftCards, {});
      }
    });
  }

  // ---------------------------------------------------------------------
  // Stage 20 batch pre-submission queue result panel (US-147)
  // ---------------------------------------------------------------------

  function batchIdFromLocation() {
    const params = new URLSearchParams(window.location.search);
    return (params.get("batch_id") || "").trim();
  }

  function syncBatchIdToUrl(batchId) {
    if (!window.history || !window.history.pushState) {
      return;
    }
    const url = new URL(window.location.href);
    if (batchId) {
      url.searchParams.set("batch_id", batchId);
    } else {
      url.searchParams.delete("batch_id");
    }
    if (url.href === window.location.href) {
      return;
    }
    window.history.pushState({batch_id: batchId || null}, "", url);
  }

  function batchQueueStatusLabel(status) {
    const labels = {
      READY_TO_SUBMIT: "待提交",
      SUBMITTING: "提交中",
      SUCCEEDED: "提交成功",
      FAILED: "提交失败",
      RETRYABLE: "可重试",
      RESULT_PERSIST_FAILED: "结果保存失败",
    };
    const value = fieldValue(status);
    return Object.prototype.hasOwnProperty.call(labels, value)
      ? labels[value]
      : value;
  }

  function batchQueueStatusClass(status) {
    const classes = {
      READY_TO_SUBMIT: "ready",
      SUBMITTING: "submitting",
      SUCCEEDED: "succeeded",
      FAILED: "failed",
      RETRYABLE: "retryable",
      RESULT_PERSIST_FAILED: "result-persist-failed",
    };
    return Object.prototype.hasOwnProperty.call(classes, status)
      ? classes[status]
      : "ready";
  }

  function batchQueueItemSummary(item) {
    if (item.ab_result_summary) {
      return "结果：" + safeText(item.ab_result_summary);
    }
    if (item.last_error) {
      return "错误：" + safeText(item.last_error);
    }
    return "尚无结果摘要";
  }

  function renderBatchQueueItem(item) {
    const row = document.createElement("div");
    row.className = "batch-queue-item";
    row.dataset.itemId = safeText(item.item_id);

    const statusRow = document.createElement("div");
    statusRow.className = "batch-queue-item-status-row";
    const status = document.createElement("span");
    status.className =
      "batch-status batch-queue-status batch-queue-status-" +
      batchQueueStatusClass(item.status);
    status.textContent = batchQueueStatusLabel(item.status);
    statusRow.appendChild(status);
    // SUCCEEDED / READY 项目不提供操作入口；FAILED / RETRYABLE 提供重试；
    // SUBMITTING / RESULT_PERSIST_FAILED 提供恢复（人工核验或自动恢复）。
    if (item.status === "FAILED" || item.status === "RETRYABLE") {
      const retryButton = document.createElement("button");
      retryButton.className = "secondary-button batch-queue-item-retry";
      retryButton.type = "button";
      retryButton.textContent = "重试";
      retryButton.setAttribute("data-request-id", safeText(item.request_id));
      retryButton.addEventListener("click", function () {
        retryBatchQueueItem(item);
      });
      statusRow.appendChild(retryButton);
    }
    if (
      item.status === "SUBMITTING" ||
      item.status === "RESULT_PERSIST_FAILED"
    ) {
      const recoverButton = document.createElement("button");
      recoverButton.className = "secondary-button batch-queue-item-recover";
      recoverButton.type = "button";
      recoverButton.textContent = "恢复";
      recoverButton.setAttribute("data-request-id", safeText(item.request_id));
      recoverButton.addEventListener("click", function () {
        recoverBatchQueueItem(item);
      });
      statusRow.appendChild(recoverButton);
    }
    row.appendChild(statusRow);

    const title = document.createElement("strong");
    title.className = "batch-queue-item-title";
    title.textContent = safeText(item.title || "未命名订阅方案");
    row.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "batch-queue-item-meta";
    meta.textContent =
      "尝试次数：" + safeText(item.attempts) +
      "；更新于：" + safeText(item.updated_at || "未记录");
    row.appendChild(meta);

    const summary = document.createElement("div");
    summary.className = "batch-queue-item-summary";
    summary.textContent = batchQueueItemSummary(item);
    row.appendChild(summary);

    return row;
  }

  function renderBatchQueuePanel() {
    if (!batchQueueList) {
      return;
    }
    const items = Array.isArray(batchQueueItems) ? batchQueueItems : [];
    if (batchQueueCount) {
      batchQueueCount.textContent = "队列中 " + items.length + " 项";
    }
    if (batchQueueRefresh) {
      batchQueueRefresh.disabled = !currentBatchId;
    }
    if (!items.length) {
      batchQueueList.className = "empty-state";
      batchQueueList.replaceChildren();
      batchQueueList.textContent =
        "暂无队列项目。接受批量卡片后，此处会显示提交前队列。";
      if (batchQueueSubmitForm) {
        batchQueueSubmitForm.hidden = true;
      }
      return;
    }
    batchQueueList.className = "batch-queue-list";
    batchQueueList.replaceChildren();
    const list = document.createElement("div");
    list.className = "batch-queue-grid";
    for (const item of items) {
      list.appendChild(renderBatchQueueItem(item));
    }
    batchQueueList.appendChild(list);
    if (batchQueueSubmitForm) {
      batchQueueSubmitForm.hidden = false;
    }
  }

  async function loadBatchQueue() {
    if (!currentBatchId) {
      batchQueueItems = [];
      renderBatchQueuePanel();
      return;
    }
    try {
      const result = await fetchJson(
        apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/queue"),
      );
      const queue = result && result.queue;
      batchQueueItems = queue && Array.isArray(queue.items) ? queue.items.slice() : [];
    } catch (error) {
      batchQueueItems = [];
      setBatchQueueSubmitResult("队列读取失败。请稍后重试。", "error-state compact-state");
    }
    renderBatchQueuePanel();
  }

  function applyQueueResult(queue) {
    const items = queue && Array.isArray(queue.items) ? queue.items.slice() : [];
    batchQueueItems = items;
    renderBatchQueuePanel();
  }

  function syncQueueStatusToCards(queueItems) {
    for (const qItem of queueItems) {
      batchDraftCards = batchDraftCards.map((row) => {
        if (row.item_id !== qItem.item_id || row.status !== "ACCEPTED") {
          return row;
        }
        const next = Object.assign({}, row);
        next.queue_status = qItem.status;
        return next;
      });
    }
  }

  function setBatchQueueSubmitError(message, field) {
    if (!batchQueueAbError) {
      return;
    }
    batchQueueAbError.textContent = message;
    batchQueueAbError.hidden = false;
    for (const input of [
      batchQueueAbBaseUrlInput,
      batchQueueAbUsernameInput,
      batchQueueAbPasswordInput,
      batchQueueAbTokenInput,
      batchQueueAbConfirmInput,
    ]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
    if (field) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  function clearBatchQueueSubmitError() {
    if (!batchQueueAbError) {
      return;
    }
    batchQueueAbError.textContent = "";
    batchQueueAbError.hidden = true;
    for (const input of [
      batchQueueAbBaseUrlInput,
      batchQueueAbUsernameInput,
      batchQueueAbPasswordInput,
      batchQueueAbTokenInput,
      batchQueueAbConfirmInput,
    ]) {
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    }
  }

  function setBatchQueueSubmitResult(message, className) {
    if (!batchQueueSubmitResult) {
      return;
    }
    batchQueueSubmitResult.className = className || "empty-state compact-state";
    batchQueueSubmitResult.replaceChildren();
    batchQueueSubmitResult.textContent = message;
  }

  function clearBatchQueueSensitiveFields() {
    clearAbSensitiveFields("batch-queue-ab", batchQueueAbConfirmInput);
  }

  function setBatchQueueInFlight(isInFlight) {
    if (batchQueueSubmitForm) {
      for (const control of batchQueueSubmitForm.querySelectorAll("button, input")) {
        control.disabled = isInFlight;
      }
    }
    if (batchQueueList) {
      for (const button of batchQueueList.querySelectorAll(".batch-queue-item-retry")) {
        button.disabled = isInFlight;
      }
    }
    if (batchQueueSubmitButton) {
      batchQueueSubmitButton.textContent = isInFlight ? "正在提交..." : "提交队列";
    }
  }

  function batchQueueSummaryMessage(summary) {
    const succeeded = summary.succeeded || 0;
    const failed = summary.failed || 0;
    const retryable = summary.retryable || 0;
    const skipped = summary.skipped || 0;
    let message = "提交成功 " + succeeded + " 项";
    if (failed) {
      message += "；提交失败 " + failed + " 项";
    }
    if (retryable) {
      message += "；可重试 " + retryable + " 项";
    }
    if (skipped) {
      message += "；跳过 " + skipped + " 项";
    }
    return message;
  }

  function showBatchQueueSubmitNotification(summary) {
    const message = batchQueueSummaryMessage(summary);
    const succeeded = summary.succeeded || 0;
    const failed = summary.failed || 0;
    const retryable = summary.retryable || 0;
    if (succeeded === 0 && (failed > 0 || retryable > 0)) {
      showNotification("error", "批量提交失败", message);
    } else if (failed > 0 || retryable > 0) {
      showNotification("success", "批量提交完成", message);
    } else {
      showNotification("success", "批量提交成功", message);
    }
  }

  async function submitBatchQueue(event) {
    event.preventDefault();
    clearBatchQueueSubmitError();
    if (!currentBatchId) {
      setBatchQueueSubmitError("缺少批次标识，无法提交队列。");
      return;
    }
    const confirm = batchQueueAbConfirmInput ? batchQueueAbConfirmInput.checked : false;
    let abConfig;
    try {
      abConfig = buildAbConfig("batch-queue-ab");
    } catch (validationError) {
      setBatchQueueSubmitError(validationError.message, validationError.field);
      return;
    }
    if (!confirm) {
      setBatchQueueSubmitError("请勾选确认后再提交到 Auto Bangumi。", batchQueueAbConfirmInput);
      return;
    }

    setBatchQueueInFlight(true);
    setBatchQueueSubmitResult("正在提交队列到 Auto Bangumi...", "loading-state compact-state");
    try {
      const result = await fetchJson(
        apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/submit"),
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            storage_dir: currentStorageDir() || null,
            ab_config: abConfig,
            confirm: true,
          }),
        },
      );
      const summary = (result && result.summary) || {};
      clearBatchQueueSensitiveFields();
      applyQueueResult(result && result.queue);
      syncQueueStatusToCards(batchQueueItems);
      if (batchDraftCards.length) {
        renderBatchParseItems(batchDraftCards);
      }
      setBatchQueueSubmitResult(
        batchQueueSummaryMessage(summary),
        "success-state compact-state",
      );
      showBatchQueueSubmitNotification(summary);
    } catch (error) {
      setBatchQueueSubmitResult(
        "Auto Bangumi 批量提交失败。请检查配置与订阅方案状态后重试。",
        "error-state compact-state",
      );
      notifyApiError("批量提交失败", error);
    } finally {
      setBatchQueueInFlight(false);
    }
  }

  async function retryBatchQueueItem(item) {
    clearBatchQueueSubmitError();
    if (!currentBatchId) {
      setBatchQueueSubmitError("缺少批次标识，无法重试。");
      return;
    }
    const confirm = batchQueueAbConfirmInput ? batchQueueAbConfirmInput.checked : false;
    let abConfig;
    try {
      abConfig = buildAbConfig("batch-queue-ab");
    } catch (validationError) {
      setBatchQueueSubmitError(validationError.message, validationError.field);
      return;
    }
    if (!confirm) {
      setBatchQueueSubmitError("请勾选确认后再提交到 Auto Bangumi。", batchQueueAbConfirmInput);
      return;
    }

    setBatchQueueInFlight(true);
    setBatchQueueSubmitResult(
      "正在重试到 Auto Bangumi...",
      "loading-state compact-state",
    );
    try {
      const result = await fetchJson(
        apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/retry"),
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            storage_dir: currentStorageDir() || null,
            request_id: item.request_id,
            ab_config: abConfig,
            confirm: true,
          }),
        },
      );
      const summary = (result && result.summary) || {};
      clearBatchQueueSensitiveFields();
      applyQueueResult(result && result.queue);
      syncQueueStatusToCards(batchQueueItems);
      if (batchDraftCards.length) {
        renderBatchParseItems(batchDraftCards);
      }
      setBatchQueueSubmitResult(
        batchQueueSummaryMessage(summary),
        "success-state compact-state",
      );
      showBatchQueueSubmitNotification(summary);
    } catch (error) {
      setBatchQueueSubmitResult(
        "Auto Bangumi 单项重试失败。请检查配置与订阅方案状态后重试。",
        "error-state compact-state",
      );
      notifyApiError("单项重试失败", error);
    } finally {
      setBatchQueueInFlight(false);
    }
  }

  async function recoverBatchQueueItem(item) {
    clearBatchQueueSubmitError();
    if (!currentBatchId) {
      setBatchQueueSubmitError("缺少批次标识，无法恢复。");
      return;
    }
    setBatchQueueInFlight(true);
    setBatchQueueSubmitResult("正在恢复队列项目...", "loading-state compact-state");
    try {
      // 先尝试自动恢复（仅 SUBMITTING 且 Request 已保存结果时生效）。
      let result = await fetchJson(
        apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/recover"),
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            storage_dir: currentStorageDir() || null,
            request_id: item.request_id,
            action: "auto",
          }),
        },
      );
      let outcome = result && result.items && result.items[0];
      if (outcome && outcome.status === "needs_manual") {
        // 自动恢复无法判定：请用户人工核验 Auto Bangumi 是否已创建订阅。
        const created = window.confirm(
          "该订阅方案处于「" + batchQueueStatusLabel(item.status) +
          "」，无法自动判断 Auto Bangumi 是否已创建订阅。\n\n" +
          "请前往 Auto Bangumi 核对后选择：\n" +
          "点击「确定」= 已创建订阅（标记为提交成功）\n" +
          "点击「取消」= 未创建订阅（标记为失败，可重试）",
        );
        result = await fetchJson(
          apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/recover"),
          {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              storage_dir: currentStorageDir() || null,
              request_id: item.request_id,
              action: created ? "succeeded" : "failed",
              confirm: true,
            }),
          },
        );
        outcome = result && result.items && result.items[0];
      }
      const summary = (result && result.summary) || {};
      applyQueueResult(result && result.queue);
      syncQueueStatusToCards(batchQueueItems);
      if (batchDraftCards.length) {
        renderBatchParseItems(batchDraftCards);
      }
      setBatchQueueSubmitResult(
        batchQueueSummaryMessage(summary),
        "success-state compact-state",
      );
      showBatchQueueSubmitNotification(summary);
    } catch (error) {
      setBatchQueueSubmitResult(
        "队列项目恢复失败。请核对 Auto Bangumi 状态后重试。",
        "error-state compact-state",
      );
      notifyApiError("恢复失败", error);
    } finally {
      setBatchQueueInFlight(false);
    }
  }

  if (batchQueueSubmitForm) {
    batchQueueSubmitForm.addEventListener("submit", submitBatchQueue);
  }
  syncAbAuthMode("batch-queue-ab");
  if (batchQueueAbAuthModeInput) {
    batchQueueAbAuthModeInput.addEventListener("change", () => syncAbAuthMode("batch-queue-ab"));
  }
  if (batchQueueAbTokenInput) batchQueueAbTokenInput.addEventListener("input", () => {
    if (batchQueueAbTokenInput.value && batchQueueAbAuthModeInput && batchQueueAbAuthModeInput.value === "password") {
      batchQueueAbAuthModeInput.value = "api_token";
      syncAbAuthMode("batch-queue-ab");
    }
  });
  if (batchQueueRefresh) {
    batchQueueRefresh.addEventListener("click", function () {
      loadBatchQueue();
    });
  }
  if (batchIdFromLocation()) {
    currentBatchId = batchIdFromLocation();
    loadBatchQueue();
  } else {
    renderBatchQueuePanel();
  }

  function setCandidateSearchError(message, field) {
    if (!candidateSearchError) {
      return;
    }
    candidateSearchError.textContent = message;
    candidateSearchError.hidden = false;
    if (candidateQueryInput) {
      candidateQueryInput.removeAttribute("aria-invalid");
    }
    if (field) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  function clearCandidateSearchError() {
    if (!candidateSearchError) {
      return;
    }
    candidateSearchError.textContent = "";
    candidateSearchError.hidden = true;
    if (candidateQueryInput) {
      candidateQueryInput.removeAttribute("aria-invalid");
    }
  }

  function setCandidateSearchResult(message, className) {
    if (!candidateSearchResult) {
      return;
    }
    candidateSearchResult.className = className || "empty-state compact-state";
    candidateSearchResult.replaceChildren();
    candidateSearchResult.textContent = message;
  }

  function candidateAreaControls() {
    const controls = [];
    if (candidateFallbackEnabled) {
      controls.push(candidateFallbackEnabled);
    }
    for (const form of [candidateSearchForm, candidateFallbackForm]) {
      if (!form) {
        continue;
      }
      for (const control of form.querySelectorAll("button, input")) {
        controls.push(control);
      }
    }
    return controls;
  }

  function syncCandidateFallbackVisibility() {
    if (!candidateFallbackForm || !candidateFallbackEnabled) {
      return;
    }
    candidateFallbackForm.hidden = !candidateFallbackEnabled.checked;
    if (!candidateFallbackEnabled.checked) {
      clearCandidateFallbackError();
    }
  }

  function setCandidateSearchInFlight(isInFlight) {
    setSearchWorkspaceInFlight(isInFlight);
    if (candidateSearchSubmit) {
      candidateSearchSubmit.textContent = isInFlight ? "正在搜索..." : "搜索候选";
    }
  }

  function setCandidateFallbackInFlight(isInFlight) {
    for (const control of candidateAreaControls()) {
      control.disabled = isInFlight;
    }
    if (candidateFallbackGenerate) {
      candidateFallbackGenerate.textContent = isInFlight
        ? "正在生成..."
        : "使用直连合集生成";
    }
  }

  function setCandidateFallbackError(message, field) {
    if (!candidateFallbackError) {
      return;
    }
    candidateFallbackError.textContent = message;
    candidateFallbackError.hidden = false;
    if (candidateFallbackInput) {
      candidateFallbackInput.removeAttribute("aria-invalid");
    }
    if (field) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  function clearCandidateFallbackError() {
    if (!candidateFallbackError) {
      return;
    }
    candidateFallbackError.textContent = "";
    candidateFallbackError.hidden = true;
    if (candidateFallbackInput) {
      candidateFallbackInput.removeAttribute("aria-invalid");
    }
  }

  function buildCandidateSearchPayload() {
    const query = candidateQueryInput ? candidateQueryInput.value.trim() : "";
    if (!query) {
      const error = new Error("搜索 MiKan 候选前必须填写番剧标题。");
      error.field = candidateQueryInput;
      throw error;
    }
    // The Web API falls back to the system-default MiKan config when no
    // request-scoped config is sent, so the UI only needs the anime title.
    return {query: query};
  }

  function renderCandidateCard(candidate, options) {
    const opts = options || {};
    const item = document.createElement("li");
    item.className = "candidate-card";

    const title = document.createElement("strong");
    title.textContent = safeText(candidate.title) || "未命名合集";
    item.appendChild(title);

    // Display-only recommendation label (e.g. 推荐：第 2 季 / 季数不符 /
    // 可能匹配). It only annotates the card; it never selects the candidate
    // or triggers Request generation.
    if (candidate.recommendation) {
      const badge = document.createElement("span");
      badge.className = "candidate-recommendation";
      badge.textContent = safeText(candidate.recommendation);
      item.appendChild(badge);
    }

    const meta = document.createElement("div");
    meta.className = "candidate-meta";
    meta.textContent = "MiKan ID: " + safeText(candidate.bangumi_id);
    item.appendChild(meta);

    const progress = document.createElement("div");
    progress.className = "candidate-progress";
    const totalEpisodes = candidate.total_episodes;
    progress.textContent =
      "播出进度：待开发 / " +
      (Number.isInteger(totalEpisodes) && totalEpisodes > 0 ? totalEpisodes + " 集" : "未知");
    item.appendChild(progress);

    if (candidate.poster_url) {
      const poster = document.createElement("img");
      poster.className = "candidate-poster";
      poster.alt = "";
      poster.src = candidate.poster_url;
      poster.loading = "lazy";
      poster.decoding = "async";
      poster.addEventListener("error", () => {
        const placeholder = document.createElement("div");
        placeholder.className = "candidate-poster candidate-poster-placeholder";
        placeholder.textContent = "暂无封面";
        poster.replaceWith(placeholder);
      }, {once: true});
      item.appendChild(poster);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "candidate-poster candidate-poster-placeholder";
      placeholder.textContent = "暂无封面";
      item.appendChild(placeholder);
    }

    const source = document.createElement("div");
    source.className = "candidate-source";
    source.textContent = "搜索词：" + safeText(candidate.source_query || opts.query);
    item.appendChild(source);

    const seasonEvidence = candidate && candidate.season_evidence;
    if (seasonEvidence && seasonEvidence.status === "NEEDS_CONFIRMATION") {
      const season = Number(seasonEvidence.season);
      const label = document.createElement("label");
      label.className = "candidate-season-confirmation";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.addEventListener("change", function () {
        candidate.season_confirmation = input.checked && season >= 1 && season <= 99
          ? season
          : null;
      });
      label.append(
        input,
        document.createTextNode(" 我确认此合集为第" + season + "季（候选标题未提供季数证据）"),
      );
      item.appendChild(label);
    } else if (seasonEvidence && seasonEvidence.status === "CONFLICT") {
      const warning = document.createElement("p");
      warning.className = "candidate-season-conflict";
      warning.textContent = "候选合集季数与搜索识别结果冲突，请先人工核对。";
      item.appendChild(warning);
      if (opts.chooseButton) {
        opts.chooseButton.disabled = true;
      }
    }

    if (opts.chooseButton) {
      item.appendChild(opts.chooseButton);
    }
    return item;
  }

  function renderCandidateCards(candidates, query, searchResult) {
    const cards = Array.isArray(candidates) ? candidates : [];
    if (!cards.length) {
      setCandidateSearchResult(
        "未找到候选合集。可调整番剧标题后重试，或勾选「搜索无结果时使用直连合集」直接生成订阅草案。",
        "empty-state compact-state",
      );
      return;
    }

    candidateSearchResult.className = "candidate-list-wrapper";
    candidateSearchResult.replaceChildren();

    const list = document.createElement("ul");
    list.className = "candidate-list";
    for (const candidate of cards) {
      const chooseButton = document.createElement("button");
      chooseButton.type = "button";
      chooseButton.className = "primary-button candidate-select";
      chooseButton.textContent = "选择此合集";
      chooseButton.addEventListener("click", () => {
        generateRequestFromCandidate(candidate);
      });
      list.appendChild(renderCandidateCard(candidate, {query: query, chooseButton: chooseButton}));
    }
    const parseSummary = renderTitleParseSummary(searchResult);
    if (parseSummary) {
      candidateSearchResult.appendChild(parseSummary);
    }
    candidateSearchResult.appendChild(list);
  }

  async function searchMikanCandidates(event) {
    event.preventDefault();
    clearCandidateSearchError();
    let payload;
    try {
      payload = buildCandidateSearchPayload();
    } catch (validationError) {
      setCandidateSearchError(
        validationError.message || "候选搜索表单校验失败。",
        validationError.field,
      );
      setCandidateSearchResult(
        "请修正候选搜索表单后再搜索。",
        "error-state compact-state",
      );
      return;
    }

    setCandidateSearchInFlight(true);
    setCandidateSearchResult(
      "正在搜索「" + payload.query + "」的 MiKan 候选...",
      "loading-state compact-state",
    );
    try {
      const result = await fetchJson("/api/v1/mikan/candidates", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const candidates = (result && result.candidates) || [];
      renderCandidateCards(candidates, result.query || payload.query, result);
      showNotification(
        "success",
        candidates.length ? "候选搜索完成" : "未找到候选合集",
        candidates.length
          ? "找到 " + candidates.length + " 个候选合集。"
          : "可调整番剧标题后重试。",
      );
    } catch (error) {
      setCandidateSearchResult(
        "候选搜索失败。请稍后重试。",
        "error-state compact-state",
      );
      notifyApiError("候选搜索失败", error);
    } finally {
      setCandidateSearchInFlight(false);
    }
  }

  if (candidateSearchForm) {
    candidateSearchForm.addEventListener("submit", searchMikanCandidates);
  }

  if (candidateFallbackForm) {
    candidateFallbackForm.addEventListener("submit", generateRequestFromFallback);
  }

  if (candidateFallbackEnabled) {
    candidateFallbackEnabled.addEventListener(
      "change",
      syncCandidateFallbackVisibility,
    );
  }

  wireSearchModeTabs();

  function setCandidateSelectionInFlight(isInFlight) {
    const buttons = document.querySelectorAll(".candidate-select");
    for (const button of buttons) {
      button.disabled = isInFlight;
    }
  }

  async function generateRequestFromCandidate(candidate) {
    if (!candidate || !candidate.mikan_url) {
      showNotification(
        "error",
        "生成失败",
        "候选合集缺少 MiKan URL，无法生成订阅方案。",
      );
      return;
    }
    hideNotification();
    setCandidateSelectionInFlight(true);
    setState(detailContainer, "正在从候选生成订阅草案...", "loading-state");
    try {
      const result = await createPreviewDraftFromCandidate(candidate);
      await finalizeGeneratedRequest(result);
    } catch (error) {
      setState(
        detailContainer,
        "从候选生成订阅草案失败。请重试。",
        "error-state",
      );
      notifyApiError("生成失败", error);
    } finally {
      setCandidateSelectionInFlight(false);
    }
  }

  async function createPreviewDraftFromCandidate(candidate) {
    // Both single and batch selection use the existing mikan_bangumi detail
    // parser and preview-modify/save lifecycle. A candidate only contains
    // public metadata; request-scoped configuration remains server-side.
    return fetchJson("/api/v1/requests", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        title: candidate.title || "未命名合集",
        source: "mikan",
        mikan_bangumi: candidate.mikan_url,
        candidate_aliases: Array.isArray(candidate.aliases) ? candidate.aliases : [],
        storage_dir: currentStorageDir() || null,
        save_request: false,
        ...(Number.isInteger(candidate.season_confirmation)
          ? {season_confirmation: candidate.season_confirmation}
          : {}),
      }),
    });
  }

  async function generateBatchRequestFromCandidate(row, candidate) {
    if (!row || fieldValue(row.status) !== "FOUND") {
      return;
    }
    if (!candidate || !candidate.mikan_url) {
      showNotification("error", "生成失败", "候选合集缺少 MiKan URL，无法生成订阅草案。");
      return;
    }
    setBatchAcceptInFlight(true);
    try {
      const result = await createPreviewDraftFromCandidate(candidate);
      const request = result && result.request;
      if (!request) {
        throw new Error("candidate preview returned no request");
      }
      batchDraftCards = batchDraftCards.map(function (current) {
        if (current.item_id !== row.item_id) {
          return current;
        }
        return Object.assign({}, current, {
          status: "DRAFT",
          preview_request: request,
          selected_candidate: candidate,
        });
      });
      renderBatchParseItems(batchDraftCards);
      showNotification(
        "success",
        "订阅草案已生成",
        "已根据所选 MiKan 合集生成当前批量条目的订阅草案。",
      );
    } catch (error) {
      notifyApiError("生成订阅草案失败", error);
    } finally {
      setBatchAcceptInFlight(false);
    }
  }

  async function generateRequestFromFallback(event) {
    event.preventDefault();
    clearCandidateFallbackError();
    const fallbackValue = candidateFallbackInput
      ? candidateFallbackInput.value.trim()
      : "";
    if (!fallbackValue) {
      setCandidateFallbackError(
        "生成前必须填写 MiKan 合集 URL 或 ID。",
        candidateFallbackInput,
      );
      return;
    }
    // Local sanity check only: the server enforces origin/path/ID rules and
    // returns the unified sanitized error for wrong-origin or wrong-path URLs.
    const isBareId = /^[0-9]+$/.test(fallbackValue);
    const isHttpUrl = /^https?:\/\//i.test(fallbackValue);
    if (!isBareId && !isHttpUrl) {
      setCandidateFallbackError(
        "必须是数字 ID 或 HTTP(S) URL。",
        candidateFallbackInput,
      );
      return;
    }

    const query = candidateQueryInput ? candidateQueryInput.value.trim() : "";
    hideNotification();
    setCandidateFallbackInFlight(true);
    setState(
      detailContainer,
      "正在从直连 MiKan 合集生成订阅草案...",
      "loading-state",
    );
    try {
      // No request-scoped MiKan config is sent: the server falls back to the
      // system default, so the fallback works without a user-supplied endpoint.
      // Direct fallback also produces an editable preview draft (save_request=false).
      const result = await fetchJson("/api/v1/requests", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: query || "MiKan 直连合集",
          source: "mikan",
          mikan_bangumi: fallbackValue,
          storage_dir: currentStorageDir() || null,
          save_request: false,
        }),
      });
      await finalizeGeneratedRequest(result);
      if (candidateFallbackInput) {
        candidateFallbackInput.value = "";
      }
    } catch (error) {
      setState(
        detailContainer,
        "从直连 MiKan 合集生成订阅草案失败。请重试。",
        "error-state",
      );
      notifyApiError("生成失败", error);
    } finally {
      setCandidateFallbackInFlight(false);
    }
  }

  function buildCreateRequestPayload(title, options) {
    const saveRequest =
      options && Object.prototype.hasOwnProperty.call(options, "saveRequest")
        ? Boolean(options.saveRequest)
        : currentSaveRequest();
    return {
      title: title,
      source: "static-fixture",
      storage_dir: currentStorageDir() || null,
      save_request: saveRequest,
    };
  }

  function requestLabel(summary) {
    return (
      summary.bangumi_title ||
      summary.request_id ||
      summary.selected_subtitle_group ||
      "未命名订阅方案"
    );
  }

  function searchableText(summary) {
    return [
      summary.bangumi_title,
      summary.request_id,
      summary.selected_subtitle_group,
      summary.expected_folder_name,
      summary.folder_name,
    ]
      .map((value) => fieldValue(value).toLowerCase())
      .join(" ");
  }

  function summaryStatus(summary) {
    return fieldValue(summary.status);
  }

  function syncStatusFilterOptions(requests) {
    const selectedStatus = listStatusFilter.value;
    const statuses = Array.from(new Set(requests.map(summaryStatus))).sort((a, b) =>
      a.localeCompare(b, "zh-CN"),
    );
    listStatusFilter.replaceChildren();

    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "全部";
    listStatusFilter.appendChild(allOption);

    for (const status of statuses) {
      const option = document.createElement("option");
      option.value = status;
      option.textContent = statusLabel(status);
      listStatusFilter.appendChild(option);
    }

    if (statuses.includes(selectedStatus)) {
      listStatusFilter.value = selectedStatus;
    }
  }

  function filteredAndSortedRequests() {
    const searchTerm = listSearchInput.value.trim().toLowerCase();
    const selectedStatus = listStatusFilter.value;
    let requests = loadedRequests.filter((summary) => {
      const matchesSearch = !searchTerm || searchableText(summary).includes(searchTerm);
      const matchesStatus =
        !selectedStatus || summaryStatus(summary) === selectedStatus;
      return matchesSearch && matchesStatus;
    });

    if (listSortSelect.value === "title_asc") {
      requests = requests.slice().sort((a, b) =>
        requestLabel(a).localeCompare(requestLabel(b), "zh-CN"),
      );
    } else if (listSortSelect.value === "request_id_asc") {
      requests = requests.slice().sort((a, b) =>
        fieldValue(a.request_id).localeCompare(fieldValue(b.request_id), "zh-CN"),
      );
    }

    return requests;
  }

  function renderList() {
    const requests = filteredAndSortedRequests();
    listCount.textContent = "显示 " + requests.length + " / " + loadedRequests.length;

    listContainer.className = "request-list";
    listContainer.replaceChildren();
    if (!loadedRequests.length) {
      setState(listContainer, "暂无已保存的订阅方案。", "empty-state");
      return;
    }
    if (!requests.length) {
      setState(listContainer, "没有匹配的订阅方案。清空搜索或筛选后可恢复列表。", "empty-state");
      return;
    }

    for (const summary of requests) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "request-list-item";
      item.dataset.requestId = summary.request_id || "";
      item.setAttribute("aria-label", "查看订阅方案详情：" + requestLabel(summary));
      if (summary.request_id === selectedRequestId) {
        item.classList.add("is-selected");
        item.setAttribute("aria-current", "true");
      }

      const title = document.createElement("strong");
      title.textContent = requestLabel(summary);

      const meta = document.createElement("span");
      meta.textContent = [
        statusLabel(summary.status),
        fieldValue(summary.selected_subtitle_group),
        fieldValue(summary.expected_folder_name),
      ].join(" / ");

      item.append(title, meta);
      item.addEventListener("click", () => {
        selectRequest(summary.request_id, {pushUrl: true});
      });
      listContainer.appendChild(item);
    }
  }

  async function loadList(options) {
    const detailRequestId = selectedRequestId;
    hideNotification();
    setState(listContainer, "正在加载订阅方案列表...", "loading-state");
    try {
      const result = await fetchJson(apiPath("/api/v1/requests"));
      loadedRequests = result.requests || [];
      syncStatusFilterOptions(loadedRequests);
      renderList();
      if (detailRequestId && !(options && options.loadSelectedDetail === false)) {
        loadDetail(detailRequestId);
      }
    } catch (error) {
      setState(listContainer, error.message, "error-state");
      notifyApiError("订阅方案列表加载失败", error);
    }
  }

  function addDetailRow(list, label, value) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = displayValue(value);
    list.append(term, description);
  }

  function createDetailSection(title, className) {
    const section = document.createElement("section");
    section.className = "detail-section " + className;
    const heading = document.createElement("h4");
    heading.textContent = title;
    section.appendChild(heading);
    return section;
  }

  function detailList(rows) {
    const fields = document.createElement("dl");
    fields.className = "detail-grid";
    for (const [label, value] of rows) {
      addDetailRow(fields, label, value);
    }
    return fields;
  }

  function copyTextToClipboard(value) {
    if (!value || !navigator.clipboard || !navigator.clipboard.writeText) {
      return;
    }
    navigator.clipboard.writeText(String(value)).catch(() => {});
  }

  function renderSeedList(container, seeds, emptyText) {
    if (!Array.isArray(seeds) || !seeds.length) {
      const empty = document.createElement("p");
      empty.className = "muted-text";
      empty.textContent = emptyText || "无有效种子标题。";
      container.appendChild(empty);
      return;
    }

    const list = document.createElement("ul");
    list.className = "seed-list";
    for (const seed of seeds) {
      const item = document.createElement("li");
      item.textContent = displayValue(seed);
      list.appendChild(item);
    }
    container.appendChild(list);
  }

  function renderExcludedSeedList(container, seeds) {
    if (!Array.isArray(seeds) || !seeds.length) {
      const empty = document.createElement("p");
      empty.className = "muted-text";
      empty.textContent = "无排除种子标题。";
      container.appendChild(empty);
      return;
    }

    const list = document.createElement("ul");
    list.className = "seed-list excluded-seed-list";
    for (const seed of seeds) {
      const item = document.createElement("li");
      const name = seed && seed.name ? seed.name : seed;
      const reason = seed && seed.reason ? seed.reason : "";
      item.textContent = displayValue(name);
      if (reason) {
        const reasonText = document.createElement("span");
        reasonText.className = "seed-exclude-reason";
        reasonText.textContent = " - " + reason;
        item.appendChild(reasonText);
      }
      list.appendChild(item);
    }
    container.appendChild(list);
  }

  function selectedRssSource(sourceInfo, config) {
    const rssSources = (sourceInfo && sourceInfo.rss_sources) || [];
    const selectedGroup = config && config.selected_subtitle_group;
    for (const source of rssSources) {
      if (source.subtitle_group === selectedGroup) {
        return source;
      }
    }
    return rssSources.length ? rssSources[0] : {};
  }

  function combinedSeedNames(validSeeds, excludedSeeds) {
    const names = [];
    function addName(value) {
      const name = value && value.name ? value.name : value;
      if (name && names.indexOf(name) === -1) {
        names.push(name);
      }
    }
    if (Array.isArray(validSeeds)) {
      validSeeds.forEach(addName);
    }
    if (Array.isArray(excludedSeeds)) {
      excludedSeeds.forEach(addName);
    }
    return names;
  }

  function renderHistorySection(container, history) {
    const section = createDetailSection("状态历史", "audit-section");

    if (history && history.error) {
      const message = document.createElement("p");
      message.className = "muted-text";
      message.textContent = history.error.error_message || "状态历史不可用。";
      section.appendChild(message);
      container.appendChild(section);
      return;
    }

    const events = (history && history.events) || [];
    if (!events.length) {
      const empty = document.createElement("p");
      empty.className = "muted-text";
      empty.textContent = "暂无状态历史。";
      section.appendChild(empty);
      container.appendChild(section);
      return;
    }

    const table = document.createElement("table");
    table.className = "history-table";
    const head = document.createElement("thead");
    head.innerHTML =
      "<tr><th>操作</th><th>前一状态</th><th>后一状态</th><th>时间</th></tr>";
    const body = document.createElement("tbody");
    for (const event of events) {
      const row = document.createElement("tr");
      const columns = [
        actionLabel(event.action),
        statusLabel(event.previous_status),
        statusLabel(event.next_status),
        displayValue(event.timestamp),
      ];
      for (const value of columns) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      }
      body.appendChild(row);
    }
    table.append(head, body);
    section.appendChild(table);
    container.appendChild(section);
  }

  function renderAbResultSection(container, abResult) {
    const section = createDetailSection("Auto Bangumi 结果", "audit-section");

    if (abResult && abResult.error) {
      const message = document.createElement("p");
      message.className = "muted-text";
      message.textContent = abResult.error.error_message || "提交结果不可用。";
      section.appendChild(message);
      container.appendChild(section);
      return;
    }

    const record = abResult && abResult.record;
    const result = record && record.ab_submit_result;
    if (!result) {
      const empty = document.createElement("p");
      empty.className = "muted-text";
      empty.textContent = "暂无 Auto Bangumi 提交结果。";
      section.appendChild(empty);
      container.appendChild(section);
      return;
    }

    const fields = detailList([
      ["success", result.success],
      ["ab_subscription_id", result.ab_subscription_id],
      ["fallback_config", result.fallback_config ? "存在" : "无"],
    ]);
    section.appendChild(fields);

    if (result.fallback_config) {
      const details = document.createElement("details");
      details.className = "fallback-config";
      const summary = document.createElement("summary");
      summary.textContent = "查看 fallback_config";
      const content = document.createElement("pre");
      content.textContent = JSON.stringify(scrubConfig(result.fallback_config), null, 2);
      details.append(summary, content);
      section.appendChild(details);
    }
    container.appendChild(section);
  }

  function setActionInFlight(isInFlight) {
    const buttons = detailContainer.querySelectorAll(".detail-action");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].disabled = isInFlight;
    }
  }

  async function performAction(requestId, actionType, body) {
    if (!requestId) return;
    hideNotification();
    setActionInFlight(true);
    try {
      const result = await fetchJson(
        apiPath("/api/v1/requests/" + encodeURIComponent(requestId) + "/" + actionType),
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(body || {}),
        }
      );
      var titles = {
        accept: "确认成功",
        cancel: "取消成功",
        modify: "修改成功",
        "submit-ab": "Auto Bangumi 提交成功",
      };
      await loadDetail(requestId);
      await loadList({loadSelectedDetail: false});
      showNotification("success", titles[actionType] || "操作成功",
        "订阅方案 " + requestId, {
          actions: [
            { label: "刷新列表", handler: loadList },
          ],
        });
    } catch (error) {
      notifyApiError("操作失败", error);
    } finally {
      setActionInFlight(false);
    }
  }

  async function deleteRequest(requestId) {
    if (!requestId) return;
    hideNotification();
    setActionInFlight(true);
    try {
      await fetchJson(
        apiPath("/api/v1/requests/" + encodeURIComponent(requestId) + "/delete"),
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ storage_dir: currentStorageDir() || null }),
        }
      );
      if (selectedRequestId === requestId) {
        selectedRequestId = null;
      }
      loadedRequests = (loadedRequests || []).filter(function (summary) {
        return summary.request_id !== requestId;
      });
      renderList();
      syncRequestIdToUrl(null);
      setState(detailContainer, "订阅方案已删除。请选择一个订阅方案查看详情。", "empty-state");
      await loadList({loadSelectedDetail: false});
      showNotification("success", "删除成功", "已删除订阅方案 " + requestId, {
        actions: [
          { label: "刷新列表", handler: loadList },
        ],
      });
    } catch (error) {
      notifyApiError("删除失败", error);
    } finally {
      setActionInFlight(false);
    }
  }

  function buildModifyForm(request) {
    var config = request.confirmable_config || {};
    var sourceInfo = request.source_info || {};
    var rssSources = sourceInfo.rss_sources || [];
    var filterRule = config.filter_rule || {};
    var originalGroup = config.selected_subtitle_group || "";
    var originalMustContain = filterRule.must_contain || "";
    var originalMustNotContain = filterRule.must_not_contain || "";
    var originalUseRegex = filterRule.use_regex === true;
    var originalCaseSensitive = filterRule.case_sensitive === true;
    var originalFolderName = config.expected_folder_name || "";

    var container = document.createElement("div");
    container.id = "detail-modify-form";
    container.className = "detail-section detail-inline-form detail-modify-form";
    container.hidden = true;

    var heading = document.createElement("h4");
    heading.textContent = "修改订阅方案";
    container.appendChild(heading);

    var groupLabel = document.createElement("label");
    groupLabel.textContent = "字幕组";
    groupLabel.htmlFor = "modify-subtitle-group";
    var groupSelect = document.createElement("select");
    groupSelect.id = "modify-subtitle-group";
    for (var i = 0; i < rssSources.length; i++) {
      var src = rssSources[i];
      var opt = document.createElement("option");
      opt.value = src.subtitle_group || "";
      opt.textContent = src.subtitle_group || "未知字幕组";
      groupSelect.appendChild(opt);
    }
    groupSelect.value = originalGroup;
    container.appendChild(groupLabel);
    container.appendChild(groupSelect);

    function appendClearControl(id, labelText, targetInput) {
      var wrapper = document.createElement("label");
      wrapper.className = "inline-check";
      wrapper.htmlFor = id;
      var checkbox = document.createElement("input");
      checkbox.id = id;
      checkbox.type = "checkbox";
      checkbox.addEventListener("change", function () {
        targetInput.disabled = checkbox.checked;
        if (checkbox.checked) {
          targetInput.value = "";
        }
      });
      wrapper.append(checkbox, document.createTextNode(labelText));
      return { wrapper: wrapper, checkbox: checkbox };
    }

    var mcLabel = document.createElement("label");
    mcLabel.textContent = "包含规则";
    mcLabel.htmlFor = "modify-must-contain";
    var mcInput = document.createElement("input");
    mcInput.id = "modify-must-contain";
    mcInput.type = "text";
    mcInput.value = originalMustContain;
    mcInput.placeholder = "如 1080p（默认按字面匹配）";
    var mcClear = appendClearControl("modify-clear-must-contain", "清空包含规则", mcInput);
    container.appendChild(mcLabel);
    container.appendChild(mcInput);
    container.appendChild(mcClear.wrapper);

    var mncLabel = document.createElement("label");
    mncLabel.textContent = "排除规则";
    mncLabel.htmlFor = "modify-must-not-contain";
    var mncInput = document.createElement("input");
    mncInput.id = "modify-must-not-contain";
    mncInput.type = "text";
    mncInput.value = originalMustNotContain;
    mncInput.placeholder = "如 [v2]（默认按字面匹配）";
    var mncClear = appendClearControl("modify-clear-must-not-contain", "清空排除规则", mncInput);
    container.appendChild(mncLabel);
    container.appendChild(mncInput);
    container.appendChild(mncClear.wrapper);

    var filterOptions = document.createElement("div");
    filterOptions.className = "filter-options";

    var regexWrapper = document.createElement("label");
    regexWrapper.className = "inline-check filter-option";
    regexWrapper.htmlFor = "modify-filter-use-regex";
    var regexInput = document.createElement("input");
    regexInput.id = "modify-filter-use-regex";
    regexInput.type = "checkbox";
    regexInput.checked = originalUseRegex;
    regexWrapper.append(regexInput, document.createTextNode("使用正则"));
    filterOptions.appendChild(regexWrapper);

    var caseWrapper = document.createElement("label");
    caseWrapper.className = "inline-check filter-option";
    caseWrapper.htmlFor = "modify-filter-case-sensitive";
    var caseInput = document.createElement("input");
    caseInput.id = "modify-filter-case-sensitive";
    caseInput.type = "checkbox";
    caseInput.checked = originalCaseSensitive;
    caseWrapper.append(caseInput, document.createTextNode("大小写敏感"));
    filterOptions.appendChild(caseWrapper);

    container.appendChild(filterOptions);

    var filterHelp = document.createElement("p");
    filterHelp.id = "modify-filter-help";
    filterHelp.className = "field-help";
    filterHelp.textContent =
      "默认按字面文本匹配且不区分大小写；勾选「使用正则」后按正则匹配，勾选「大小写敏感」后区分大小写。";
    container.appendChild(filterHelp);

    var fnLabel = document.createElement("label");
    fnLabel.textContent = "folder_name";
    fnLabel.htmlFor = "modify-folder-name";
    var fnInput = document.createElement("input");
    fnInput.id = "modify-folder-name";
    fnInput.type = "text";
    fnInput.value = originalFolderName;
    fnInput.placeholder = "期望存储目录名";
    var fnClear = appendClearControl("modify-clear-folder-name", "清空 folder_name", fnInput);
    container.appendChild(fnLabel);
    container.appendChild(fnInput);
    container.appendChild(fnClear.wrapper);

    var formError = document.createElement("p");
    formError.id = "detail-modify-error";
    formError.className = "field-error";
    formError.setAttribute("role", "alert");
    formError.hidden = true;
    container.appendChild(formError);

    var btnRow = document.createElement("div");
    btnRow.className = "notification-actions";

    var submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "primary-button detail-action";
    submitBtn.textContent = "提交修改";
    submitBtn.addEventListener("click", function () {
      formError.hidden = true;
      formError.textContent = "";
      var patch = {};
      if (groupSelect.value !== originalGroup) {
        patch.selected_subtitle_group = groupSelect.value;
      }
      var mcVal = mcInput.value.trim();
      var mncVal = mncInput.value.trim();
      var useRegex = regexInput.checked;
      var caseSensitive = caseInput.checked;
      var mcChanged = mcClear.checkbox.checked || mcVal !== originalMustContain;
      var mncChanged = mncClear.checkbox.checked || mncVal !== originalMustNotContain;
      if (
        mcChanged ||
        mncChanged ||
        useRegex !== originalUseRegex ||
        caseSensitive !== originalCaseSensitive
      ) {
        patch.filter_rule = {};
        if (mcChanged) {
          patch.filter_rule.must_contain = mcClear.checkbox.checked ? "" : mcVal;
        }
        if (mncChanged) {
          patch.filter_rule.must_not_contain = mncClear.checkbox.checked ? "" : mncVal;
        }
        patch.filter_rule.use_regex = useRegex;
        patch.filter_rule.case_sensitive = caseSensitive;
      }
      var fnVal = fnInput.value.trim();
      if (fnClear.checkbox.checked || fnVal !== originalFolderName) {
        patch.expected_folder_name = fnClear.checkbox.checked ? "" : fnVal;
      }
      if (!Object.keys(patch).length) {
        formError.textContent = "请至少修改或清空一个字段。";
        formError.hidden = false;
        return;
      }
      performAction(request.request_id, "modify", { patch: patch });
    });
    btnRow.appendChild(submitBtn);

    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "secondary-button";
    cancelBtn.textContent = "取消";
    cancelBtn.addEventListener("click", function () {
      container.hidden = true;
    });
    btnRow.appendChild(cancelBtn);

    container.appendChild(btnRow);
    return container;
  }

  function buildPreviewEditForm(request) {
    // Editable preview draft form. Unlike the saved-request modify form this is
    // always visible, uses the dry-run preview-modify endpoint to recompute seed
    // display, and never calls the saved modify API.
    const config = request.confirmable_config || {};
    const sourceInfo = request.source_info || {};
    const rssSources = sourceInfo.rss_sources || [];
    const filterRule = config.filter_rule || {};
    const originalGroup = config.selected_subtitle_group || "";
    const originalMustContain = filterRule.must_contain || "";
    const originalMustNotContain = filterRule.must_not_contain || "";
    const originalUseRegex = filterRule.use_regex === true;
    const originalCaseSensitive = filterRule.case_sensitive === true;
    const originalFolderName = config.expected_folder_name || "";

    const container = document.createElement("div");
    container.id = "detail-preview-edit-form";
    container.className = "detail-section detail-inline-form detail-preview-edit-form";

    const heading = document.createElement("h4");
    heading.textContent = "编辑订阅草案";
    container.appendChild(heading);

    const groupLabel = document.createElement("label");
    groupLabel.textContent = "字幕组";
    groupLabel.htmlFor = "preview-subtitle-group";
    const groupSelect = document.createElement("select");
    groupSelect.id = "preview-subtitle-group";
    for (let i = 0; i < rssSources.length; i++) {
      const src = rssSources[i];
      const opt = document.createElement("option");
      opt.value = src.subtitle_group || "";
      opt.textContent = src.subtitle_group || "未知字幕组";
      groupSelect.appendChild(opt);
    }
    groupSelect.value = originalGroup;
    container.appendChild(groupLabel);
    container.appendChild(groupSelect);

    const mcLabel = document.createElement("label");
    mcLabel.textContent = "包含规则";
    mcLabel.htmlFor = "preview-must-contain";
    const mcInput = document.createElement("input");
    mcInput.id = "preview-must-contain";
    mcInput.type = "text";
    mcInput.value = originalMustContain;
    mcInput.placeholder = "如 1080p（默认按字面匹配）";
    container.appendChild(mcLabel);
    container.appendChild(mcInput);

    const mncLabel = document.createElement("label");
    mncLabel.textContent = "排除规则";
    mncLabel.htmlFor = "preview-must-not-contain";
    const mncInput = document.createElement("input");
    mncInput.id = "preview-must-not-contain";
    mncInput.type = "text";
    mncInput.value = originalMustNotContain;
    mncInput.placeholder = "如 [v2]（默认按字面匹配）";
    container.appendChild(mncLabel);
    container.appendChild(mncInput);

    const filterOptions = document.createElement("div");
    filterOptions.className = "filter-options";

    const regexWrapper = document.createElement("label");
    regexWrapper.className = "inline-check filter-option";
    regexWrapper.htmlFor = "preview-filter-use-regex";
    const regexInput = document.createElement("input");
    regexInput.id = "preview-filter-use-regex";
    regexInput.type = "checkbox";
    regexInput.checked = originalUseRegex;
    regexWrapper.append(regexInput, document.createTextNode("使用正则"));
    filterOptions.appendChild(regexWrapper);

    const caseWrapper = document.createElement("label");
    caseWrapper.className = "inline-check filter-option";
    caseWrapper.htmlFor = "preview-filter-case-sensitive";
    const caseInput = document.createElement("input");
    caseInput.id = "preview-filter-case-sensitive";
    caseInput.type = "checkbox";
    caseInput.checked = originalCaseSensitive;
    caseWrapper.append(caseInput, document.createTextNode("大小写敏感"));
    filterOptions.appendChild(caseWrapper);

    container.appendChild(filterOptions);

    const filterHelp = document.createElement("p");
    filterHelp.id = "preview-filter-help";
    filterHelp.className = "field-help";
    filterHelp.textContent =
      "默认按字面文本匹配且不区分大小写；勾选「使用正则」后按正则匹配，勾选「大小写敏感」后区分大小写。";
    container.appendChild(filterHelp);

    const fnLabel = document.createElement("label");
    fnLabel.textContent = "folder_name";
    fnLabel.htmlFor = "preview-folder-name";
    const fnInput = document.createElement("input");
    fnInput.id = "preview-folder-name";
    fnInput.type = "text";
    fnInput.value = originalFolderName;
    fnInput.placeholder = "期望存储目录名";
    container.appendChild(fnLabel);
    container.appendChild(fnInput);

    const formError = document.createElement("p");
    formError.id = "preview-edit-error";
    formError.className = "field-error";
    formError.setAttribute("role", "alert");
    formError.hidden = true;
    container.appendChild(formError);

    const btnRow = document.createElement("div");
    btnRow.className = "notification-actions";

    const applyBtn = document.createElement("button");
    applyBtn.type = "button";
    applyBtn.className = "primary-button detail-action";
    applyBtn.textContent = "应用修改";
    applyBtn.addEventListener("click", function () {
      formError.hidden = true;
      formError.textContent = "";
      const patch = collectPreviewEditPatch(request);
      if (!patch || !Object.keys(patch).length) {
        formError.textContent = "请至少修改一个字段。";
        formError.hidden = false;
        return;
      }
      previewModifyAndRerender(request, patch);
    });
    btnRow.appendChild(applyBtn);

    container.appendChild(btnRow);
    return container;
  }

  function buildCancelForm(request) {
    var container = document.createElement("div");
    container.id = "detail-cancel-form";
    container.className = "detail-section detail-inline-form detail-cancel-form";
    container.hidden = true;

    var heading = document.createElement("h4");
    heading.textContent = "取消订阅方案";
    container.appendChild(heading);

    var reasonLabel = document.createElement("label");
    reasonLabel.textContent = "取消原因（可选）";
    reasonLabel.htmlFor = "cancel-reason";
    var reasonInput = document.createElement("textarea");
    reasonInput.id = "cancel-reason";
    reasonInput.rows = 3;
    reasonInput.placeholder = "例如：暂时不订阅，或匹配结果不符合预期";
    container.append(reasonLabel, reasonInput);

    var btnRow = document.createElement("div");
    btnRow.className = "notification-actions";

    var submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "danger-button detail-action";
    submitBtn.textContent = "提交取消";
    submitBtn.addEventListener("click", function () {
      if (!window.confirm("确认取消此订阅方案？")) {
        return;
      }
      var reason = reasonInput.value.trim();
      performAction(request.request_id, "cancel", {
        cancel_reason: reason || undefined,
      });
    });
    btnRow.appendChild(submitBtn);

    var collapseBtn = document.createElement("button");
    collapseBtn.type = "button";
    collapseBtn.className = "secondary-button";
    collapseBtn.textContent = "收起";
    collapseBtn.addEventListener("click", function () {
      container.hidden = true;
    });
    btnRow.appendChild(collapseBtn);

    container.appendChild(btnRow);
    return container;
  }

  async function savePreviewRequest(request) {
    if (!request) {
      showNotification("error", "保存失败", "订阅草案缺失，无法保存。");
      return;
    }

    hideNotification();
    setActionInFlight(true);
    setState(detailContainer, "正在保存订阅草案...", "loading-state");
    try {
      // Persist the (possibly modified) preview draft as-is. The server only
      // accepts PENDING_CONFIRM drafts, so the saved object enters the existing
      // confirmation flow and can then be confirmed, cancelled, modified, or
      // deleted like any other saved Request.
      const savedRequest = await savePreviewDraftRequest(request);
      const generatedRequestId = savedRequest && savedRequest.request_id;
      const batchItemId = currentBatchDetailItemId;
      if (batchItemId) {
        updateBatchCardRequest(batchItemId, savedRequest);
      }
      selectedRequestId = generatedRequestId;
      renderDetailPayload(
        {request: savedRequest, summary: null},
        batchItemId ? {batchItemId: batchItemId} : undefined,
      );
      await loadList({loadSelectedDetail: false});
      syncRequestIdToUrl(selectedRequestId);
      showNotification("success", "保存成功", "已保存订阅草案 " + selectedRequestId, {
        actions: [
          { label: "刷新列表", handler: loadList },
          { label: "查看详情", handler: () => loadDetail(selectedRequestId) },
        ],
      });
    } catch (error) {
      setState(detailContainer, "订阅草案保存失败。请稍后重试。", "error-state");
      notifyApiError("保存失败", error);
    } finally {
      setActionInFlight(false);
    }
  }

  function collectPreviewEditPatch(request) {
    // Read the currently visible preview edit form and build a modify patch
    // against the request's current config. Returns null when the form is
    // absent, and an empty object when nothing changed.
    const form = document.getElementById("detail-preview-edit-form");
    if (!form || !request) {
      return null;
    }
    const config = request.confirmable_config || {};
    const filterRule = config.filter_rule || {};
    const originalGroup = config.selected_subtitle_group || "";
    const originalMustContain = filterRule.must_contain || "";
    const originalMustNotContain = filterRule.must_not_contain || "";
    const originalUseRegex = filterRule.use_regex === true;
    const originalCaseSensitive = filterRule.case_sensitive === true;
    const originalFolderName = config.expected_folder_name || "";

    const groupSelect = form.querySelector("#preview-subtitle-group");
    const mcInput = form.querySelector("#preview-must-contain");
    const mncInput = form.querySelector("#preview-must-not-contain");
    const regexInput = form.querySelector("#preview-filter-use-regex");
    const caseInput = form.querySelector("#preview-filter-case-sensitive");
    const fnInput = form.querySelector("#preview-folder-name");

    const patch = {};
    if (groupSelect && groupSelect.value && groupSelect.value !== originalGroup) {
      patch.selected_subtitle_group = groupSelect.value;
    }
    const mcVal = mcInput ? mcInput.value.trim() : "";
    const mncVal = mncInput ? mncInput.value.trim() : "";
    const useRegex = regexInput ? regexInput.checked : false;
    const caseSensitive = caseInput ? caseInput.checked : false;
    const mcChanged = mcVal !== originalMustContain;
    const mncChanged = mncVal !== originalMustNotContain;
    if (
      mcChanged ||
      mncChanged ||
      useRegex !== originalUseRegex ||
      caseSensitive !== originalCaseSensitive
    ) {
      patch.filter_rule = {};
      if (mcChanged) {
        patch.filter_rule.must_contain = mcVal;
      }
      if (mncChanged) {
        patch.filter_rule.must_not_contain = mncVal;
      }
      patch.filter_rule.use_regex = useRegex;
      patch.filter_rule.case_sensitive = caseSensitive;
    }
    const fnVal = fnInput ? fnInput.value.trim() : "";
    if (fnVal !== originalFolderName) {
      patch.expected_folder_name = fnVal;
    }
    return patch;
  }

  async function previewModify(request, patch) {
    // Dry-run modify: recompute the in-memory preview request without saving.
    const result = await fetchJson("/api/v1/requests/preview-modify", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        request: request,
        patch: patch || {},
        storage_dir: currentStorageDir() || null,
      }),
    });
    return result && result.request;
  }

  function updateCurrentPreviewRequest(modified) {
    if (currentDetailPayload && typeof currentDetailPayload === "object") {
      if (currentDetailPayload.request) {
        currentDetailPayload.request = modified;
      } else {
        currentDetailPayload = modified;
      }
    } else {
      currentDetailPayload = modified;
    }
  }

  async function previewModifyAndRerender(request, patch) {
    hideNotification();
    setActionInFlight(true);
    setState(detailContainer, "正在重新计算订阅草案...", "loading-state");
    const batchItemId = currentBatchEditItemId;
    try {
      const modified = await previewModify(request, patch);
      if (!modified) {
        throw new Error("订阅草案修改失败。");
      }
      updateCurrentPreviewRequest(modified);
      if (batchItemId) {
        updateBatchCardRequest(batchItemId, modified);
      }
      renderDetailPayload(currentDetailPayload, {
        preview: true,
        batchItemId: batchItemId,
      });
      showNotification(
        "success",
        "已应用修改",
        batchItemId
          ? "当前批量卡片已回流最新订阅草案。"
          : "订阅草案种子展示已重新计算。",
      );
    } catch (error) {
      if (batchItemId && currentDetailPayload) {
        renderDetailPayload(currentDetailPayload, {
          preview: true,
          batchItemId: batchItemId,
        });
        setPreviewEditError(error.message || "订阅草案修改失败。请重试。");
      } else {
        setState(detailContainer, "订阅草案修改失败。请重试。", "error-state");
      }
      notifyApiError("修改失败", error);
    } finally {
      setActionInFlight(false);
    }
  }

  function renderDetailPayload(payload, options) {
    currentDetailPayload = payload;
    currentBatchEditItemId =
      options && options.batchItemId ? options.batchItemId : null;
    currentBatchDetailItemId =
      options && options.batchItemId ? options.batchItemId : null;
    var request = payload.request || payload;
    var isPreview = Boolean(
      (options && options.preview) ||
      (Object.prototype.hasOwnProperty.call(payload, "saved_request") && !payload.saved_request)
    );
    var input = request.input || {};
    var sourceInfo = request.source_info || {};
    var matched = sourceInfo.matched_bangumi || {};
    var config = request.confirmable_config || {};
    var filterRule = config.filter_rule || {};
    var source = selectedRssSource(sourceInfo, config);
    var validSeeds = source.valid_seed_names || config.effective_seed_names || [];
    var excludedSeeds = source.excluded_seed_names || [];
    var effectiveSeeds = config.effective_seed_names || validSeeds;
    var rssSources = sourceInfo.rss_sources || [];
    var selectedGroupName = config.selected_subtitle_group || "未选择字幕组";
    // Complete seeds grouped by the MiKan subtitle group the detail page
    // resolved. Each group keeps its own complete seed list (seed_names), with
    // a fallback to combined valid/excluded titles for older snapshots.
    var groupedSeeds = [];
    var totalCompleteCount = 0;
    for (var rsi = 0; rsi < rssSources.length; rsi++) {
      var rssSource = rssSources[rsi];
      var groupName = rssSource.subtitle_group || "未知字幕组";
      var groupSeedNames =
        rssSource.seed_names ||
        combinedSeedNames(
          rssSource.valid_seed_names || [],
          rssSource.excluded_seed_names || [],
        );
      groupedSeeds.push({subtitleGroup: groupName, seedNames: groupSeedNames});
      totalCompleteCount += groupSeedNames.length;
    }

    detailContainer.className = "request-detail";
    detailContainer.replaceChildren();

    var heading = document.createElement("h3");
    heading.textContent = input.raw_title || matched.title || "订阅方案";

    var overviewSection = createDetailSection("Overview", "overview-section");
    var overviewHeader = document.createElement("div");
    overviewHeader.className = "overview-actions";
    var overviewFields = detailList([
      ["request_id", request.request_id],
      ["状态", statusLabel(request.status)],
      ["保存状态", isPreview ? "订阅草案（未保存）" : "已保存"],
      ["原始标题", input.raw_title],
      ["匹配标题", matched.title],
    ]);
    var copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "secondary-button copy-request-id";
    copyButton.textContent = "复制 request_id";
    copyButton.addEventListener("click", function () {
      copyTextToClipboard(request.request_id);
    });
    overviewHeader.append(overviewFields, copyButton);
    overviewSection.appendChild(overviewHeader);

    var isPending = request.status === "PENDING_CONFIRM";
    var isAccepted = request.status === "ACCEPTED";
    var actionsContainer = document.createElement("div");
    actionsContainer.className = "detail-actions notification-actions";

    if (isPreview) {
      var previewNote = document.createElement("p");
      previewNote.className = "field-help preview-mode-note";
      previewNote.textContent =
        "订阅草案（未保存）：可编辑下方订阅方案；点击「应用修改」重新计算种子展示，点击「保存草案」后进入待确认流程。";
      actionsContainer.appendChild(previewNote);

      var saveDraftBtn = document.createElement("button");
      saveDraftBtn.type = "button";
      saveDraftBtn.className = "primary-button detail-action";
      saveDraftBtn.textContent = "保存草案";
      saveDraftBtn.addEventListener("click", async function () {
        var patch = collectPreviewEditPatch(request);
        if (patch && Object.keys(patch).length) {
          try {
            var modified = await previewModify(request, patch);
            savePreviewRequest(modified);
          } catch (error) {
            notifyApiError("保存失败", error);
          }
        } else {
          savePreviewRequest(request);
        }
      });
      actionsContainer.appendChild(saveDraftBtn);
    } else if (isPending) {
      var acceptBtn = document.createElement("button");
      acceptBtn.type = "button";
      acceptBtn.className = "primary-button detail-action";
      acceptBtn.textContent = "确认";
      acceptBtn.addEventListener("click", function () {
        if (window.confirm("确认接受此订阅方案？")) {
          performAction(request.request_id, "accept", {});
        }
      });
      actionsContainer.appendChild(acceptBtn);

      var cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "danger-button detail-action";
      cancelBtn.textContent = "取消";
      cancelBtn.addEventListener("click", function () {
        var form = document.getElementById("detail-cancel-form");
        if (form) {
          form.hidden = !form.hidden;
        }
      });
      actionsContainer.appendChild(cancelBtn);

      var modifyBtn = document.createElement("button");
      modifyBtn.type = "button";
      modifyBtn.className = "secondary-button detail-action";
      modifyBtn.textContent = "修改";
      modifyBtn.addEventListener("click", function () {
        var form = document.getElementById("detail-modify-form");
        if (form) {
          form.hidden = !form.hidden;
        }
      });
      actionsContainer.appendChild(modifyBtn);
    } else if (isAccepted) {
      var statusNote = document.createElement("p");
      statusNote.className = "field-help";
      statusNote.textContent = "此订阅方案已" + statusLabel(request.status) + "，可提交到 Auto Bangumi。";
      actionsContainer.appendChild(statusNote);

      var abSubmitBtn = document.createElement("a");
      abSubmitBtn.className = "secondary-button detail-action";
      abSubmitBtn.href =
        "/settings?request_id=" + encodeURIComponent(request.request_id) + "#auto-bangumi";
      abSubmitBtn.textContent = "去 Settings 提交 Auto Bangumi";
      actionsContainer.appendChild(abSubmitBtn);

      var acceptedModifyBtn = document.createElement("button");
      acceptedModifyBtn.type = "button";
      acceptedModifyBtn.className = "secondary-button detail-action";
      acceptedModifyBtn.textContent = "修改";
      acceptedModifyBtn.addEventListener("click", function () {
        var form = document.getElementById("detail-modify-form");
        if (form) {
          form.hidden = !form.hidden;
        }
      });
      actionsContainer.appendChild(acceptedModifyBtn);

      var deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "danger-button detail-action";
      deleteBtn.textContent = "删除";
      deleteBtn.addEventListener("click", function () {
        if (window.confirm("确认删除此订阅方案？此操作不可恢复。")) {
          deleteRequest(request.request_id);
        }
      });
      actionsContainer.appendChild(deleteBtn);
    } else {
      var statusNote = document.createElement("p");
      statusNote.className = "field-help";
      statusNote.textContent = "此订阅方案已" + statusLabel(request.status) + "，不可操作。";
      actionsContainer.appendChild(statusNote);
    }

    if (currentBatchDetailItemId) {
      var batchRow = batchDraftCards.find(function (row) {
        return row.item_id === currentBatchDetailItemId;
      });
      if (batchRow && canAcceptBatchCard(batchRow)) {
        var batchAcceptBtn = document.createElement("button");
        batchAcceptBtn.type = "button";
        batchAcceptBtn.className = "primary-button detail-action batch-detail-accept";
        batchAcceptBtn.textContent = "接受当前批量草案";
        batchAcceptBtn.disabled = batchAcceptInFlight;
        batchAcceptBtn.addEventListener("click", function () {
          if (window.confirm("确认接受当前批量卡片？")) {
            acceptBatchCard(batchRow);
          }
        });
        actionsContainer.appendChild(batchAcceptBtn);
      }
    }

    var cancelForm = isPreview ? document.createDocumentFragment() : buildCancelForm(request);
    var modifyForm = isPreview ? buildPreviewEditForm(request) : buildModifyForm(request);
    var sourceSection = createDetailSection("Source", "source-section");
    sourceSection.appendChild(
      detailList([
        ["字幕组", config.selected_subtitle_group],
        ["RSS 来源", config.selected_rss_url ? "已选择" : "未选择"],
        ["匹配番剧标题", matched.title],
      ]),
    );

    var filterSection = createDetailSection("Filter", "filter-section");
    var matchMode = filterRule.use_regex === true ? "正则" : "普通字符";
    var caseMode = filterRule.case_sensitive === true ? "区分大小写" : "不区分大小写";
    filterSection.appendChild(
      detailList([
        ["包含规则", filterRule.must_contain],
        ["排除规则", filterRule.must_not_contain],
        ["匹配模式", matchMode],
        ["大小写", caseMode],
        ["folder_name", config.expected_folder_name],
        ["有效种子数", effectiveSeeds.length],
        ["排除种子数", excludedSeeds.length],
      ]),
    );

    var seedsSection = createDetailSection("Seeds", "seeds-section");

    // Effective seeds come first and are expanded by default, while still
    // allowing the user to collapse the section when scanning long lists.
    var effectiveGroup = document.createElement("details");
    effectiveGroup.className = "seed-details seed-group effective-seed-group";
    effectiveGroup.open = true;
    var effectiveHeading = document.createElement("summary");
    effectiveHeading.textContent =
      "有效种子（当前选中字幕组：" + selectedGroupName + "）(" +
      effectiveSeeds.length + ")";
    effectiveGroup.appendChild(effectiveHeading);
    renderSeedList(effectiveGroup, effectiveSeeds, "无有效种子标题。");
    seedsSection.appendChild(effectiveGroup);

    // Complete seeds come second, grouped by the MiKan subtitle group that the
    // detail page resolved. Each group shows its name and seed count with an
    // expandable seed list; the whole area collapses by default.
    var completeDetails = document.createElement("details");
    completeDetails.className = "seed-details complete-seed-details";
    var completeSummary = document.createElement("summary");
    completeSummary.textContent =
      "完整种子（按字幕组分组）(" + totalCompleteCount + ")";
    var completeGroups = document.createElement("div");
    completeGroups.className = "seed-groups complete-seed-groups";
    if (!groupedSeeds.length) {
      var noComplete = document.createElement("p");
      noComplete.className = "muted-text";
      noComplete.textContent = "无种子标题。";
      completeGroups.appendChild(noComplete);
    }
    for (var groupIndex = 0; groupIndex < groupedSeeds.length; groupIndex++) {
      var groupData = groupedSeeds[groupIndex];
      var groupDetails = document.createElement("details");
      groupDetails.className = "subgroup-seed-group";
      var groupSummary = document.createElement("summary");
      groupSummary.textContent =
        groupData.subtitleGroup + " (" + groupData.seedNames.length + ")";
      groupDetails.appendChild(groupSummary);
      renderSeedList(groupDetails, groupData.seedNames, "无种子标题。");
      completeGroups.appendChild(groupDetails);
    }
    completeDetails.append(completeSummary, completeGroups);
    seedsSection.appendChild(completeDetails);

    // Excluded seeds come last, collapsed by default, with Chinese exclusion
    // reasons rendered beside each seed title.
    var excludedDetails = document.createElement("details");
    excludedDetails.className = "seed-details excluded-seed-details";
    var excludedSummary = document.createElement("summary");
    excludedSummary.textContent = "排除种子 (" + excludedSeeds.length + ")";
    var excludedGroup = document.createElement("div");
    excludedGroup.className = "seed-group";
    renderExcludedSeedList(excludedGroup, excludedSeeds);
    excludedDetails.append(excludedSummary, excludedGroup);
    seedsSection.appendChild(excludedDetails);

    var batchContextSection = document.createDocumentFragment();
    if (currentBatchDetailItemId) {
      var contextRow = batchDraftCards.find(function (row) {
        return row.item_id === currentBatchDetailItemId;
      });
      if (contextRow) {
        var contextSection = createDetailSection("批量草案上下文", "batch-detail-context");
        contextSection.append(
          buildBatchCardPreferenceBlock(contextRow),
          buildBatchCardSearchSourceBlock(contextRow),
        );
        batchContextSection.appendChild(contextSection);
      }
    }

    var auditSection = createDetailSection("Audit", "audit-group-section");
    renderHistorySection(auditSection, payload.history);
    renderAbResultSection(auditSection, payload.ab_result);

    detailContainer.append(
      heading,
      actionsContainer,
      cancelForm,
      modifyForm,
      overviewSection,
      sourceSection,
      filterSection,
      seedsSection,
      batchContextSection,
      auditSection,
    );
  }

  function selectRequest(requestId, options) {
    selectedRequestId = requestId || null;
    renderList();
    if (options && options.pushUrl) {
      syncRequestIdToUrl(selectedRequestId);
    }
    loadDetail(selectedRequestId);
  }

  async function loadDetail(requestId) {
    if (!requestId) {
      setState(detailContainer, "订阅方案 ID 无效。", "error-state");
      showNotification("error", "详情加载失败", "订阅方案 ID 无效。");
      return;
    }

    hideNotification();
    setState(detailContainer, "正在加载订阅方案详情...", "loading-state");
    try {
      const result = await fetchJson(
        apiPath("/api/v1/requests/" + encodeURIComponent(requestId)),
      );
      renderDetailPayload(result);
    } catch (error) {
      setState(detailContainer, "订阅方案详情加载失败。请确认 request_id 是否存在。", "error-state");
      showNotification("error", "订阅方案详情加载失败", "请确认 request_id 是否存在。");
    }
  }

  async function finalizeGeneratedRequest(result) {
    var generatedRequestId = result.request && result.request.request_id;
    selectedRequestId = result.saved_request ? generatedRequestId : null;
    renderDetailPayload(result, {preview: !result.saved_request});
    await loadList({loadSelectedDetail: false});
    if (result.saved_request) {
      selectedRequestId = generatedRequestId;
      syncRequestIdToUrl(selectedRequestId);
      showNotification("success", "保存成功", "已保存订阅方案 " + selectedRequestId, {
        actions: [
          {
            label: "刷新列表",
            handler: loadList,
          },
          {
            label: "查看详情",
            handler: () => loadDetail(selectedRequestId),
          },
        ],
      });
    } else {
      syncRequestIdToUrl(null, {replace: true});
      showNotification(
        "success",
        "预览已生成",
        "这是未保存的订阅草案；保存后可确认、修改或删除。",
        {
          actions: [
            {
              label: "保存草案",
              className: "primary-button",
              handler: () => {
                const current =
                  (currentDetailPayload && currentDetailPayload.request) ||
                  result.request ||
                  null;
                if (current) {
                  savePreviewRequest(current);
                }
              },
            },
          ],
        },
      );
    }
  }

  async function generateRequest(event) {
    event.preventDefault();
    clearFormError();
    const title = titleInput.value.trim();
    if (!title) {
      setFormError("请输入标题，至少包含 1 个非空白字符。");
      showNotification("error", "校验失败", "请输入标题，至少包含 1 个非空白字符。");
      titleInput.focus();
      return;
    }

    let payload;
    try {
      payload = buildCreateRequestPayload(title);
    } catch (validationError) {
      setFormError(validationError.message || "订阅方案表单校验失败。", validationError.field);
      showNotification("error", "校验失败", validationError.message || "订阅方案表单校验失败。");
      if (validationError.field && validationError.field.focus) {
        validationError.field.focus();
      }
      return;
    }

    hideNotification();
    setSubmitInFlight(true);
    setState(detailContainer, "正在生成 Request...", "loading-state");
    try {
      const result = await fetchJson("/api/v1/requests", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          ...payload,
        }),
      });
      await finalizeGeneratedRequest(result);
    } catch (error) {
      setState(detailContainer, error.message, "error-state");
      notifyApiError("生成失败", error);
    } finally {
      setSubmitInFlight(false);
    }
  }

  refreshButton.addEventListener("click", loadList);
  listSearchInput.addEventListener("input", renderList);
  listStatusFilter.addEventListener("change", renderList);
  listSortSelect.addEventListener("change", renderList);
  form.addEventListener("submit", generateRequest);
  window.addEventListener("popstate", () => {
    const requestId = requestIdFromLocation();
    selectedRequestId = requestId || null;
    renderList();
    if (requestId) {
      loadDetail(requestId);
    } else {
      hideNotification();
      setState(detailContainer, "选择一个订阅方案后查看详情。", "empty-state");
    }
  });
  selectedRequestId = requestIdFromLocation() || null;
  syncCandidateFallbackVisibility();
  loadList();
})();
