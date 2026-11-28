"""uv 子进程壳与独立 Python 拉取的多源回退（装测 10061 实锤的修复面）。

自 tts_runtime 抽出（runner 外溢同期的小模块化）：``_run_uv`` 是全部 uv
步骤（venv + pip 各批次）的唯一子进程出口，双栈/配乐运行环境共用；阶梯 =
镜像逐个换 + 末轮剥代理。单镜像被拒/毒化即全链死、死本地代理连镜像都毒死
——这两条都只发生在「拉解释器」这一步，pip 各批次不在阶梯之列。
"""

from __future__ import annotations

import logging
import os
import subprocess  # noqa: S404 - 固定二进制受控参数
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# 独立 CPython 与 PyPI 走国内镜像（uv 官方源国内不稳）
_UV_ENV = {
    "UV_PYTHON_INSTALL_MIRROR": "https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download",
    "UV_HTTP_TIMEOUT": "120",
}
# 独立 Python 构建的多源回退（装测用户 2026-11-28 10061 实锤：单镜像被
# 「目标计算机积极拒绝」即全链死，用户卡死在第一步）。序按 2026-11-28 全源
# 真探（本机直连口径）：gh-proxy 200/0.9s、ghproxy.net 200/9s、GitHub 直连
# 200/4.3s；ghfast.top 与 gh.llkk.cc 已死剔除。直连殿后：走用户代理环境的
# 用户（含正常代理）恰好能用，裸连用户大概率也到不了 GitHub。
_PYTHON_MIRRORS: tuple[str, ...] = (
    "https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download",
    "https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download",
    "https://github.com/astral-sh/python-build-standalone/releases/download",
)
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _without_proxy(env: dict[str, str]) -> dict[str, str]:
    """剥代理环境变量：镜像源国内可达，死本地代理（10061「积极拒绝」的经典
    签名——Clash 类工具关了但系统代理环境变量还在）会把镜像访问一起毒死。"""
    clean = {k: v for k, v in env.items() if k not in _PROXY_ENV_KEYS}
    clean["NO_PROXY"] = "*"
    clean["no_proxy"] = "*"
    return clean


def _run_uv(
    uv: Path,
    venv: Path,
    *args: str,
    env_patch: dict[str, str] | None = None,
    strip_proxy: bool = False,
) -> None:
    cmd = [str(uv), *args]
    env = {**os.environ, **_UV_ENV, **(env_patch or {})}
    if strip_proxy:
        env = _without_proxy(env)
    if args and args[0] == "pip":
        # --python 必须落在子命令之后：uv 0.8.4 的 `pip` 组不接受组级 --python
        py = str(venv / "Scripts" / "python.exe")
        cmd = [str(uv), "pip", *args[1:2], "--python", py, *args[2:]]
    # 编码必须显式 UTF-8：uv 输出恒为 UTF-8（含 ├─▶ 等多字节制图符），而
    # text=True 默认走系统 locale（中文 Windows = GBK）——读流线程解码即死、
    # 缓冲区留空，「exit 1 双流全空」的真凶（2026-11-19 A/B 实锤）。
    result = subprocess.run(  # noqa: S603 - 固定二进制受控参数
        cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=3600,
        creationflags=_NO_WINDOW, env=env, check=False,
    )
    if result.returncode != 0:
        # stderr 可能是 None（Windows 管道异常/进程被强杀场景，装测实锤
        # 'NoneType' object is not subscriptable）——防御取空串，别让报错本身再炸。
        # stderr 空时回退 stdout 尾部；两者皆空至少带退出码并把完整输出落盘
        # ——Arc 机装测二连实锤：exit 1 且双流全空（正常 uv 失败必写 stderr，
        # 反常场景只有完整原始输出才能定位），尾部进报错+全量落盘双保险。
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        dump = venv.parent / "uv-last-error.log"
        try:  # 落盘失败不遮蔽原错误（只读盘/杀软拦写都可能）——诊断材料尽力而为
            dump.write_text(
                f"cmd: {' '.join(cmd)}\nexit: {result.returncode}\n"
                f"--- stdout ---\n{result.stdout or ''}\n"
                f"--- stderr ---\n{result.stderr or ''}\n",
                encoding="utf-8",
            )
            _LOGGER.info(f"[uv] 失败完整输出已落盘：{dump}")
        except OSError as dump_exc:
            _LOGGER.warning(f"[uv] 失败输出落盘失败（{dump_exc}）")
        _LOGGER.info(f"[uv] stdout 尾部：{out[-200:]}")
        _LOGGER.info(f"[uv] stderr 尾部：{err[-200:]}")
        detail = (err or out)[-300:]
        # 安装链有 torch/双栈 58 项/funasr/kokoro 四个批次同走本函数——报错必须
        # 区分是哪一批（取第一个包名；flag 后面还有 --index-url 等不算目标）。
        target = next((a for a in args[2:] if not a.startswith("-")), "")
        label = f"{' '.join(args[:2])} {target}".strip()
        raise RuntimeError(
            f"uv {label} 失败（exit {result.returncode}）: {detail}"
            f"（完整输出已存 {dump}）"
        )


def _create_venv(uv: Path, venv: Path) -> None:
    """uv venv + 独立 Python 3.11，多源回退：镜像逐个换，末轮剥代理环境。

    uv 拉独立 CPython 走 UV_PYTHON_INSTALL_MIRROR——单镜像被拒/毒化即全链死
    （装测 10061 实锤，用户卡死在第一步）。连接被拒失败极快（立即 RST），
    阶梯逐轮换源代价可忽略；只在**venv 这一步**回退，pip 各批次（torch 已有
    自身多源循环、PyPI 走 tuna）不在此列——重跑长安装批是浪费。
    """
    last: Exception | None = None
    for index, mirror in enumerate(_PYTHON_MIRRORS):
        final = index == len(_PYTHON_MIRRORS) - 1
        try:
            _run_uv(
                uv,
                venv,
                "venv",
                str(venv),
                "--python",
                "3.11",
                env_patch={"UV_PYTHON_INSTALL_MIRROR": mirror},
                strip_proxy=final,
            )
            return
        except RuntimeError as exc:
            last = exc
            host = "GitHub 直连" if final else mirror.split("https://", 1)[-1].split("/", 1)[0]
            _LOGGER.warning(f"[uv] 独立 Python 拉取失败（{host}），尝试下一来源")
    raise RuntimeError(f"独立 Python 拉取全部来源失败（镜像与代理均已尝试）: {last}")
