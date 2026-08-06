(function () {
  const form = document.getElementById("request-generate-form");
  const titleInput = document.getElementById("request-title");
  const storageInput = document.getElementById("storage-dir");
  const saveInput = document.getElementById("save-request");
  const formError = document.getElementById("request-form-error");
  const submitButton = document.getElementById("request-generate-submit");
  const clearPreferencesButton = document.getElementById("clear-web-preferences");
  const refreshButton = document.getElementById("request-list-refresh");
  const listSearchInput = document.getElementById("request-list-search");
  const listStatusFilter = document.getElementById("request-list-status-filter");
  const listSortSelect = document.getElementById("request-list-sort");
  const listCount = document.getElementById("request-list-count");
  const listContainer = document.getElementById("request-list-container");
  const detailContainer = document.getElementById("request-detail-container");
  const notification = document.getElementById("page-notification");
  const preferenceKeys = {
    storageDir: "miguOrca.web.storageDir",
    saveRequest: "miguOrca.web.saveRequest",
  };

  let selectedRequestId = null;
  let loadedRequests = [];

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
    if (savedStorageDir) {
      storageInput.value = savedStorageDir;
    }
    if (savedSaveRequest !== null) {
      saveInput.checked = savedSaveRequest === "true";
    }
  }

  function persistWebPreferences() {
    const storageDir = storageInput.value.trim();
    if (storageDir) {
      writePreference(preferenceKeys.storageDir, storageDir);
    } else {
      removePreference(preferenceKeys.storageDir);
    }
    writePreference(preferenceKeys.saveRequest, String(saveInput.checked));
  }

  function clearWebPreferences() {
    removePreference(preferenceKeys.storageDir);
    removePreference(preferenceKeys.saveRequest);
    storageInput.value = "";
    saveInput.checked = false;
  }

  function storageQuery() {
    const storageDir = storageInput.value.trim();
    if (!storageDir) {
      return "";
    }
    return "?storage_dir=" + encodeURIComponent(storageDir);
  }

  function apiPath(path) {
    return path + storageQuery();
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
    notification.hidden = true;
    notification.replaceChildren();
    notification.className = "page-notification";
    notification.setAttribute("role", "status");
  }

  function showNotification(kind, title, message, options) {
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

  function setFormError(message) {
    formError.textContent = message;
    formError.hidden = false;
    titleInput.setAttribute("aria-invalid", "true");
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
        "to" + "ken|secret|password|authorization|cookie|api[_-]?key|url|endpoint",
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
      if (summary.request_id === selectedRequestId) {
        item.classList.add("is-selected");
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
        selectedRequestId = summary.request_id;
        loadDetail(summary.request_id);
        renderList();
      });
      listContainer.appendChild(item);
    }
  }

  async function loadList() {
    hideNotification();
    setState(listContainer, "正在加载 Request 列表...", "loading-state");
    try {
      const result = await fetchJson(apiPath("/api/v1/requests"));
      loadedRequests = result.requests || [];
      syncStatusFilterOptions(loadedRequests);
      renderList();
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

  function renderSeedList(container, seeds) {
    if (!Array.isArray(seeds) || !seeds.length) {
      const empty = document.createElement("p");
      empty.className = "muted-text";
      empty.textContent = "无有效种子标题。";
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

  function renderDetailPayload(payload) {
    const request = payload.request || payload;
    const input = request.input || {};
    const sourceInfo = request.source_info || {};
    const matched = sourceInfo.matched_bangumi || {};
    const config = request.confirmable_config || {};
    const filterRule = config.filter_rule || {};
    const effectiveSeeds = config.effective_seed_names || [];

    detailContainer.className = "request-detail";
    detailContainer.replaceChildren();

    const heading = document.createElement("h3");
    heading.textContent = input.raw_title || matched.title || "Request";

    const overviewSection = createDetailSection("Overview", "overview-section");
    const overviewHeader = document.createElement("div");
    overviewHeader.className = "overview-actions";
    const overviewFields = detailList([
      ["request_id", request.request_id],
      ["status", request.status],
      ["原始标题", input.raw_title],
      ["匹配标题", matched.title],
    ]);
    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "secondary-button copy-request-id";
    copyButton.textContent = "复制 request_id";
    copyButton.addEventListener("click", () => {
      copyTextToClipboard(request.request_id);
    });
    overviewHeader.append(overviewFields, copyButton);
    overviewSection.appendChild(overviewHeader);

    const sourceSection = createDetailSection("Source", "source-section");
    sourceSection.appendChild(
      detailList([
        ["字幕组", config.selected_subtitle_group],
        ["RSS 来源", config.selected_rss_url ? "已选择" : "未选择"],
        ["匹配番剧标题", matched.title],
      ]),
    );

    const filterSection = createDetailSection("Filter", "filter-section");
    filterSection.appendChild(
      detailList([
        ["must_contain", filterRule.must_contain],
        ["must_not_contain", filterRule.must_not_contain],
        ["folder_name", config.expected_folder_name],
        ["有效种子数", effectiveSeeds.length],
      ]),
    );

    const seedsSection = createDetailSection("Seeds", "seeds-section");
    const seedDetails = document.createElement("details");
    seedDetails.className = "seed-details";
    const seedSummary = document.createElement("summary");
    seedSummary.textContent =
      "查看完整有效种子标题列表 (" + effectiveSeeds.length + ")";
    const seedsContainer = document.createElement("div");
    renderSeedList(seedsContainer, effectiveSeeds);
    seedDetails.append(seedSummary, seedsContainer);
    seedsSection.appendChild(seedDetails);

    const auditSection = createDetailSection("Audit", "audit-group-section");
    renderHistorySection(auditSection, payload.history);
    renderAbResultSection(auditSection, payload.ab_result);

    detailContainer.append(
      heading,
      overviewSection,
      sourceSection,
      filterSection,
      seedsSection,
      auditSection,
    );
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
      setState(detailContainer, error.message, "error-state");
      notifyApiError("Request 详情加载失败", error);
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

    hideNotification();
    setSubmitInFlight(true);
    persistWebPreferences();
    setState(detailContainer, "正在生成 Request...", "loading-state");
    try {
      const result = await fetchJson("/api/v1/requests", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: title,
          storage_dir: storageInput.value.trim() || null,
          save_request: saveInput.checked,
        }),
      });
      selectedRequestId = result.request && result.request.request_id;
      renderDetailPayload(result);
      await loadList();
      if (result.saved_request) {
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
        showNotification("success", "生成成功", "已生成 Request " + selectedRequestId);
      }
    } catch (error) {
      setState(detailContainer, error.message, "error-state");
      notifyApiError("生成失败", error);
    } finally {
      setSubmitInFlight(false);
    }
  }

  restoreWebPreferences();
  storageInput.addEventListener("change", persistWebPreferences);
  saveInput.addEventListener("change", persistWebPreferences);
  clearPreferencesButton.addEventListener("click", clearWebPreferences);
  refreshButton.addEventListener("click", loadList);
  listSearchInput.addEventListener("input", renderList);
  listStatusFilter.addEventListener("change", renderList);
  listSortSelect.addEventListener("change", renderList);
  form.addEventListener("submit", generateRequest);
  loadList();
})();
