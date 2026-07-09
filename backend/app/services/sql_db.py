import struct
import threading
import time

import pyodbc
from azure.identity import ClientSecretCredential, ManagedIdentityCredential


class sql_db:
    """SQL Server 数据库服务封装。

    支持用户名密码、Azure Service Principal 和 Managed Identity 三种认证方式，
    提供查询和非查询 SQL 执行接口。
    """

    SQL_COPT_SS_ACCESS_TOKEN = 1256

    def __init__(self, config: dict = None):
        conf = config or {}
        self.auth_method = conf.get("auth_method", "password")
        self.server = conf.get("server")
        self.port = conf.get("port", 1433)
        self.database = conf["database"]
        self.driver = conf.get("driver", "ODBC Driver 18 for SQL Server")
        self.encrypt = conf.get("encrypt", "yes")
        self.trust_server_certificate = conf.get("trust_server_certificate", "no")
        self.timeout = conf.get("timeout", 30)

        if self.auth_method == "service_principal":
            self.client_id = conf["client_id"]
            self.client_secret = conf["client_secret"]
            self.tenant_id = conf["tenant_id"]
            self.credential = ClientSecretCredential(
                tenant_id=self.tenant_id,
                client_id=self.client_id,
                client_secret=self.client_secret
            )
        elif self.auth_method == "managed_identity":
            managed_client_id = conf.get("client_id")
            if managed_client_id:
                self.credential = ManagedIdentityCredential(client_id=managed_client_id)
            else:
                self.credential = ManagedIdentityCredential()
        else:
            self.username = conf["username"]
            self.password = conf["password"]

        # 连接池：复用连接，避免每条 SQL 都重连 Azure SQL（握手/取 token 每次 ~1s）。
        # 进程内、线程安全；每个线程取走各自的连接（pyodbc 连接非线程安全），保留并行度。
        self._max_pool = int(conf.get("max_pool", 5))
        self._max_idle_s = int(conf.get("max_idle_s", 300))    # 空闲超时回收（防长时间 TCP 被断）
        self._max_age_s = int(conf.get("max_age_s", 1800))     # 存活超时回收（Azure 网关约 30 分钟断空闲）
        self._pool: list = []                                  # [(conn, created_ts, last_used_ts)]
        self._pool_lock = threading.Lock()

    @staticmethod
    def _format_driver(driver: str):
        driver = driver.strip()
        if driver.startswith("{") and driver.endswith("}"):
            return driver
        return f"{{{driver}}}"

    def _format_server(self):
        if self.port and "," not in self.server:
            return f"{self.server},{self.port}"
        return self.server

    def _build_connection_string(self):
        parts = [
            f"DRIVER={self._format_driver(self.driver)}",
            f"SERVER={self._format_server()}",
            f"DATABASE={self.database}",
            f"Encrypt={self.encrypt}",
            f"TrustServerCertificate={self.trust_server_certificate}",
            f"Connection Timeout={self.timeout}",
        ]
        if self.auth_method == "password":
            parts.extend([
                f"UID={self.username}",
                f"PWD={self.password}",
            ])
        return ";".join(parts)

    @staticmethod
    def _pack_access_token(token: str):
        encoded_token = token.encode("utf-16-le")
        return struct.pack(f"<I{len(encoded_token)}s", len(encoded_token), encoded_token)

    def _create_connection(self):
        connection_string = self._build_connection_string()
        if self.auth_method in ("service_principal", "managed_identity"):
            token = self.credential.get_token("https://database.windows.net/.default")
            conn = pyodbc.connect(
                connection_string,
                attrs_before={self.SQL_COPT_SS_ACCESS_TOKEN: self._pack_access_token(token.token)}
            )
        else:
            conn = pyodbc.connect(connection_string)
        conn.autocommit = True   # 复用连接：避免 SELECT 遗留未提交事务、写入即时生效
        return conn

    # ── 连接池（复用 + 失效重连） ──
    @staticmethod
    def _safe_close(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    # 连接失效（TCP 袭断 / 服务端关连 / 超时）类的 SQLSTATE / 报错关键字
    _CONN_ERR_SQLSTATES = {"08S01", "08S02", "08001", "08003", "08004", "08007", "HYT00", "HYT01", "01002"}

    @classmethod
    def _is_conn_error(cls, exc) -> bool:
        state = exc.args[0] if (getattr(exc, "args", None) and isinstance(exc.args[0], str)) else ""
        if state[:2] == "08" or state in cls._CONN_ERR_SQLSTATES:
            return True
        msg = str(exc).lower()
        return any(k in msg for k in (
            "communication link failure", "closed connection", "connection is closed",
            "attempt to use a closed connection", "connection is busy", "tcp provider",
            "read from the stream", "not connected", "broken pipe", "connection reset",
            "server failed to resume", "the connection is broken", "login timeout",
        ))

    def _acquire(self):
        """取一个可用连接：回收过老/空闲太久（可能 TCP 已断）的，否则新建。返回 (conn, created_ts)。"""
        now = time.time()
        with self._pool_lock:
            while self._pool:
                conn, created, last_used = self._pool.pop()
                if now - created > self._max_age_s or now - last_used > self._max_idle_s:
                    self._safe_close(conn)      # 太老/空闲太久 → 弃用，重建
                    continue
                return conn, created
        return self._create_connection(), now

    def _release(self, conn, created, broken: bool = False) -> None:
        if broken:
            self._safe_close(conn)              # 连接已死 → 丢弃，不回池
            return
        with self._pool_lock:
            if len(self._pool) < self._max_pool:
                self._pool.append((conn, created, time.time()))
                return
        self._safe_close(conn)                  # 池满 → 直接关

    def _run(self, query, params, fetch: bool):
        last_exc = None
        for _ in range(3):                      # 建连或连接失效时最多重试 3 次（换一个/重建连接）
            try:
                conn, created = self._acquire()
            except pyodbc.Error as exc:         # 建连失败（如库正在唤醒）→ 短暂重试
                last_exc = exc
                continue
            try:
                with conn.cursor() as cursor:
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    if fetch:
                        columns = [c[0] for c in cursor.description]
                        result = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    else:
                        result = cursor.rowcount
                self._release(conn, created)
                return result
            except pyodbc.Error as exc:
                conn_dead = self._is_conn_error(exc)
                self._release(conn, created, broken=conn_dead)
                if not conn_dead:
                    raise                       # 真·SQL 错误 → 不重试
                last_exc = exc                  # 连接失效 → 换一个连接重试
        raise last_exc

    def execute_query(self, query, params=None):
        """执行查询语句（复用池化连接；连接失效自动重连重试）。返回行字典列表。"""
        return self._run(query, params, fetch=True)

    def execute_non_query(self, query, params=None):
        """执行非查询语句（复用池化连接；连接失效自动重连重试）。返回受影响行数。"""
        return self._run(query, params, fetch=False)

    def close(self) -> None:
        """关闭池中所有连接（进程退出/重置时调用）。"""
        with self._pool_lock:
            for conn, _c, _u in self._pool:
                self._safe_close(conn)
            self._pool.clear()