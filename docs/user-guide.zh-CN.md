# OpsPilot 用户使用说明

适用版本：当前本地 MVP（v0.2）。界面为英文，本说明保留按钮原名，方便对照操作。

OpsPilot 面向替多个客户维护应用的软件工作室。工作室操作员在一个工作台查看应用状态、记录故障处理过程，并生成客户维护报告。

## 1. 第一次使用：先体验演示工作区

打开 **http://127.0.0.1:8080**，点击 **Explore demo workspace**。

如果网页打不开，在 PowerShell 中运行：

```powershell
cd D:\projects\opspilot
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

需要 Python 3.12 或以上。启动脚本会准备虚拟环境并安装依赖，首次运行需要联网。保持终端运行；在该终端按 `Ctrl+C` 停止。端口已被占用时，先打开现有页面；若需要另外启动一份，可加 `-Port 8081`，再访问对应端口。

演示工作区首次初始化会创建三个客户、四个项目和一条后台任务故障。已有数据会保留，所以再次打开时，数量和故障状态可能与首次演示不同。

**演示项目、历史观测以及 Azure/AWS 标签是样例，不代表已连接云账户。** 新版控制台中的 worker 恢复也是模拟操作。

## 2. 工作区、客户、项目是什么关系？

| 名称 | 含义 | 示例 |
| --- | --- | --- |
| Workspace | 你的软件工作室 | Northstar Studio |
| Client | 工作室服务的客户 | Meridian Finance |
| Project | 一个应用在一个环境中的监控对象 | Invoice API / Production |
| Incident | 需要跟进的故障记录 | 发票接口检查失败 |
| Deployment | 客户流水线上报的一次发布 | v1.4.2 / commit abc123 |

一个客户可以拥有多个项目。同一应用的生产和测试环境应分别新建项目。

当前是**单工作室工作区**：客户只是项目分组，没有各自的登录账号和数据访问权限。不要把工作室登录令牌交给最终客户；需要对外沟通时，导出并审核对应客户的报告。

## 3. 页面导航

| 菜单 | 用途 |
| --- | --- |
| Overview | 查看项目、健康状态、未关闭事件、近期发布和活动 |
| Projects | 查看全部项目，按状态筛选，打开项目详情 |
| Clients | 创建客户、查看客户项目、准备维护报告 |
| Incidents | 查看故障证据、记录处理备注、确认和关闭事件 |
| Deployments | 查看上报的版本及其发布后检查结果 |
| Client reports | 预览和下载最近 30 天的客户维护报告 |
| Connections | 了解 HTTP、heartbeat 和发布流水线接入方式 |
| Runbooks | 查看恢复演练操作流程及交接要求 |
| Workspace settings | 查看当前工作区和功能边界说明；目前不是可编辑的设置表单 |

桌面顶部搜索框可以搜索项目名称或客户名称。手机上通过左上角菜单切换页面。

## 4. 五分钟完成一次故障恢复演练

1. 在 Overview 或 Projects 打开 **Reporting worker**。
2. 查看 **Latest evidence**，确认是否存在模拟 worker 暂停的证据。
3. 如果当前没有故障，点击 **Inject worker fault → Confirm operation**，生成一次故障观测和事件。
4. 点击 **Approve recovery · RB-001 → Confirm operation**，恢复模拟 worker。
5. 等待操作完成，再点击 **Run check**。看到通过结果后，再进行下一步。
6. 点击 **Verify & resolve**，在 **Operator note / handoff** 填入处理和验证记录，例如：

   > Approved RB-001 to resume the simulated worker. A fresh check passed. No customer infrastructure was affected.

7. 点击 **Resolve with evidence**。事件变为 **Resolved**。
8. 进入 Client reports，为该项目所属客户生成维护报告，查看恢复和验证记录。

**恢复操作完成不会自动关闭事件。** 系统要求事件发生之后有一次新的、仍在有效时间范围内的通过观测；仅写一句“已修复”无法绕过检查。

## 5. 接入客户的公开网站或 API

适用：可以通过公网 HTTP/HTTPS 访问的应用。不需要 SSH、GitHub 仓库权限或云账户密钥。

### 第一步：创建客户

进入 **Clients → Add client**：

- **Client / company name**：客户公司名称。
- **Contact name or email**：选填联系人，用于记录；不会自动发送邮件。

保存后，点击该客户卡片的 **Add project**，或页面上的 **Connect project**。

### 第二步：填写项目信息

| 字段 | 填写内容 |
| --- | --- |
| Client | 选择项目所属客户 |
| Project name | 容易识别的应用名称，例如 Customer portal |
| Hosted on | Azure、AWS、Coolify、Vercel 或 Other |
| Environment | Production 或 Staging |

Hosted on 是分类标签，不会发起 Azure/AWS 登录，也不会自动发现该账户下的资源。

### 第三步：选择 Public endpoint

- **Public health endpoint**：填写你拥有或获准监控的只读健康地址，例如 `https://api.your-domain.com/health`。
- **Check interval**：检查间隔，单位秒。默认 300；允许 60–86400。
- **Expected HTTP status**：预期状态码，默认 200；允许 200–299。

