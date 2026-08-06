(function () {
  const form = document.getElementById("request-generate-form");
  const titleInput = document.getElementById("request-title");
  const storageInput = document.getElementById("storage-dir");
  const saveInput = document.getElementById("save-request");
  const refreshButton = document.getElementById("request-list-refresh");
  const listContainer = document.getElementById("request-list-container");
  const detailContainer = document.getElementById("request-detail-container");

  let selectedRequestId = null;

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

  function fieldValue(value) {
    if (value === null || value === undefined || value === "") {
      return "未设置";
    }
    if (Array.isArray(value)) {
      return value.length ? value.join("，") : "无";
    }
    return String(value);
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

  function renderList(requests) {
    listContainer.className = "request-list";
    listContainer.replaceChildren();
    if (!requests.length) {
      setState(listContainer, "暂无已保存的 Request。", "empty-state");
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
        renderList(requests);
      });
      listContainer.appendChild(item);
    }
  }

  async function loadList() {
    setState(listContainer, "正在加载 Request 列表...", "loading-state");
    try {
      const result = await fetchJson(apiPath("/api/v1/requests"));
      renderList(result.requests || []);
    } catch (error) {
      setState(listContainer, error.message, "error-state");
    }
  }

  function addDetailRow(list, label, value) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = fieldValue(value);
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
      item.textContent = fieldValue(seed);
      list.appendChild(item);
    }
    container.appendChild(list);
  }

  function renderDetail(request) {
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
      renderDetail(result.request || {});
    } catch (error) {
      setState(detailContainer, error.message, "error-state");
    }
  }

  async function generateRequest(event) {
    event.preventDefault();
    setState(detailContainer, "正在生成 Request...", "loading-state");
    try {
      const result = await fetchJson("/api/v1/requests", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: titleInput.value,
          storage_dir: storageInput.value.trim() || null,
          save_request: saveInput.checked,
        }),
      });
      selectedRequestId = result.request && result.request.request_id;
      renderDetail(result.request || {});
      await loadList();
    } catch (error) {
      setState(detailContainer, error.message, "error-state");
    }
  }

  refreshButton.addEventListener("click", loadList);
  form.addEventListener("submit", generateRequest);
  loadList();
})();
