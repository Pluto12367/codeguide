"""风险热区（git churn × PageRank）测试。"""

import subprocess
from pathlib import Path

import pytest

from codeguide.models import RepoProfile
from codeguide.risks import git_churn, repo_risks, risk_map


def _profile_with_edges(edges: list[tuple[str, str, int]]) -> RepoProfile:
    nodes = sorted({e[0] for e in edges} | {e[1] for e in edges})
    return RepoProfile(
        root="/fake", name="fake", total_files=len(nodes), total_lines=100,
        languages={"python": {"files": len(nodes), "lines": 100}},
        files=[], graph_nodes=nodes,
        graph_edges=[list(e) for e in edges],
    )


def test_risk_map_ordering():
    profile = _profile_with_edges([
        ("pkg/cli.py", "pkg/core.py", 3),
        ("pkg/api.py", "pkg/core.py", 2),
        ("pkg/api.py", "pkg/utils.py", 1),
        ("pkg/cli.py", "pkg/utils.py", 1),
    ])
    # core 最核心；utils 改动最频繁
    churn = {"pkg/core.py": 2, "pkg/utils.py": 10, "pkg/cli.py": 1}
    rows = risk_map(profile, churn)

    assert rows, "有 churn 且有依赖时应产出风险列表"
    assert "pkg/api.py" not in {r["path"] for r in rows}  # 无 churn 记录的文件不出现
    top = rows[0]
    # utils：改动最多且被依赖，应当排第一
    assert top["path"] == "pkg/utils.py"
    assert {"path", "commits", "pagerank", "risk"} <= set(top)
    # 风险分降序
    risks = [r["risk"] for r in rows]
    assert risks == sorted(risks, reverse=True)


def test_risk_map_empty_cases():
    profile = _profile_with_edges([("a.py", "b.py", 1)])
    assert risk_map(profile, {}) == []  # 无 churn
    churn = {"not_in_graph.py": 5}
    assert risk_map(profile, churn) == []  # churn 路径不在依赖图中


def test_git_churn_on_real_repo(tmp_path: Path):
    """在临时 git 仓库上端到端验证 churn 统计（需要 git 可用）。"""
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git 不可用")

    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"]}

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args],
                       check=True, capture_output=True, env=env)

    git("init", "-q")
    (root / "pkg" / "hot.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pkg" / "cold.py").write_text("y = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    (root / "pkg" / "hot.py").write_text("x = 2\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "change hot")
    (root / "pkg" / "hot.py").write_text("x = 3\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "change hot again")

    churn = git_churn(root)
    assert churn is not None
    assert churn["pkg/hot.py"] == 3
    assert churn["pkg/cold.py"] == 1


def test_git_churn_non_repo(tmp_path: Path):
    assert git_churn(tmp_path) is None or git_churn(tmp_path) == {}