点击 **Continue** 检查摘要，再点击 **Create connection**。

只支持公网端口 80/443。`localhost`、内网地址、带用户名密码的 URL 不支持；系统不会跟随重定向。若入口返回 301/302，填写最终健康地址。需要鉴权请求头的健康接口目前也不能直接配置，改用 heartbeat。

### 第四步：保存凭据并完成第一次检查

创建成功后显示一次项目令牌和接入命令。先把令牌放入项目或 CI 的秘密存储，再点击 **Run first check**。

公开 URL 的定时检查由 OpsPilot 执行，不需要在客户应用中安装东西。项目令牌用于后续发布事件等上报，不是公开检查所必需的服务器凭据。

检查详情会显示状态、延迟和证据。调度器每 30 秒检查一次哪些项目到期，实际执行时间还可能受排队和请求耗时影响，间隔不是精确时刻保证。

## 6. 接入内网应用、后台服务或 worker

适用：OpsPilot 无法直接访问，但该服务能主动连接 OpsPilot 的情况。

```text
客户私有应用 → 本地健康检查 → HTTPS heartbeat → OpsPilot
```

1. 新建项目，在连接方式中选择 **Outbound heartbeat**。
2. 设置预期上报间隔，例如 300 秒。
3. 创建后保存项目 ID 和项目令牌。ID 可以从生成命令中的 `/api/ingest/项目ID/heartbeat` 取得。
4. 在能访问客户服务健康接口的机器上运行 `scripts/heartbeat.py`。

PowerShell 示例，需替换占位值：

```powershell
$env:OPSPILOT_URL = 'https://你的opspilot域名'
$env:OPSPILOT_PROJECT_ID = '项目ID'
$env:OPSPILOT_PROJECT_TOKEN = '项目令牌'
$env:HEALTH_URL = 'http://127.0.0.1:9000/health'
$env:HEARTBEAT_INTERVAL = '300'
python scripts/heartbeat.py
```

脚本访问 `HEALTH_URL`，响应状态为 200 时上报健康，否则上报失败。在终端运行适合验证；持续使用时由客户环境的服务管理器或容器管理该进程，并将令牌注入环境变量。

远程服务必须能访问 `OPSPILOT_URL`。你电脑上的 `127.0.0.1:8080` 对远程云服务器来说指的是它自己，不能用于跨机器接入。正式远程接入需要部署一个可访问的 HTTPS 控制台。

上报内容应反映真实服务状态。不要用永远返回成功的定时消息替代业务检查。当前脚本只检查一个健康接口，不能自动判断登录、付款或队列是否真正正常。

## 7. 接入发布流水线

需要验证真实登录和学习记录时，可新建 **Business workflow** 项目，按 [业务检查配置说明](business-checks.zh-CN.md) 设置客户侧浏览器运行器。它与普通 heartbeat 分开，提供五个步骤的状态和证据。

适用：让现有 GitHub Actions 或其他 CI 在发布完成后记录版本，并验证公开健康接口。

把项目令牌存入 CI secret，配置以下变量，然后调用仓库中的脚本：

```powershell
$env:OPSPILOT_URL = 'https://你的opspilot域名'
$env:OPSPILOT_PROJECT_ID = '项目ID'
$env:OPSPILOT_PROJECT_TOKEN = '项目令牌'
$env:RELEASE_VERSION = 'v1.4.2'
$env:GITHUB_SHA = '对应提交SHA'
python scripts/send-deployment.py
```

- **HTTP 项目**：收到发布事件后立即检查其健康 URL。通过为 Verified，失败为 Failed。
- **Heartbeat 项目**：发布记录为 Pending，当前版本还不能把某次 heartbeat 与特定发布版本关联。
- 脚本只有收到 Verified 才返回成功退出码；Failed、Pending 或请求失败都返回非零，供 CI 阻止继续执行后续步骤。

OpsPilot 接收和验证发布记录，不会替你部署客户应用，也不会自动执行回滚。Verified 只证明配置的检查通过，不代表全部业务功能已验证。

## 8. 如何理解状态？

| 状态 | 含义 | 推荐动作 |
| --- | --- | --- |
| Healthy | 最近有效观测通过 | 根据需要查看具体检查覆盖 |
| Degraded | 最近有效观测失败 | 打开项目详情和相关事件 |
| Awaiting data | 尚无观测 | 执行首次检查或确认上报脚本运行 |
| No recent data | 最后观测已超过两个配置间隔 | 检查应用、连接和上报进程；不能认定应用仍健康 |
| Investigating | 事件已打开，尚未确认处理 | 查看证据并记录处理计划 |
| Acknowledged | 操作员已确认事件并留下备注 | 继续调查和修复 |
| Resolved | 操作员在有效通过观测后关闭事件 | 保留记录并跟进预防措施 |

新 heartbeat 项目没有收到第一条数据时仍显示 Awaiting data；超过宽限期后也会产生 missing-heartbeat 事件。发现时间受调度周期影响。

**项目状态和事件状态是两回事。** 应用已经 Healthy，之前的事件仍可能等待人工关闭。

