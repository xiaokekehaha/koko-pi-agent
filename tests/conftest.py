# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolate_teams_dir(tmp_path):
    """把团队根目录指到临时目录，让团队配置落在测试自己的沙箱里。

    团队目录是 <home>/.koko/teams，不重定向的话跑一次测试就会在真实主目录里
    留下一堆 squad、squad-2 这样的残留，下一次跑还会撞上「团队已存在」。

    只替换 teams.models 里的 Path.home，不动全局：memory 等模块同样按主目录
    解析路径，全局替换会连带改掉它们的行为。目录名避开 "home"，
    memory 的用例会在同一个 tmp_path 下自己建这个名字的目录。
    """
    home = tmp_path / "teams-home"
    home.mkdir(parents=True, exist_ok=True)
    with patch("koko_pi_agent.teams.models.Path.home", return_value=home):
        yield
