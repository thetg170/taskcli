# taskcli

CLI tạo Task / Sub-task / Release / Hotfix trên BecaWork và log tiến độ hằng ngày.

Tài liệu sử dụng và convention duy nhất nằm tại:

[BECADOC.md](./BECADOC.md)

Chạy nhanh:

```bash
uv run taskcli --help
uv run taskcli task list --mine --scope all --from 2026-11-01 --to today --recursive --json
uv run taskcli report work --from 2026-11-01 --to today --json
uv run taskcli report timesheet --month 2026-11 --json
```

Cài/cập nhật binary `taskcli`:

```bash
uv tool install --reinstall .
taskcli whoami --json
```

Chạy test:

```bash
python3 -m unittest discover -s tests -v
```
