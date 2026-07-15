# BecaWork Task CLI — Handbook

Tài liệu tham chiếu để tạo issue và log worklog trên BecaWork bằng CLI.

Phạm vi: tạo **Task / Sub-task / Release / Hotfix** và **log tiến độ hằng ngày** vào subtask.

Nguyên tắc lõi: tên ngắn, nội dung đủ, đúng parent, đúng người xử lý, dry-run trước khi ghi thật, truy vết bằng JSON + idempotency.

> Ví dụ dùng `uv run taskcli ...`. Nếu đã `uv tool install .` thì thay bằng `taskcli ...`.

## 1. Cài đặt & cấu hình

```bash
uv run taskcli --help          # chạy trực tiếp trong repo
uv tool install .              # cài global -> dùng `taskcli`
uv tool install --reinstall .  # cài lại sau khi sửa code
taskcli whoami --json          # kiểm tài khoản + assignee mặc định (assignee_id, full_name, email)
```

`.env` chỉ chứa credential và default kỹ thuật:

```env
BECA_USERNAME=your_username
BECA_PASSWORD=your_password
# BECA_COOKIE=copy_browser_cookie_if_needed
TASKCLI_TIMEOUT=30
TASKCLI_VERBOSE=false
```

Thứ tự ưu tiên (phải thắng thấp): `~/.config/taskcli/config.toml` < `.env` / env vars < **CLI flags**.

Flag hay dùng khi tạo:

| Flag | Ý nghĩa | Ví dụ |
|---|---|---|
| `--project` | project id trên BecaWork | `1330631` |
| `--parent-id` | `WORKFLOW_ID` của công việc cha | `1423339` |
| `--assignee` | override; bỏ trống = user đăng nhập | `P:10881` |
| `--title` `--role` `--desc` | nội dung issue | |
| `--version` `--module` `--issue` | dùng cho release/hotfix | |

## 2. Quy ước chung (áp dụng mọi lệnh)

Những cờ này dùng ở khắp nơi nên không lặp lại ở từng lệnh:

- **`--json`** — mọi lệnh đều hỗ trợ; agent **luôn** dùng. JSON ra stdout, log/debug ra stderr.
- **`--dry-run`** — mọi lệnh *ghi* đều hỗ trợ. Xem trước payload, đúng rồi **bỏ `--dry-run`** để ghi thật. Dry-run không đụng BecaWork, không ghi idempotency store.
- **`--related`** — chỉ lấy item có user đăng nhập trong danh sách xử lý/giao/theo dõi.
- **`--query "..."`** — lọc theo tên project/story/task thay vì kéo quá nhiều dòng.
- **`--external-id`** + idempotency — gọi lại cùng key trả record cũ, không tạo trùng (chi tiết §9).
- **Assignee mặc định** = user đang đăng nhập; truyền `--assignee` nếu muốn khác.

## 3. Tra cứu trước khi tạo / log

Đi từ trên xuống để lấy `project_id` và `WORKFLOW_ID` cha:

```text
project list → story list → task list → subtask list
```

| Lệnh | Dùng để |
|---|---|
| `project list` | liệt kê project |
| `story list --project <id>` | story/work trong project (alias: `work list`) |
| `task list` | task con của **mọi** story/work |
| `task list --parent-id <WORKFLOW_ID>` | task con dưới **một** story/work |
| `subtask list` | subtask của **mọi** task |
| `subtask list --parent-id <TASK_WORKFLOW_ID>` | subtask dưới **một** task (chỉ 1 cấp trực tiếp) |
| `subtask list --parent-id <ID> --recursive` | subtask dưới **một** task, gồm cả subtask lồng nhau (subtask của subtask, mọi cấp) |
| `subtask show <WORKFLOW_ID>` | chi tiết/nội dung mô tả đầy đủ của một subtask |
| `logtime list <id> [--date today]` | logtime đã ghi của một subtask/task |
| `logtime list [--related] [--date today]` | logtime của **tất cả** task related (bỏ `<id>`); bỏ `--date` = mọi ngày |
| `logtime timesheet --date <today\|yesterday\|YYYY-MM-DD>` | logtime thật của **một ngày cụ thể**, lấy từ TimeSheet BecaWork — bao quát **mọi project** (xem lưu ý bên dưới) |
| `logtime timesheet --date <ngày> --days N` | logtime thật trong **N ngày làm việc gần nhất** tính đến `--date` (tự nhảy qua Thứ 7/CN, vd `--days 3` = 3 ngày làm việc gần nhất) |

