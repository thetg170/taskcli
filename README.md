# taskcli

CLI tạo Task / Sub-task / Release / Hotfix trên BecaWork và log tiến độ hằng ngày.

Tài liệu sử dụng và convention duy nhất nằm tại:

[BECADOC.md](./BECADOC.md)

Chạy nhanh:

```bash
uv run taskcli --help
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
