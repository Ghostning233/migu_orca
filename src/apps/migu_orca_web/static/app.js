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
  const settingsAbEndpointInput = document.getElementById("settings-ab-endpoint");
  const settingsAbTokenInput = document.getElementById("settings-ab-token");
  const settingsAbFallbackInput = document.getElementById("settings-ab-fallback-enabled");
  const settingsAbFormError = document.getElementById("settings-ab-error");
  const settingsAbResult = document.getElementById("settings-ab-result");
  const settingsAbSubmitButton = document.getElementById("settings-ab-submit");
  const settingsAbReturnLink = document.getElementById("settings-ab-return-link");
  const preferenceKeys = {
    storageDir: "miguOrca.web.storageDir",
    saveRequest: "miguOrca.web.saveRequest",
  };

  let selectedRequestId = null;
  let loadedRequests = [];
  let currentDetailPayload = null;
  let storageDirPreference = "";
  let saveRequestPreference = true;

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
      ? "默认保存 Request JSON"
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
      "偏好已清除；Request 工作台将使用默认 `.migu_orca/storage` 并保存 Request JSON。",
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

  function setSettingsAbError(message, field) {
    if (!settingsAbFormError) {
      return;
    }
    settingsAbFormError.textContent = message;
    settingsAbFormError.hidden = false;
    for (const input of [settingsAbEndpointInput, settingsAbTokenInput]) {
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
    for (const input of [settingsAbEndpointInput, settingsAbTokenInput]) {
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
    if (settingsAbEndpointInput) {
      settingsAbEndpointInput.value = "";
    }
    if (settingsAbTokenInput) {
      settingsAbTokenInput.value = "";
    }
  }

  function initializeSettingsAbForm() {
    if (!settingsAbForm) {
      return;
    }
    const requestId = settingsAbRequestIdFromLocation();
    if (!requestId) {
      settingsAbForm.hidden = true;
      if (settingsAbContext) {
        settingsAbContext.textContent =
          "从 ACCEPTED Request 详情进入后，可在此提交到 Auto Bangumi。";
      }
      return;
    }
    settingsAbForm.hidden = false;
    if (settingsAbRequestId) {
      settingsAbRequestId.textContent = requestId;
    }
    if (settingsAbContext) {
      settingsAbContext.textContent =
        "已选择 Request " + requestId + "；请确认该 Request 已 ACCEPTED 后再提交。";
    }
    if (settingsAbReturnLink) {
      settingsAbReturnLink.href = "/index?request_id=" + encodeURIComponent(requestId);
    }
  }

  async function submitSettingsAb(event) {
    event.preventDefault();
    clearSettingsAbError();
    const requestId = settingsAbRequestIdFromLocation();
    const endpoint = settingsAbEndpointInput ? settingsAbEndpointInput.value.trim() : "";
    const token = settingsAbTokenInput ? settingsAbTokenInput.value.trim() : "";
    if (!requestId) {
      setSettingsAbError("缺少 request_id，无法提交 Auto Bangumi。");
      return;
    }
    if (!endpoint) {
      setSettingsAbError("提交 Auto Bangumi 前必须填写 endpoint。", settingsAbEndpointInput);
      return;
    }
    if (!token) {
      setSettingsAbError("提交 Auto Bangumi 前必须填写 token。", settingsAbTokenInput);
      return;
    }
    if (!window.confirm("确认提交此 Request 到 Auto Bangumi？")) {
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
            ab_config: {
              endpoint: endpoint,
              token: token,
              fallback_enabled: settingsAbFallbackInput ? settingsAbFallbackInput.checked : false,
            },
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
      showNotification("success", "Auto Bangumi 提交成功", "Request " + requestId, {
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
        "Auto Bangumi 提交失败。请检查配置与 Request 状态后重试。",
        "error-state compact-state",
      );
      showNotification("error", "Auto Bangumi 提交失败", "请检查配置与 Request 状态后重试。");
    } finally {
      setSettingsAbInFlight(false);
    }
  }

  initializeSettingsAbForm();

  if (settingsAbForm) {
    settingsAbForm.addEventListener("submit", submitSettingsAb);
  }

  if (!form) {
    return;
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
      "未命名 Request"
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
    allOption.textContent = "All";
    listStatusFilter.appendChild(allOption);

    for (const status of statuses) {
      const option = document.createElement("option");
      option.value = status;
      option.textContent = status;
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
      setState(listContainer, "暂无已保存的 Request。", "empty-state");
      return;
    }
    if (!requests.length) {
      setState(listContainer, "没有匹配的 Request。清空搜索或筛选后可恢复列表。", "empty-state");
      return;
    }

    for (const summary of requests) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "request-list-item";
      item.dataset.requestId = summary.request_id || "";
      item.setAttribute("aria-label", "查看 Request 详情：" + requestLabel(summary));
      if (summary.request_id === selectedRequestId) {
        item.classList.add("is-selected");
        item.setAttribute("aria-current", "true");
      }

      const title = document.createElement("strong");
      title.textContent = requestLabel(summary);

      const meta = document.createElement("span");
      meta.textContent = [
        fieldValue(summary.status),
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
    setState(listContainer, "正在加载 Request 列表...", "loading-state");
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
      notifyApiError("Request 列表加载失败", error);
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
      "<tr><th>action</th><th>previous_status</th><th>next_status</th><th>timestamp</th></tr>";
    const body = document.createElement("tbody");
    for (const event of events) {
      const row = document.createElement("tr");
      for (const key of ["action", "previous_status", "next_status", "timestamp"]) {
        const cell = document.createElement("td");
        cell.textContent = displayValue(event[key]);
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
        "Request " + requestId, {
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
      setState(detailContainer, "Request 已删除。请选择一个 Request 查看详情。", "empty-state");
      await loadList({loadSelectedDetail: false});
      showNotification("success", "删除成功", "已删除 Request " + requestId, {
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
    heading.textContent = "修改 Request";
    container.appendChild(heading);

    var groupLabel = document.createElement("label");
    groupLabel.textContent = "字幕组";
    groupLabel.htmlFor = "modify-subtitle-group";
    var groupSelect = document.createElement("select");
    groupSelect.id = "modify-subtitle-group";
    var emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "不修改";
    groupSelect.appendChild(emptyOpt);
    for (var i = 0; i < rssSources.length; i++) {
      var src = rssSources[i];
      var opt = document.createElement("option");
      opt.value = src.subtitle_group || "";
      opt.textContent = src.subtitle_group || "未知字幕组";
      groupSelect.appendChild(opt);
    }
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
      if (groupSelect.value && groupSelect.value !== originalGroup) {
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

  function buildCancelForm(request) {
    var container = document.createElement("div");
    container.id = "detail-cancel-form";
    container.className = "detail-section detail-inline-form detail-cancel-form";
    container.hidden = true;

    var heading = document.createElement("h4");
    heading.textContent = "取消 Request";
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
      if (!window.confirm("确认取消此 Request？")) {
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
    const title = request && request.input && request.input.raw_title
      ? request.input.raw_title
      : "";
    if (!title) {
      showNotification("error", "保存失败", "预览 Request 缺少标题，无法保存。");
      return;
    }

    hideNotification();
    setSubmitInFlight(true);
    setState(detailContainer, "正在保存预览 Request...", "loading-state");
    try {
      const result = await fetchJson("/api/v1/requests", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(buildCreateRequestPayload(title, {saveRequest: true})),
      });
      selectedRequestId = result.request && result.request.request_id;
      renderDetailPayload(result);
      await loadList({loadSelectedDetail: false});
      syncRequestIdToUrl(selectedRequestId);
      showNotification("success", "保存成功", "已保存 Request " + selectedRequestId, {
        actions: [
          { label: "刷新列表", handler: loadList },
          { label: "查看详情", handler: () => loadDetail(selectedRequestId) },
        ],
      });
    } catch (error) {
      setState(detailContainer, "预览 Request 保存失败。请稍后重试。", "error-state");
      notifyApiError("保存失败", error);
    } finally {
      setSubmitInFlight(false);
    }
  }

  function renderDetailPayload(payload, options) {
    currentDetailPayload = payload;
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
    var allSeeds = source.seed_names || combinedSeedNames(validSeeds, excludedSeeds);
    var effectiveSeeds = config.effective_seed_names || validSeeds;

    detailContainer.className = "request-detail";
    detailContainer.replaceChildren();

    var heading = document.createElement("h3");
    heading.textContent = input.raw_title || matched.title || "Request";

    var overviewSection = createDetailSection("Overview", "overview-section");
    var overviewHeader = document.createElement("div");
    overviewHeader.className = "overview-actions";
    var overviewFields = detailList([
      ["request_id", request.request_id],
      ["status", request.status],
      ["保存状态", isPreview ? "预览（未保存）" : "已保存"],
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
        "预览模式：此 Request 尚未保存，只能查看，保存后才可确认、取消、修改、删除或提交 Auto Bangumi。";
      actionsContainer.appendChild(previewNote);

      var savePreviewBtn = document.createElement("button");
      savePreviewBtn.type = "button";
      savePreviewBtn.className = "primary-button detail-action";
      savePreviewBtn.textContent = "保存此 Request";
      savePreviewBtn.addEventListener("click", function () {
        savePreviewRequest(request);
      });
      actionsContainer.appendChild(savePreviewBtn);
    } else if (isPending) {
      var acceptBtn = document.createElement("button");
      acceptBtn.type = "button";
      acceptBtn.className = "primary-button detail-action";
      acceptBtn.textContent = "确认";
      acceptBtn.addEventListener("click", function () {
        if (window.confirm("确认接受此 Request？")) {
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
      statusNote.textContent = "此 Request 已" + fieldValue(request.status) + "，可提交到 Auto Bangumi。";
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
        if (window.confirm("确认删除此 Request？此操作不可恢复。")) {
          deleteRequest(request.request_id);
        }
      });
      actionsContainer.appendChild(deleteBtn);
    } else {
      var statusNote = document.createElement("p");
      statusNote.className = "field-help";
      statusNote.textContent = "此 Request 已" + fieldValue(request.status) + "，不可操作。";
      actionsContainer.appendChild(statusNote);
    }

    var cancelForm = isPreview ? document.createDocumentFragment() : buildCancelForm(request);
    var modifyForm = isPreview ? document.createDocumentFragment() : buildModifyForm(request);
    var sourceSection = createDetailSection("Source", "source-section");
    sourceSection.appendChild(
      detailList([
        ["字幕组", config.selected_subtitle_group],
        ["RSS 来源", config.selected_rss_url ? "已选择" : "未选择"],
        ["匹配番剧标题", matched.title],
      ]),
    );

    var filterSection = createDetailSection("Filter", "filter-section");
    filterSection.appendChild(
      detailList([
        ["must_contain", filterRule.must_contain],
        ["must_not_contain", filterRule.must_not_contain],
        ["folder_name", config.expected_folder_name],
        ["有效种子数", effectiveSeeds.length],
        ["排除种子数", excludedSeeds.length],
      ]),
    );

    var seedsSection = createDetailSection("Seeds", "seeds-section");
    var seedDetails = document.createElement("details");
    seedDetails.className = "seed-details";
    var seedSummary = document.createElement("summary");
    seedSummary.textContent =
      "查看筛选种子列表 (完整 " + allSeeds.length + " / 有效 " +
      effectiveSeeds.length + " / 排除 " + excludedSeeds.length + ")";
    var seedsContainer = document.createElement("div");
    seedsContainer.className = "seed-groups";
    var allGroup = document.createElement("div");
    allGroup.className = "seed-group";
    var allHeading = document.createElement("h5");
    allHeading.textContent = "完整种子 (" + allSeeds.length + ")";
    allGroup.appendChild(allHeading);
    renderSeedList(allGroup, allSeeds, "无种子标题。");
    var validGroup = document.createElement("div");
    validGroup.className = "seed-group";
    var validHeading = document.createElement("h5");
    validHeading.textContent = "有效种子 (" + effectiveSeeds.length + ")";
    validGroup.appendChild(validHeading);
    renderSeedList(validGroup, effectiveSeeds, "无有效种子标题。");
    var excludedGroup = document.createElement("div");
    excludedGroup.className = "seed-group";
    var excludedHeading = document.createElement("h5");
    excludedHeading.textContent = "排除种子 (" + excludedSeeds.length + ")";
    excludedGroup.appendChild(excludedHeading);
    renderExcludedSeedList(excludedGroup, excludedSeeds);
    seedsContainer.append(allGroup, validGroup, excludedGroup);
    seedDetails.append(seedSummary, seedsContainer);
    seedsSection.appendChild(seedDetails);

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
      setState(detailContainer, "Request ID 无效。", "error-state");
      showNotification("error", "详情加载失败", "Request ID 无效。");
      return;
    }

    hideNotification();
    setState(detailContainer, "正在加载 Request 详情...", "loading-state");
    try {
      const result = await fetchJson(
        apiPath("/api/v1/requests/" + encodeURIComponent(requestId)),
      );
      renderDetailPayload(result);
    } catch (error) {
      setState(detailContainer, "Request 详情加载失败。请确认 request_id 是否存在。", "error-state");
      showNotification("error", "Request 详情加载失败", "请确认 request_id 是否存在。");
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
      setFormError(validationError.message || "Request 表单校验失败。", validationError.field);
      showNotification("error", "校验失败", validationError.message || "Request 表单校验失败。");
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
      var generatedRequestId = result.request && result.request.request_id;
      selectedRequestId = result.saved_request ? generatedRequestId : null;
      renderDetailPayload(result, {preview: !result.saved_request});
      await loadList({loadSelectedDetail: false});
      if (result.saved_request) {
        selectedRequestId = generatedRequestId;
        syncRequestIdToUrl(selectedRequestId);
        showNotification("success", "保存成功", "已保存 Request " + selectedRequestId, {
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
        showNotification("success", "预览已生成", "这是未保存预览；保存后才可操作。", {
          actions: [
            {
              label: "保存此 Request",
              className: "primary-button",
              handler: () => {
                if (result.request) {
                  savePreviewRequest(result.request);
                }
              },
            },
          ],
        });
      }
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
      setState(detailContainer, "选择一个 Request 后查看详情。", "empty-state");
    }
  });
  selectedRequestId = requestIdFromLocation() || null;
  loadList();
})();