Thêm `--related`, `--query`, `--limit`, `--status`, `--json` tùy nhu cầu.

Field trả về theo operation (đều bọc trong `{"ok":true,"operation":...,"<mảng>":[...]}`):

| operation | field chính mỗi item |
|---|---|
| `project.list` | `project_id`, `project_name`, `count` |
| `story.list` | `workflow_id`, `title`, `project_id`, `project_name`, `status` |
| `task.list` | `workflow_id`, `title`, `project_id`, `status`, `category` |
| `subtask.list` | `workflow_id`, `title`, `project_id`, `status`, `parent_id`, `category` |
| `logtime.list` | `date`, `hours`, `action`, `description` (+ `total_logs`, `total_hours`) |

`category` là Loại thật lấy từ BecaWork (`categoryName`, vd `"Task"` hoặc `"Sub-task"`) — **không suy ra Loại từ việc item nằm trong kết quả `task.list` hay `subtask.list`**, vì BecaWork cho phép Task làm cha của Task khác (lồng nhiều cấp), nên một item trả về từ `subtask list` vẫn có thể có `category` thật là `"Task"`.

`parent_id` luôn là `workflow_id` của cha **trực tiếp** (không phải cha gốc); muốn hiển thị phân cấp nhiều tầng, dựng cây bằng cách nối các item theo `parent_id` (xem thêm ở §7).

**Quan trọng — `logtime status`/`logtime list --related` chỉ quét task/subtask trong phạm vi "liên quan tới user" qua `task list --related`.** Nếu bạn log giờ lên một task ở project khác (không nằm trong danh sách related đó), 2 lệnh này sẽ **bỏ sót**, báo thiếu giờ dù thực ra đã log đủ. Muốn biết chính xác **tổng số giờ đã log trong một ngày cụ thể** (bao quát mọi project), dùng `logtime timesheet --date <ngày> --json` — lệnh này lấy thẳng từ TimeSheet chính thức của BecaWork (nguồn UI `work/timesheet` dùng), không đi qua cây task/subtask nên không bị giới hạn phạm vi project. Trả về `total_hours`, `total_logs`, và `logtimes` (mảng chi tiết từng dòng: `date`, `workflow_id`, `title`, `hours`, `action`, `description`, đã strip HTML). Thêm `--days N` để lấy cả khoảng N ngày gần nhất (trả thêm `date_from`, `date_to`) — dùng khi user hỏi kiểu *"3 ngày gần nhất đã log gì"*.

`description` giữ nguyên xuống dòng (`\n`) khi nội dung gốc có nhiều mục (vd viết theo format 4 mục ở §6: Đã thực hiện/Kết quả/Vướng mắc/Bước tiếp theo) — khi hiển thị cho user, **giữ nguyên từng dòng riêng biệt** (thụt lề dưới dòng tiêu đề), đừng nối thành 1 dòng dài bằng `;` hay `—` vì sẽ rất khó đọc.

Quy tắc dùng kết quả:

- `project_id` → `--project`; `workflow_id` → `--parent-id`.
- Nếu task có subtask, **log vào `workflow_id` của subtask**, không log vào task cha.

Flow chuẩn:

```bash
uv run taskcli project list --query "BecaVMS" --json
uv run taskcli story list --project 1330631 --query "Dataset" --json
uv run taskcli task list --parent-id 1423339 --json
uv run taskcli subtask list --related --parent-id 1424181 --json
uv run taskcli task create --role BE --title "..." --project 1330631 --parent-id 1423339 --dry-run --json
```

