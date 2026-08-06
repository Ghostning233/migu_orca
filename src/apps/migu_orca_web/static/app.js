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
      throw new Error(payload.error_message || "请求失败");
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
    setState(listContainer, "正在加载 Request 列表...", "loading-state");
    try {
      const result = await fetchJson(apiPath("/api/v1/requests"));
      loadedRequests = result.requests || [];
      syncStatusFilterOptions(loadedRequests);
      renderList();
    } catch (error) {
      setState(listContainer, error.message, "error-state");
    }
  }

  function addDetailRow(list, label, value) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = displayValue(value);
    list.append(term, description);
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
    const section = document.createElement("section");
    section.className = "audit-section";
    const heading = document.createElement("h4");
    heading.textContent = "状态历史";
    section.appendChild(heading);

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
    const section = document.createElement("section");
    section.className = "audit-section";
    const heading = document.createElement("h4");
    heading.textContent = "Auto Bangumi 结果";
    section.appendChild(heading);

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

    const fields = document.createElement("dl");
    fields.className = "detail-grid";
    addDetailRow(fields, "success", result.success);
    addDetailRow(fields, "ab_subscription_id", result.ab_subscription_id);
    addDetailRow(fields, "fallback_config", result.fallback_config ? "存在" : "无");
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

    detailContainer.className = "request-detail";
    detailContainer.replaceChildren();

    const heading = document.createElement("h3");
    heading.textContent = input.raw_title || matched.title || "Request";

    const fields = document.createElement("dl");
    fields.className = "detail-grid";
    addDetailRow(fields, "request_id", request.request_id);
    addDetailRow(fields, "status", request.status);
    addDetailRow(fields, "匹配标题", matched.title);
    addDetailRow(fields, "字幕组", config.selected_subtitle_group);
    addDetailRow(fields, "RSS 来源", config.selected_rss_url ? "已选择" : "未选择");
    addDetailRow(fields, "必须包含", filterRule.must_contain);
    addDetailRow(fields, "必须排除", filterRule.must_not_contain);
    addDetailRow(fields, "folder_name", config.expected_folder_name);
    addDetailRow(fields, "有效种子数", (config.effective_seed_names || []).length);

    const seedsHeading = document.createElement("h4");
    seedsHeading.textContent = "有效种子标题";
    const seedsContainer = document.createElement("div");
    renderSeedList(seedsContainer, config.effective_seed_names);

    detailContainer.append(heading, fields, seedsHeading, seedsContainer);
    renderHistorySection(detailContainer, payload.history);
    renderAbResultSection(detailContainer, payload.ab_result);
  }

  async function loadDetail(requestId) {
    if (!requestId) {
      setState(detailContainer, "Request ID 无效。", "error-state");
      return;
    }

    setState(detailContainer, "正在加载 Request 详情...", "loading-state");
    try {
      const result = await fetchJson(
        apiPath("/api/v1/requests/" + encodeURIComponent(requestId)),
      );
      renderDetailPayload(result);
    } catch (error) {
      setState(detailContainer, error.message, "error-state");
    }
  }

  async function generateRequest(event) {
    event.preventDefault();
    clearFormError();
    const title = titleInput.value.trim();
    if (!title) {
      setFormError("请输入标题，至少包含 1 个非空白字符。");
      titleInput.focus();
      return;
    }

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
    } catch (error) {
      setState(detailContainer, error.message, "error-state");
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
