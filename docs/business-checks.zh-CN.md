# 真实业务检查：登录、学习记录和页面显示

这个检查器会打开荷兰语应用的真实页面，用专用账号登录，确认 Supabase 返回预先保存的学习记录，再验证单词本和复习页面真的显示该记录。

**当前尚未配置线上测试账号，不能认定线上检查已通过。** 本地浏览器测试使用真实应用代码配合假的认证和数据库响应，用于验证检查器是否能区分成功和失败，不会把测试结果上报为生产记录。

## 检查内容

| 步骤 | 通过条件 |
| --- | --- |
| Application opens | 页面可打开，并能进入邮箱密码登录表单 |
| Test account signs in | 页面完成密码登录，返回用户 ID 与配置一致，Auth 用户接口也确认相同身份 |
| Saved learning record is readable | 页面成功读取该用户的 `sync_data`；预期单词在 notebook 中，对应学习记录与约定的等级一致，并被应用载入 |
| Saved word appears in notebook | 单词本页面实际显示对应单词卡片 |
| Review screen shows saved progress | 复习页面切换到该单词，显示的 Memory level 与预期值一致 |

每次使用新的独立浏览器环境。不会用上一次登录的缓存把云同步失败掩盖成成功。失败后的步骤标记 Skipped，不能把只完成登录的执行记录当成全链路成功。

这是针对当前荷兰语应用的适配器，不是任何网站都能直接使用的通用脚本。其他客户的软件需要自己的登录步骤、页面定位和业务断言。

## 1. 准备专用测试账号与固定记录

1. 在荷兰语应用中注册一个**只用于监控**的邮箱密码账号，按应用提示完成邮箱确认。
2. 手动登录，收藏一个明确的单词。首次建议使用 Core 的 `C1`，单词为 `de`。
3. 对该词完成一次复习。记录复习后页面显示的 Memory level；不要假设必定是 1。
4. 等待同步，再用新的浏览器窗口登录，确认收藏和复习等级仍在。
5. 在自己的 Supabase 管理后台查看此测试账号的用户 UUID，作为 `expected_user_id`。
6. 准备应用完整 URL 和它实际使用的 Supabase 项目 URL。检查器会验证认证请求目标，防止连错环境。

以后不要用这个账号日常学习。若更改了监控单词或等级，需同步更新配置，否则“固定记录不匹配”会被判定为失败。

不要使用日常个人账号或 service-role 密钥。检查器不需要数据库管理员权限、不创建账号、不生成学习记录，也不执行付费 AI 或付款操作。

## 2. 在 OpsPilot 创建 Business workflow 项目

1. 进入 **Clients** 创建或选择客户。
2. **Connect project** 填写项目名，例如 `Dutch App — Login & Learning`。
3. 连接方式选择 **Business workflow**。
4. 设置预期观测间隔，例如 900 秒（15 分钟）。这只是数据新鲜度配置，不会在服务器上自动启动浏览器。
5. 创建项目，保存显示一次的连接字段：`opspilot_url`、`opspilot_project_id`、`opspilot_project_token`。

业务项目只能接受浏览器步骤结果，普通 heartbeat 不能把它变为 Healthy。尚未运行时显示 Awaiting data；超过两个配置间隔没有结果会产生观测缺失事件。

## 3. 安装浏览器运行环境

在 OpsPilot 项目目录执行：

```powershell
cd D:\projects\opspilot
.\.venv\Scripts\python.exe -m pip install -r requirements-runner.txt
```

默认配置使用 Windows 上已安装的 Edge：`"browser_channel": "msedge"`。

若运行机器没有 Edge，安装 Chromium 并将该字段改为 `""`：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Linux CI 还需要浏览器系统依赖，可使用 Playwright 的 `install --with-deps chromium`。浏览器应运行在你控制的机器或私有 CI 环境中。

## 4. 填写本机配置

已提供 `config/dutch-business.local.json` 空白配置；如果不存在，从 `config/dutch-business.example.json` 复制一份。

本机 `.local.json` 文件已加入 git 忽略规则。不要把账号密码填进受版本管理的 example 文件。

| 字段 | 填写内容 |
| --- | --- |
| app_url | 荷兰语应用真实地址；本地开发也可填写 localhost 地址 |
| supabase_url | 该应用实际使用的 Supabase 项目 URL |
| email / password | 专用测试账号；也可通过下面的环境变量提供 |
| expected_user_id | 测试账号的 UUID |
| fixture_source_id | 固定单词的 source ID，例如 C1 |
| fixture_level | 已保存并手动确认的等级，JSON 数字 |
| browser_channel | Windows Edge 填 msedge；Playwright Chromium 填空字符串 |
| timeout_ms | 单步默认超时，建议保留 15000 |
| opspilot_url | 接收检查结果的 OpsPilot 地址 |
| opspilot_project_id | Business workflow 项目 ID |
| opspilot_project_token | 该项目的上报令牌 |

