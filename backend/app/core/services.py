from config import config
from typing import Any, Type, TypeVar, cast, Callable, Optional, overload

T = TypeVar("T")

class service_entry:
    """服务注册项"""
    def __init__(self, service_type: Type, is_singleton: bool):
        self.service_type = service_type
        self.is_singleton = is_singleton
        self.instances: dict[str, any] = {}  # 按名称缓存实例，懒加载

class service_meta(type):
    """元类，用于支持 services[Type] / services[Type, name] / services[Type, name, config] / services[Type, name, config, singleton] 语法。"""
    @overload
    def __getitem__(cls, key: Type[T]) -> T: ...
    @overload
    def __getitem__(cls, key: tuple[Type[T], str]) -> T: ...
    @overload
    def __getitem__(cls, key: tuple[Type[T], str, Any]) -> T: ...
    @overload
    def __getitem__(cls, key: tuple[Type[T], str, Any, bool]) -> T: ...
    def __getitem__(cls, key):
        if isinstance(key, tuple):
            return cls.get(*key)
        return cls.get(key)

class services(metaclass=service_meta):
    """全局服务容器（IoC 容器）。

    通过 services.register(Type) 注册服务类。
    通过 services[Type] 获取默认服务实例。
    通过 services[Type, "name"] 获取指定名称的服务实例（使用全局 config）。
    通过 services[Type, "name", custom_config] 获取指定名称的服务实例（使用自定义 config）。
    通过 services[Type, "name", custom_config, singleton] 获取指定名称的服务实例，并覆盖注册时的单例/工厂模式。
    支持单例模式和工厂模式，单例实例在首次访问时按名称懒加载创建。
    """

    _config: config = None
    _registry: dict[Type, service_entry] = {}  # 统一的服务注册表
    _config_keys: dict[Type, str] = {}  # Type -> config key 映射表
    _initialized: bool = False

    @classmethod
    def init(cls):
        cls._config = config()
        cls._registry = dict()
        cls._config_keys = dict()

    @classmethod
    def register(cls, service, singleton=True):
        if not cls._initialized:
            cls.init()
            cls._initialized = True

        # 避免二次注册
        if service in cls._registry:
            raise ValueError(f"Service '{service}' is already registered.")
        
        cls._registry[service] = service_entry(service, singleton)

    @classmethod
    def register_default_config(cls, service_type: Type, config_key: str):
        """注册服务类型到 config key 的映射。

        当通过 services[Type] 获取实例时，services 会自动从全局 config 中
        提取 config[config_key] 作为子配置传递给构造函数，而非传递整个 config 对象。

        Args:
            service_type: 服务类型
            config_key: 该服务在 config.json 中对应的顶层 key
        """
        cls._config_keys[service_type] = config_key

    @classmethod
    def _resolve_config(cls, service_type: Type, name: str, custom_config) -> Any:
        """解析应传递给构造函数的配置。

        优先级：custom_config > config[name] > config[registered_key] > 整个 config 对象
        """
        if custom_config is not None:
            return custom_config
        if name != "__default__":
            return cls._config.get(name, {})
        if service_type in cls._config_keys:
            return cls._config.get(cls._config_keys[service_type], {})
        return cls._config

    @classmethod
    def get(cls, service_type: Type[T], name: str = "__default__", custom_config=None, singleton: Optional[bool] = None, auto_create: bool = True) -> T | None:
        if service_type not in cls._registry:
            raise KeyError(f"Service '{service_type}' not registered.")
        entry = cls._registry[service_type]
        # 优先使用 get 时传入的 singleton，否则用 register 时的 is_singleton
        is_singleton = singleton if singleton is not None else entry.is_singleton
        if is_singleton:
            # 单例模式：按名称缓存
            if name not in entry.instances:
                if not auto_create:
                    return None
                cfg = cls._resolve_config(service_type, name, custom_config)
                entry.instances[name] = service_type(cfg)
            return cast(T, entry.instances[name])
        else:
            if not auto_create:
                return None
            cfg = cls._resolve_config(service_type, name, custom_config)
            # 工厂模式：每次创建新实例
            return cast(T, service_type(cfg))

    @classmethod
    def reload(cls, service_types: Type | list[Type] | None = None):
        """使用最新的 config 重新实例化已缓存的单例服务。

        Args:
            service_types: 指定要重新实例化的服务类型，可以是单个类型或类型列表。
                           为 None 时重新实例化所有已缓存的服务。
        """
        cls._config = config()

        if service_types is None:
            targets = cls._registry.values()
        else:
            if not isinstance(service_types, list):
                service_types = [service_types]
            targets = []
            for st in service_types:
                if st not in cls._registry:
                    raise KeyError(f"Service '{st}' not registered.")
                targets.append(cls._registry[st])

        for entry in targets:
            if entry.instances:
                for name in list(entry.instances.keys()):
                    cfg = cls._resolve_config(entry.service_type, name, None)
                    entry.instances[name] = entry.service_type(cfg)

    @classmethod
    def remove_instance(cls, service_type: Type, name: str) -> bool:
        """从缓存中移除指定名称的服务实例。

        用于临时创建的服务实例（如按 run_id 命名的 task_pool），
        在使用完毕后显式释放，避免内存泄漏。

        注意：仅从缓存中移除引用，不负责调用实例的 shutdown/dispose。
        调用方应在移除前自行关闭资源。

        Args:
            service_type: 服务类型
            name: 实例名称

        Returns:
            True — 成功移除；False — 名称不存在
        """
        if service_type not in cls._registry:
            return False
        entry = cls._registry[service_type]
        if name in entry.instances:
            del entry.instances[name]
            return True
        return False

    @classmethod
    def get_all_instances(cls, service_type: Type[T]) -> dict[str, T]:
        """获取指定服务类型的所有已缓存实例。

        Args:
            service_type: 服务类型

        Returns:
            dict[str, T]: 名称 -> 实例 的字典（仅包含已创建的单例实例）。
                          工厂模式的服务（非单例）返回空字典。
        """
        if service_type not in cls._registry:
            raise KeyError(f"Service '{service_type}' not registered.")
        entry = cls._registry[service_type]
        return dict(entry.instances)

    @classmethod
    def list_all_singletons(cls) -> list[dict]:
        """列出所有已缓存的单例实例及其元数据。

        Returns:
            list[dict]: 每个元素包含:
                - type_name: str         服务类型名称
                - instance_key: str      实例名称
                - has_reconfigure: bool  是否支持运行时配置（有 reconfigure 方法）
                - has_get_runtime_config: bool  是否支持读取运行时配置
        """
        result = []
        for service_type, entry in cls._registry.items():
            if not entry.is_singleton or not entry.instances:
                continue
            type_name = service_type.__name__
            for instance_key, instance in entry.instances.items():
                result.append({
                    "type_name": type_name,
                    "instance_key": instance_key,
                    "has_reconfigure": callable(getattr(instance, "reconfigure", None)),
                    "has_get_runtime_config": callable(getattr(instance, "get_runtime_config", None)),
                })
        return result

    @classmethod
    def get_instance_by_names(cls, type_name: str, instance_key: str):
        """通过类型名称和实例 key 查找已缓存的单例实例。

        Args:
            type_name: 服务类型的 __name__
            instance_key: 实例名称

        Returns:
            实例对象，未找到则返回 None
        """
        for service_type, entry in cls._registry.items():
            if service_type.__name__ == type_name:
                return entry.instances.get(instance_key)
        return None

    @classmethod
    def config(cls, key: str, default=None):
        """从全局 config 中获取指定 key 的配置。

        Args:
            key: 配置项的键名
            default: key 不存在时的默认值

        Returns:
            对应的配置值，或 default
        """
        return cls._config.get(key, default) if cls._config else default

    @classmethod
    def get_config_env_overrides(cls) -> dict[str, str]:
        """返回 config 加载时通过环境变量覆盖的配置项。"""
        return getattr(cls._config, "_env_overrides", {}) if cls._config else {}

    @classmethod
    def list(cls):
        return list(cls._registry.keys())