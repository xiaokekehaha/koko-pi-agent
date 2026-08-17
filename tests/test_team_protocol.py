# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""结构化消息协议：关闭协商与计划审批。"""

import json

from koko_pi_agent.teams import protocol
from koko_pi_agent.teams.mailbox import MailboxMessage, create_message


class TestShutdownNegotiation:
    def test_关闭请求能被识别(self):
        req = protocol.shutdown_request("lead", "alice", "收工")
        assert req.type == protocol.SHUTDOWN_REQUEST
        assert protocol.request_id_of(req), "关闭请求必须带 request_id，否则应答对不上"
        assert protocol.is_shutdown_request(req)

        # 纯文本前缀同样要认，窗格队友可能是旧版本进程
        legacy = create_message("lead", "[shutdown] stop")
        assert protocol.is_shutdown_request(legacy)

        normal = create_message("lead", "继续改 auth 模块")
        assert not protocol.is_shutdown_request(normal), "普通消息不该被误判"

    def test_应答带回请求标识与表态(self):
        req = protocol.shutdown_request("lead", "alice", "收工")
        rid = protocol.request_id_of(req)

        yes = protocol.shutdown_response("alice", "lead", rid, True, "done")
        assert protocol.approved(yes)
        assert protocol.request_id_of(yes) == rid

        no = protocol.shutdown_response("alice", "lead", rid, False, "还在跑测试")
        assert not protocol.approved(no)

        # 没表态时按不同意处理，不能当成点头
        silent = create_message("alice", "")
        assert not protocol.approved(silent)


class TestPlanApproval:
    def test_一来一回(self):
        req = protocol.plan_approval_request("alice", "lead", "1. 先读 auth 包\n2. 抽出接口")
        assert req.type == protocol.PLAN_APPROVAL_REQUEST
        assert "抽出接口" in req.text, "计划全文应放在正文里"

        rid = protocol.request_id_of(req)
        rej = protocol.plan_approval_response("lead", "alice", rid, False, "别动 handler 层")
        assert not protocol.approved(rej)
        assert rej.text == "别动 handler 层", "驳回意见应放在正文里"
        assert protocol.request_id_of(rej) == rid


class TestSerialization:
    def test_字段能穿过一次序列化(self):
        req = protocol.shutdown_request("lead", "alice", "收工")
        rid = protocol.request_id_of(req)
        resp = protocol.shutdown_response("alice", "lead", rid, False, "还没跑完")

        got = MailboxMessage.from_dict(json.loads(json.dumps(resp.to_dict())))
        assert got.type == protocol.SHUTDOWN_RESPONSE
        assert protocol.request_id_of(got) == rid
        assert protocol.approved(got) is False, "approve=False 必须原样穿过序列化"

    def test_请求标识不重复(self):
        seen = {protocol.new_request_id() for _ in range(200)}
        assert len(seen) == 200, "请求 ID 撞了"