Recent checks 的百分比表示采样通过率，不是按时间统计的 uptime。没有记录的时间不能当成正常运行。

## 9. 处理真实项目故障

1. 进入 **Incidents**，打开失败证据。
2. 点击 **Acknowledge**，记录当前判断和下一步。
3. 在客户原有的云平台、日志系统和发布工具中调查并修复。
4. 回到 OpsPilot：HTTP 项目执行 **Run check**；heartbeat 项目等待服务发出新的健康观测。
5. 点击 **Verify & resolve**，记录采取的操作、验证结果和后续事项。

当前真实项目是只观测接入，不提供远程重启、SSH、容器控制、自动回滚或 AI 根因调查。只有演示项目能使用模拟故障和恢复按钮。

跨时区交接建议写清：当前业务影响、UTC 时间、已做操作、证据、剩余问题和下一次检查时间。当前备注保存的是最近一次提交的内容；历史确认和关闭操作可在活动记录中查找。

## 10. 生成客户维护报告

1. 进入 **Client reports**。
2. 找到客户，点击 **Prepare report**。
3. 检查报告预览，再点击 **Download Markdown**。

报告包括最近 30 天的观测数量、通过数量、窗口内新开的事件和操作证据，并标明演示数据。当前报告的事件列表按“打开时间在最近 30 天内”筛选，不能代替完整的历史未结事件清单；分享前同时检查 Incidents。

下载的是 `.md` 文本文件，可以用 VS Code 或支持 Markdown 的工具阅读。当前没有 PDF 导出、自动邮件发送或客户门户。报告中的备份恢复会明确标注尚未验证。

## 11. 令牌与登录

| 凭据 | 用途 | 放在哪里 |
| --- | --- | --- |
| Workspace token / OPS_TOKEN | 操作员登录整个工作区 | 工作室管理员保管 |
| Project token | 某个项目的 heartbeat 和发布事件上报 | 该项目服务或 CI 的 secret |

项目令牌只显示一次。如果遗失，打开项目详情，点击 **Rotate project token → Rotate token**。旧令牌立即失效，需马上更新 heartbeat 和 CI。

网页会话有效期为八小时；服务重启后需要重新登录。忘记工作室令牌需要由部署管理员在服务环境中替换 `OPS_TOKEN` 并重启；网页没有密码重置功能。

## 12. 创建没有演示数据的本地工作区

在新的 PowerShell 窗口中执行；下面显式指定独立数据库，防止沿用已有演示数据库配置：

```powershell
cd D:\projects\opspilot
$env:OPS_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:DATABASE_URL = 'sqlite:///data/live.db'
Write-Host $env:OPS_TOKEN
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Live -Port 8081
```

妥善保存本机终端显示的工作室令牌。打开 `http://127.0.0.1:8081`，输入该令牌，点击 **Open workspace**。先创建客户，再接入项目。

`-Live` 表示关闭演示入口，不代表已经完成生产部署。界面是同一个工作室共享的操作入口；正式托管前还需要部署网络、数据库、身份权限和恢复机制。参见 [Azure 部署说明](azure-deployment.md)。

启动脚本读取环境变量，不会自动载入 `.env`；Docker Compose 才会自动读取对应的 `.env` 文件。

## 13. 常见问题

| 问题 | 排查方法 |
| --- | --- |
| 页面打不开 | 检查服务是否运行，确认终端打印的端口；当前后台运行的实例可能与新终端不是同一个进程 |
| 新界面未显示 | 强制刷新浏览器，确认访问的是新版 `start.ps1` 启动的控制台，而不是旧 `app.py` 实验页面 |
| 查看不到之前的数据 | 确认工作目录和 `DATABASE_URL`；早期手动启动可能使用 `data/control.db`，新版启动脚本默认使用 `data/demo.db` 或 `data/live.db` |
| HTTP 检查访问 localhost 失败 | 公网检查禁止私有地址；换公网地址或使用 outbound heartbeat |
| 接口返回 301/302 | 填写最终地址，检查器不跟随重定向 |
| 401 / Invalid project token | 检查项目 ID 和令牌是否对应，确认不是工作室令牌，确认轮换后已更新 sender |
| 太多登录尝试 | 等待五分钟后再试；同一来源五分钟内连续失败十次会触发限制 |
| 恢复后仍无法关闭事件 | 等待一次新的通过观测；确认它晚于事件打开时间，且没有过期 |
| 出现 heartbeat missing | 检查 sender 是否存活、网络是否可达、上报间隔是否匹配，以及服务启动后的首次上报是否成功 |
| 某些页面只有介绍，没有设置按钮 | 当前 Connections 的云平台说明和 Workspace settings 部分是能力说明，不是完整配置入口 |

## 14. 当前功能范围

已可用：多客户项目管理、公开检查、私有上报、发布事件、故障记录、审核式关闭事件、报告导出、本地演示恢复。

尚未实现：独立客户账号、成员角色、订阅计费、Azure/AWS 账户自动发现、远程生产修复、AI 调查、自动通知、备份恢复验证。Azure 模板已经编译验证，但不能据此认为云资源已部署成功。
