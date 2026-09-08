"""教务系统登录客户端。

对应 Go 版的 client/client.go 与 pkg/login/login.go：
- newjw 密码登录：csrftoken + RSA(PKCS1v15) 加密密码
- cas 统一身份认证登录：AES(ECB/PKCS7) 加密密码，再携带票据跳回 newjw
- 会话 cookie 的保存 / 恢复
"""

import base64
import logging
import re
import time

import requests
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA

logger = logging.getLogger(__name__)

NEWJW_BASE = "https://newjw.hdu.edu.cn/jwglxt"
CAS_BASE = "https://sso.hdu.edu.cn"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

TIMEOUT = 30  # 普通请求的超时秒数

# 未登录时接口会被重定向到统一身份认证页，响应里出现该字样即会话失效
NOT_LOGGED_IN = "统一身份认证"


class LoginError(Exception):
    """登录失败（账号密码错误、配置获取失败、票据跳转失败等）。"""


# ---- 密码加密（对应 Go 版 util/rsa.go、util/aes.go）----

def rsa_encrypt(modulus_b64, plaintext):
    """newjw 登录：服务端下发 base64 modulus，构造 RSA 公钥加密后 base64。"""
    n = int.from_bytes(base64.b64decode(modulus_b64), "big")
    cipher = PKCS1_v1_5.new(RSA.construct((n, 65537)))
    return base64.b64encode(cipher.encrypt(plaintext.encode())).decode()


def aes_ecb_encrypt(key_b64, plaintext):
    """cas 登录：base64 key + AES/ECB/PKCS7 填充，输出 base64。"""
    key = base64.b64decode(key_b64)
    data = plaintext.encode()
    pad = 16 - len(data) % 16  # PKCS7：补 N 个值为 N 的字节
    data += bytes([pad]) * pad
    return base64.b64encode(AES.new(key, AES.MODE_ECB).encrypt(data)).decode()


# ---- 登录页 HTML 解析（对应 Go 版的 XPath）----

def _input_value(html, name):
    """取 <input name="..."> 的 value（兼容属性顺序）。"""
    tag = re.search(rf'<input[^>]*name="{name}"[^>]*>', html)
    if not tag:
        return None
    value = re.search(r'value="([^"]*)"', tag.group(0))
    return value.group(1) if value else None


def _hidden_text(html, element_id):
    """取指定 id 元素的文本（cas 页的 execution / croypto 藏在这里）。"""
    m = re.search(rf'id="{element_id}"[^>]*>([^<]*)<', html)
    return m.group(1).strip() if m else None


