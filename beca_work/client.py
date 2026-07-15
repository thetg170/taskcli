from __future__ import annotations

import html.parser
import json
import sys
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


LOGIN_URL = (
    "https://sso.becawork.vn/Account/Login?"
    "ReturnUrl=%2Fconnect%2Fauthorize%2Fcallback%3Fclient_id%3Dbeca.workflow"
    "%26redirect_uri%3Dhttps%253A%252F%252Fworkflow.becawork.vn%252Fsignin-oidc"
    "%26response_type%3Dcode%2520id_token"
    "%26scope%3DEOfficeAPI.read%2520openid%2520profile%2520email"
    "%26response_mode%3Dform_post"
)
MAX_AUTH_STEPS = 5


class FormParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action = ""
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and not self.action:
            self.action = values.get("action") or ""
            return

        if tag != "input":
            return

        name = values.get("name")
        if name:
            self.inputs[name] = values.get("value") or ""


class BecaClient:
    def __init__(self, cookie: str | None = None, timeout: float = 30, verbose: bool = False) -> None:
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.cookie = cookie
        self.xsrf_token: str | None = None
        self.timeout = timeout
        self.verbose = verbose

    def login(self, username: str, password: str) -> None:
        login_page = self.opener.open(
            Request(LOGIN_URL, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=self.timeout,
        )
        login_html = login_page.read().decode("utf-8")

        parser = FormParser()
        parser.feed(login_html)

        form_data = {
            **parser.inputs,
            "Username": username,
            "Password": password,
            "Input.Username": username,
            "Input.Password": password,
            "RememberMe": "false",
            "button": "login",
        }

        request = Request(
            LOGIN_URL,
            data=urlencode(form_data).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://sso.becawork.vn",
                "Referer": LOGIN_URL,
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        response = self.opener.open(request, timeout=self.timeout)
        self.log("Login status:", response.status, short_url(response.geturl()))
        body = response.read().decode("utf-8")

        if "<form" in body and "signin-oidc" in body:
            self.submit_html_form(body, response.geturl())

    def request_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        method: str = "GET",
        print_body: bool = True,
    ) -> object | None:
        request_headers = {
            **(headers or {}),
            **self.xsrf_headers(method),
        }
        body = self.open_with_auth_forms(url, headers=request_headers, data=data, method=method)

        try:
            parsed = json.loads(body)
            if print_body:
                print(json.dumps(parsed, ensure_ascii=False, indent=2))
            return parsed
        except json.JSONDecodeError:
            self.log("Response is not JSON. The login flow may still be incomplete.")
            self.log(redact_html(body))
            return None

    def xsrf_headers(self, method: str) -> dict[str, str]:
        if method.upper() not in {"POST", "PUT", "DELETE", "PATCH"}:
            return {}
        return {"X-XSRF-TOKEN": self.get_xsrf_token()}

    def get_xsrf_token(self) -> str:
        if self.xsrf_token:
            return self.xsrf_token

        request = Request(
            "https://work.becawork.vn/api/antiforgery/token",
            headers=self.base_headers({"Content-Type": "application/json; charset=UTF-8"}),
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            self.xsrf_token = json.loads(response.read().decode("utf-8"))

        return self.xsrf_token

    def open_with_auth_forms(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        method: str = "GET",
    ) -> str:
        current_url = url
        body = ""

        for _ in range(MAX_AUTH_STEPS):
            request = Request(
                current_url,
                data=data,
                headers=self.base_headers(headers),
                method=method,
            )

            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                final_url = response.geturl()
                self.log("Status:", response.status, short_url(final_url))

            if is_json(body):
                return body

            if "<form" in body and "signin-oidc" in body:
                self.submit_html_form(body, final_url)
                current_url = url
                continue

            if "<form" in body and "Account/Login" in final_url:
                return body

            break

        return body

    def submit_html_form(self, html: str, base_url: str) -> str:
        parser = FormParser()
        parser.feed(html)

        if not parser.action or not parser.inputs:
            return html

        action = urljoin(base_url, parser.action)
        request = Request(
            action,
            data=urlencode(parser.inputs).encode("utf-8"),
            headers=self.base_headers(
                {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": origin_for(action),
                    "Referer": base_url,
                }
            ),
            method="POST",
        )

        response = self.opener.open(request, timeout=self.timeout)
        body = response.read().decode("utf-8")
        self.log("Callback status:", response.status, short_url(response.geturl()))
        return body

    def base_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
            **(extra or {}),
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def log(self, *values: object) -> None:
        if self.verbose:
            print(*values, file=sys.stderr)


def is_json(body: str) -> bool:
    text = body.lstrip()
    return text.startswith("{") or text.startswith("[")


def short_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def origin_for(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def redact_html(body: str) -> str:
    if "<input" in body and ("id_token" in body or "code" in body):
        return "[redacted HTML auth form containing code/id_token]"
    return body[:1000]
