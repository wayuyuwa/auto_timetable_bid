# UTAR 课程注册爬虫

[English](README.md) | [中文](README.zh.md)

> **免责声明**：本项目**仅供教育目的**使用。它展示了网页爬虫、自动化和GUI开发的概念。用户需确保使用本工具时遵守UTAR的服务条款和政策。开发者不对任何滥用或使用本工具产生的后果负责。

一个使用Python展示网页爬虫和自动化技术的教育项目。本项目展示了：
- 使用BeautifulSoup和Selenium进行网页爬虫
- 使用PyQt5开发GUI界面
- CAPTCHA验证码破解
- 浏览器自动化交互
- 配置管理
- 线程和异步操作
- 使用vibe coding嘎嘎写代码 (bushi)

## 功能特点

- **双重爬虫方法**：
  - BeautifulSoup用于轻量级爬虫
  - Selenium用于完整的浏览器自动化，包括CAPTCHA处理
- **自动化课程注册**：
  - 支持基于时间表的课程注册
  - 基于偏好的自动时段选择
  - 会话管理和自动重新登录
- **用户友好界面**：
  - 基于PyQt5的现代界面
  - 设置持久化
  - 进度反馈
  - 可折叠的Selenium选项
- **附加功能**：
  - 安全的凭证存储
  - 使用ddddocr进行CAPTCHA验证码破解
  - 支持无头模式

## 系统要求

- Python 3.8+
- PyQt5
- Selenium
- BeautifulSoup4
- ddddocr
- Firefox WebDriver（用于Selenium）

## 安装步骤

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/utar-course-registration-scraper.git
cd utar-course-registration-scraper
```

2. 创建并激活虚拟环境：
```bash
python -m venv venv
source venv/bin/activate  # Windows系统: venv\Scripts\activate
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

4. 下载Firefox WebDriver：
   - 访问 [Mozilla GeckoDriver 发布页面](https://github.com/mozilla/geckodriver/releases)
   - 下载适合您系统的版本
   - 将驱动程序添加到系统PATH中

## 使用方法

1. 运行应用程序：
```bash
python src/main.py
```

2. 配置设置：
   - 选择爬虫方法（BeautifulSoup或Selenium）
   - 输入UTAR账号凭证
   - （可选）选择时间表文件
   - （可选）配置Selenium选项（无头模式）

3. 开始爬取：
   - 点击"执行爬取"开始
   - 使用"停止"按钮安全终止进程
   - 在结果显示区域监控进度

## 配置文件

应用程序使用以下配置文件：

- `config.ini`：主配置文件，包含URL、超时和其他设置
- `user_settings.json`：用户特定设置（凭证、偏好）
- `.gitignore`：配置为排除敏感文件

## 项目结构

```
src/
├── gui/
│   ├── main_window.py      # 主GUI实现
│   └── __init__.py
├── scrapers/
│   ├── beautifulsoup_scraper.py
│   ├── selenium_scraper.py
│   └── __init__.py
├── utils/
│   ├── captcha_solver.py   # CAPTCHA破解工具
│   ├── config.py          # 配置加载器
│   ├── settings.py        # 设置管理器
│   ├── timetable_reader.py # 时间表解析
│   └── __init__.py
└── main.py                # 应用程序入口点
```

## 安全说明

- 凭证存储在本地`user_settings.json`文件中
- 该文件通过`.gitignore`排除在git之外
- 在生产环境中考虑使用环境变量存储敏感数据

## 教育价值

本项目作为以下方面的学习资源：
- 网页爬虫技术
- 浏览器自动化
- GUI开发
- 线程和异步编程
- 配置管理
- 安全最佳实践
- 错误处理和日志记录

## 贡献指南

1. Fork本仓库
2. 创建特性分支
3. 提交您的更改
4. 推送到分支
5. 创建Pull Request

## 许可证

本项目采用MIT许可证 - 详见LICENSE文件