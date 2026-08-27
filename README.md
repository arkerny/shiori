# Shiori

> Dedicated to Shiori, a yuri enthusiast.

A simple schedule application for HDU.

PS: 理论上来说任何学校的系统都能接进来，改动 newjw 里面的内容即可（可能还需要重写一下该死的 json 和 hdu 的匹配）

## 如何运行

目前仅支持从源码运行。

**环境要求**：Python 3.10+（Windows / macOS / Linux 均可）

```bash
# 1. 克隆仓库
git clone <repo-url>
cd shiori

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python main.py
```

首次启动时会自动在 `~/.shiori/` 下生成 `config.json`（数据目录，课程缓存与日志也存放在这里）。打开设置对话框填入教务系统账号（newjw 或 cas，newjw 优先，失败自动换 cas）以及学年学期后即可开始使用。

## 如何使用

基本排课流程如下：

1. **配置账号**：在设置对话框中填入教务系统账号（`hdu.newjw` 或 `hdu.cas`）和学年学期（如 `2026` / `1`）。
2. **同步课程池**：点击信息面板中的「更新课程池」按钮，从教务系统在线拉取本学期全部可选课程（任务落实聚合较慢，高峰期可能需要较长时间，请耐心等待）。
3. **勾选课程**：在右侧课程列表中勾选心仪的教学班，左侧课表网格会实时预览周课表、学分统计与时间冲突（冲突课程在信息面板中以红色标出）。
4. **同步个人课表**：点击「更新个人课表」，从教务系统拉取已选课数据；信息面板会自动对比本地勾选与教务实际选课，用不同颜色标注**补选**（本地有、教务无）、**退选**（教务有、本地无）与**冲突**，作为去教务系统操作的清单。
5. **导出课表**：课表视图支持导出为 PNG 图片。

所有配置（课表节次时间、学期周数、列显示、学分上限等）都可在设置对话框中调整，或直接编辑 `~/.shiori/config.json`。

## 致谢

newjw 教务系统对接功能由 [HDU-KillCourse](https://github.com/cr4n5/HDU-KillCourse) 重写得到，感谢作者。

## 关于开发

欢迎提 issue，精美的 UI 和部分繁杂的逻辑的程序是 vibe 的（但 100% 人工 Review），其余（极小部分）为手写~