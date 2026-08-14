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
  let currentDetailPayload = null;

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

  function buildCreateRequestPayload(title) {
    return {
      title: title,
      source: "static-fixture",
      storage_dir: storageInput.value.trim() || null,
      save_request: saveInput.checked,
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

  function setActionInFlight(isInFlight) {
    const buttons = detailContainer.querySelectorAll(".detail-action");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].disabled = isInFlight;
    }
  }

  function setAbSubmitInFlight(isInFlight) {
    var form = document.getElementById("detail-ab-submit-form");
    if (!form) {
      return;
    }
    var controls = form.querySelectorAll("button, input");
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i];
      if (control.tagName === "INPUT" && control.type === "hidden") {
        continue;
      }
      control.disabled = isInFlight;
    }
  }

  async function performAction(requestId, actionType, body) {
    if (!requestId) return;
    hideNotification();
    setActionInFlight(true);
    if (actionType === "submit-ab") {
      setAbSubmitInFlight(true);
    }
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
      if (actionType === "submit-ab") {
        const nextPayload = {
          ...(currentDetailPayload || {}),
          request: result.request,
          ab_result: {
            available: true,
            record: {
              request_id: requestId,
              ab_submit_result: result.ab_submit_result,
            },
            error: null,
          },
        };
        renderDetailPayload(nextPayload);
      } else {
        await loadDetail(requestId);
      }
      await loadList();
      showNotification("success", titles[actionType] || "操作成功",
        "Request " + requestId, {
          actions: [
            { label: "刷新列表", handler: loadList },
          ],
        });
    } catch (error) {
      notifyApiError(actionType === "submit-ab" ? "提交失败" : "操作失败", error);
    } finally {
      if (actionType === "submit-ab") {
        setAbSubmitInFlight(false);
      }
      setActionInFlight(false);
    }
  }

  function buildAbSubmitForm(request) {
    var container = document.createElement("div");
    container.id = "detail-ab-submit-form";
    container.className = "detail-section detail-inline-form";
    container.hidden = true;

    var heading = document.createElement("h4");
    heading.textContent = "Auto Bangumi 提交";
    container.appendChild(heading);

    var endpointLabel = document.createElement("label");
    endpointLabel.textContent = "endpoint";
    endpointLabel.htmlFor = "ab-submit-endpoint";
    var endpointInput = document.createElement("input");
    endpointInput.id = "ab-submit-endpoint";
    endpointInput.name = "ab_submit_endpoint";
    endpointInput.type = "text";
    endpointInput.autocomplete = "off";
    endpointInput.placeholder = "Auto Bangumi API 地址";
    container.append(endpointLabel, endpointInput);

    var tokenLabel = document.createElement("label");
    tokenLabel.textContent = "token";
    tokenLabel.htmlFor = "ab-submit-token";
    var tokenInput = document.createElement("input");
    tokenInput.id = "ab-submit-token";
    tokenInput.name = "ab_submit_token";
    tokenInput.type = "password";
    tokenInput.autocomplete = "off";
    tokenInput.placeholder = "Auto Bangumi Token";
    container.append(tokenLabel, tokenInput);

    var fallbackLabel = document.createElement("label");
    fallbackLabel.className = "checkbox-row";
    fallbackLabel.htmlFor = "ab-submit-fallback-enabled";
    var fallbackInput = document.createElement("input");
    fallbackInput.id = "ab-submit-fallback-enabled";
    fallbackInput.name = "ab_submit_fallback_enabled";
    fallbackInput.type = "checkbox";
    fallbackInput.value = "true";
    fallbackLabel.append(
      fallbackInput,
      document.createTextNode("fallback_enabled"),
    );
    container.appendChild(fallbackLabel);

    var help = document.createElement("p");
    help.className = "field-help";
    help.textContent = "配置仅用于本次提交，不写入浏览器存储、URL 或 storage JSON。";
    container.appendChild(help);

    var error = document.createElement("p");
    error.id = "ab-submit-form-error";
    error.className = "field-error";
    error.setAttribute("role", "alert");
    error.hidden = true;
    container.appendChild(error);

    function setAbFormError(message, field) {
      error.textContent = message;
      error.hidden = false;
      endpointInput.removeAttribute("aria-invalid");
      tokenInput.removeAttribute("aria-invalid");
      if (field) {
        field.setAttribute("aria-invalid", "true");
        field.focus();
      }
    }

    function clearAbFormError() {
      error.textContent = "";
      error.hidden = true;
      endpointInput.removeAttribute("aria-invalid");
      tokenInput.removeAttribute("aria-invalid");
    }

    var btnRow = document.createElement("div");
    btnRow.className = "notification-actions";

    var submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "detail-action";
    submitBtn.textContent = "提交 Auto Bangumi";
    submitBtn.addEventListener("click", function () {
      clearAbFormError();
      var endpoint = endpointInput.value.trim();
      if (!endpoint) {
        setAbFormError("提交 Auto Bangumi 前必须填写 endpoint。", endpointInput);
        return;
      }
      var token = tokenInput.value.trim();
      if (!token) {
        setAbFormError("提交 Auto Bangumi 前必须填写 token。", tokenInput);
        return;
      }
      if (!window.confirm("确认提交此 Request 到 Auto Bangumi？")) {
        return;
      }
      performAction(request.request_id, "submit-ab", {
        storage_dir: storageInput.value.trim() || null,
        ab_config: {
          endpoint: endpoint,
          token: token,
          fallback_enabled: fallbackInput.checked,
        },
      });
    });
    btnRow.appendChild(submitBtn);

    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "secondary-button detail-action";
    cancelBtn.textContent = "取消";
    cancelBtn.addEventListener("click", function () {
      clearAbFormError();
      container.hidden = true;
    });
    btnRow.appendChild(cancelBtn);

    container.appendChild(btnRow);
    return container;
  }

  function buildModifyForm(request) {
    var config = request.confirmable_config || {};
    var sourceInfo = request.source_info || {};
    var rssSources = sourceInfo.rss_sources || [];
    var filterRule = config.filter_rule || {};

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

    var mcLabel = document.createElement("label");
    mcLabel.textContent = "must_contain";
    mcLabel.htmlFor = "modify-must-contain";
    var mcInput = document.createElement("input");
    mcInput.id = "modify-must-contain";
    mcInput.type = "text";
    mcInput.value = filterRule.must_contain || "";
    mcInput.placeholder = "正则筛选规则（包含）";
    container.appendChild(mcLabel);
    container.appendChild(mcInput);

    var mncLabel = document.createElement("label");
    mncLabel.textContent = "must_not_contain";
    mncLabel.htmlFor = "modify-must-not-contain";
    var mncInput = document.createElement("input");
    mncInput.id = "modify-must-not-contain";
    mncInput.type = "text";
    mncInput.value = filterRule.must_not_contain || "";
    mncInput.placeholder = "正则筛选规则（排除）";
    container.appendChild(mncLabel);
    container.appendChild(mncInput);

    var fnLabel = document.createElement("label");
    fnLabel.textContent = "folder_name";
    fnLabel.htmlFor = "modify-folder-name";
    var fnInput = document.createElement("input");
    fnInput.id = "modify-folder-name";
    fnInput.type = "text";
    fnInput.value = config.expected_folder_name || "";
    fnInput.placeholder = "期望存储目录名";
    container.appendChild(fnLabel);
    container.appendChild(fnInput);

    var btnRow = document.createElement("div");
    btnRow.className = "notification-actions";

    var submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "detail-action";
    submitBtn.textContent = "提交修改";
    submitBtn.addEventListener("click", function () {
      var patch = {};
      if (groupSelect.value) {
        patch.selected_subtitle_group = groupSelect.value;
      }
      var mcVal = mcInput.value.trim();
      var mncVal = mncInput.value.trim();
      if (mcVal || mncVal) {
        patch.filter_rule = {};
        if (mcVal) patch.filter_rule.must_contain = mcVal;
        if (mncVal) patch.filter_rule.must_not_contain = mncVal;
      }
      var fnVal = fnInput.value.trim();
      if (fnVal) {
        patch.expected_folder_name = fnVal;
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

  function renderDetailPayload(payload) {
    currentDetailPayload = payload;
    var request = payload.request || payload;
    var input = request.input || {};
    var sourceInfo = request.source_info || {};
    var matched = sourceInfo.matched_bangumi || {};
    var config = request.confirmable_config || {};
    var filterRule = config.filter_rule || {};
    var effectiveSeeds = config.effective_seed_names || [];

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

    if (isPending) {
      var acceptBtn = document.createElement("button");
      acceptBtn.type = "button";
      acceptBtn.className = "detail-action";
      acceptBtn.textContent = "确认";
      acceptBtn.addEventListener("click", function () {
        if (window.confirm("确认接受此 Request？")) {
          performAction(request.request_id, "accept", {});
        }
      });
      actionsContainer.appendChild(acceptBtn);

      var cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "secondary-button detail-action";
      cancelBtn.textContent = "取消";
      cancelBtn.addEventListener("click", function () {
        var reason = window.prompt("请输入取消原因（可选）：") || "";
        performAction(request.request_id, "cancel", {
          cancel_reason: reason || undefined,
        });
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

      var abSubmitBtn = document.createElement("button");
      abSubmitBtn.type = "button";
      abSubmitBtn.className = "secondary-button detail-action";
      abSubmitBtn.textContent = "提交 Auto Bangumi";
      abSubmitBtn.addEventListener("click", function () {
        var form = document.getElementById("detail-ab-submit-form");
        if (form) {
          form.hidden = !form.hidden;
          if (!form.hidden) {
            var endpoint = document.getElementById("ab-submit-endpoint");
            if (endpoint) {
              endpoint.focus();
            }
          }
        }
      });
      actionsContainer.appendChild(abSubmitBtn);
    } else {
      var statusNote = document.createElement("p");
      statusNote.className = "field-help";
      statusNote.textContent = "此 Request 已" + fieldValue(request.status) + "，不可操作。";
      actionsContainer.appendChild(statusNote);
    }

    var modifyForm = buildModifyForm(request);
    var abSubmitForm = buildAbSubmitForm(request);

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
      ]),
    );

    var seedsSection = createDetailSection("Seeds", "seeds-section");
    var seedDetails = document.createElement("details");
    seedDetails.className = "seed-details";
    var seedSummary = document.createElement("summary");
    seedSummary.textContent =
      "查看完整有效种子标题列表 (" + effectiveSeeds.length + ")";
    var seedsContainer = document.createElement("div");
    renderSeedList(seedsContainer, effectiveSeeds);
    seedDetails.append(seedSummary, seedsContainer);
    seedsSection.appendChild(seedDetails);

    var auditSection = createDetailSection("Audit", "audit-group-section");
    renderHistorySection(auditSection, payload.history);
    renderAbResultSection(auditSection, payload.ab_result);

    detailContainer.append(
      heading,
      actionsContainer,
      modifyForm,
      abSubmitForm,
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
    persistWebPreferences();
    setState(detailContainer, "正在生成 Request...", "loading-state");
    try {
      const result = await fetchJson("/api/v1/requests", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          ...payload,
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