class JwClient:
    """带 cookie 会话的教务系统客户端（对应 Go 版 client.Client）。"""

    def __init__(self, user_agent=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent or DEFAULT_USER_AGENT

    # ---- 基础请求 ----

    def get(self, url, timeout=TIMEOUT):
        return self.session.get(url, timeout=timeout).text

    def post_form(self, url, form, timeout=TIMEOUT, headers=None):
        return self.session.post(url, data=form, timeout=timeout,
                                 headers=headers).text

    # ---- 登录（对应 Go 版 pkg/login/login.go）----

    def newjw_login(self, username, password):
        """newjw 直接登录。"""
        login_url = f"{NEWJW_BASE}/xtgl/login_slogin.html"

        csrftoken = _input_value(self.get(login_url), "csrftoken")
        if not csrftoken:
            raise LoginError("获取 csrftoken 失败")

        key = self.session.get(
            f"{NEWJW_BASE}/xtgl/login_getPublicKey.html",
            params={"time": int(time.time())}, timeout=TIMEOUT,
        ).json()

        result = self.post_form(login_url, {
            "csrftoken": csrftoken,
            "yhm": username,
            "mm": rsa_encrypt(key["modulus"], password),
        })
        if "用户名或密码不正确" in result:
            raise LoginError("用户名或密码不正确")

    def cas_login(self, username, password):
        """统一身份认证登录，成功后携带票据跳回 newjw。"""
        html = self.get(f"{CAS_BASE}/login")
        execution = _hidden_text(html, "login-page-flowkey")
        croypto = _hidden_text(html, "login-croypto")
        if not execution or not croypto:
            raise LoginError("获取 cas 登录配置失败")

        result = self.post_form(f"{CAS_BASE}/login", {
            "username": username,
            "type": "UsernamePassword",
            "_eventId": "submit",
            "geolocation": "",
            "execution": execution,
            "captcha_code": "",
            "croypto": croypto,
            "password": aes_ecb_encrypt(croypto, password),
        })
        if NOT_LOGGED_IN in result:  # 仍停在登录页 = 认证失败
            raise LoginError("用户名或密码不正确")

        result = self.get(f"{CAS_BASE}/login?service=http://newjw.hdu.edu.cn/sso/driot4login")
        if "杭州电子科技大学本科教学管理服务平台" not in result:
            raise LoginError("cas 登录 newjw 失败")

    def login(self, newjw=None, cas=None):
        """登录教务系统：newjw 优先，失败自动换 cas（两套独立账号密码）。

        参数形如 {"username": ..., "password": ...}，字段不全或未提供的账号跳过。
        返回实际成功的方式（"newjw" / "cas"）。
        """
        methods = [("newjw", self.newjw_login, newjw),
                   ("cas", self.cas_login, cas)]
        last_error = None
        for name, method, account in methods:
            if not account or not account.get("username") or not account.get("password"):
                continue
            try:
                method(account["username"], account["password"])
                logger.info("%s 登录成功", name)
                return name
            except LoginError as e:
                logger.warning("%s 登录失败: %s", name, e)
                self.session.cookies.clear()  # 换方式前重置会话（对应 Go 版 NewClient）
                last_error = e
        if last_error:
            raise last_error
        raise LoginError("未配置任何可用的教务系统账号密码")

    # ---- cookies 持久化（对应 Go 版 SaveCookies / LoadCookies）----

    def save_cookies(self):
        """提取 newjw 的会话 cookie，返回可存入 config 的 dict。"""
        cookies = {"jsessionid": "", "route": ""}
        for cookie in self.session.cookies:
            if cookie.name == "JSESSIONID":
                cookies["jsessionid"] = cookie.value
            elif cookie.name == "route":
                cookies["route"] = cookie.value
        return cookies

    def load_cookies(self, cookies):
        """用保存的 cookie 恢复会话。"""
        for name, key in (("JSESSIONID", "jsessionid"), ("route", "route")):
            if cookies.get(key):
                self.session.cookies.set(name, cookies[key],
                                         domain="newjw.hdu.edu.cn", path="/jwglxt")

    def logged_in(self):
        """用个人课表接口探测当前会话是否有效（对应 Go 版 GetStuInfo）。"""
        url = f"{NEWJW_BASE}/kbcx/xskbcx_cxXsgrkb.html?gnmkdm=N2151"
        return NOT_LOGGED_IN not in self.get(url)


def login_with_config(app_config, force_password=False):
    """按 config 完成登录，返回已登录的 JwClient。

    优先用保存的 cookies 免登录；过期则用账号密码登录
    （newjw 优先，失败自动换 cas），成功后把 cookies 回写 config。
    force_password=True 时跳过 cookies 直接密码登录（cookies 已知失效时用）。

    app_config 只要求有 .hdu（dict）和 .save_config()，如 AppConfig。
    """
    hdu = app_config.hdu
    client = JwClient(hdu.get("user_agent") or None)

    # 1. 先试保存的 cookies（对应 Go 版 Login 里的 cookies 分支）
    cookies = hdu.get("cookies", {})
    if not force_password and cookies.get("enabled") \
            and cookies.get("jsessionid") and cookies.get("route"):
        logger.info("尝试已保存的 cookies...")
        client.load_cookies(cookies)
        if client.logged_in():
            logger.info("cookies 有效，免登录成功")
            return client
        logger.info("cookies 已过期，改用密码登录")
        client = JwClient(hdu.get("user_agent") or None)  # 重置会话

    # 2. 密码登录
    client.login(newjw=hdu.get("newjw"), cas=hdu.get("cas"))

    # 3. 登录成功，保存 cookies 供下次免登录
    hdu["cookies"] = client.save_cookies()
    app_config.save_config()
    return client


def query_with_relogin(app_config, query):
    """登录后执行 query(client)；会话在查询中过期则强制重登一次再试。

    登录态有效期很短，登录成功 → 发起查询之间也可能失效，
    所以 query 抛 LoginError 时不直接失败，而是跳过 cookies
    重新密码登录后重试一次。query 形如 client -> 课程列表。
    """
    client = login_with_config(app_config)
    try:
        return query(client)
    except LoginError:
        logger.warning("登录态已过期，重新登录后重试...")
        client = login_with_config(app_config, force_password=True)
        return query(client)


def as_int(value, default):
    """配置值安全转 int；缺失/非法时回退默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def query_with_retry(func, retries, what, error_cls, step=3, max_wait=10):
    """执行 func；网络类异常（requests.RequestException）自动重试。

    LoginError 不在本层重试，直接抛出交给 query_with_relogin 重登后
    整体重来，避免拿着失效会话空转。连续 retries+1 次失败抛 error_cls。
    """
    for attempt in range(retries + 1):
        if attempt:
            wait = min(step * attempt, max_wait)
            logger.warning("%s超时或网络错误，%ds 后进行第 %d 次尝试...",
                           what, wait, attempt + 1)
            time.sleep(wait)
        try:
            return func()
        except LoginError:
            raise
        except requests.RequestException as e:
            logger.warning("%s失败（第 %d 次尝试）: %s", what, attempt + 1, e)
    logger.error("%s连续 %d 次超时或网络错误，放弃重试", what, retries + 1)
    raise error_cls(f"{what}连续 {retries + 1} 次超时或网络错误")
