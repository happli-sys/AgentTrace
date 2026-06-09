"""
全局 patch 注册表，用引用计数管理 patch 生命周期。

同一个函数被多个并发 session patch 时：
  - 只替换模块属性一次（第一个 session）
  - 后续 session 直接复用已有 wrapper
  - revert 时引用计数减一，归零才真正还原原始函数

这样保证并发 session 下 ContextVar 隔离的正确性。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Tuple

_lock  = threading.Lock()
# key: (id(owner), attr_name) → (original_fn, refcount)
_registry: Dict[Tuple[int, str], Tuple[Callable, int]] = {}


def register(owner: Any, attr: str, original: Callable,
             wrapper: Callable) -> bool:
    """
    注册一个 patch。
    返回 True 表示首次 patch（调用方需要 setattr），
    返回 False 表示已存在（调用方无需 setattr）。
    """
    key = (id(owner), attr)
    with _lock:
        if key in _registry:
            orig, count = _registry[key]
            _registry[key] = (orig, count + 1)
            return False   # 已经 patched，不需要再 setattr
        else:
            _registry[key] = (original, 1)
            setattr(owner, attr, wrapper)
            return True


def unregister(owner: Any, attr: str) -> None:
    """
    释放一次引用。引用计数归零时还原原始函数。
    """
    key = (id(owner), attr)
    with _lock:
        if key not in _registry:
            return
        original, count = _registry[key]
        if count <= 1:
            try:
                setattr(owner, attr, original)
            except Exception:
                pass
            del _registry[key]
        else:
            _registry[key] = (original, count - 1)


def get_original(owner: Any, attr: str) -> Callable | None:
    key = (id(owner), attr)
    with _lock:
        entry = _registry.get(key)
        return entry[0] if entry else None
