# Tibo Reset Monitor

零 GPT 用量的 Tibo / Codex / ChatGPT Work 重置信号监控。

## 它会做什么

- 每 6 小时由 GitHub Actions 自动运行一次。
- 不需要你的电脑开机，也不要求你的电脑访问 X。
- 监控：
  - https://codex-resets.com/
  - https://resets.today/
- 使用本地关键词规则判断：
  - 🟢 已确认重置
  - 🟠 高概率将重置
  - 🟡 仅模糊暗示
- 只在出现新的有效信号时向飞书推送。
- 每条英文内容后会自动附带中文翻译；优先使用无需 API Key 的免费网页翻译接口，失败时用本地 reset 语义规则兜底。
- 首次运行只建立历史基线，不会把旧的几十条记录全部推给你。
- 连续两次所有监控源都失效时，会发一条“监控健康提醒”。
- 每 30 天自动更新一次状态文件，用来避免 public repo 因 60 天无仓库活动导致 scheduled workflow 被自动停用。
- 监控与判断不调用 OpenAI API、ChatGPT、Work 或 Codex；中文翻译使用免费的网页翻译接口，不消耗 ChatGPT / Work / Codex 额度。

## 第一步：创建飞书接收群

1. 在飞书里新建一个群，只有你自己也可以。
2. 打开群设置。
3. 找到“群机器人”。
4. 添加“自定义机器人”。
5. 名称可以填：`Tibo Reset Monitor`。
6. 安全设置建议选择“关键词”，关键词填：`Tibo`。
7. 复制机器人 Webhook 地址。

Webhook 类似：

`https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx`

不要把这个地址直接写进 GitHub 仓库文件。

### 可选：开启签名校验

如果你在飞书机器人里额外开启了“签名校验”，还会得到一个 Secret。
本项目已经支持签名校验；后面在 GitHub 中额外建立 `FEISHU_SECRET` 即可。

如果你不想折腾，使用“关键词：Tibo”已经足够完成这个私人监控。

## 第二步：创建 GitHub 公共仓库

1. 登录 GitHub。
2. 点右上角 `+` → `New repository`。
3. Repository name 填：`tibo-reset-monitor`。
4. 选择 `Public`。
5. 创建仓库。

使用 public repo + 标准 GitHub-hosted runner，GitHub Actions 不消耗付费 Actions 分钟。

## 第三步：上传本项目

把压缩包解压后，将以下文件完整上传到仓库根目录：

- `.github/workflows/monitor.yml`
- `monitor.py`
- `requirements.txt`
- `state.json`
- `README.md`

注意 `.github/workflows/monitor.yml` 的目录层级不能改。

## 第四步：添加飞书 Webhook Secret

进入 GitHub 仓库：

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

创建：

- Name：`FEISHU_WEBHOOK`
- Secret：粘贴你的飞书机器人完整 Webhook

如果你开启了飞书“签名校验”，再创建：

- Name：`FEISHU_SECRET`
- Secret：粘贴飞书提供的签名 Secret

## 第五步：允许 Actions 写入 state.json

进入：

`Settings` → `Actions` → `General`

找到：

`Workflow permissions`

选择：

`Read and write permissions`

保存。

这是为了让监控程序自动记录“已经看过哪些信号”，防止重复通知，并做 30 天保活。

## 第六步：第一次手动测试

1. 打开仓库的 `Actions`。
2. 左侧选择 `Tibo Reset Monitor`。
3. 点 `Run workflow`。
4. 保持“发送一条飞书测试通知”为开启状态。
5. 运行。

第一次运行会：

- 读取当前追踪页面。
- 将当前历史信号写入 `state.json` 作为基线。
- 不推送历史旧消息。
- 给飞书发送一条“测试通知成功”。

如果飞书收到：

`【Tibo Reset Monitor】✅ 测试通知成功`

就表示部署完成。

## 之后不需要做什么

部署完成后：

- 北京时间约 00:17、06:17、12:17、18:17 自动检查。
- 没有新信号：不通知。
- 有新信号：飞书通知。
- 电脑关机：照常工作。
- 本机不需要代理。
- ChatGPT / Work / Codex 用量：0。
- OpenAI API：0。
- X API：0。

GitHub 的 scheduled workflow 不是实时任务，偶尔可能因平台负载延迟。这里故意使用第 17 分钟运行，避免每小时整点的高峰。

## 修改检查频率

文件：

`.github/workflows/monitor.yml`

当前：

```yaml
- cron: "17 */6 * * *"
  timezone: "Asia/Shanghai"
```

每 3 小时：

```yaml
- cron: "17 */3 * * *"
  timezone: "Asia/Shanghai"
```

每 12 小时：

```yaml
- cron: "17 */12 * * *"
  timezone: "Asia/Shanghai"
```

## 隐私

public repo 中会公开监控代码和 `state.json`，但不会公开你的飞书 Webhook。
Webhook 保存在 GitHub Actions Secrets 中。

不要把真实 Webhook 手工写进 `monitor.py`、`README.md` 或 workflow 文件。
