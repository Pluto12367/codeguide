# 发布指南

首次发布需要你完成的一次性操作（涉及你的 GitHub / PyPI 账号，代码已全部就绪）：

## 1. 发布到 GitHub

仓库已本地初始化并提交。推荐用 gh CLI（本机已安装）：

```bash
cd E:\creative-projects\codeguide
gh auth status                      # 确认已登录
# 建议先把 pyproject.toml 与 README 中的 yourname 替换为你的 GitHub 用户名
gh repo create codeguide --public --source=. --push
```

推上去后 GitHub Actions 会自动跑测试（`.github/workflows/ci.yml`）。

## 2. 发布到 PyPI（可信发布，无需 token）

1. 登录 [pypi.org](https://pypi.org)（没有账号先注册一个）
2. 进入 Account Settings → Publishing → Add a "Pending Publisher"：
   - PyPI project name: `codeguide`
   - GitHub repository: `<你的用户名>/codeguide`
   - Workflow name: `publish.yml`
   - Environment: `pypi`
3. 在 GitHub 仓库 Settings → Environments 创建名为 `pypi` 的环境
4. 发版触发发布：

```bash
git tag v0.4.0
git push origin v0.4.0
gh release create v0.4.0 --title "v0.4.0" --notes "首个公开版本，详见 CHANGELOG.md"
```

Release 发布后，`.github/workflows/publish.yml` 会自动构建 sdist/wheel
并通过可信发布上传到 PyPI。

## 3. 本地验证（发布前可选）

```bash
pip install build twine
python -m build
twine check dist/*
```

## 备选：用 API token 手动上传

不想用可信发布的话：

```bash
python -m build
twine upload dist/*   # 提示时输入 __token__ 和 PyPI token
```

## 注意

- 发布前把 `pyproject.toml` 和 `README.md` 里的 `yourname` 占位替换成真实用户名
- `codeguide` 这个名字在 PyPI 可能已被占用，先到 pypi.org 搜一下；
  被占用的改名：`pyproject.toml` 中的 `name` 改为 `codeguide-ai` 之类
- 版本更新流程：改 `codeguide/__init__.py` 的 `__version__` →
  在 `CHANGELOG.md` 记录 → 打 tag → 发 Release
