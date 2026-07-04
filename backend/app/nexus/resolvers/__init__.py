"""Resolver 接口与内置实现。"""
from nexus.resolvers.base import Resolver
from nexus.resolvers.sql import SqlResolver

__all__ = ["Resolver", "SqlResolver"]
