from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.parse import urlencode

from .client import BecaClient
from .config import require_env


WORK_IN_PROCESS_URL = "https://work.becawork.vn/api/Default/Work_GetWorkInProcess"
MY_WORK_COUNT_BY_PROJECT_URL = "https://work.becawork.vn/api/Default/Work_MyWorkCountByProject"
GET_LOGTIME_URL = "https://work.becawork.vn/api/Default/Work_GetLogtimeByWorkId"
CHECK_OVER_LOGTIME_URL = "https://work.becawork.vn/api/Default/Work_CheckOverInLogtime"
GET_API_SETTING_URL = "https://work.becawork.vn/api/Default/Work_GetApiSetting"
GET_INF_LOGIN_URL = "https://work.becawork.vn/api/Default/Work_GetInfLogin?IsMobile=false"
GET_FORMAT_WORKFLOW_URL = "https://work.becawork.vn/api/ApiEoffice/Eoffice_GetData"
SAVE_FORM_URL = "https://work.becawork.vn/api/ApiEoffice/Eoffice_ValidateAndInsertData"
WORK_DETAIL_INFO_URL = "https://work.becawork.vn/api/Default/Work_DetailInfo"
UPDATE_JSON_DATA_URL = "https://work.becawork.vn/api/Default/Work_UpdateJsonData"
GET_NEXT_STATUS_URL = "https://work.becawork.vn/api/Default/Work_GetNextStatus"
GET_STATUS_BY_PROJECT_URL = "https://work.becawork.vn/api/Default/Work_getStatusByProject"
GET_WORK_BY_CODE_URL = "https://work.becawork.vn/api/Default/Work_GetWorkByCode"
INSERT_HISTORY_STATUS_WORK_URL = "https://work.becawork.vn/api/Default/Work_InsertHistoryStatusWork"
UPDATE_WORK_BY_WORK_PROCESS_URL = "https://work.becawork.vn/api/Default/Work_UpdateWorkByWorkProcess"
GET_WORK_CHILD_URL = "https://work.becawork.vn/api/Default/Work_GetWorkChild"
CREATE_WORK_ID_TEMP_URL = "https://work.becawork.vn/api/Default/Work_CreateWorkIdTemp"
INSERT_WORK_URL = "https://work.becawork.vn/api/Default/Work_InsertWork"
CHECK_APPLY_SLA_IN_PROJECT_URL = "https://work.becawork.vn/api/Default/Work_CheckApplySLAInProject"


def get_work_in_process(client: BecaClient, print_body: bool = True) -> list[dict]:
    params = {
        "title": "",
        "projectName": "",
        "group": "",
        "status": "          ",
        "employee": "",
        "type": "Xử lý",
        "isComplete": 1,
        "layout": 2,
        "pageNumber": 1,
        "rowNumber": int(os.getenv("WORK_ROW_NUMBER", "100")),
        "projectType": "",
        "typeSort": 0,
        "overDue": -1,
    }

    data = client.request_json(
        f"{WORK_IN_PROCESS_URL}?{urlencode(params)}",
        print_body=print_body,
    )
    return data if isinstance(data, list) else []


def list_workflows(client: BecaClient) -> list[dict[str, object]]:
    project_id = os.getenv("LOG_PROJECT_ID", "").strip()
    keyword = os.getenv("LOG_WORK_TITLE_KEYWORD", "").strip().lower()
    works = get_work_in_process(client, print_body=False)

    rows = [normalize_work(work) for work in works]
    if project_id:
        rows = [row for row in rows if str(row["project_id"]).strip() == project_id]
    if keyword:
        rows = [row for row in rows if keyword in str(row["title"]).lower()]

    print_work_table(rows)
    return rows