可以让 `email` / `password` 保持空白，改用运行环境提供：

```powershell
$env:DUTCH_TEST_EMAIL = '你的专用测试邮箱'
# 密码通过安全提示输入，避免直接写入终端命令历史。
$dutchProbePassword = Read-Host 'Dedicated test account password' -AsSecureString
$env:DUTCH_TEST_PASSWORD = [System.Net.NetworkCredential]::new('', $dutchProbePassword).Password
```

这些凭据只用于本机浏览器。工作区不存储测试密码、原始学习记录或 Supabase access token。OpsPilot 接收的只有步骤标识、状态、耗时和固定错误码。

## 5. 第一次运行

先校验配置，不启动浏览器、不访问应用：

```powershell
.\.venv\Scripts\python.exe scripts/check-dutch-business.py --validate-config --no-publish
```

再实际检查，但暂不向 OpsPilot 上报：

```powershell
.\.venv\Scripts\python.exe scripts/check-dutch-business.py --no-publish
```

确认五步符合预期后，执行完整检查并上报：

```powershell
.\.venv\Scripts\python.exe scripts/check-dutch-business.py
```

退出码：

- `0`：全部业务步骤通过；若启用上报，上报也成功。
- `1`：至少一个业务步骤失败；其余步骤按顺序跳过。
- `2`：配置、浏览器启动或结果上报失败。不能当作业务健康。

真实远程 runner 不能把自己机器的 localhost 当作你电脑上的 OpsPilot。跨机器使用时配置可达的 HTTPS 地址。运行器不会跟随携带项目令牌的上报重定向。

## 6. 查看结果和处理故障

打开项目详情的 **Browser business workflow** 区域：

- 每一步有 Passed / Failed / Skipped 结果、耗时和说明。
- 登录失败和学习数据读取失败会分别定位，不会统称“网站已挂”。
- 业务失败会创建故障事件；重复上报同一个 run ID 不重复计数。
- 服务恢复后，执行一次新的完整检查。通过后再到事件中填写备注并关闭。
- 最近 30 天的客户报告也包含最新业务检查的步骤证据。

如果 runner 停止了，旧的通过记录可能仍显示在步骤列表中，但项目状态会变为 No recent data，并显示原始观测时间；旧结果不能证明当前正常。

## 7. 定时执行

检查器每次执行一轮后退出。可由 Windows 任务计划程序或私有 CI 每 15 分钟执行一次上面的命令。

任务工作目录设置为 `D:\projects\opspilot`，解释器使用该项目 `.venv\Scripts\python.exe`。不要让同一任务并发执行；将 OpsPilot 的预期观测间隔设成实际调度间隔。配置文件和环境变量需对运行该任务的系统账号可用。

不要依赖在网页上点击 Run check：当前业务流程凭据保留在客户运行器，控制台不会远程启动浏览器。项目详情的 **Runner setup guide** 可再次查看配置步骤。

## 8. 读取检查的边界

荷兰语应用会自动把数据同步回 Supabase。为避免监控时覆盖数据，检查器会阻断浏览器内的数据写入和无关 POST 请求，仅允许指定 Supabase 项目的密码登录；检查结束后尝试注销本次会话并销毁浏览器环境。Realtime 订阅在本次检查中关闭，确保初次 REST 读取本身能通过。

因此，这次检查验证的是**登录、读取和页面展示**，不证明“新增学习记录、保存成功或跨设备实时同步”正常。也不测试 Google 登录、Magic Link、支付、AI 功能或所有浏览器兼容性。

不保存截图、HAR、trace、cookie 文件或登录状态。失败信息使用固定错误码，避免把密码、JWT 或学习内容带进日志。正常登录会产生认证服务自身的登录事件，这不等于业务数据写入。

## 9. 开发者验证（不需要真实账号）

后端测试：`python -m pytest tests -q`。

真实页面契约测试需先启动一个只用于测试的 Vite 实例。在荷兰语应用目录使用：

```powershell
$env:VITE_SUPABASE_URL = 'http://127.0.0.1:54321'
$env:VITE_SUPABASE_ANON_KEY = 'local-browser-contract-test-only'
npm.cmd run dev -- --host 127.0.0.1 --port 5175 --strictPort
```

另一个终端进入 OpsPilot，安装 runner 依赖后执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/browser_dutch.py -q
```

测试拦截假 Supabase URL 的请求，并阻断本地业务 API 调用。验证密码错误、缺失记录、数据库错误、页面未渲染等情况；不会登录真实账号或调用收费功能。测试结束后停止这个测试 Vite 实例，别把它当作真实应用环境。

参考：[Playwright 身份验证与隔离](https://playwright.dev/docs/auth)、[Supabase 密码登录](https://supabase.com/docs/reference/javascript/auth-signinwithpassword)、[Supabase 用户验证](https://supabase.com/docs/reference/javascript/auth-getuser)。