## 4. Convention tạo issue

```text
Project → Version/Sprint → Story → Task → Sub-task
                                        → Release ticket
                                        → Hotfix ticket
```

- **Story** — mục tiêu/tính năng nghiệp vụ hoàn chỉnh.
- **Task** — phần việc của một vai trò trong story.
- **Sub-task** — đầu việc nhỏ, có đầu ra rõ ràng.
- **Release** — phát hành một version lên môi trường.
- **Hotfix** — sửa nhanh lỗi production theo version hotfix.

Mỗi issue chỉ một đầu ra chính; không gộp nhiều kết quả độc lập.

Đặt tên:

| Loại | Format | Ví dụ |
|---|---|---|
| Task | `[VAI_TRÒ] [Động từ] [Đối tượng]` | `[BE] Xây dựng API đăng nhập` |
| Sub-task | `[VAI_TRÒ] [Đầu việc cụ thể]` | `[QC] Thiết kế testcase đăng nhập` |
| Release | `[RELEASE] Ver X.Y.Z [Môi trường]` | `[RELEASE] Ver 2.4.0 Production` |
| Hotfix | `[HOTFIX] Ver X.Y.Z [Module] [Lỗi]` | `[HOTFIX] Ver 2.4.1 Đăng nhập lỗi token` |

- Vai trò: `PM, PO, BA, UIUX, FE, BE, MOBILE, DEVOPS, QC, DE, AI`
- Động từ: `Phân tích, Thiết kế, Xây dựng, Tích hợp, Kiểm thử, Cấu hình, Triển khai, Cập nhật, Tối ưu`
- Tránh: `Fix lỗi`, `Làm API`, `Xử lý chức năng`, `Kiểm tra lại`, và ghi tên người/ngày/trạng thái/% trong title.

Description tối thiểu:

```text
Mục tiêu:
Phạm vi:
Đầu ra:
Acceptance Criteria:
```

Hotfix thêm: `Actual / Expected / Steps / Environment / Evidence / Rollback`.

Checklist trước khi tạo: có `--project`; `--parent-id` đúng cha; title đúng convention; assignee đúng; description rõ mục tiêu + đầu ra; đã `--dry-run --json`; payload có `CongViecCha` đúng parent.

## 5. Tạo issue

CLI tự thêm prefix `[VAI_TRÒ]` / `[RELEASE]` / `[HOTFIX]`; nếu title đã có prefix thì giữ nguyên. Thêm `--dry-run` để xem trước (§2).

```bash
# Task  → [BE] Xây dựng API detect face
uv run taskcli task create --role BE \
  --title "Xây dựng API detect face" \
  --desc "Triển khai API, validate input, trả kết quả predict." \
  --project 1330631 --parent-id 1423339 --json

# Sub-task  → [QC] Thiết kế testcase detect face
uv run taskcli subtask create --role QC \
  --title "Thiết kế testcase detect face" \
  --project 1330631 --parent-id 1423339 --json

# Release  → [RELEASE] Ver 2.4.0 Production   (hoặc truyền --title trực tiếp)
uv run taskcli release create --version v2.4.0 --env Production \
  --project 1330631 --parent-id 1423339 --json

# Hotfix  → [HOTFIX] Ver 2.4.1 Detect Face lỗi token khi gọi API
uv run taskcli hotfix create --version v2.4.1 \
  --module "Detect Face" --issue "lỗi token khi gọi API" \
  --project 1330631 --parent-id 1423339 --json
```

## 6. Worklog hằng ngày

Log vào `WORKFLOW_ID` của subtask (thêm `--dry-run` để xem trước).

**Mô tả (`--desc`) luôn theo format 4 mục sau** (khớp template mặc định của khung Log Time trên BecaWork):

