import struct

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
            return pyodbc.connect(
                connection_string,
                attrs_before={self.SQL_COPT_SS_ACCESS_TOKEN: self._pack_access_token(token.token)}
            )
        return pyodbc.connect(connection_string)

    def execute_query(self, query, params=None):
        """执行查询语句，每次调用新建连接，自动关闭。"""
        with self._create_connection() as conn:
            with conn.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                columns = [column[0] for column in cursor.description]
                all_rows = cursor.fetchall()
                results = [dict(zip(columns, row)) for row in all_rows]
        return results

    def execute_non_query(self, query, params=None):
        """执行非查询语句，每次调用新建连接，自动关闭。"""
        with self._create_connection() as conn:
            with conn.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                conn.commit()
                affected = cursor.rowcount
        return affected