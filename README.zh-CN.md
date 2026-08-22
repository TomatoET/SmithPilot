<p align="center">
  <img src="assets/app_icons/app-icon-128.png" width="96" alt="SmithPilot 标志">
</p>

<p align="center">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

# SmithPilot

[![CI](https://github.com/TomatoET/SmithPilot/actions/workflows/ci.yml/badge.svg)](https://github.com/TomatoET/SmithPilot/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4.svg)](https://github.com/TomatoET/SmithPilot/releases)

SmithPilot V0.4 是一款 Windows 桌面应用，用于引导 Agilent/Keysight E5071C
矢量网络分析仪完成以下测量流程：

- 使用可编辑的 TX 频段预设和 Marker 频率配置测量参数
- 一键配置 3 条 Trace：S11 Smith、S22 Smith、S21 Log Mag
- 引导完成 Open、Short、Load 和 Thru 的机械式双端口 SOLT 校准
- 使用 USB ECal 模块执行电子式双端口校准
- 受控保存和调用分析仪状态
- 配置、测量并回读 Auto Port Extension
- 在 Measurement Tools 中显示 Data/Memory Trace、执行 Data -> Mem，
  并将命名截图保存到仪器后拉取至电脑

V0.4 包含最终版 SmithPilot 应用程序图标、窗口图标和 Windows 可执行文件构建配置。

SmithPilot 的设计定位是半自动化工具。它不会代替操作人员连接校准件、焊接夹具、
控制外部平台工具、开启 PA 功率或自动选择匹配元件。

> [!WARNING]
> SmithPilot 会修改分析仪设置、校准数据、状态文件和仪器存储内容。
> 在真实硬件上使用前，请备份重要状态并检查所有 RF 连接。
> 自动化测试不能代替在目标分析仪及其固件版本上的实际验证。

SmithPilot 是独立项目，与 Keysight Technologies 或 Agilent Technologies
不存在隶属、合作或背书关系。相关产品名称和商标归各自权利人所有。

## 技术栈

- Python 3.11+
- PySide6
- PyVISA
- PyVISA-py
- Python 标准库 `unittest`

## 项目结构

```text
SmithPilot/
|-- main.py
|-- requirements.txt
|-- requirements-dev.txt
|-- SmithPilot.spec
|-- README.md
|-- README.zh-CN.md
|-- LICENSE
|-- assets/
|   |-- app_icons/
|   `-- menu_icons/
|-- config/
|   `-- band_presets.json
|-- docs/
|   |-- HARDWARE_VALIDATION.md
|   `-- workflow_prd.md
|-- app/
|   |-- __init__.py
|   |-- main_window.py
|   |-- vna_workflow.py
|   `-- widgets/
|       `-- __init__.py
|-- instrument/
|   |-- __init__.py
|   |-- base_vna.py
|   `-- e5071c.py
|-- tests/
|   |-- test_e5071c_v02_scpi.py
|   |-- test_main.py
|   |-- test_main_window_settings.py
|   `-- test_vna_workflow.py
`-- utils/
    |-- __init__.py
    `-- logger.py
```

## 安装

创建并激活 Python 虚拟环境，然后安装运行依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

运行 `run_smithpilot.bat` 时，如果存在 `.venv\Scripts\python.exe`，脚本会优先使用它；
否则使用系统 `PATH` 中的 `python`。

## 运行

```powershell
python main.py
```

应用启动后默认处于未连接状态，不会自动连接仪器。

没有真实 E5071C 时，可选择 `Use Mock Instrument`，在不打开 VISA 会话的情况下体验流程。

## Windows 打包

V0.4 使用 PyInstaller 生成单目录 Windows 程序包，发布产物包括：

- `SmithPilot.exe`
- Python、PySide6 和 PyVISA 运行时依赖
- 应用程序和窗口图标资源

使用仓库中的 PyInstaller spec 文件执行可复现构建：

```powershell
pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean SmithPilot.spec
```

构建结果位于 `dist\SmithPilot`。推送版本标签或手动运行构建工作流时，
GitHub Actions 也会生成可下载的压缩包。

## E5071C LAN 连接

1. 使用局域网或网线直连，将电脑与 E5071C 接入同一网络。
2. 在仪器的 LAN/网络设置中确认 E5071C IP 地址。
3. 在 SmithPilot 中输入该 IP 地址。
4. SmithPilot 会保存最后一次使用的非空 IP 地址，并在下次启动时恢复。
5. SmithPilot 默认创建以下 E5071C SCPI Socket VISA 资源：

```text
TCPIP0::<IP>::5025::SOCKET
```

示例：

```text
TCPIP0::192.0.2.10::5025::SOCKET
```

SmithPilot 通过 `ResourceManager("@py")` 使用 PyVISA-py。连接时首先尝试
SCPI Socket 资源；失败后自动尝试以下 LAN/VXI-11 资源：

```text
TCPIP0::<IP>::inst0::INSTR
```

应用的连接超时时间为 10000 ms。

## 操作流程

1. 连接 E5071C。
2. 打开 `Setup` 页面。
3. 选择 TX 频段预设，或手动修改 Start、Stop、Points 和 Markers。
4. 点击 `Configure Analyzer`，配置 3 条 Trace。
5. 打开 `Calibration` 页面。
6. 打开 `Mechanical SOLT` 执行手动校准，并确认校准件型号，默认值为 `85032F`。
7. 只有在界面要求的 Open、Short、Load 或 Thru 已正确连接后，才能执行对应机械校准步骤。
8. 也可以打开 `Electronic ECal`，连接 USB ECal 模块，点击 `Refresh ECal`，
   选择模块并确认 ECal 已连接到 Port 1 和 Port 2 之间，然后点击 `Run 2-Port ECal`。
9. ECal 完成后，可按需执行 `Confidence Check`。
10. 打开 `State`，使用明确的状态文件名保存或调用分析仪状态。
11. 打开 `Port Extension` 页面。
12. 选择 `Port 1`、`Port 2` 或 `All`；按需启用损耗补偿；在所选延伸参考面连接 OPEN，
    然后执行 Auto Port Extension。每次测量前，SmithPilot 会先清除 E5071C 中 Port 1/2
    的旧选择，再仅启用本次选择的端口。
13. 打开 `Measurement Tools` 页面。
14. 点击 `Data -> Mem: Trace 1-3`，将 Trace 1-3 当前数据复制到 Memory 作为参考。
15. 点击 `Display Data & Mem`，同时显示 Trace 1-3 的 Data 和 Memory。
16. 输入截图名称，选择 VNA Folder 和电脑保存目录，然后点击 `Capture Screen`。
    SmithPilot 先使用 `:MMEM:STOR:IMAG` 将图片保存到 E5071C，再使用
    `:MMEM:TRAN?` 将同一文件传输到电脑。仪器端文件默认保留，最后一次使用的
    VNA 和电脑目录会在下次启动时恢复。

## 频段预设

Setup 页面从以下文件加载频段预设：

```text
config/band_presets.json
```

每个频段使用一个对象：

```json
{
  "name": "WCDMA B1 TX",
  "unit": "MHz",
  "start": 1920,
  "stop": 1980,
  "points": 1601,
  "markers": [1920, 1950, 1980]
}
```

支持的单位为 `Hz`、`kHz`、`MHz` 和 `GHz`。`markers` 必须位于 Start/Stop 范围内，
E5071C 最多支持 10 个 Marker。在 SmithPilot 运行期间修改文件后，点击 Setup 页面上的
`Reload Presets`。如果文件缺失，程序会使用内置默认预设；如果文件格式错误，程序会继续
使用内置预设，并在界面和日志中显示警告。

## 安全策略

所有直接仪器操作都集中在 `instrument/e5071c.py` 中。

手动 SCPI Console 只允许 V0.1 已定义的有限写操作：

- Start Frequency
- Stop Frequency
- Sweep Points
- Single Sweep 支持命令

机械校准、ECal、Port Extension 和 Save/Recall 通过受控驱动方法执行。
这些方法会验证输入，并且只能由明确的界面按钮触发。手动控制台仍会阻止
`:MMEM:STOR`、`:SENS1:CORR:COLL:ECAL:SOLT2` 等任意写命令。

在界面要求的校准件或夹具状态正确连接之前，不要执行校准或 Auto Port Extension。
在 USB ECal 模块已选中并正确连接到 VNA Port 1 和 Port 2 之间之前，不要执行 ECal。

## Mock Instrument 模式

没有真实 E5071C 时，可选择 `Use Mock Instrument`。Mock 模式会在界面和日志中明确标识，
且不会打开 VISA 资源；它可以验证界面流程和命令顺序。

Mock 仪器身份信息：

```text
Manufacturer = Agilent Technologies
Model = E5071C
Serial = MOCK001
Firmware = MOCK
```

## 测试

安装开发依赖，并执行与 CI 相同的检查：

```powershell
pip install -r requirements-dev.txt
python -m ruff check .
python -m unittest discover -s tests
python -m compileall -q app instrument tests main.py
python -m pip_audit -r requirements.txt
```

自动化测试不会在真实仪器上执行机械校准或 ECal。硬件验证应先执行 `*IDN?`、
`SYST:ERR?` 等只读检查；只有当操作人员准备好校准件或 ECal 模块后，才能继续校准。

验证等级和安全检查清单请参阅 [硬件验证文档](docs/HARDWARE_VALIDATION.md)。

## 常见错误

### Wrapper not found: No package named pyvisa_py

运行 SmithPilot 的 Python 环境没有安装 PyVISA-py。

解决方法：

```powershell
pip install -r requirements.txt
```

### VI_ERROR_RSRC_NFOUND

找不到 VISA 资源，请检查：

- IP 地址是否正确。
- 电脑与 E5071C 是否在同一网络。
- E5071C 的 LAN 远程控制服务是否已启用。
- SmithPilot 会依次尝试 `TCPIP0::<IP>::5025::SOCKET` 和
  `TCPIP0::<IP>::inst0::INSTR`。

### Timeout

仪器未在 10000 ms 超时时间内响应，请检查：

- 网线、交换机或直连链路。
- 仪器 LAN 设置。
- 使用 `TCPIP0::<IP>::5025::SOCKET` 时，确认仪器能在 TCP 5025 端口响应 SCPI。
- 使用 `TCPIP0::<IP>::inst0::INSTR` 时，确认仪器 LAN/VXI-11 服务已启用。
- 是否有其他程序占用仪器会话。
- 当前分析仪状态是否支持所执行的 SCPI 命令。

### Connection Refused

电脑可以访问该 IP，但远端拒绝连接，请检查：

- E5071C 远程控制设置。
- 防火墙规则。
- 仪器是否支持所选 VISA LAN 资源模式。

## 说明

- Single Sweep 使用 SCPI trigger/initiate 命令，并等待 `*OPC?`。
- 校准和 Port Extension 命令也会在 E5071C 支持的步骤中等待操作完成。
- 实现范围和不包含的功能请参阅 `docs/workflow_prd.md`。

## 贡献与安全

欢迎参与贡献。提交 Pull Request 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
发现安全漏洞时，请按照 [SECURITY.md](SECURITY.md) 通过私有渠道报告，不要创建公开 Issue。

版本变更记录位于 [CHANGELOG.md](CHANGELOG.md)。SmithPilot 使用
[MIT License](LICENSE) 发布。
