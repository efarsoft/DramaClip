"""subtitle.safe_zone RPC：遮罩几何的唯一出口（前端不各写一份常量）。"""

from __future__ import annotations

from dramaclip.api import subtitle as subtitle_api
from dramaclip.transport.rpc import Router, RpcRequest


def test_safe_zone_rpc() -> None:
    router = Router()
    subtitle_api.register(router)
    response = router.dispatch(RpcRequest(id="1", method="subtitle.safe_zone", params={}))
    assert response.error is None
    assert response.result["reference"] == [1080, 1920]
    assert response.result["bottom"] == 300 / 1920
    assert "待真机校验" in response.result["note"]
