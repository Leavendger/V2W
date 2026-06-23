# HuggingFace Token 配置指南

> 说话人分离功能依赖 `pyannote.audio`，其模型是 **gated**（需登录 + 接受使用条款才能下载），因此需要配置一个 HuggingFace Access Token。
>
> 说话人分离整体设计见 [speaker-diarization-design.md](speaker-diarization-design.md)。
>
> 全程约 5–10 分钟，**完全免费**。

## 为什么需要 token

`pyannote/speaker-diarization-3.1` 是工业级的说话人分离模型，作者要求使用者：

1. 注册 HuggingFace 账号；
2. 在模型页面明确接受使用条款（用于统计与合规）；
3. 用个人 Access Token 证明身份后才能下载。

token 只用于「下载模型」这一步，本地运行，**不上传你的音频或数据**。

---

## 步骤一：注册 HuggingFace 账号

1. 打开 https://huggingface.co/join
2. 用邮箱注册（或 Google / GitHub 登录）
3. 完成邮箱验证

> 已有账号直接登录即可。

## 步骤二：接受两个模型的使用条款

必须分别访问下面两个页面，各点一次 **Agree and access repository**：

1. **说话人分离主模型**（必须）
   - https://huggingface.co/pyannote/speaker-diarization-3.1
2. **分割子模型**（必须，主模型内部依赖它）
   - https://huggingface.co/pyannote/segmentation-3.0

> 在每个页面找到「You need to agree to share your contact information to access this model」区域，点击同意按钮。同意后页面会显示可访问状态，可能需要等几分钟生效。

## 步骤三：生成 Access Token

1. 进入 https://huggingface.co/settings/tokens（头像 → Settings → Access Tokens）
2. 点 **New token**
3. 填写：
   - **Name**：例如 `v2w-diarization`
   - **Type**：选 **Read**（只读即可，不要用 Write）
4. 点 Create → 复制生成的 token

> token 形如 `hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`。**只显示一次，务必复制保存**，丢失就重新生成。

## 步骤四：配置到 V2W

### 方式 A：环境变量（推荐，token 不进 git）

在 shell 配置文件（macOS 为 `~/.zshrc`）追加：

```bash
export HF_TOKEN="hf_你刚才复制的token"
```

让配置生效：

```bash
source ~/.zshrc
```

### 方式 B：临时设置（仅当前终端）

```bash
export HF_TOKEN="hf_你刚才复制的token"
```

然后在该终端启动应用。

> ⚠️ **不要把 token 写进 `config.py` 再提交 git**。`config.py` 里用 `os.environ.get('HF_TOKEN')` 读取，token 只存在于你的环境变量中。

## 步骤五：安装依赖 + 首次下载模型

```bash
# 1. 安装 pyannote.audio（已加入 requirements.txt）
pip install -r requirements.txt

# 2. 启动应用（首次识别时会自动下载模型，约 100MB，缓存到 ~/.cache/huggingface/）
python app.py
```

模型只在**首次**运行时下载，之后离线可用。

## 验证

1. 上传一段会议录音，上传时勾选「识别说话人」；
2. 等待转写 + 分离完成（比纯转写慢）；
3. 进入详情页，每段开头应显示 **「说话人 1 / 2 / 3」**；
4. 导出 Markdown，段落显示 `**说话人 N**`。

如出现 `[发言人]` 占位，说明分离未生效，对照下方排查。

---

## 常见问题

### 1. `You need to agree to share your contact information...`

→ 步骤二的两个模型条款**没接受**或**未生效**。回页面确认已点 Agree，等几分钟重试。两个模型**都要**接受。

### 2. `401 Unauthorized` / token 无效

→ token 复制不完整或已失效。回 https://huggingface.co/settings/tokens 重新生成，确认 Type 是 **Read**，重新配置环境变量并 `source ~/.zshrc`。

### 3. 模型下载失败 / 超时

→ 网络问题。可设置镜像或重试；下载是分块的，断点可续传。已下好的部分在 `~/.cache/huggingface/`。

### 4. 确认环境变量是否生效

```bash
echo $HF_TOKEN      # 应输出 hf_xxx
```

或在 Python 里：

```bash
python -c "import os; print(os.environ.get('HF_TOKEN'))"
```

输出 `None` 说明没设好，重做步骤四。

### 5. 没勾选「识别说话人」

→ 即使 token 配好了，不勾选也不会跑分离，段落仍是 `[发言人]`。上传时记得勾选（或把全局 `DIARIZATION_ENABLED` 设为 `True`）。

### 6. 转写完成但没分离，无报错

→ token 缺失或 pyannote 加载失败时，V2W 会**优雅降级**（跳过分离，正常完成转写）。查看应用日志（终端输出）是否有 `diarization skipped` 类告警，按上述 1–4 项排查。

---

## 安全说明

- token 仅用于本地下载模型，不上传任何音频；
- 建议用 **Read** 类型 token（权限最小）；
- token 通过环境变量传入，**不写入项目文件、不进 git**；
- 怀疑泄露？到 https://huggingface.co/settings/tokens 直接删除或重新生成即可。