```text
Đã thực hiện: <việc đã làm>
Kết quả: <đầu ra/kết quả cụ thể>
Vướng mắc: <khó khăn gặp phải, nếu không có ghi "Không">
Bước tiếp theo: <việc dự kiến làm tiếp>
```

```bash
uv run taskcli log 1424723 "Đã thực hiện: Dựng endpoint predict và validate input
Kết quả: Endpoint chạy được, trả đúng response mẫu
Vướng mắc: Không
Bước tiếp theo: Viết test case cho endpoint" \
  --time 2h --type progress --date today \
  --external-id "2026-07-02:1424723:progress" --json
```

`--type` map sang action BecaWork:

| `--type` | BecaWork | Dùng khi |
|---|---|---|
| `progress` (mặc định) | Thực hiện | dev hằng ngày |
| `review` | Xem xét | |
| `test` | Kiểm thử | |
| `follow` | Theo dõi | |

Không chắc thì bỏ `--type` (mặc định `progress`). Xem lại: `logtime list <id> [--date today] --json`.

Xem log của **nhiều task cùng lúc** (không cần biết từng `id`): bỏ `<id>`, thêm `--related` để lọc theo user đăng nhập, bỏ `--date` để lấy mọi ngày.

```bash
uv run taskcli logtime list --related --json                 # tất cả log, mọi ngày, mọi task related
uv run taskcli logtime list --related --date today --json    # chỉ log hôm nay
uv run taskcli logtime list --related --date yesterday --json
```

Kết quả gộp field `workflow_id`, `title` vào từng dòng log để phân biệt log thuộc task nào.

External-id cho log: `<YYYY-MM-DD>:<WORKFLOW_ID>:progress` (vd `2026-07-02:1423339:progress`).

## 7. Dùng với agent

Mục tiêu: agent trả lời được *"tôi có những task gì?"*, *"hôm nay còn task nào chưa logtime?"* rồi *"log giùm task X 8 tiếng: ..."*.

**Phân biệt hai loại câu hỏi — đừng nhầm:**

| Câu hỏi | Lệnh dùng | Không dùng |
|---|---|---|
| "Tôi có task gì" / "task đang xử lý" | `task list --related --json` + `subtask list --related --json` | `logtime status` (đây là câu hỏi về **worklog**, không phải câu hỏi về **danh sách task**) |
| "Hôm nay logtime chưa / đủ giờ chưa" (số giờ tổng của 1 ngày) | `logtime timesheet --date today --json` | `logtime status` — chỉ quét task related, có thể báo sai nếu log ở project khác (xem §3) |
| "Task nào chưa log" (muốn biết chưa log lên **task nào**, không chỉ tổng giờ) | `logtime status --date today --json` | |

Khi hỏi "tôi có task gì": trả lời **ngắn gọn theo trạng thái** (vd nhóm theo `Open` / `In Progress` / `Feedback`...), không liệt kê thêm cột logtime không liên quan tới câu hỏi. Nếu số lượng nhiều, có thể hỏi lại user muốn lọc theo project/status nào trước khi liệt kê hết.

**Hiển thị phân cấp task/subtask (cái nào là con của cái nào):** đừng liệt kê phẳng khi user muốn thấy quan hệ cha-con. Dựng cây bằng `parent_id` của mỗi item (root là item không có cha trong tập kết quả, ví dụ lấy từ `task list --related`), rồi in dạng danh sách lồng nhau, thụt lề theo cấp độ:

```text
- <Work ID> [<Status>] (<category>) <Task title>
  - <Work ID con> [<Status>] (<category>) <Task title con>
    - <Work ID cháu> [<Status>] (<category>) <Task title cháu>
```

Một task có thể lồng nhiều cấp Task-trong-Task (không chỉ dừng ở Task→Sub-task), nên tránh gán cứng "Loại" theo tên lệnh — luôn hiển thị bằng field `category` thật (xem §3).

