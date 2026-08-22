"""github_automator —— 把任意项目提炼、打包并自动化提交到 GitHub 的工具包。

对外由顶层 cli.py 转发调用；包内模块各司其职：
analyzer(只读分析) / packager(打包) / docgen(文档) / github(远程) / cli(编排)。
维护约定：见 github-automator-规范手册.md。
依赖：仅 Python 标准库（不引入第三方包）。
"""

__version__ = "0.1.0"
