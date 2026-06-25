"""V2W — AI 会议总结引擎（P10）

统一走 OpenAI 兼容的 /chat/completions 协议，一套客户端通吃主流厂商
（DeepSeek / 智谱 GLM / 通义 / OpenAI / 本地 Ollama），provider 由
config.current_llm_provider() 解析、llm_providers.json 驱动。
"""
import json
import re
import logging
import requests

logger = logging.getLogger(__name__)

# 结构化输出提示词：要求严格 JSON
SYSTEM_PROMPT = '你是专业的会议纪要助手，严格按要求的 JSON 格式输出，不要多余解释。'

SUMMARY_PROMPT = """基于以下带说话人标注的会议逐字稿，生成会议纪要。只输出如下 JSON（不要 markdown 代码块、不要多余文字）：
{
  "summary": "3-5 句话概括会议的主要结论与讨论要点",
  "action_items": ["会后需要跟进的事项，每条一句话，尽量带负责人"],
  "keywords": ["3-8 个会议关键词"]
}
要求：
- summary 抓核心结论，不要流水账；
- action_items 只列真正需要跟进的事项，没有就返回空数组 []；
- 全部用中文。"""

# 分段总结用：针对一个片段提取要点（map 阶段）
CHUNK_PROMPT = """以下是会议逐字稿的一个片段。提取该片段的要点，只输出 JSON：
{
  "summary": "本片段要点（1-3 句）",
  "action_items": ["本片段提到的待办事项"],
  "keywords": ["本片段关键词"]
}
没有待办则 action_items 返回 []，全中文。"""

# 合并用：把多片段要点合并成完整纪要（reduce 阶段）
MERGE_PROMPT = """以下是一场会议分片段提取的要点汇总。请合并成完整的会议纪要，去重整合。只输出 JSON：
{
  "summary": "3-5 句话概括整场会议的主要结论",
  "action_items": ["全部待办事项（去重后）"],
  "keywords": ["整场会议关键词（去重后，3-8 个）"]
}
全中文。"""


def build_transcript_text(segments):
    """把转写段落拼成喂给 LLM 的纯文本：每行「[说话人 · 时间] 文字」。

    复用 TranscriptSegment.speaker_display（优先重命名，回退「说话人 N」）。
    """
    lines = []
    for seg in segments:
        speaker = (seg.speaker_display or '').strip()
        ts = seg.formatted_time
        prefix = f'[{speaker} · {ts}] ' if speaker else f'[{ts}] '
        lines.append(prefix + (seg.text or '').strip())
    return '\n'.join(lines)


def _call_chat(provider, messages, json_mode=True):
    """统一 OpenAI 兼容 chat/completions 调用，返回助手回复文本。"""
    url = provider['base_url'] + '/chat/completions'
    payload = {
        'model': provider['model'],
        'messages': messages,
        'temperature': 0.3,
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    headers = {
        'Authorization': 'Bearer ' + provider.get('api_key', ''),
        'Content-Type': 'application/json',
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=180)
        resp.raise_for_status()
    except requests.HTTPError as e:
        body = ''
        try:
            body = resp.text[:300]
        except Exception:
            pass
        raise RuntimeError(f'LLM 接口返回错误 {resp.status_code}: {body}') from e
    except requests.RequestException as e:
        raise RuntimeError(f'LLM 调用失败（网络/超时）：{e}') from e

    data = resp.json()
    return data['choices'][0]['message']['content']


def chat_complete(prompt, text, provider, json_mode=True):
    """单次对话：拼接逐字稿，返回模型回复。"""
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': prompt + '\n\n会议逐字稿：\n' + text},
    ]
    return _call_chat(provider, messages, json_mode=json_mode)


def _chunk_text(text, chunk_chars):
    """按行累积切块，尽量不在一句话中间断开。"""
    chunks, cur, cur_len = [], [], 0
    for line in text.split('\n'):
        if cur_len + len(line) > chunk_chars and cur:
            chunks.append('\n'.join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append('\n'.join(cur))
    return chunks


def _normalize(d):
    """把模型返回的 dict 归一化为 {summary, action_items[{text,done}], keywords[str]}。

    action_items 统一成对象数组，便于 P10b 勾选标记完成状态（done 默认 False）。
    """
    summary = (d.get('summary') or d.get('摘要') or '').strip()
    raw_actions = d.get('action_items') or d.get('行动项') or d.get('todos') or []
    raw_keywords = d.get('keywords') or d.get('关键词') or []

    norm_actions = []
    for a in raw_actions:
        if isinstance(a, str):
            t = a.strip()
            if t:
                norm_actions.append({'text': t, 'done': False})
        elif isinstance(a, dict):
            parts = []
            main = a.get('text') or a.get('content') or a.get('item')
            if main:
                parts.append(str(main).strip())
            if a.get('owner'):
                parts.append(f'（{a["owner"]}）')
            if a.get('due'):
                parts.append(f'截止 {a["due"]}')
            t = ' '.join(parts).strip()
            if t:
                norm_actions.append({'text': t, 'done': bool(a.get('done'))})
    norm_kw = [str(k).strip() for k in raw_keywords if str(k).strip()]
    return {'summary': summary, 'action_items': norm_actions, 'keywords': norm_kw}


def parse_summary_json(raw):
    """容错解析模型输出为 {summary, action_items, keywords}。"""
    empty = {'summary': '', 'action_items': [], 'keywords': []}
    if not raw:
        return empty
    # 1) 直接解析
    try:
        return _normalize(json.loads(raw))
    except (ValueError, TypeError):
        pass
    # 2) 去掉 markdown 代码块再解析
    stripped = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
    try:
        return _normalize(json.loads(stripped))
    except (ValueError, TypeError):
        pass
    # 3) 提取首个 {...} 块
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return _normalize(json.loads(m.group(0)))
        except (ValueError, TypeError):
            pass
    # 4) 兜底：整段当摘要
    logger.warning('Failed to parse summary JSON, fallback to raw text')
    return {'summary': raw.strip()[:2000], 'action_items': [], 'keywords': []}


def map_reduce_summarize(text, provider, chunk_chars):
    """长文本 map-reduce：分段提取要点 → 合并。"""
    chunks = _chunk_text(text, chunk_chars)
    if len(chunks) <= 1:
        return chat_complete(SUMMARY_PROMPT, text, provider)

    logger.info(f'map-reduce: {len(chunks)} chunks')
    partials = []
    for i, ch in enumerate(chunks):
        raw = chat_complete(CHUNK_PROMPT, ch, provider)
        partials.append(parse_summary_json(raw))

    merged = '\n\n'.join(
        f'【片段{i + 1}】\n摘要：{p["summary"]}\n行动项：{json.dumps(p["action_items"], ensure_ascii=False)}\n关键词：{json.dumps(p["keywords"], ensure_ascii=False)}'
        for i, p in enumerate(partials)
    )
    return chat_complete(MERGE_PROMPT, merged, provider)


def summarize_segments(segments, provider, chunk_chars=6000):
    """主入口：转写段落 → {summary, action_items, keywords}。

    抛出 RuntimeError 表示 LLM 调用层面的失败，由调用方捕获记录。
    """
    text = build_transcript_text(segments)
    if not text.strip():
        raise RuntimeError('逐字稿为空，无法总结')

    if len(text) > chunk_chars:
        raw = map_reduce_summarize(text, provider, chunk_chars)
    else:
        raw = chat_complete(SUMMARY_PROMPT, text, provider)

    return parse_summary_json(raw)