**`subtask list --related` (không có `--parent-id`) tự đệ quy đầy đủ:** với mỗi task liên quan tới user, nó tự lấy **toàn bộ subtask ở mọi cấp** (kể cả subtask của subtask), và một subtask lồng sâu vẫn được tính miễn tổ tiên (task cha) của nó liên quan tới user — **không** yêu cầu chính subtask đó phải tự mang tag "related" (nhiều subtask trong BecaWork không có sẵn field người xử lý riêng dù vẫn thuộc về task của user). Chỉ khi gọi `subtask list` **không có** `--related` và **không có** `--parent-id` (liệt kê subtask của *mọi* task trong toàn hệ thống) thì mới chỉ lấy 1 cấp trực tiếp — trường hợp này hiếm dùng; nếu cần đủ mọi cấp cho một task cụ thể, dùng `subtask list --parent-id <TASK_WORKFLOW_ID> --recursive --json`.

**`logtime status` / `logtime list` (không truyền id) dùng chung cơ chế đệ quy + kế thừa "related" ở trên** — không cần agent tự lặp `--parent-id --recursive`: với mỗi task liên quan, nó tự lấy toàn bộ subtask mọi cấp; nếu task **không có subtask nào** thì tự kiểm tra logtime ngay trên chính task đó (vì quy ước là log trực tiếp lên task khi task không có subtask, xem §3). Trước khi có xử lý này, subtask lồng sâu không tự mang tag related, và task không có subtask, đều bị bỏ sót hoàn toàn khỏi kết quả — khiến agent báo "chưa log" hoặc liệt kê thiếu task/subtask dù thực ra dữ liệu đã có, chỉ là lệnh không quét tới.

```bash
uv run taskcli logtime list --related --json
# +--missing-only   chỉ subtask chưa log
# +--related        chỉ subtask của user đăng nhập
# +--query "test"   lọc theo keyword
```

Schema `logtime.status`:

```json
{
  "ok": true, "operation": "logtime.status", "date": "2026-07-02",
  "total_tasks": 3, "logged_tasks": 1, "missing_tasks": 2,
  "tasks": [
    { "workflow_id": "1423339", "status": "Open", "title": "[DE] The test",
      "project_id": "1330631", "has_logtime": false, "logtime_hours": 0, "logtimes": [] }
  ]
}
```

Quy tắc agent:

- `missing_tasks = 0` → báo ngày đó đã log đủ.
- Có `has_logtime=false` → hiện `workflow_id`, `status`, `title`.
- Keyword khớp **đúng một** subtask → dùng `workflow_id` đó; khớp **nhiều** → hỏi lại, không đoán.
- User không nói số giờ → hỏi lại; `8 tiếng` → `--time 8h`.
- User không nói log cho hôm nay hay hôm qua thì hỏi lại.
- Nếu `workflow_id`, giờ, ngày, nội dung đều đã rõ ràng từ yêu cầu của user, agent có thể chạy `log` trực tiếp (không bắt buộc `--dry-run` trước). Chỉ dùng `--dry-run` khi cần xác minh thêm (ví dụ payload phức tạp hoặc user yêu cầu xem trước). Không in credential ra câu trả lời.
- Nội dung log (`--desc`) luôn viết theo format 4 mục ở §6 (`Đã thực hiện` / `Kết quả` / `Vướng mắc` / `Bước tiếp theo`), kể cả khi user chỉ mô tả ngắn gọn — agent tự diễn giải thành đủ 4 mục.

Prompt mẫu đưa cho agent khác:

```text
Bạn có thể dùng taskcli trong repo này. Luôn dùng --json.
- Hỏi "hôm nay logtime chưa": chạy `uv run taskcli logtime status --date today --json`.
- Muốn log theo mô tả tự nhiên:
  1) logtime status với --query nếu có keyword
  2) chọn workflow_id nếu chỉ một subtask khớp rõ; nhiều thì hỏi lại
  3) đủ thông tin (workflow_id, giờ, ngày, nội dung) thì log trực tiếp; --dry-run chỉ dùng khi cần xem trước
  4) nội dung log luôn viết đủ 4 mục: Đã thực hiện / Kết quả / Vướng mắc / Bước tiếp theo
Không ghi credential ra câu trả lời.
```

