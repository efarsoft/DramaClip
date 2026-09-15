# -*- coding: utf-8 -*-
"""修 llm_client 429 退避 + _run_plan_variants 模式间加间隔。"""
p = 'service/dramaclip/engines/semantic/llm_client.py'
src = open(p, encoding='utf-8', newline='').read()
NL = chr(10)

old = (
    '        max_retries = 3' + NL
    + '        for attempt in range(max_retries):' + NL
    + '            try:' + NL
    + '                with urllib.request.urlopen(request, timeout=self._timeout_s) as response:' + NL
    + '                    body = json.loads(response.read().decode("utf-8"))' + NL
    + '                break' + NL
    + '            except urllib.error.HTTPError as exc:' + NL
    + '                if exc.code == 429 and attempt < max_retries - 1:' + NL
    + '                    wait = 5 * (attempt + 1)' + NL
    + '                    logging.getLogger(__name__).warning(' + NL
    + '                        "LLM 429 限流，%ds 后重试 (%d/%d)", wait, attempt + 1, max_retries' + NL
    + '                    )' + NL
    + '                    time.sleep(wait)' + NL
    + '                    continue' + NL
    + '                raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc' + NL
    + '            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:' + NL
    + '                raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc'
)

new = (
    '        max_retries = 3' + NL
    + '        backoff = [30, 60, 120]' + NL
    + '        body = None' + NL
    + '        for attempt in range(max_retries):' + NL
    + '            req = urllib.request.Request(' + NL
    + '                f"{self._config.base_url}/chat/completions",' + NL
    + '                data=json.dumps(payload).encode("utf-8"),' + NL
    + '                headers=headers,' + NL
    + '                method="POST",' + NL
    + '            )' + NL
    + '            try:' + NL
    + '                with urllib.request.urlopen(req, timeout=self._timeout_s) as response:' + NL
    + '                    body = json.loads(response.read().decode("utf-8"))' + NL
    + '                break' + NL
    + '            except urllib.error.HTTPError as exc:' + NL
    + '                if exc.code == 429 and attempt < max_retries - 1:' + NL
    + '                    wait = backoff[attempt]' + NL
    + '                    logging.getLogger(__name__).warning(' + NL
    + '                        "LLM 429 限流，%ds 后重试 (%d/%d)", wait, attempt + 1, max_retries' + NL
    + '                    )' + NL
    + '                    time.sleep(wait)' + NL
    + '                    continue' + NL
    + '                raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc' + NL
    + '            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:' + NL
    + '                raise LlmUnavailable(f"LLM 请求失败: {exc}") from exc'
)

assert old in src, '旧 429 块未命中'
src = src.replace(old, new)

# 把外层的 request 构建删掉（已移入循环）
old_req = (
    '        request = urllib.request.Request(' + NL
    + '            f"{self._config.base_url}/chat/completions",' + NL
    + '            data=json.dumps(payload).encode("utf-8"),' + NL
    + '            headers=headers,' + NL
    + '            method="POST",' + NL
    + '        )' + NL
)
assert old_req in src
src = src.replace(old_req, '')

open(p, 'w', encoding='utf-8', newline='').write(src)
print('llm_client 429 退避 ok')

# ---- _run_plan_variants 模式间加间隔 ----
p2 = 'service/dramaclip/api/narration.py'
src2 = open(p2, encoding='utf-8', newline='').read()
old2 = '        for mode in modes:\n            if cancel_event.is_set():'
new2 = '        for mode in modes:\n            if cancel_event.is_set():'
if old2 in src2:
    # 在循环体末尾（done_count += 1 那段后面）加 mode 间间隔
    old3 = '                done_count += 1\n                context.job_store.set_progress(\n                    job_id, round(done_count / total * 100, 1), tag\n                )'
    new3 = old3 + '\n                # 模式间间隔：九模式同时发选题会触发 DashScope QPS 上限\n                time.sleep(3)'
    if old3 in src2:
        src2 = src2.replace(old3, new3, 1)
        print('mode 间隔 ok')
    else:
        print('mode 间隔锚未命中')

if 'import time' not in src2:
    src2 = src2.replace('import json\n', 'import json\nimport time\n', 1)
    open(p2, 'w', encoding='utf-8', newline='').write(src2)
    print('time import ok')

open(p2, 'w', encoding='utf-8', newline='').write(src2)
print('narration.py 完成')