def list_projects(client: BecaClient) -> list[dict[str, object]]:
    project_type = os.getenv("PROJECT_LIST_TYPE", "Việc đã xử lý")
    data = client.request_json(
        f"{MY_WORK_COUNT_BY_PROJECT_URL}?{urlencode({'type': project_type})}",
        print_body=False,
    )
    projects = data if isinstance(data, list) else []
    rows = [normalize_project(project) for project in projects]
    print_project_table(rows, project_type)
    return rows


def normalize_work(work: dict) -> dict[str, object]:
    workflow_id = work.get("userWorkflowId") or work.get("workId") or work.get("id")
    project_id = str(work.get("projectId") or "").strip()
    return {
        "workflow_id": str(workflow_id).strip() if workflow_id is not None else "",
        "title": work.get("title") or work.get("Title") or "",
        "project_id": project_id,
        "project_name": work.get("projectName") or "",
        "status": work.get("statusName") or work.get("status") or "",
        "start": work.get("start") or "",
        "end": work.get("end") or "",
    }


def normalize_project(project: dict) -> dict[str, object]:
    project_id = (
        project.get("projectId")
        or project.get("ProjectId")
        or project.get("id")
        or project.get("Id")
        or project.get("value")
    )
    name = (
        project.get("projectName")
        or project.get("ProjectName")
        or project.get("name")
        or project.get("Name")
        or project.get("title")
        or project.get("Title")
        or project.get("label")
    )
    count = (
        project.get("total")
        or project.get("Total")
        or project.get("count")
        or project.get("Count")
        or project.get("quantity")
        or project.get("Quantity")
        or project.get("qty")
        or project.get("Qty")
        or project.get("soLuong")
        or project.get("SoLuong")
    )
    return {
        "project_id": str(project_id).strip() if project_id is not None else "",
        "project_name": name or "",
        "count": count if count is not None else "",
        "raw": project,
    }


def print_work_table(rows: list[dict[str, object]]) -> None:
    if not rows:
        print("No works found.")
        return

    print(f"{'#':>2}  {'WORKFLOW_ID':<12}  {'PROJECT_ID':<12}  {'STATUS':<10}  TITLE")
    for index, row in enumerate(rows, start=1):
        title = str(row["title"]).replace("\n", " ")
        if len(title) > 90:
            title = f"{title[:87]}..."
        print(
            f"{index:>2}  {str(row['workflow_id']):<12}  "
            f"{str(row['project_id']):<12}  {str(row['status']):<10}  {title}"
        )


def print_project_table(rows: list[dict[str, object]], project_type: str) -> None:
    if not rows:
        print(f"No projects found for type: {project_type}")
        return

    print(f"Type: {project_type}")
    print(f"{'#':>2}  {'PROJECT_ID':<12}  {'COUNT':<8}  PROJECT_NAME")
    for index, row in enumerate(rows, start=1):
        name = str(row["project_name"]).replace("\n", " ")
        if len(name) > 90:
            name = f"{name[:87]}..."
        print(
            f"{index:>2}  {str(row['project_id']):<12}  "
            f"{str(row['count']):<8}  {name}"
        )


def print_status_table(rows: list[dict[str, object]], title: str) -> None:
    if not rows:
        print(f"No statuses found. {title}")
        return

    print(title)
    print(f"{'#':>2}  {'STATUS_ID':<12}  {'CURRENT':<8}  {'TYPE':<12}  NAME")
    for index, row in enumerate(rows, start=1):
        print(
            f"{index:>2}  {str(row['status_id']):<12}  "
            f"{str(row['is_current']):<8}  {str(row['status_type']):<12}  {row['name']}"
        )


def get_logtime(client: BecaClient, workflow_id: str, print_body: bool = True) -> object | None:
    url = f"{GET_LOGTIME_URL}?{urlencode({'WorkFlowId': workflow_id})}"
    return client.request_json(url, print_body=print_body)


def get_work_detail(client: BecaClient, workflow_id: str, print_body: bool = True) -> object | None:
    url = f"{WORK_DETAIL_INFO_URL}?{urlencode({'workId': workflow_id})}"
    return client.request_json(url, print_body=print_body)