## 8. Cập nhật issue

```bash
uv run taskcli task show 1424723 --json
uv run taskcli subtask show 1424723 --json
uv run taskcli task update 1424723 --status "In Progress" --json
uv run taskcli task update 1424723 --progress 50 --json
uv run taskcli subtask update 1424723 --progress 50 --json
uv run taskcli task done 1424723 --json
```

`--progress` nhận `0..100` hoặc có `%`; CLI gửi lên BecaWork field `Tiendo` dạng `50%`.
Task và subtask đều dùng `WORKFLOW_ID`, nên update `%` được cho cả hai. Agent nên dùng `subtask update` khi đang thao tác với subtask để câu lệnh rõ nghĩa.

Chuyển trạng thái nhanh, dùng cho cả `task` và `subtask`:

| Lệnh | Trạng thái BecaWork |
|---|---|
| `task done <id>` / `subtask done <id>` | Done |
| `task reject <id>` / `subtask reject <id>` | Reject |
| `task feedback <id>` / `subtask feedback <id>` | Feedback |
| `task pending <id>` / `subtask pending <id>` | Pending |
| `task need-to-test <id>` / `subtask need-to-test <id>` | Need to Test |

```bash
uv run taskcli subtask reject 1423339 --dry-run --json
uv run taskcli task need-to-test 1424723 --json
```

Trạng thái khác không có shortcut thì dùng `--status "<tên>"` trong `task update` / `subtask update`.

## 9. Lịch sử & hoạt động

Hai lệnh trả lời hai câu hỏi khác nhau — đừng nhầm: `history` soi **một task/subtask cụ thể** đã đổi những gì; `activity` soi **cả một project** (hoặc một người) vừa động vào việc gì.

```bash
uv run taskcli history 1425088 --json               # task/subtask này đã đổi status/parent từ khi nào, ai đổi
uv run taskcli activity --project 1330631 --json     # ai vừa động vào task nào trong project này
uv run taskcli activity --mine --json                 # chỉ hoạt động của chính user đăng nhập
```

`history` → mảng `history`, mỗi dòng là một lần đổi field: `date`, `field` (tên field BecaWork đổi, vd `"Trạng thái"`, `"Công việc cha"`), `old_value`, `new_value`, `updated_by`. Dùng khi cần trả lời *"task này chuyển sang In Progress từ ngày nào"* hoặc *"ai đổi parent của task này"*.

`activity` → mảng `activity`, mỗi dòng là một sự kiện: `workflow_id`, `title`, `field`, `user`, `time` (dạng tương đối, vd `"1 ngày trước."`), `content` (nội dung trước → sau khi đổi, đã strip HTML). Lọc theo `--project`, `--mine` (hoặc `--user-id` là id BecaWork **có** prefix `P:`, vd `P:10881` — xem `whoami`), giới hạn số dòng bằng `--limit`.

**`--date-from`/`--date-to` không có tác dụng lọc** (đã kiểm chứng: truyền `2020-01-01` vẫn ra cùng kết quả như không truyền) — BecaWork trả cố định N hoạt động gần nhất bất kể khoảng ngày. Đừng dùng 2 flag này để suy luận "có hoạt động đúng ngày X hay không"; chỉ dùng `activity` như một feed "gần đây" chung chung, muốn giới hạn số dòng thì dùng `--limit`.

## 10. Test & troubleshooting

```bash
python3 -m unittest discover -s tests -v
```

- **Thiếu credential** — set `BECA_USERNAME`+`BECA_PASSWORD` hoặc `BECA_COOKIE` trong `.env`.
- **Tạo nhầm parent** — luôn dry-run, nhìn `{"name":"CongViecCha","value":"..."}`.
- **Tạo trùng** — dùng `--external-id` ổn định cho mỗi task/log.
