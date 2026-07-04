import os
import json
import copy
import weakref


class config:
    _instances: weakref.WeakSet = weakref.WeakSet()

    def __init__(self, config_file=None, overrides: dict = None, db_config_key: str = "pg_db", auto_refresh: bool = True):
        if not config_file:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            env = os.getenv("APP_ENVIRONMENT", "").strip()
            if env:
                config_file = os.path.join(base_dir, f"config.{env}.json")
            else:
                config_file = os.path.join(base_dir, "config.json")
        self._db_config_key = db_config_key
        self._env_overrides: dict[str, str] = {}
        # 阶段1：加载文件配置
        self._file_config = self._load_file_config(config_file)
        # 阶段2：合并 文件 → DB → 环境变量
        self._config = self._build_config()
        # 最高优先级：传入的 overrides 覆盖
        if overrides:
            self._deep_merge(self._config, overrides)
        # 注册到弱引用集合
        if auto_refresh:
            config._instances.add(self)

    @staticmethod
    def _mask(value: str, show: int = 4) -> str:
        """将敏感值脱敏，保留前后各 show 个字符，中间用 *** 替代。"""
        if len(value) <= show * 2:
            return "***"
        return f"{value[:show]}***{value[-show:]}"

    @staticmethod
    def _deep_merge(base: dict, override: dict):
        """递归合并 override 到 base，override 的值优先。"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                config._deep_merge(base[key], value)
            else:
                base[key] = value

    @staticmethod
    def _apply_kv_pair(data: dict, path: str, raw_value: str):
        """将一条 'dot.path.key' + value 应用到 data 字典。
        value 支持 json@ / secret@ 前缀，规则与环境变量一致。
        返回 (display_str, is_secret)。"""
        keys = path.strip().lower().split(".")
        value = raw_value.strip()
        is_secret = False
        if value.startswith("json@"):
            value = json.loads(value[5:])
        elif value.startswith("secret@"):
            value = value[7:]
            is_secret = True
        if len(keys) == 1:
            # 单段路径：直接作为顶层 key
            data[keys[0]] = value
        else:
            # 多段路径：逐层创建嵌套字典
            if keys[0] not in data:
                data[keys[0]] = {}
            _data = data[keys[0]]
            for part in keys[1:-1]:
                if part not in _data:
                    _data[part] = {}
                _data = _data[part]
            _data[keys[-1]] = value
        if is_secret:
            display = f"{'.'.join(keys)} = {config._mask(value)}"
        else:
            display = f"{'.'.join(keys)} = {value}"
        return display, is_secret

    def _load_file_config(self, config_file):
        """阶段1：仅加载 JSON 文件，返回原始字典。"""
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise Exception(f"无法加载配置文件 {config_file}: {e}")

    def _apply_env_overrides(self, data: dict):
        """阶段2b：应用环境变量覆盖。"""
        self._env_overrides = {}
        app_prefix = os.getenv("APP_PREFIX", "").strip()
        if not app_prefix:
            return
        for key, value in os.environ.items():
            orig_key = key.strip()
            key = orig_key.lower()
            if key.startswith(f"{app_prefix.lower()}_"):
                parts = value.split(":", 1)
                if len(parts) == 1:
                    data[key[len(app_prefix)+1:]] = value
                    self._env_overrides[orig_key] = value
                else:
                    path = parts[0].strip()
                    raw_value = parts[1].strip()
                    display, is_secret = config._apply_kv_pair(data, path, raw_value)
                    if is_secret:
                        self._env_overrides[orig_key] = display
                    else:
                        self._env_overrides[orig_key] = display

    def _build_config(self) -> dict:
        """构建最终配置：文件 → DB → 环境变量。"""
        data = copy.deepcopy(self._file_config)
        #self._load_db_config(data)
        self._apply_env_overrides(data)
        return data

    @staticmethod
    def refresh_from_db():
        """从数据库重新加载配置，刷新所有已注册的 config 实例。
        优先级保持：环境变量 > DB > 文件。"""
        for inst in list(config._instances):
            inst._config = inst._build_config()

    def update(self, overrides: dict):
        """传入 overrides 字典，深度合并以修改部分配置。"""
        if overrides:
            self._deep_merge(self._config, overrides)

    def get(self, key, default=None):
        return self._config.get(key, default)

    @property
    def msal(self):
        return self._config.get("msal", {})