def get_work_by_code(client: BecaClient, workflow_id: str, print_body: bool = True) -> object | None:
    url = f"{GET_WORK_BY_CODE_URL}?{urlencode({'WorkId': workflow_id})}"
    return client.request_json(url, print_body=print_body)


def update_progress(client: BecaClient) -> dict[str, object | None]:
    workflow_id = require_env("WORKFLOW_ID")
    progress = normalize_progress(require_env("WORK_PROGRESS"))
    before = get_work_detail(client, workflow_id, print_body=False)

    params = {
        "userWorkFlowId": workflow_id,
        "fileName": "Tiendo",
        "value": progress,
    }
    headers = {
        "Origin": "https://work.becawork.vn",
        "Referer": f"https://work.becawork.vn/work/mywork?workId={workflow_id}",
    }
    result = client.request_json(
        f"{UPDATE_JSON_DATA_URL}?{urlencode(params)}",
        headers=headers,
        method="PUT",
        print_body=False,
    )
    after = get_work_detail(client, workflow_id, print_body=False)

    output = {
        "workflow_id": workflow_id,
        "old_progress": progress_from_detail(before),
        "requested_progress": progress,
        "new_progress": progress_from_detail(after),
        "update_response": result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output


def list_statuses(client: BecaClient) -> list[dict[str, object]]:
    workflow_id = require_env("WORKFLOW_ID")
    detail = require_work_detail(client, workflow_id)
    rows = [normalize_status(status) for status in get_next_statuses(client, workflow_id, detail)]
    print_status_table(rows, f"Available statuses for WORKFLOW_ID={workflow_id}")
    return rows


def list_project_statuses(client: BecaClient) -> list[dict[str, object]]:
    project_id = os.getenv("LOG_PROJECT_ID", "").strip()
    if not project_id:
        detail = require_work_detail(client, require_env("WORKFLOW_ID"))
        project_id = str(detail.get("projectId") or "").strip()

    rows = [normalize_status(status) for status in get_statuses_by_project(client, project_id)]
    print_status_table(rows, f"All statuses for PROJECT_ID={project_id}")
    return rows


def update_status(client: BecaClient) -> dict[str, object | None]:
    workflow_id = require_env("WORKFLOW_ID")
    target_status = require_env("WORK_STATUS")
    before = require_work_detail(client, workflow_id)
    work_value = get_work_by_code(client, workflow_id, print_body=False)
    statuses = get_next_statuses(client, workflow_id, before)
    selected = find_status(statuses, target_status)

    if not selected and is_truthy(os.getenv("WORK_STATUS_ALLOW_ANY")):
        selected = find_status(
            get_statuses_by_project(client, str(before.get("projectId") or "")),
            target_status,
        )
    if not selected:
        raise SystemExit(f"Cannot find allowed WORK_STATUS: {target_status}")

    old_status_id = str(before.get("status") or "").strip()
    new_status_id = str(selected.get("userWorkflowId") or "").strip()
    if not new_status_id:
        raise SystemExit(f"Status has no userWorkflowId: {selected}")

    update_result: object | None = {"skipped": True}
    history_result: object | None = {"skipped": True}
    process_result: object | None = {"skipped": True}
    progress_result: object | None = {"skipped": True}

    if old_status_id != new_status_id:
        update_result = update_work_field(client, workflow_id, "TrangThaiCongViec", new_status_id)
        history_result = insert_status_history(client, workflow_id, old_status_id, new_status_id)
        node_id = work_value.get("nodeid") if isinstance(work_value, dict) else None
        if node_id:
            process_result = update_work_process(client, workflow_id, str(node_id))
        if selected.get("trangThaiCongViec") == "Hoàn thành":
            progress_result = update_work_field(client, workflow_id, "Tiendo", "100%")

    after = require_work_detail(client, workflow_id)
    output = {
        "workflow_id": workflow_id,
        "old_status_id": old_status_id,
        "old_status_name": before.get("statusName"),
        "requested_status": target_status,
        "new_status_id": after.get("status"),
        "new_status_name": after.get("statusName"),
        "selected_status": normalize_status(selected),
        "update_response": update_result,
        "history_response": history_result,
        "process_response": process_result,
        "progress_response": progress_result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output


def inspect_child_work_payload(client: BecaClient) -> dict[str, object | None]:
    return build_child_work_output(client, dry_run=True)


def create_child_work(client: BecaClient) -> dict[str, object | None]:
    return build_child_work_output(client, dry_run=is_truthy(os.getenv("CHILD_DRY_RUN")))


def build_child_work_output(client: BecaClient, dry_run: bool) -> dict[str, object | None]:
    parent_id = require_env("WORKFLOW_ID")
    title = require_env("CHILD_TITLE")
    child_context = build_child_work_context(client, parent_id, title)

    output: dict[str, object | None] = {
        **child_context["metadata"],
        "dry_run": dry_run,
        "payload": child_context["payload"],
    }
    if dry_run:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return output

    sla_result = check_apply_sla_in_project(
        client,
        str(child_context["metadata"]["project_id"]),
        str(child_context["metadata"]["status_id"]),
        str(child_context["metadata"]["priority"]),
        parent_id,
    )
    if response_data(sla_result) == "NotAllow":
        raise SystemExit("Cannot create child work. Work_CheckApplySLAInProject returned NotAllow.")

    work_id_temp = create_work_id_temp(client)
    insert_result = insert_work(
        client,
        child_context["payload"],
        str(child_context["metadata"]["form_id"]),
        str(child_context["metadata"]["step_id"]),
        work_id_temp,
        parent_id,
    )
    created_id = extract_created_work_id(insert_result)
    children_after = get_work_children(client, parent_id)

    output.update(
        {
            "work_id_temp": work_id_temp,
            "created_workflow_id": created_id,
            "insert_response": insert_result,
            "children_after_count": len(children_after),
            "children_after": [normalize_work(child) for child in children_after],
        }
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output


def build_child_work_context(client: BecaClient, parent_id: str, title: str) -> dict[str, object]:
    detail = require_work_detail(client, parent_id)
    work_value = get_work_by_code(client, parent_id, print_body=False)
    api_setting = get_api_setting(client)
    form_id = str(api_setting["id_getWorkForm"]["id"])
    step_id = str(api_setting["id_StepWork"]["id"])
    project_id = child_project_id(detail, work_value)
    form_format = get_format_workflow(
        client,
        form_id,
        project_id=project_id,
        work_id=parent_id,
        is_child=True,
        work_type=os.getenv("CHILD_WORK_TYPE") or None,
    )
    user = get_current_user(client)
    current_user_id = person_ref(user.get("id"))
    children = get_work_children(client, parent_id)

    status_id = child_status_id(client, project_id, form_format)
    priority = os.getenv("CHILD_PRIORITY") or default_field_value(form_format, "Douutien") or "Bình thường"
    assignee = os.getenv("CHILD_ASSIGNEE") or current_user_id
    assigner = os.getenv("CHILD_ASSIGNER") or default_field_value(form_format, "Nguoigiao") or current_user_id
    category_id = (
        os.getenv("CHILD_CATEGORY_ID")
        or default_field_value(form_format, "Loaicv")
        or dict_value(work_value, "loaicv")
    )

    values: dict[str, object] = {
        "Tieude": title,
        "Nguoixuly": assignee,
        "TrangThaiCongViec": status_id,
        "Ngaybatdau": os.getenv("CHILD_START") or now_minute_string(),
        "Ngayketthuc": os.getenv("CHILD_END"),
        "Douutien": priority,
        "Tiendo": child_progress_value(),
        "Noidung": html_description(os.getenv("CHILD_DESCRIPTION", "")) if os.getenv("CHILD_DESCRIPTION") else "",
        "Nguoigiao": assigner,
        "Nguoiphoihop": os.getenv("CHILD_COOPERATORS"),
        "Nguoitheodoi": os.getenv("CHILD_FOLLOWERS"),
        "Duan": project_id,
        "IndexWork": str(len(children) + 1),
        "Loaicv": category_id,
        "GroupProject": dict_value(work_value, "groupProject") or dict_value(detail, "groupProjectId"),
        "QuyTrinhDinhKem": os.getenv("CHILD_PROCESS_ID"),
        "CongViecCha": parent_id,
        "FormExtendWorkflowId": os.getenv("CHILD_FORM_EXTEND_WORKFLOW_ID", ""),
        "IsActive": "True",
        "IsDelete": "False",
        "Ngaygiaoviec": now_string(),
        "NguoiXuLyDauTien": assignee,
        "IsAddUserExcuteByChangeStatus": "True",
        "IsCreateWorkChild": "True",
        "RequireAttachFileToCompleteWork": default_field_value(
            form_format,
            "RequireAttachFileToCompleteWork",
        )
        or "0",
    }
    fields = object_to_fields(values, form_format)
    payload = {
        "data": fields,
        "data_json": json.dumps({item["name"]: item["value"] for item in fields}, ensure_ascii=False),
        "isDraft": True,
    }
    metadata = {
        "parent_workflow_id": parent_id,
        "parent_title": detail.get("title"),
        "project_id": project_id,
        "project_name": detail.get("projectName"),
        "form_id": form_id,
        "step_id": step_id,
        "status_id": status_id,
        "status_name": status_name(client, project_id, status_id),
        "priority": priority,
        "category_id": category_id,
        "assignee": assignee,
        "assigner": assigner,
        "children_before_count": len(children),
    }
    return {"payload": payload, "metadata": metadata}


def check_over_logtime(
    client: BecaClient,
    log_date: str,
    hours: str,
    old_hours: str = "0",
) -> object | None:
    params = {
        "newVal": hours,
        "oldVal": old_hours,
        "day": log_date,
        "isCheckin": "false",
    }
    return client.request_json(f"{CHECK_OVER_LOGTIME_URL}?{urlencode(params)}")


def add_logtime(client: BecaClient) -> object | None:
    workflow_id = require_env("WORKFLOW_ID")
    log_date = require_env("LOG_DATE")
    hours = os.getenv("LOG_HOURS", "8")
    description = os.getenv("LOG_DESCRIPTION", "test")
    action = os.getenv("LOG_ACTION", "Thực hiện")
    project_id = get_project_id(client, workflow_id)

    print("Checking logtime before submit...")
    check_result = check_over_logtime(client, log_date, hours)
    if isinstance(check_result, (int, float)) and check_result < 0:
        raise SystemExit(f"Cannot add logtime. Work_CheckOverInLogtime returned {check_result}.")

    api_setting = get_api_setting(client)
    form_id = str(api_setting["id_getWorkFormLogTime"]["id"])
    step_id = str(api_setting["id_getWorkFormLogTimeStep"]["id"])
    form_format = get_format_workflow(client, form_id)
    user = get_current_user(client)

    values = {
        "Nguoilap": default_field_value(form_format, "Nguoilap") or user.get("fullName"),
        "Ngaylap": now_string(),
        "Email": default_field_value(form_format, "Email") or user.get("email"),
        "Duan": project_id,
        "Congviec": workflow_id,
        "Ngay": f"{log_date} 00:00:00",
        "SoGio": hours,
        "Hanhdong": action,
        "Mota": html_description(description),
        "UserId": f"P:{user.get('id')}",
    }
    fields = object_to_fields(values, form_format)
    payload = {
        "data": fields,
        "data_json": json.dumps({item["name"]: item["value"] for item in fields}, ensure_ascii=False),
        "isDraft": True,
    }
    params = {
        "urlStr": f"/api/apikey/userWorkflows/{form_id}/addDynamicUserWorkflow/{step_id}",
        "apiId": form_id,
    }
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://work.becawork.vn",
        "Referer": f"https://work.becawork.vn/work/mywork?workId={workflow_id}",
    }
    return client.request_json(
        f"{SAVE_FORM_URL}?{urlencode(params)}",
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )


def get_project_id(client: BecaClient, workflow_id: str) -> str:
    project_id = os.getenv("LOG_PROJECT_ID")
    if project_id:
        return project_id

    logs = get_logtime(client, workflow_id, print_body=False)
    if isinstance(logs, list) and logs:
        value = logs[0].get("Duan")
        if value:
            return str(value).strip()

    raise SystemExit("Missing LOG_PROJECT_ID. Could not infer project id from existing logtime.")


def get_api_setting(client: BecaClient) -> dict:
    data = client.request_json(GET_API_SETTING_URL, print_body=False)
    if not isinstance(data, dict):
        raise SystemExit("Cannot load Work_GetApiSetting.")
    return data


def get_current_user(client: BecaClient) -> dict:
    data = client.request_json(GET_INF_LOGIN_URL, print_body=False)
    if not isinstance(data, dict):
        raise SystemExit("Cannot load Work_GetInfLogin.")
    return data


def get_format_workflow(
    client: BecaClient,
    form_id: str,
    project_id: str = "undefined",
    work_id: str = "undefined",
    is_child: bool | None = None,
    work_type: str | None = None,
) -> list:
    params = {
        "urlStr": "getFormatWorkflow",
        "projectId": project_id,
        "workId": work_id,
    }
    body = json.dumps(
        [
            {"Name": "id", "Value": form_id},
            {"Name": "isChild", "Value": is_child},
            {"Name": "WorkType", "Value": work_type},
        ]
    ).encode("utf-8")
    data = client.request_json(
        f"{GET_FORMAT_WORKFLOW_URL}?{urlencode(params)}",
        headers={"Content-Type": "application/json; charset=UTF-8"},
        data=body,
        method="POST",
        print_body=False,
    )
    if not isinstance(data, list):
        raise SystemExit("Cannot load workflow form format.")
    return data


def get_work_children(client: BecaClient, workflow_id: str) -> list[dict]:
    params = {"WorkflowCode": workflow_id, "newLayout": "true"}
    data = client.request_json(f"{GET_WORK_CHILD_URL}?{urlencode(params)}", print_body=False)
    if isinstance(data, list) and data:
        return data
    # newLayout=true only returns children one level below a Story; a Task
    # parented under another Task (nesting beyond that) comes back empty
    # there even though BecaWork's own UI shows it. newLayout=false (legacy
    # shape) still returns those deeper children, so fall back to it.
    params = {"WorkflowCode": workflow_id, "newLayout": "false"}
    data = client.request_json(f"{GET_WORK_CHILD_URL}?{urlencode(params)}", print_body=False)
    return data if isinstance(data, list) else []


def create_work_id_temp(client: BecaClient) -> str:
    data = client.request_json(CREATE_WORK_ID_TEMP_URL, print_body=False)
    return str(data).strip()


def check_apply_sla_in_project(
    client: BecaClient,
    project_id: str,
    status_id: str,
    priority: str,
    workflow_id: str,
) -> object | None:
    params = {
        "projectId": project_id,
        "statusId": status_id,
        "priority": priority,
    }
    return client.request_json(
        f"{CHECK_APPLY_SLA_IN_PROJECT_URL}?{urlencode(params)}",
        headers=work_headers(workflow_id),
        print_body=False,
    )


def insert_work(
    client: BecaClient,
    payload: dict[str, object],
    form_id: str,
    step_id: str,
    work_id_temp: str,
    parent_id: str,
) -> object | None:
    url_str = f"/api/apikey/userWorkflows/{form_id}/addDynamicUserWorkflow/{step_id}"
    params = {
        "urlStr": url_str,
        "apiId": form_id,
        "workIdTemp": work_id_temp,
    }
    return client.request_json(
        f"{INSERT_WORK_URL}?{urlencode(params)}",
        headers={**work_headers(parent_id), "Content-Type": "application/json; charset=UTF-8"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        print_body=False,
    )


def default_field_value(form_format: list, name: str) -> str | None:
    field = find_field(form_format, name)
    value = field.get("defaultValue") if field else None
    return str(value) if value is not None else None


def child_project_id(detail: dict, work_value: object | None) -> str:
    candidates = [
        os.getenv("CHILD_PROJECT_ID"),
        os.getenv("LOG_PROJECT_ID"),
        detail.get("projectId"),
        detail.get("projectCode"),
        dict_value(work_value, "duan"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate).strip()
    raise SystemExit("Cannot infer project id for child work. Set CHILD_PROJECT_ID or LOG_PROJECT_ID.")


def child_status_id(client: BecaClient, project_id: str, form_format: list) -> str:
    requested = os.getenv("CHILD_STATUS", "Open")
    statuses = get_statuses_by_project(client, project_id)
    selected = find_status(statuses, requested)
    if selected:
        return str(selected.get("userWorkflowId") or "").strip()

    fallback = default_field_value(form_format, "TrangThaiCongViec")
    if fallback:
        return fallback
    raise SystemExit(f"Cannot find CHILD_STATUS in project statuses: {requested}")


def status_name(client: BecaClient, project_id: str, status_id: str) -> str | None:
    selected = find_status(get_statuses_by_project(client, project_id), status_id)
    return str(selected.get("name")) if selected else None


def child_progress_value() -> str | None:
    progress = os.getenv("CHILD_PROGRESS", "").strip()
    return normalize_progress(progress) if progress else None


def dict_value(data: object | None, key: str) -> object | None:
    return data.get(key) if isinstance(data, dict) else None


def response_data(data: object | None) -> object | None:
    if isinstance(data, dict) and "data" in data:
        return data.get("data")
    return data


def person_ref(value: object | None) -> str:
    user_id = str(value or "").strip()
    if not user_id:
        return ""
    return user_id if user_id.startswith("P:") else f"P:{user_id}"


def extract_created_work_id(data: object | None) -> str | None:
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, dict):
            value = nested.get("id") or nested.get("UserWorkflowId") or nested.get("userWorkflowId")
            return str(value) if value is not None else None
        if nested is not None:
            return str(nested)

        value = data.get("id") or data.get("UserWorkflowId") or data.get("userWorkflowId")
        return str(value) if value is not None else None
    return None


def find_field(form_format: list, name: str) -> dict | None:
    for section in form_format:
        for field in section.get("row", []):
            if field.get("name") == name:
                return field
    return None


def object_to_fields(values: dict[str, object], form_format: list) -> list[dict[str, object]]:
    fields = []
    for name, value in values.items():
        field = find_field(form_format, name)
        if field and field.get("type") == "dateTime" and value:
            field_value = str(value)
        elif value is None or value == "":
            field_value = None
        else:
            field_value = str(value)
        fields.append({"name": name, "value": field_value})
    return fields


def html_description(description: str) -> str:
    if description.lstrip().startswith("<"):
        return description
    return f"<p>{description}</p>"


def normalize_progress(value: str) -> str:
    raw_value = value.strip().removesuffix("%").strip()
    try:
        progress = int(raw_value)
    except ValueError as exc:
        raise SystemExit("WORK_PROGRESS must be a number from 0 to 100.") from exc

    if progress < 0 or progress > 100:
        raise SystemExit("WORK_PROGRESS must be from 0 to 100.")
    return f"{progress}%"


def progress_from_detail(detail: object | None) -> object | None:
    if not isinstance(detail, dict):
        return None
    return detail.get("progress") or detail.get("tiendo")


def require_work_detail(client: BecaClient, workflow_id: str) -> dict:
    detail = get_work_detail(client, workflow_id, print_body=False)
    if not isinstance(detail, dict):
        raise SystemExit(f"Cannot load work detail for WORKFLOW_ID={workflow_id}.")
    return detail


def get_next_statuses(client: BecaClient, workflow_id: str, detail: dict) -> list[dict]:
    project_id = str(detail.get("projectId") or "").strip()
    params = {
        "WorkId": workflow_id,
        "projectId": project_id,
        "useForChild": os.getenv("WORK_STATUS_USE_FOR_CHILD", "false"),
    }
    data = client.request_json(f"{GET_NEXT_STATUS_URL}?{urlencode(params)}", print_body=False)
    return data if isinstance(data, list) else []


def get_statuses_by_project(client: BecaClient, project_id: str) -> list[dict]:
    params = {
        "projectCode": project_id,
        "notGetStatusForChild": os.getenv("WORK_STATUS_NOT_GET_CHILD", "false"),
    }
    data = client.request_json(f"{GET_STATUS_BY_PROJECT_URL}?{urlencode(params)}", print_body=False)
    return data if isinstance(data, list) else []


def normalize_status(status: dict) -> dict[str, object]:
    return {
        "status_id": str(status.get("userWorkflowId") or "").strip(),
        "row_id": status.get("id"),
        "name": status.get("name") or "",
        "status_type": status.get("trangThaiCongViec") or "",
        "is_current": bool(status.get("isCurrentStatus")),
        "raw": status,
    }


def find_status(statuses: list[dict], value: str) -> dict | None:
    wanted = normalize_text(value)
    for status in statuses:
        candidates = [
            status.get("userWorkflowId"),
            status.get("id"),
            status.get("name"),
            status.get("theSameId"),
        ]
        if wanted in {normalize_text(candidate) for candidate in candidates if candidate is not None}:
            return status
    return None


def update_work_field(client: BecaClient, workflow_id: str, field_name: str, value: str) -> object | None:
    params = {
        "userWorkFlowId": workflow_id,
        "fileName": field_name,
        "value": value,
    }
    return client.request_json(
        f"{UPDATE_JSON_DATA_URL}?{urlencode(params)}",
        headers=work_headers(workflow_id),
        method="PUT",
        print_body=False,
    )


def insert_status_history(
    client: BecaClient,
    workflow_id: str,
    old_status_id: str,
    new_status_id: str,
) -> object | None:
    payload = [
        {"name": "OldValue", "value": old_status_id},
        {"name": "NewValue", "value": new_status_id},
    ]
    return client.request_json(
        f"{INSERT_HISTORY_STATUS_WORK_URL}?{urlencode({'workId': workflow_id})}",
        headers={**work_headers(workflow_id), "Content-Type": "application/json; charset=UTF-8"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        print_body=False,
    )


def update_work_process(client: BecaClient, workflow_id: str, node_id: str) -> object | None:
    params = {
        "parentWorkId": workflow_id,
        "nodeId": node_id,
    }
    return client.request_json(
        f"{UPDATE_WORK_BY_WORK_PROCESS_URL}?{urlencode(params)}",
        headers=work_headers(workflow_id),
        method="GET",
        print_body=False,
    )


def work_headers(workflow_id: str) -> dict[str, str]:
    return {
        "Origin": "https://work.becawork.vn",
        "Referer": f"https://work.becawork.vn/work/mywork?workId={workflow_id}",
    }


def normalize_text(value: object) -> str:
    return str(value).strip().casefold()


def is_truthy(value: str | None) -> bool:
    return normalize_text(value or "") in {"1", "true", "yes", "y"}


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_minute_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
